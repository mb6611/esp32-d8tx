#!/usr/bin/env python3
"""Telemetry-listen experiment host (firmware TLM / TCAP, protocol/PROTOCOL.md "Telemetry listen").

Drives the ESP32 d8tone firmware, saves every `EV tlm` capture under
tools/d8-tx-host/runs/<run>/ (the 2026-11-07/08 runs are in experiments/09-telemetry/data/), and decodes it with tools/d8-tx-host/d8.py, looking
for a CRC-valid 18-byte FrSky D8 telemetry frame 0x11, 66, 178, A1, A2, RSSI, hub count,
telemetry id, hub bytes.

    # battery-on trial: LINK with a telemetry trigger every 47 slots, ~20 s (old blocking dump)
    python tlm_listen.py link --seconds 20 --every 47 --power 127 --fofs -50000
    # LINK keeps sending while the capture goes out (int8), host acks the telemetry id, MSP log
    python tlm_listen.py link --seconds 60 --every 48 --power 127 --fofs -50000 --stream --ack \
        --cap-us 9000 --msp /dev/cu.usbmodem0x80000001
    # one capture, no keying (receiver check; 2440 MHz has a 40 MHz crystal harmonic)
    python tlm_listen.py tcap 2439900
    # one capture right after keying one data packet on that channel (turnaround check)
    python tlm_listen.py tcap 2412000 --pre 127
    # decode saved captures again
    python tlm_listen.py decode experiments/09-telemetry/data/<run>

ch7 (ARM) is always 1000 and throttle 1000 in the S stream; the firmware gates ch7 too.
Run with a Python that has numpy + pyserial.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
import zlib

import numpy as np

_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import d8  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from d8hub import HubParser, acc_g, next_tid  # noqa: E402

# new runs land here; move a run into a new experiments/NN-*/data/ to keep it
RESULTS = os.path.join(_ROOT, "tools", "d8-tx-host", "runs")
TXID = (66, 178)
SLOT_S = 0.008994
S_LINE = b"S 1000 1500 1500 1500 1000 1000 1000 1000\n"  # TAER1234, throttle low, ch7 (ARM) low
RE_KV = re.compile(r"(\w+)=(-?[0-9a-fA-F]+)")


# ---------------------------------------------------------------- decoding
def load_iq(raw: bytes, n: int, bits: int = 16) -> np.ndarray:
    """int16 LE (or int8, TLM stream=1) I,Q interleaved -> complex, Q negated (RF = LO + f, as host CAP16 decoding)."""
    a = np.frombuffer(raw, "<i2" if bits == 16 else "i1").astype(np.float64).reshape(-1, 2)[:n]
    return a[:, 0] - 1j * a[:, 1]


def frame_info(raw: bytes) -> dict:
    """Fields of a D8 telemetry frame (Betaflight cc2500_frsky_d.c buildTelemetryFrame)."""
    n = raw[6]
    rssi = raw[5] - 256 if raw[5] >= 128 else raw[5]
    return {"hex": raw[:18].hex(), "a1": raw[3], "a2": raw[4], "rssi_dbm": rssi, "hub_count": n,
            "telemetry_id": raw[7], "hub": raw[8:8 + min(n, 10)].hex(),
            "a1_vbat_v_if_vbat_source": round(raw[3] * 5 / 100.0, 2)}


def decode_capture(iq: np.ndarray, fs: float, shifts=None) -> list[dict]:
    """Search carrier shifts (the drone's FSCTRL0 offset and our FOFS move it) for CRC-valid frames."""
    if shifts is None:
        shifts = np.arange(-150e3, 150e3 + 1, 25e3)
    hits: list[dict] = []
    x = iq - iq.mean()
    if not np.any(x):
        return hits
    for s in shifts:
        if abs(s) + 40e3 > fs / 2:
            continue
        dec = d8.StandardDecoder(fs, shift_hz=float(s))
        for r in dec.decode(x, fix1=False):
            p = r.packet
            if not p.crc_ok:
                continue
            h = {"t_ms": round(r.t * 1e3, 3), "shift_hz": float(s), "cfo_hz": round(float(r.cfo) + float(s), 0),
                 "sync_errors": r.sync_errors, "txid": list(p.tx_id), "telemetry": p.tx_id == TXID and p.raw[0] == 0x11}
            h.update(frame_info(p.raw))
            if not any(abs(o["t_ms"] - h["t_ms"]) < 2 and o["hex"] == h["hex"] for o in hits):
                hits.append(h)
    return hits


def stats(iq: np.ndarray, fs: float) -> dict:
    x = iq - iq.mean()
    p = np.abs(x) ** 2
    blk = max(1, int(fs * 250e-6))  # 250 us power envelope
    nb = len(p) // blk
    env = p[: nb * blk].reshape(nb, blk).mean(1) if nb else p
    med = float(np.median(env)) or 1e-12
    spec = np.fft.fftshift(np.abs(np.fft.fft(x * np.hanning(len(x)))) ** 2)
    f = np.fft.fftshift(np.fft.fftfreq(len(x), 1 / fs))
    k = int(np.argmax(spec))
    return {"dc_i": round(float(iq.real.mean()), 1), "dc_q": round(float(iq.imag.mean()), 1),
            "rms": round(float(np.sqrt(p.mean())), 1), "peak_abs": round(float(np.abs(iq).max()), 1),
            "env_db_over_median": [round(10 * np.log10(e / med), 1) for e in env],
            "spec_peak_hz": round(float(f[k]), 0),
            "spec_peak_db_over_median": round(float(10 * np.log10(spec[k] / (np.median(spec) or 1e-12))), 1),
            "bursts_ms": [(round(a / fs * 1e3, 2), round(b / fs * 1e3, 2))
                          for a, b in d8.find_bursts(iq, fs, min_ms=1.0, max_ms=20.0, thresh_db=8.0)]}


# ---------------------------------------------------------------- serial
class Board:
    def __init__(self, port: str, baud: int = 921600):
        import serial
        self.s = serial.Serial(port, baud, timeout=0.05)
        self.buf = b""
        self.raw = open(os.environ["TLM_RAW"], "wb") if os.environ.get("TLM_RAW") else None  # debug: tee every byte

    def _read(self, n: int) -> bytes:
        d = self.s.read(n)
        if self.raw and d:
            self.raw.write(d)
            self.raw.flush()
        return d

    def readline(self, timeout: float) -> str | None:
        end = time.time() + timeout
        while b"\n" not in self.buf:
            if time.time() > end:
                return None
            self.buf += self._read(4096)
        line, self.buf = self.buf.split(b"\n", 1)
        return line.decode("ascii", "replace").strip()

    def readn(self, n: int, timeout: float) -> bytes:
        end = time.time() + timeout
        while len(self.buf) < n and time.time() < end:
            self.buf += self._read(max(4096, n - len(self.buf)))
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def cmd(self, line: str, timeout: float = 2.0) -> str:
        self.s.write((line + "\n").encode())
        end = time.time() + timeout
        while time.time() < end:
            r = self.readline(end - time.time())
            if r is None:
                break
            if r.startswith("OK") or r.startswith("ERR"):
                return r
            if r:
                print("  <", r)
        raise RuntimeError(f"no reply to {line!r}")

    def read_capture(self, header: str) -> tuple[dict, bytes]:
        kv = {k: v for k, v in RE_KV.findall(header)}
        meta = {k: (int(v) if k != "crc" else v) for k, v in kv.items()}
        raw = self.readn(meta["bytes"] + 1, 5.0)
        data = raw[: meta["bytes"]]
        meta["crc_ok"] = len(data) == meta["bytes"] and (zlib.crc32(data) & 0xFFFFFFFF) == int(kv["crc"], 16)
        return meta, data


def save(run_dir: str, idx: int, meta: dict, data: bytes, extra: dict) -> dict:
    os.makedirs(run_dir, exist_ok=True)
    base = os.path.join(run_dir, f"cap{idx:04d}")
    with open(base + ".iq16", "wb") as f:
        f.write(data)
    fs = 16e6 / meta["dec"]
    iq = load_iq(data, meta["n"], meta.get("bits", 16))
    rec = dict(meta, **extra, fs=fs, file=os.path.basename(base) + ".iq16")
    rec["stats"] = stats(iq, fs)
    rec["frames"] = decode_capture(iq, fs) if meta["crc_ok"] else []
    with open(base + ".json", "w") as f:
        json.dump(rec, f, indent=1)
    return rec


def summary_line(rec: dict) -> str:
    s = rec["stats"]
    tel = [h for h in rec["frames"] if h["telemetry"]]
    t = (f" TELEMETRY a1={tel[0]['a1']} a2={tel[0]['a2']} rssi={tel[0]['rssi_dbm']}dBm id={tel[0]['telemetry_id']}"
         f" hub[{tel[0]['hub_count']}]={tel[0]['hub']} t={tel[0]['t_ms']}ms cfo={tel[0]['cfo_hz']}") if tel else ""
    return (f"k={rec.get('k')} ch={rec.get('ch')} tid={rec.get('tid')} turn={rec.get('turn_ns', 0) / 1000:.1f}us "
            f"run={rec.get('run_us')}us n={rec['n']} g={rec.get('g0')}/{rec.get('g1')} lost={rec.get('lost')} "
            f"bad={rec.get('bad')} late={rec.get('late')} work={rec.get('work')} crc={'ok' if rec['crc_ok'] else 'BAD'} "
            f"rms={s['rms']} peak={s['peak_abs']} dc=({s['dc_i']},{s['dc_q']}) bursts={s['bursts_ms']} "
            f"frames={len(rec['frames'])}{t}")


def run_dir_for(tag: str) -> str:
    return os.path.join(RESULTS, time.strftime("%Y%m%d-%H%M%S") + "-" + tag)


# ---------------------------------------------------------------- modes
def mode_tcap(a) -> None:
    b = Board(a.port)
    print(b.cmd("PING"))
    if a.fofs is not None:
        print(b.cmd(f"FOFS {a.fofs}"))
    rd = run_dir_for("tcap")
    for i in range(a.count):
        b.s.write(f"TCAP {a.khz} {a.cap_us} {a.gain} {a.dec} {a.pre}\n".encode())
        end = time.time() + 5
        while time.time() < end:
            line = b.readline(end - time.time())
            if line is None:
                raise RuntimeError("no EV tlm")
            if line.startswith("EV tlm "):
                meta, data = b.read_capture(line)
                rec = save(rd, i, meta, data, {"mode": "tcap", "khz": a.khz, "pre_pwr": a.pre, "gain_req": a.gain})
                print(summary_line(rec))
            elif line.startswith("OK") or line.startswith("ERR"):
                if line.startswith("ERR"):
                    print(line)
                break
    print("saved", rd)


def mode_link(a) -> None:
    b = Board(a.port)
    print(b.cmd("PING"))
    if a.fofs is not None:
        print(b.cmd(f"FOFS {a.fofs}"))
    print(b.cmd(f"TLM {a.every} {a.cap_us} {a.gain} {a.dec} {1 if a.same else 0} {int(a.stream)} {int(a.ack)}"
                f" {int(a.mark)} {a.retry}"))
    print(b.cmd(f"TID {a.tid0}"))
    print(b.cmd(f"TLMX {a.tlmx}"))
    rd = run_dir_for("link")
    stop = threading.Event()
    lock = threading.Lock()
    os.makedirs(rd, exist_ok=True)
    json.dump(vars(a), open(os.path.join(rd, "args.json"), "w"), indent=1)
    hub = HubParser()
    hub_bytes = 0
    msp_th = None
    if a.msp:
        import bf_msp
        import serial

        def msp_watch():
            port = serial.Serial(a.msp, 115200, timeout=0.05)
            if a.msp_rc_hz:  # RC-only fast poll (ch8 trigger marker, see --mark); stop.is_set() ends it via seconds
                with open(os.path.join(rd, "msp_rc.csv"), "w") as f:
                    bf_msp.fast(port, f, a.seconds + 1.0, a.msp_rc_hz)
                port.close()
                return
            with open(os.path.join(rd, "msp.log"), "w") as f:
                while not stop.is_set():
                    try:
                        line = bf_msp.row(bf_msp.sample(port))
                    except (TimeoutError, ValueError) as e:
                        line = "%.3f ERR %s" % (time.time(), e)
                    f.write(line + "\n")
                    f.flush()
                    time.sleep(0.1)
            port.close()
        msp_th = threading.Thread(target=msp_watch, daemon=True)
        msp_th.start()

    def sender():
        nxt = time.perf_counter()
        while not stop.is_set():
            with lock:
                b.s.write(S_LINE)
            nxt += SLOT_S
            d = nxt - time.perf_counter()
            if d > 0:
                time.sleep(d)
            else:
                nxt = time.perf_counter()

    with lock:
        b.s.write(f"LINK {a.power} {a.timeout}\n".encode())
    line = b.readline(2.0)
    t_link0 = time.time()
    print("<", line)
    if not line or not line.startswith("OK"):
        raise RuntimeError("LINK refused")
    th = threading.Thread(target=sender, daemon=True)
    th.start()
    t_end = time.time() + a.seconds
    n_cap = n_tel = 0
    drops: list[dict] = []
    probes: list[dict] = []
    tries_hit: dict[int, int] = {}
    tries_cap: dict[int, int] = {}
    link_end = ""
    log = open(os.path.join(rd, "events.log"), "w")
    log.write(f"{t_link0:.4f} host LINK OK\n")
    try:
        while time.time() < t_end:
            line = b.readline(1.0)
            if line is None:
                continue
            log.write(f"{time.time():.3f} {line[:300]}\n")
            if line.startswith("EV tlm "):
                meta, data = b.read_capture(line)
                rec = save(rd, n_cap, meta, data, {"mode": "link", "power": a.power, "fofs": a.fofs,
                                                    "every": a.every, "same": a.same})
                n_cap += 1
                tel = [h for h in rec["frames"] if h["telemetry"]]
                n_tel += bool(tel)
                tr = int(meta.get("try", 0))
                tries_cap[tr] = tries_cap.get(tr, 0) + 1
                tries_hit[tr] = tries_hit.get(tr, 0) + bool(tel)
                print(summary_line(rec))
                if tel and tel[0]["hub_count"]:
                    hb = bytes.fromhex(tel[0]["hub"])
                    hub_bytes += len(hb)
                    for f in hub.feed(hb):
                        print("  hub", f[1], f[2], acc_g([f]) or "")
                if a.ack:
                    nt = next_tid(meta["tid"], [h["telemetry_id"] for h in tel])
                    with lock:
                        b.s.write(f"TID {nt}\n".encode())
                    log.write(f"{time.time():.3f} host TID {nt}\n")
            elif line.startswith("EV probe"):
                probes.append({k: int(v) for k, v in RE_KV.findall(line)})
            elif line.startswith("EV tlm_drop"):
                drops.append({k: int(v) for k, v in RE_KV.findall(line)})
                print("<", line)
            elif line.startswith("EV link_end"):
                print("<", line)
                link_end = line
                break
            elif line:
                print("<", line)
    finally:
        stop.set()
        th.join(1)
        b.s.write(b"STOP\n")
        end = time.time() + 2
        while time.time() < end:
            line = b.readline(end - time.time())
            if line is None:
                break
            if line.startswith("EV tlm "):
                b.read_capture(line)  # drain
                continue
            print("<", line)
            log.write(f"{time.time():.3f} {line[:300]}\n")
            if line.startswith("OK") or line.startswith("ERR"):
                break
        b.cmd("TLM 0")
        log.close()
        if msp_th:
            msp_th.join(1)
    # per request = shipped captures (the last try of each request); per attempt = every trigger packet sent
    n_att = n_cap + len(drops)
    att_hit = n_tel  # each request has at most one decoded reply (its shipped capture)
    print(f"requests={n_cap} caught={n_tel} ({100.0 * n_tel / max(n_cap, 1):.1f}%) attempts={n_att} "
          f"attempt_catch={100.0 * att_hit / max(n_att, 1):.1f}% first_try={tries_hit.get(0, 0)}/{tries_cap.get(0, 0) + sum(1 for d in drops if d.get('try') == 0)} "
          f"by_try_cap={tries_cap} by_try_hit={tries_hit} drops={len(drops)} probes={len(probes)}")
    json.dump({"captures": n_cap, "with_telemetry": n_tel, "attempts": n_att, "drops": drops, "probes": probes,
               "tries_cap": tries_cap, "tries_hit": tries_hit, "link_end": link_end, "t_link0": t_link0,
               "hub_bytes": hub_bytes,
               "hub_frames": [list(f) for f in hub.frames], "acc_g": acc_g(hub.frames)},
              open(os.path.join(rd, "result.json"), "w"), indent=1)
    print(f"captures={n_cap} with_telemetry={n_tel} hub_bytes={hub_bytes} hub_frames={len(hub.frames)} saved {rd}")


def mode_decode(a) -> None:
    for name in sorted(os.listdir(a.dir)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(a.dir, name)
        rec = json.load(open(path))
        data = open(os.path.join(a.dir, rec["file"]), "rb").read()
        iq = load_iq(data, rec["n"], rec.get("bits", 16))
        rec["stats"] = stats(iq, rec["fs"])
        rec["frames"] = decode_capture(iq, rec["fs"])
        json.dump(rec, open(path, "w"), indent=1)
        print(name, summary_line(rec))


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", default="/dev/cu.usbserial-0001")
    sub = ap.add_subparsers(dest="mode", required=True)

    def common(p):
        p.add_argument("--cap-us", type=int, default=10000)
        p.add_argument("--gain", type=int, default=40, help="manual RX gain code, -1 = hardware AGC")
        p.add_argument("--dec", type=int, default=32, choices=(16, 32, 64))
        p.add_argument("--fofs", type=int, default=None, help="FOFS Hz before the run (LO offset for TX and RX)")

    p = sub.add_parser("link")
    common(p)
    p.add_argument("--seconds", type=float, default=20)
    p.add_argument("--every", type=int, default=47)
    p.add_argument("--power", type=int, default=127)
    p.add_argument("--timeout", type=int, default=1000)
    p.add_argument("--same", action="store_true", help="listen on the trigger channel (default: next hop channel)")
    p.add_argument("--stream", action="store_true", help="TLM stream=1: int8 capture shipped while LINK keeps sending")
    p.add_argument("--ack", action="store_true", help="TLM ack=1: host sends TID (id+1 after a reply, same id after a miss)")
    p.add_argument("--tid0", type=int, default=0, help="first telemetry id")
    p.add_argument("--msp", default=None, help="FC MSP port: log RSSI/failsafe to msp.log every 0.1 s")
    p.add_argument("--msp-rc-hz", type=float, default=0,
                   help="instead of msp.log, poll MSP_RC at this rate into msp_rc.csv (drone-side receipt of --mark)")
    p.add_argument("--mark", action="store_true",
                   help="TLM mark=1: ch8 = 1500 us on trigger packets, 1600 on re-triggers, else 1000 (outside aux ranges)")
    p.add_argument("--tlmx", default="0 0", help='TLMX "tail_bits settle_us [all]" end-of-trigger experiment knobs')
    p.add_argument("--retry", type=int, default=0, choices=(0, 1, 2, 3),
                   help="TLM retry=N (needs --stream): re-trigger at the next free slot when the on-chip check sees no reply")
    p = sub.add_parser("tcap")
    common(p)
    p.add_argument("khz", type=int)
    p.add_argument("--pre", type=int, default=-1, help="key one data packet at this power first (-1 = none)")
    p.add_argument("--count", type=int, default=1)
    p = sub.add_parser("decode")
    p.add_argument("dir")
    a = ap.parse_args(argv)
    {"link": mode_link, "tcap": mode_tcap, "decode": mode_decode}[a.mode](a)


if __name__ == "__main__":
    main()
