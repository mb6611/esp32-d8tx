#!/usr/bin/env python3
"""Generate the golden protocol vectors under protocol/ from the Python package (the single source of truth).

Run from anywhere: python python/tools/gen_vectors.py. Output is deterministic (no clocks, fixed seeds), so a second
run rewrites byte-identical files. The TS core, the Python tests (python/tests/test_vectors.py) and the firmware C test
(firmware/test/test_vectors.c via protocol/vectors/commands.h) all check against these files.
"""
from __future__ import annotations

import json
import os
import shutil
import struct
import sys
import threading
import time

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "python"))

from d8tx import D8Link  # noqa: E402
from d8tx import protocol as P  # noqa: E402
from d8tx import msp as M  # noqa: E402
from d8tx.hub import HubParser, HubState, armed_from_rpm  # noqa: E402
from d8tx.link import unpack4  # noqa: E402
from d8tx.telemetry import (Tracker, decode_capture, load_iq, next_tid, parse_reply, parse_tlm_header,  # noqa: E402
                            payload_ok, rssi_dbm, vbat_from_a1)
from d8tx.link import D8Error  # noqa: E402

OUT = os.path.join(ROOT, "protocol")
VEC = os.path.join(OUT, "vectors")
SRC_CAPS = os.path.join(ROOT, "python", "tests", "data", "telemetry")


def dump(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="\n") as f:
        json.dump(obj, f, indent=1, sort_keys=False)
        f.write("\n")


def write_bytes(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def hx(b):
    return bytes(b).hex()


def pl(kind, val):
    """parse_line result -> JSON object."""
    if kind == "ok":
        return {"kind": "ok", "data": val}
    if kind == "err":
        return {"kind": "err", "code": val[0], "text": val[1]}
    if kind == "ev":
        return {"kind": "ev", "name": val[0], "data": val[1]}
    return {"kind": "other", "text": val}


# ---------------------------------------------------------------- commands.json / commands.h
class GenPort:
    """Accepts any command with OK (INFO etc.) so D8Link.start() runs its sequence; records written lines."""

    def __init__(self, tlm_err=False):
        self.lines, self.out_waiting, self._rx, self._lk = [], 0, bytearray(), threading.Lock()
        self.tlm_err = tlm_err

    def read(self, n=1):
        with self._lk:
            d = bytes(self._rx[:n])
            del self._rx[:n]
        if not d:
            time.sleep(0.002)
        return d

    def _emit(self, s):
        with self._lk:
            self._rx += (s + "\n").encode()

    def write(self, b):
        for ln in b.decode().splitlines():
            self.lines.append(ln)
            if ln.startswith("S "):
                continue
            if ln.startswith("TLM ") and self.tlm_err:
                self._emit("ERR unknown cmd")
            elif ln == "STOP":
                self._emit("OK")
            else:
                self._emit("OK")
        return len(b)

    def close(self):
        pass


def start_scenarios():
    scen = [
        {"name": "defaults", "tlm_err": False, "steps": [{"op": "start"}, {"op": "stop"}]},
        {"name": "args", "tlm_err": False, "steps": [
            {"op": "start", "power": 60, "timeout_ms": 500, "allow_arm": True, "fofs_hz": -63000},
            {"op": "stop"}]},
        {"name": "telemetry_off_after_on", "tlm_err": False, "steps": [
            {"op": "start"}, {"op": "stop"}, {"op": "start", "telemetry": False}, {"op": "stop"},
            {"op": "start", "telemetry": False}, {"op": "stop"}]},
        {"name": "firmware_without_tlm", "tlm_err": True, "steps": [
            {"op": "start"}, {"op": "stop"}, {"op": "start", "telemetry": False}, {"op": "stop"}]},
    ]
    for s in scen:
        port = GenPort(s["tlm_err"])
        link = D8Link("x", serial_obj=port)
        for st in s["steps"]:
            n0 = len(port.lines)
            if st["op"] == "start":
                kw = {k: v for k, v in st.items() if k != "op"}
                link.start(**kw)
                time.sleep(0.02)
            else:
                link.stop()
            st["lines"] = [ln for ln in port.lines[n0:] if not ln.startswith("S ")]
        link.close()
    return scen


STICK_CASES = [
    ([1500] * 8, False), ([1500] * 8, True),
    ([0, 1500, 3000, 1500, 1500, 1500, 2000, 1500], False),  # clamp, ch7 gated
    ([1000] * 6 + [2000, 1000], True),
    ([1000, 1000, 1000, 1000, 1000, 1000, 2000, 1000], False),
    ([1000, 1000, 1000, 1000, 1000, 1000, 1300, 1000], True),
    ([1000, 1000, 1000, 1000, 1000, 1000, 1301, 1000], True),
    ([1000.5, 1001.5, 1002.5, 1500.4, 1500.6, 1999.5, 1250.5, -0.5], True),  # python round() is banker's rounding
    ([2500.5, 999.5, -1000, 1e9, 1499.49, 1499.5, 1500.5, 1501.5], True),
    ([1500] * 7, False), ([1500] * 9, True), ([], False),
    ([1100, 1200, 1300, 1400, 1600, 1700, 1800, 1900], True),
    ([2000, 2000, 2000, 2000, 2000, 2000, 2000, 2000], True),
    ([1000] * 8, False),
]


def commands():
    sticks = []
    for ch, arm in STICK_CASES:
        try:
            line, clamped = P.fmt_sticks(ch, allow_arm=arm)
            sticks.append({"ch": ch, "allow_arm": arm, "line": line, "channels": clamped})
        except ValueError as e:
            sticks.append({"ch": ch, "allow_arm": arm, "error": str(e)})
    checks = []
    for n in (0, 1, 94, 95, 96, 200):
        for suffix in ("", "\n", "\r\n"):
            s = "x" * n + suffix
            try:
                P.check_line(s)
                checks.append({"line": s, "ok": True})
            except ValueError as e:
                checks.append({"line": s, "ok": False, "error": str(e)})
    return {
        "constants": {"LO": P.LO, "MID": P.MID, "HI": P.HI, "ARM_CH": P.ARM_CH, "ARM_LIMIT": P.ARM_LIMIT,
                      "SLOT_S": P.SLOT_S, "DEFAULT_FOFS_HZ": P.DEFAULT_FOFS_HZ, "TXID": list(P.TXID),
                      "TLM_RECIPE": P.TLM_RECIPE, "MAX_LINE": P.MAX_LINE},
        "sticks": sticks,
        "check_line": checks,
        "start_sequences": start_scenarios(),
        # Lines the firmware must accept/reject (checked by firmware/test/test_vectors.c). "err" = protocol v1 error
        # code from err_code(); lines the host sends are accepted, malformed or out-of-range ones are rejected.
        "firmware_lines": [
            {"line": "INFO", "ok": True}, {"line": "STAT", "ok": True}, {"line": "STOP", "ok": True},
            {"line": "PING", "ok": True}, {"line": "ARMOK", "ok": True},
            {"line": "ARMOK 1", "ok": False, "err": "args"},
            {"line": "FOFS -75000", "ok": True}, {"line": "FOFS 200000", "ok": True},
            {"line": "FOFS 200001", "ok": False, "err": "range"}, {"line": "FOFS x", "ok": False, "err": "range"},
            {"line": "LINK 127", "ok": True}, {"line": "LINK 127 300", "ok": True},
            {"line": "LINK 0 1000", "ok": True}, {"line": "LINK 128", "ok": False, "err": "range"},
            {"line": "LINK 5 1001", "ok": False, "err": "range"}, {"line": "LINK", "ok": False, "err": "args"},
            {"line": "TID 0", "ok": True}, {"line": "TID 31", "ok": True},
            {"line": P.TLM_RECIPE, "ok": True}, {"line": "TLM 0", "ok": True},
            {"line": "BOGUS", "ok": False, "err": "unknown"}, {"line": "S 1500", "ok": False, "err": "args"},
            {"line": "S 1 2 3 4 5 6 7 x", "ok": False, "err": "range"},
        ],
    }


def write_commands_h(cmds):
    lines = ["/* Generated by python/tools/gen_vectors.py from protocol/vectors/commands.json. Do not edit. */",
             "#ifndef D8_COMMANDS_H", "#define D8_COMMANDS_H", "",
             "typedef struct { const char *line; int ch[8]; } vec_s_t;",
             "typedef struct { const char *line; int ok; const char *err; } vec_line_t;", "",
             "static const vec_s_t VEC_S[] = {"]
    for c in cmds["sticks"]:
        if "line" in c:
            ln = c["line"].rstrip("\n")
            lines.append('    {"%s", {%s}},' % (ln, ", ".join(map(str, c["channels"]))))
    lines += ["};", "", "static const vec_line_t VEC_LINES[] = {"]
    for c in cmds["firmware_lines"]:
        lines.append('    {"%s", %d, %s},' % (c["line"], int(c["ok"]), '"%s"' % c["err"] if "err" in c else "0"))
    lines += ["};", "", "#endif", ""]
    write_bytes(os.path.join(VEC, "commands.h"), "\n".join(lines).encode())


# ---------------------------------------------------------------- replies.json
REPLY_LINES = [
    "OK", "OK\r", "OK proto=1 fw=abc\r", "  OK  ", "OK proto=1 fw=d8tx-v1 slot_us=8994 channels=47 pwr_max=127",
    "OK keyed=0 link=0 fofs=-75000 armok=0", "OK a=-5 b=x c= flag", "OK tid=7", "OK n=0x10 m=-", "OKAY",
    "ERR", "ERR busy", "ERR busy link active", "ERR   range   fofs  out of range", "ERR unknown cmd",
    "EV link slots=3 late_max_us=9", "EV link_end why=stop slots=5 late_max_us=7 retune_max_us=3",
    "EV tlm k=48 ch=112 tid=0 n=4500 bytes=9000 crc=2a84fe9b", "EV tlm_drop", "EV", "EV ", "EVlink x=1",
    "hello", "", "   ", "\r", "S 1500 1500", "oK", "EV a x=1 x=2",
]


def replies():
    return [{"line": ln, "parsed": pl(*P.parse_line(ln))} for ln in REPLY_LINES]


# ---------------------------------------------------------------- reader.json
class _GatedPort:
    def __init__(self):
        self.chunks, self.go, self.done = [], threading.Event(), threading.Event()

    def read(self, n=1):
        if not self.go.is_set():
            time.sleep(0.001)
            return b""
        if self.chunks:
            return self.chunks.pop(0)
        self.done.set()
        time.sleep(0.001)
        return b""

    def write(self, b):
        return len(b)

    def close(self):
        pass


def run_reader(chunks):
    port = _GatedPort()
    link = D8Link("x", serial_obj=port)
    events = []
    link._on_capture = lambda meta, payload: events.append({"type": "capture", "meta": meta, "payload": hx(payload)})
    link._handle = lambda line: events.append({"type": "line", "text": line, "parsed": pl(*P.parse_line(line))})
    port.chunks = [bytes(c) for c in chunks]
    port.go.set()
    assert port.done.wait(5)
    time.sleep(0.01)
    link._closed = True
    return events


def split(data, size):
    return [data[i:i + size] for i in range(0, len(data), size)] or [b""]


def reader():
    payload_a = bytes(range(256)) * 2
    payload_nl = b"\n\n\nEV tlm k=1 bytes=5\nOK\n" + bytes([0, 10, 13, 255, 10])
    hdr = lambda n, crc="deadbeef", **kw: ("EV tlm k=48 ch=112 tid=%d n=%d dec=32 bits=8 fs=500000 bytes=%d crc=%s\n"
                                          % (kw.get("tid", 0), n // 2, n, crc)).encode()
    streams = {
        "plain_lines": b"OK proto=1\nOK\r\nERR busy x\nEV link slots=1\nnoise line\n",
        "capture_between_lines": b"OK\n" + hdr(512) + payload_a + b"\nEV link slots=2\nOK\n",
        "capture_with_newlines_in_payload": hdr(len(payload_nl)) + payload_nl + b"\nOK tid=3\n",
        "two_captures_back_to_back": hdr(8, tid=1) + b"\x00\x01\x02\x03\x04\x05\x06\x07\n" + hdr(4, tid=2) +
                                     b"\xff\xfe\xfd\xfc\n",
        "int4_header": b"EV tlm k=96 ch=167 tid=5 n=2000 dec=64 bits=4 fs=250000 bytes=6 crc=0000abcd\n" +
                      b"\x11\x22\x33\x44\x55\x66\n",
        "header_zero_bytes_is_a_line": b"EV tlm k=1 bytes=0\nOK\n",
        "header_too_big_is_a_line": b"EV tlm k=1 bytes=65537\nOK\n",
        "header_4000_bytes": hdr(4000) + bytes(range(256)) * 15 + bytes(160) + b"\nOK\n",
        "header_without_bytes_is_a_line": b"EV tlm k=1 tid=2\nOK\n",
        "tlm_drop_is_a_line": b"EV tlm_drop\nEV tlm_end x=1\n",
        "incomplete_payload_yields_nothing_more": b"OK\n" + hdr(100) + bytes(50),
        "no_trailing_newline": b"OK\nOK proto=1",
        "non_ascii_bytes": b"OK \xff\xfe\n",
        "long_garbage_resync": b"x" * 5000 + b"OK\nEV link slots=9\n",
    }
    chunkings = {
        "long_garbage_resync": [1000],
        "header_4000_bytes": [4096],
    }
    cases = []
    for name, data in streams.items():
        for size in chunkings.get(name, [0, 1, 7, 64]):
            ch = [data] if size == 0 else split(data, size)
            cases.append({"name": f"{name}/chunk{size}", "chunks": [hx(c) for c in ch], "events": run_reader(ch)})
    return cases


# ---------------------------------------------------------------- tlm_header / unpack4 / tid_rule
def tlm_header():
    lines = [
        "EV tlm k=48 ch=112 tid=0 n=4500 dec=32 bits=8 fs=500000 bytes=9000 crc=2a84fe9b run_us=9322 try=0",
        "EV tlm k=96 ch=167 tid=31 n=2000 dec=64 bits=4 fs=250000 bytes=2000 crc=0000ABCD",
        "EV tlm bytes=-5 crc=ff", "EV tlm foo=12 bytes=10 crc=deadbeef", "EV tlm k=1", "EV tlm crc=00000000 bytes=3",
        "EV tlm a=1 a=2",
    ]
    hdr = [{"line": ln, "meta": parse_tlm_header(ln)} for ln in lines]
    import zlib
    pay = [b"", b"abc", bytes(range(64))]
    ok = []
    for p in pay:
        crc = "%08x" % (zlib.crc32(p) & 0xFFFFFFFF)
        ok.append({"payload": hx(p), "meta": {"bytes": len(p), "crc": crc}, "ok": payload_ok({"bytes": len(p), "crc": crc}, p)})
        ok.append({"payload": hx(p), "meta": {"bytes": len(p) + 1, "crc": crc}, "ok": payload_ok({"bytes": len(p) + 1, "crc": crc}, p)})
        ok.append({"payload": hx(p), "meta": {"bytes": len(p), "crc": "00000001"}, "ok": payload_ok({"bytes": len(p), "crc": "00000001"}, p)})
        ok.append({"payload": hx(p), "meta": {"bytes": len(p)}, "ok": payload_ok({"bytes": len(p)}, p)})
        ok.append({"payload": hx(p), "meta": {"crc": crc}, "ok": payload_ok({"crc": crc}, p)})
    # load_iq on int8 / int16 payloads: list of [I, -Q]
    iq = []
    p8 = bytes([1, 2, 255, 128, 127, 0, 5, 6])
    p16 = struct.pack("<8h", 1, -2, 300, -300, 32767, -32768, 0, 5)
    for p, bits, n in ((p8, 8, 4), (p8, 8, 3), (p16, 16, 4), (p16, 16, 2)):
        a = load_iq(p, n, bits)
        iq.append({"payload": hx(p), "bits": bits, "n": n, "i": a.real.tolist(), "q": a.imag.tolist()})
    return {"headers": hdr, "payload_ok": ok, "load_iq": iq}


def unpack4_vectors():
    rng = np.random.default_rng(4)
    cases = [b"", b"\x00", b"\x08", b"\x80", b"\xff", b"\x77", b"\x0f\xf0\x12\x34\x89\xab", bytes(range(256)),
             bytes(rng.integers(0, 256, 64, dtype=np.uint8))]
    return [{"payload": hx(c), "iq8": hx(unpack4(c))} for c in cases]


def tid_rule():
    out = []
    for sent in list(range(0, 32)) + [32, 33, 63, 64]:
        for r in (None, sent, sent - 1, sent + 1, 0, 31):
            out.append({"sent": sent, "reply_tid": r, "next": next_tid(sent, r)})
    return out


# ---------------------------------------------------------------- hub.json
def hubframes(*pairs):
    out = b""
    for fid, val in pairs:
        v = val & 0xFFFF
        body = bytes([v & 0xFF, v >> 8]).replace(b"\x5d", b"\x5d\x3d").replace(b"\x5e", b"\x5d\x3e")
        out += bytes([0x5E, fid]) + body
    return out + b"\x5e"


def feed_chunks(chunks):
    p = HubParser()
    got = []
    for c in chunks:
        got += [list(x) for x in p.feed(c)]
    return got


def hub():
    streams = {
        "stuffing": hubframes((0x24, 0x5E5D), (0x03, 300), (0x28, -5)),
        "all_escapes": hubframes((0x24, 0x5D5D), (0x25, 0x5E5E), (0x26, 0x3D3E)),
        "id_5d": b"\x5e\x5d\x3d\x01\x00\x5e",
        "no_header_ignored": b"\x01\x02\x03" + hubframes((0x39, 123)),
        "header_restarts_frame": b"\x5e\x24\x01\x5e\x03\x2c\x01\x5e",
        "truncated": b"\x5e\x24\x01",
        "negative": hubframes((0x28, -32768), (0x40, 32767), (0x41, -1)),
        "garbage_in_ids": hubframes((0x00, 1), (0xFF, 2), (0x5E ^ 0x60, 3)),
        "patched_set": hubframes((0x46, 0b100001), (0x47, 0x2000), (0x40, 123), (0x41, -45), (0x42, 6),
                                 (0x43, 150), (0x44, -900), (0x45, 3599)),
        "vfas_hi_precision": hubframes((0x39, 126), (0x3A, 7), (0x3B, 5)),
        "dangling_escape": b"\x5e\x24\x5d\x3d\x5d",
    }
    parser = []
    for name, data in streams.items():
        for size in (0, 1, 3, 10):
            ch = [data] if size == 0 else split(data, size)
            parser.append({"name": f"{name}/chunk{size}", "chunks": [hx(c) for c in ch], "frames": feed_chunks(ch)})

    # HubState: updates (id, value, t) -> snapshot(now) and vfas_v
    state_cases = [
        {"name": "empty", "updates": [], "now": 5.0},
        {"name": "stock_fields", "updates": [[0x03, 300, 1.0], [0x02, 31, 1.0], [0x24, 0, 1.0], [0x25, -3, 1.0],
                                              [0x26, 1000, 1.0], [0x28, 25, 2.0], [0x04, 77, 2.0], [0x05, 40, 2.0],
                                              [0x14, 270, 2.0], [0x39, 123, 2.5]], "now": 3.0},
        {"name": "vfas_bp_ap", "updates": [[0x3A, 7, 0.0], [0x3B, 5, 0.0]], "now": 1.0},
        {"name": "vfas_only_bp", "updates": [[0x3A, 7, 0.0]], "now": 1.0},
        {"name": "patched_all", "updates": [[0x46, 0b100001, 1.0], [0x47, 0x2000, 1.0], [0x40, 123, 1.0],
                                             [0x41, -45, 1.0], [0x42, 6, 1.0], [0x43, 150, 1.0], [0x44, -900, 1.0],
                                             [0x45, 3599, 1.0]], "now": 1.25},
        {"name": "patched_flight_modes", "updates": [[0x46, 0b000010, 0.0]], "now": 0.0},
        {"name": "patched_horizon", "updates": [[0x46, 0b000100, 0.0]], "now": 0.0},
        {"name": "patched_partial_vector", "updates": [[0x43, 10, 0.0]], "now": 0.0},
        {"name": "patched_later_overrides", "updates": [[0x46, 1, 0.0], [0x46, 0, 0.5]], "now": 1.0},
    ]
    for c in state_cases:
        h = HubState()
        for hid, v, t in c["updates"]:
            h.update(hid, v, t)
        c["snapshot"] = h.snapshot(c["now"])
        c["vfas_v"] = h.vfas_v()

    armed = []
    for rpm in (None, 0, 1, 50, 199, 200, 260, 300, 400, 401, 500, -1):
        for base in (None, 0, 100, 200, 260, 300, 400, 500):
            armed.append({"rpm": rpm, "baseline": base, "armed": armed_from_rpm(rpm, base)})
    return {"parser": parser, "state": state_cases, "armed_from_rpm": armed}


# ---------------------------------------------------------------- reply_parse.json
def pack_fast(roll, pitch, yaw, gx, gy, gz, seq=0):
    m12, m14 = (1 << 12) - 1, (1 << 14) - 1
    v = (roll & m12) | ((pitch & m12) << 12) | (yaw << 24) | ((gx & m14) << 36) | ((gy & m14) << 50) \
        | ((gz & m14) << 64) | (seq << 78)
    return v.to_bytes(10, "little")


def reply_cases():
    raws = {
        "hub_3_bytes": bytes([0x11, 66, 178, 75, 26, 71, 3, 9, 0x5E, 0x03, 0x00, 0x1B, 0, 0, 0, 0, 0, 0, 0, 0])[:18],
        "hub_10_bytes": bytes([0x11, 66, 178, 0, 0, 77, 10, 0]) + bytes.fromhex("00005e0200005e030000"),
        "hub_count_over_10": bytes([0x11, 66, 178, 1, 2, 3, 15, 4]) + bytes(range(0x10, 0x1A)),
        "hub_count_0": bytes([0x11, 66, 178, 1, 2, 3, 0, 4]) + bytes(10),
        "hub_cnt_7f": bytes([0x11, 66, 178, 1, 2, 3, 0x7F, 31]) + bytes(range(1, 11)),
        "hub_3_stripped": bytes([0x11, 0, 0, 1, 2, 3, 3, 5]) + b"\x5e\x24\x01\x00\x00\x00\x00\x00\x00\x00",
        "fast_signs": bytes([0x11, 0, 0, 60, 7, 70, 0x8A, 0]) + pack_fast(-1800, -900, 3599, -8191, 8191, -1, 3),
        "fast_max": bytes([0x11, 0, 0, 60, 7, 70, 0x8A, 1]) + pack_fast(1800, 900, 0, 8191, -8192, 0, 1),
        "fast_small": bytes([0x11, 0, 0, 60, 7, 70, 0x8A, 2]) + pack_fast(-1, 1, 1, 1, 1, 1),
        "fast_cnt_80": bytes([0x11, 0, 0, 60, 7, 70, 0x80, 2]) + pack_fast(0, 0, 0, 0, 0, 0),
        "rssi_a1_high": bytes([0x11, 66, 178, 255, 255, 255, 0, 0]) + bytes(10),
    }
    out = []
    for name, raw in raws.items():
        r = parse_reply(raw)
        r["hub"] = hx(r["hub"])
        out.append({"name": name, "raw": hx(raw), "reply": r})
    a1 = [{"a1": a, "vbat_v": vbat_from_a1(a)} for a in (0, 1, 75, 100, 252, 255)]
    rssi = [{"byte": b, "dbm": rssi_dbm(b)} for b in range(256)]
    return {"parse_reply": out, "vbat_from_a1": a1, "rssi_dbm": rssi}


# ---------------------------------------------------------------- tracker.json
class Clk:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def run_tracker(ops):
    clk, tr = Clk(), None
    tr = Tracker(clk)
    snaps = []
    for op in ops:
        o = op["op"]
        if o == "reset":
            tr.reset(enabled=op["enabled"])
        elif o == "reply":
            rep = parse_reply(bytes.fromhex(op["raw"]))
            if "cfo_hz" in op:
                rep["cfo_hz"] = op["cfo_hz"]
            tr.note_reply(rep)
        elif o == "miss":
            tr.note_trigger_miss()
        elif o == "arm":
            tr.note_arm_on_air(op["high"])
        elif o == "advance":
            clk.t += op["s"]
        elif o == "snapshot":
            snaps.append(tr.snapshot())
    return snaps


def rep(tid, hub=b"", a1=75, a2=0, rssi=71, cnt=None):
    c = len(hub) if cnt is None else cnt
    return hx(bytes([0x11, 66, 178, a1, a2, rssi, c, tid]) + (bytes(hub) + bytes(10))[:10])


def fastrep(tid, *a, seq=0):
    return hx(bytes([0x11, 0, 0, 60, 7, 70, 0x8A, tid]) + pack_fast(*a, seq=seq))


def tracker():
    S = {"op": "snapshot"}
    adv = lambda s: {"op": "advance", "s": s}
    cases = []
    cases.append({"name": "idle", "ops": [S]})
    cases.append({"name": "enabled_idle", "ops": [{"op": "reset", "enabled": True}, S]})
    cases.append({"name": "a1_battery", "ops": [
        {"op": "reply", "raw": rep(0, a1=0, a2=1), "cfo_hz": -12345.0}, S,
        {"op": "reply", "raw": rep(1, a1=252, a2=1)}, S, {"op": "reply", "raw": rep(2, a1=75)}, S]})
    cases.append({"name": "hub_armed_inference", "ops": [
        {"op": "arm", "high": False},
        {"op": "reply", "raw": rep(0, hubframes((0x03, 300), (0x02, 31), (0x24, 0), (0x25, 0), (0x26, 1000))[:10])}, S,
        adv(3.0), {"op": "reply", "raw": rep(1, hubframes((0x02, 30), (0x03, 300)))}, S,
        adv(0.5), {"op": "reply", "raw": rep(2, hubframes((0x02, 32), (0x03, 300)))}, S,
        adv(0.5), {"op": "reply", "raw": rep(3, hubframes((0x03, 260)))}, S,
        {"op": "arm", "high": True}, adv(0.5), {"op": "reply", "raw": rep(4, hubframes((0x03, 500)))}, S,
        adv(6.0), S]})
    cases.append({"name": "rpm_baseline_learning", "ops": [
        {"op": "arm", "high": False}, adv(2.5),
        {"op": "reply", "raw": rep(0, hubframes((0x03, 500)))},
        {"op": "reply", "raw": rep(1, hubframes((0x03, 500)))},
        {"op": "reply", "raw": rep(2, hubframes((0x03, 500)))}, S,
        {"op": "reply", "raw": rep(3, hubframes((0x03, 0)))}, S]})
    cases.append({"name": "patched_armed_wins", "ops": [
        {"op": "reply", "raw": rep(0, hubframes((0x46, 1), (0x03, 500))[:10])}, S,
        adv(5.5), S, {"op": "reply", "raw": rep(1, hubframes((0x03, 300)))}, S]})
    cases.append({"name": "resend_filter", "ops": [
        {"op": "reply", "raw": rep(7, hubframes((0x39, 123)))}, S,
        {"op": "reply", "raw": rep(7, hubframes((0x39, 99)))}, S,  # same tid, different bytes: fresh
        {"op": "reply", "raw": rep(7, hubframes((0x39, 99)))}, S,  # same tid, same bytes: resend, skipped
        {"op": "reply", "raw": rep(8, hubframes((0x39, 99)))}, S]})
    cases.append({"name": "vfas_overrides_a1", "ops": [
        {"op": "reply", "raw": rep(0, hubframes((0x39, 162)), a1=100)}, S, adv(3.5), S]})
    cases.append({"name": "catch_rate_window", "ops": [
        {"op": "miss"}, adv(1), {"op": "reply", "raw": rep(0)}, adv(1), {"op": "miss"}, S, adv(9.5), S, adv(2), S]})
    cases.append({"name": "link_and_powered_ages", "ops": [
        {"op": "reply", "raw": rep(0)}, S, adv(0.99), S, adv(0.02), S, adv(2.0), S, adv(0.01), S]})
    cases.append({"name": "fast_mixed_with_hub", "ops": [S] + sum(
        [[adv(0.25), {"op": "reply", "raw": fastrep(i, 10 * i, 0, 100, 4, 8, 12, seq=i & 3)}] +
         ([{"op": "reply", "raw": rep(9, hubframes((0x39, 123))[:4], cnt=4)}] if i == 2 else [])
         for i in range(6)], []) + [S, adv(2), S, adv(4), S]})
    cases.append({"name": "fast_does_not_disturb_resend", "ops": [
        {"op": "reply", "raw": rep(7, hubframes((0x39, 123))[:4], cnt=4)}, S,
        {"op": "reply", "raw": fastrep(8, 0, 0, 0, 0, 0, 0)}, S,
        {"op": "reply", "raw": rep(7, hubframes((0x39, 123))[:4], cnt=4)}, S]})
    cases.append({"name": "reset_clears", "ops": [
        {"op": "reply", "raw": rep(0, hubframes((0x39, 123)))}, {"op": "reset", "enabled": True}, S]})
    for c in cases:
        c["snapshots"] = run_tracker(c["ops"])
    return cases


# ---------------------------------------------------------------- msp.json
class _BytesPort:
    def __init__(self, data):
        self.d = bytearray(data)

    def read(self, n=1):
        b = bytes(self.d[:n])
        del self.d[:n]
        if not b:
            time.sleep(0.001)
        return b

    def write(self, b):
        pass


def msp_reply(cmd, payload, dirc=b">"):
    f = M.frame(cmd, payload)
    return b"$M" + dirc + f[3:]


def read_resp(raw):
    try:
        c, p = M.read_frame(_BytesPort(raw), timeout=0.05)
        return {"cmd": c, "payload": hx(p)}
    except ValueError as e:
        return {"error": "value", "message": str(e)}
    except TimeoutError as e:
        return {"error": "timeout", "message": str(e)}


def msp():
    status = struct.pack("<HHHIBHH", 100, 0, 0, 1, 0, 5, 0) + bytes([0]) + bytes([26]) + struct.pack("<I", 1 << 2) + b"\0"
    status2 = struct.pack("<HHHIBHH", 125, 1, 3, 0, 1, 12, 7) + bytes([2, 9, 9]) + bytes([26]) + \
        struct.pack("<I", (1 << 0) | (1 << 25)) + b"\0"
    status3 = struct.pack("<HHHIBHH", 125, 0, 0, 1, 0, 0, 0) + bytes([0]) + bytes([5]) + struct.pack("<I", 0xFFFFFFFF)
    frames = [{"cmd": c, "payload": hx(p), "frame": hx(M.frame(c, p))} for c, p in
              [(M.MSP_RC, b""), (M.MSP_STATUS, b""), (M.MSP_ATTITUDE, b""), (M.MSP_MOTOR, b""), (M.MSP_ANALOG, b""),
               (200, bytes([1, 2, 3])), (255, bytes(range(255)))]]
    good = msp_reply(M.MSP_RC, struct.pack("<8H", *range(1000, 1800, 100)))
    responses = {
        "good": good,
        "leading_junk": b"junk$" + good,
        "dollar_m_junk": b"$$MM" + good,
        "bad_checksum": good[:-1] + bytes([good[-1] ^ 1]),
        "error_reply": msp_reply(M.MSP_RC, b"", b"!"),
        "empty_payload": msp_reply(M.MSP_STATUS, b""),
        "truncated": good[:-3],
        "nothing": b"",
        "two_frames_first_only": good + msp_reply(M.MSP_STATUS, status),
        "other_dir_char": msp_reply(M.MSP_RC, b"\x01\x00", b"<"),
    }
    resp = [{"name": k, "raw": hx(v), "result": read_resp(v)} for k, v in responses.items()]
    parse = {
        "rc": [{"payload": hx(p), "result": M.parse_rc(p)} for p in
               (struct.pack("<8H", *range(1000, 1800, 100)), b"", b"\x01", b"\x01\x02\x03",
                struct.pack("<16H", *range(1000, 1016)))],
        "attitude": [{"payload": hx(p), "result": M.parse_attitude(p)} for p in
                     (struct.pack("<hhh", 15, -20, 90), struct.pack("<hhh", -1800, 900, -180),
                      struct.pack("<hhh", 0, 0, 359), struct.pack("<hhh", 32767, -32768, 0))],
        "analog": [{"payload": hx(p), "result": M.parse_analog(p)} for p in
                   (struct.pack("<BHHhH", 0, 0, 77, 0, 0), struct.pack("<BHHhH", 126, 500, 1023, -5, 1260),
                    struct.pack("<BHHhH", 255, 65535, 65535, -32768, 65535))],
        "status": [{"payload": hx(p), "result": M.parse_status(p)} for p in (status, status2, status3)],
        "motors": [{"payload": hx(struct.pack("<8H", 1000, 1500, 2000, 0, 0, 0, 0, 0)),
                    "result": M.parse_rc(struct.pack("<8H", 1000, 1500, 2000, 0, 0, 0, 0, 0))[:4]}],
    }
    return {"constants": {"STATUS": M.MSP_STATUS, "MOTOR": M.MSP_MOTOR, "RC": M.MSP_RC, "ATTITUDE": M.MSP_ATTITUDE,
                          "ANALOG": M.MSP_ANALOG, "ARMING_DISABLE": M.ARMING_DISABLE, "ARMED_FLAG": M.ARMED_FLAG},
            "frames": frames, "responses": resp, "parse": parse}


# ---------------------------------------------------------------- captures
def rep_json(r):
    if r is None:
        return None
    out = {k: v for k, v in r.items() if k not in ("hub", "fast")}
    out["hub"] = hx(r["hub"])
    if "fast" in r:
        out["fast"] = r["fast"]
    return out


def make_i4(raw, n):
    """int8 I/Q capture (fs 500k) -> shipped-int4 form: 2x boxcar decimate (fs 250k), 1.0..9.0 ms window, mean-remove,
    requantize to +-7 with a per-capture scale, pack I in the low nibble and Q in the high nibble."""
    a = np.frombuffer(raw, "i1").astype(np.float64).reshape(-1, 2)[:n]
    a = a[500:4500]  # 1.0 .. 9.0 ms at 500 kS/s
    a = a[: len(a) // 2 * 2].reshape(-1, 2, 2).mean(1)  # 2x boxcar
    a = a - a.mean(0)
    sc = 7.0 / max(np.abs(a).max(), 1e-9)
    q = np.clip(np.round(a * sc), -7, 7).astype(np.int8)
    packed = ((q[:, 0] & 0xF) | ((q[:, 1] & 0xF) << 4)).astype(np.uint8)
    return packed.tobytes(), len(q)


def captures():
    import zlib
    index = []
    src = json.load(open(os.path.join(SRC_CAPS, "index.json")))
    cdir = os.path.join(OUT, "captures")
    if os.path.isdir(cdir):
        shutil.rmtree(cdir)

    def entry(fmt, fname, payload, bits, fs, n, tid, note):
        e = {"file": f"{fmt}/{fname}", "format": fmt, "bits": bits, "fs": fs, "n": n, "bytes": len(payload),
             "crc": "%08x" % (zlib.crc32(payload) & 0xFFFFFFFF), "tid": tid, "note": note}
        p = unpack4(payload) if bits == 4 else payload
        iq = load_iq(p, n, 8 if bits == 4 else bits)
        e["expect"] = rep_json(decode_capture(iq, fs))
        index.append(e)
        write_bytes(os.path.join(cdir, e["file"]), payload)
        return e

    for m in src:
        raw = open(os.path.join(SRC_CAPS, m["file"]), "rb").read()
        entry("i8_d32", m["file"], raw, 8, m["fs"], m["n"], m["tid"], "real capture, 500 kS/s int8")
        pk, n4 = make_i4(raw, m["n"])
        entry("i4_d64", m["file"].replace(".iq8", ".iq4"), pk, 4, m["fs"] / 2, n4, m["tid"],
              "derived: 2x boxcar, 1-9 ms window, requantized to int4 (see make_i4)")
    rng = np.random.default_rng(1)
    noise = np.clip(np.round(rng.normal(0, 20, (4500, 2))), -128, 127).astype(np.int8)
    entry("i8_d32", "noise.iq8", noise.tobytes(), 8, 500000.0, 4500, 0, "seeded gaussian noise: must decode to nothing")
    n4raw, n4n = make_i4(noise.tobytes(), 4500)
    entry("i4_d64", "noise.iq4", n4raw, 4, 250000.0, n4n, 0, "noise, int4 form: must decode to nothing")
    dump(os.path.join(cdir, "index.json"), index)
    return index


def main():
    cmds = commands()
    dump(os.path.join(VEC, "commands.json"), cmds)
    write_commands_h(cmds)
    dump(os.path.join(VEC, "replies.json"), replies())
    dump(os.path.join(VEC, "reader.json"), reader())
    dump(os.path.join(VEC, "tlm_header.json"), tlm_header())
    dump(os.path.join(VEC, "unpack4.json"), unpack4_vectors())
    dump(os.path.join(VEC, "tid_rule.json"), tid_rule())
    dump(os.path.join(VEC, "hub.json"), hub())
    dump(os.path.join(VEC, "reply_parse.json"), reply_cases())
    dump(os.path.join(VEC, "tracker.json"), tracker())
    dump(os.path.join(VEC, "msp.json"), msp())
    idx = captures()
    miss = [e["file"] for e in idx if e["expect"] is None]
    print("captures:", len(idx), "undecoded:", miss)


if __name__ == "__main__":
    main()
