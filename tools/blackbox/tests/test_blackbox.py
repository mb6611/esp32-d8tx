"""Offline tests: capture splitting, MSP scanning, flash download (fake FC), CLI helper, decode (C + Python), plot.
Run: tools/blackbox/.venv/bin/python -m pytest tools/blackbox/tests -q
"""
import hashlib, io, os, struct, sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import bbl, bbcapture, bbcli, bbdecode, bbplot, make_sample  # noqa: E402

SAMPLE = os.path.join(HERE, "data", "sample_capture.raw")
SAMPLE_SHA256 = "47e9aa4c98cd7c34d99b6f1152ef037ccb7bde549af46c9fa67d3e15858f2b1b"
needs_c = pytest.mark.skipif(bbdecode.find_decoder() is None, reason="blackbox_decode not built (build_decoder.sh)")


def raw():
    return open(SAMPLE, "rb").read()


def test_sample_pinned_and_reproducible():
    d = raw()
    assert hashlib.sha256(d).hexdigest() == SAMPLE_SHA256
    assert make_sample.build() == d


# ---------------------------------------------------------------- encoders round-trip

@pytest.mark.parametrize("vals", [[0, 1, -2], [3, -4, 7], [20, -31, 5], [100, -40000, 9000000], [-2**31, 2**31 - 1, 0]])
def test_tag2_3s32_roundtrip(vals):
    b = bytearray()
    bbl.write_tag2_3s32(b, vals)
    assert bbl.Reader(bytes(b)).tag2_3s32() == vals


@pytest.mark.parametrize("vals", [[0, 0, 0, 0], [1, -8, 0, 7], [5, 100, -3, 0], [-7, 300, 2, -129], [32767, -32768, 1, 120]])
def test_tag8_4s16_roundtrip(vals):
    b = bytearray()
    bbl.write_tag8_4s16(b, vals)
    r = bbl.Reader(bytes(b))
    assert r.tag8_4s16() == vals and r.eof()


# ---------------------------------------------------------------- capture splitting

def test_split_sample_two_sessions_and_msp_outside():
    d = raw()
    sessions, outside = bbl.split_stream(d)
    assert len(sessions) == 2 and all(s.complete for s in sessions)
    frames = [f for c in outside for f in bbl.msp_frames(c)[0]]
    assert [(f[0], f[1]) for f in frames] == [(">", 110), (">", 101), (">", 101)]
    body = bbl.sessions_bytes(d, sessions)
    assert body.startswith(bbl.LOG_START) and body.endswith(bbl.LOG_END)
    assert len(bbl.find_logs(body)) == 2
    assert b"$M>" not in body[:20] and len(body) == sum(s.end - s.start for s in sessions)


def test_split_truncated_session_and_no_session():
    d = raw()
    s1 = bbl.split_stream(d)[0][0]
    cut = d[:s1.start + 5000]                     # Ctrl-C while armed: no LOG_END
    sessions, _ = bbl.split_stream(cut)
    assert len(sessions) == 1 and not sessions[0].complete and sessions[0].end == len(cut)
    sessions, outside = bbl.split_stream(b"$M>\x00\x65\x65noise")
    assert sessions == [] and bbl.msp_frames(outside[0])[0] == [(">", 101, b"")]


def test_msp_jumbo_frame():
    payload = bytes(range(256)) * 2
    body = bytes([255, 71]) + struct.pack("<H", len(payload)) + payload
    fr = b"$M>" + body + bytes([bbl.msp_checksum(body)])
    assert bbl.msp_frames(b"xx" + fr)[0] == [(">", 71, payload)]


class FakePort:
    """Serves a byte stream in chunks; replies to MSP requests via a handler."""
    is_fake = True

    def __init__(self, stream=b"", handler=None, chunk=777):
        self.rx, self.handler, self.chunk, self.tx = bytearray(stream), handler, chunk, bytearray()

    @property
    def in_waiting(self):
        return min(len(self.rx), self.chunk)

    def read(self, n=1):
        d = bytes(self.rx[:min(n, self.chunk)])
        del self.rx[:len(d)]
        return d

    def write(self, b):
        self.tx += b
        if self.handler:
            f = bbl.parse_msp_at(bytes(b), 0) if b.startswith(b"$M<") else None
            if f:
                self.rx += self.handler(f[1], f[2])
            else:
                self.rx += self.handler(None, bytes(b)) or b""


def test_record_stops_after_sessions_and_writes_bbl(tmp_path):
    d = raw()
    ticks = iter(range(10**6))
    port = FakePort(d)
    got = bbcapture.record(port, str(tmp_path / "c.raw"), sessions=2, idle=3, log=lambda *a: None,
                           clock=lambda: next(ticks) * 0.001)
    assert (tmp_path / "c.raw").read_bytes() == got
    s = bbcapture.split_and_write(got, str(tmp_path / "c"))
    assert s["sessions"] == 2 and s["complete"] == 2 and s["msp_frames_outside"] >= 2
    s1 = bbl.split_stream(d)[0][0]
    assert bbl.find_logs((tmp_path / "c.bbl").read_bytes()) == [0, s1.end - s1.start]


def test_record_idle_timeout_without_log_end(tmp_path):
    d = raw()
    s1 = bbl.split_stream(d)[0][0]
    ticks = iter(range(10**6))
    msgs = []
    got = bbcapture.record(FakePort(d[:s1.start + 4000]), str(tmp_path / "c.raw"), sessions=1, idle=0.5,
                           log=msgs.append, clock=lambda: next(ticks) * 0.01)
    assert any("idle" in m for m in msgs) and len(got) == s1.start + 4000


def msp_reply(cmd, payload):
    if len(payload) >= 255:
        body = bytes([255, cmd]) + struct.pack("<H", len(payload)) + payload
    else:
        body = bytes([len(payload), cmd]) + payload
    return b"$M>" + body + bytes([bbl.msp_checksum(body)])


def _batt_port(analog, batt):
    def h(c, p):
        if c == 110:
            return msp_reply(110, struct.pack("<BHHhH", *analog))
        if c == 130 and batt is not None:
            return msp_reply(130, struct.pack("<BHBHhBH", *batt))
        return msp_reply(c, b"")[:2] + b"!" + msp_reply(c, b"")[3:]  # error reply
    return FakePort(handler=h)


def test_vbat_check_parses_analog():
    # cells, cap, dv, mAh, cA, state, cV
    port = _batt_port((0, 0, 0, 0, 3), (0, 300, 0, 0, 0, 4, 2))
    r = bbcapture.battery_readings(port)
    assert r == {"analog_dv": 0.0, "analog_cv": 0.03, "cells": 0, "batt_dv": 0.0, "batt_state": 4, "batt_cv": 0.02}
    assert bbcapture.vbat_volts(port, r) == pytest.approx(0.03)


def test_vbat_check_takes_worst_reading():
    # a 1S pack: legacy 0.1 V byte says 4.1 V even if another field were misread as ~0
    port = _batt_port((41, 0, 0, 0, 0), None)
    assert bbcapture.vbat_volts(port) == pytest.approx(4.1)
    port = _batt_port((0, 0, 0, 0, 0), (1, 300, 0, 0, 0, 0, 0))
    assert bbcapture.vbat_volts(port) == float("inf")  # a detected cell refuses even at 0 V
    port = _batt_port((0, 0, 0, 0, 0), (0, 300, 0, 0, 0, 4, 395))
    assert bbcapture.vbat_volts(port) == pytest.approx(3.95)


def test_flash_download_no_flash(tmp_path):
    msgs = []
    port = FakePort(handler=lambda c, p: msp_reply(70, struct.pack("<BIII", 0, 0, 0, 0)))
    assert bbcapture.flash_download(port, str(tmp_path / "f.bbl"), log=msgs.append) is None
    assert "no onboard dataflash" in msgs[0]


def test_flash_download_with_flash(tmp_path):
    img = bbl.split_stream(raw())[0]
    flash = bbl.sessions_bytes(raw(), img)

    def fc(cmd, p):
        if cmd == 70:
            return msp_reply(70, struct.pack("<BIII", 3, 64, 2 * 1024 * 1024, len(flash)))
        addr, n, _ = struct.unpack("<IHB", p)
        n = min(n, 2048, len(flash) - addr)        # FC may return less than asked
        return msp_reply(71, struct.pack("<IHB", addr, n, 0) + flash[addr:addr + n])

    out = bbcapture.flash_download(FakePort(handler=fc), str(tmp_path / "f.bbl"), chunk=4096, log=lambda *a: None)
    assert open(out, "rb").read() == flash


# ---------------------------------------------------------------- CLI helper

def test_cli_apply_and_error_stops():
    seen = []

    def fc(cmd, b):
        line = b.decode().strip()
        seen.append(line)
        if line == "#":
            return b"\r\nEntering CLI Mode, type 'exit' to return, or 'help'\r\n\r\n# "
        if line in ("save", "exit"):
            return b"\r\n# Rebooting\r\n"
        if line.startswith("set bogus"):
            return (line + "\r\n###ERROR IN set: INVALID NAME: bogus###\r\n\r\n# ").encode()
        return (line + "\r\nblackbox_device set to SERIAL\r\n\r\n# ").encode()

    cmds = bbcli.config_lines(open(os.path.join(ROOT, "config", "enable_serial_vcp.txt")).read())
    assert cmds[0] == "serial 20 129 115200 57600 0 2000000" and "set blackbox_device = SERIAL" in cmds
    ok, tr = bbcli.run(FakePort(handler=fc), cmds, save=True)
    assert ok and seen[-1] == "save" and "blackbox_device set to SERIAL" in tr
    seen.clear()
    ok, _ = bbcli.run(FakePort(handler=fc), ["set bogus = 1", "set blackbox_device = SERIAL"], save=True)
    assert not ok and seen[-1] == "exit" and "set blackbox_device = SERIAL" not in seen


# ---------------------------------------------------------------- decode + plot

def expected_rows():
    out = []
    for n, t0, seed in ((600, 5_000_000, 1), (400, 42_000_000, 2)):
        _, names, rows = bbl.synth_session(n, t0_us=t0, seed=seed)
        out.append((names, rows))
    return out


def test_python_parser_matches_ground_truth():
    body = bbl.sessions_bytes(raw(), bbl.split_stream(raw())[0])
    logs = bbl.parse(body)
    assert len(logs) == 2
    for log, (names, rows) in zip(logs, expected_rows()):
        assert log.fields == names and log.ended and log.corrupt == 0 and len(log.main) == len(rows)
        for got, want in zip(log.main, rows):
            assert got[1:] == want[1:]             # loopIteration: see README (BF 4.x 'P interval' quirk)
        assert [s[1][0] for s in log.slow] == [1, 3]


def load(csv):
    c = bbplot.read_csv(csv)
    return {k: [int(x) for x in v] for k, v in c.items()}


@needs_c
def test_c_decoder_matches_python(tmp_path):
    p = tmp_path / "cap.bbl"
    p.write_bytes(bbl.sessions_bytes(raw(), bbl.split_stream(raw())[0]))
    c = bbdecode.decode(str(p), str(tmp_path / "c"), engine="c")
    py = bbdecode.decode(str(p), str(tmp_path / "py"), engine="py")
    assert len(c) == len(py) == 2
    for fc, fp, (names, rows) in zip(c, py, expected_rows()):
        cc, cp = load(fc), load(fp)
        for n in names:
            k = "time (us)" if n == "time" else n
            assert cc[k] == cp[k], n
        assert cc["gyroADC[1]"] == [r[names.index("gyroADC[1]")] for r in rows]


@pytest.mark.parametrize("engine", ["py", pytest.param("c", marks=needs_c)])
def test_plot_multi_session(tmp_path, engine):
    p = tmp_path / "cap.bbl"
    p.write_bytes(bbl.sessions_bytes(raw(), bbl.split_stream(raw())[0]))
    res = bbplot.plot([str(p)], str(tmp_path), engine)
    assert [os.path.basename(r["png"]) for r in res] == ["cap.01.png", "cap.02.png"]
    assert [r["frames"] for r in res] == [600, 400]
    for r in res:
        assert open(r["png"], "rb").read(8) == b"\x89PNG\r\n\x1a\n" and os.path.getsize(r["png"]) > 20000
        assert r["rate_hz"] == pytest.approx(1000, rel=0.01)


def test_cli_enter_when_already_in_cli_and_leave_on_reboot():
    def fc(cmd, b):
        if b == b"#":
            return b"#"  # already in CLI: only the echo
        if b == b"\r\n":
            return b"\r\n# "
        return b""
    port = FakePort(handler=fc)
    assert bbcli.enter(port).endswith("# ")

    class Gone(FakePort):
        def read(self, n=1):
            raise OSError(6, "Device not configured")
    assert "port closed" in bbcli.leave(Gone(), False)


def test_reconstruct_header_splices_and_decodes(tmp_path):
    import reconstruct_header as rh
    w = bbl.Writer(main=rh.main_table(rssi=True, yaw_d=False, amperage=True))
    w.header()
    full = bytes(w.out)
    k = full.find(b"\nH Field S predictor")
    tail = full[k - 3:]  # the capture lost everything before the end of the 'Field S signed' line
    out = rh.rebuild(tail, rh.main_table(rssi=True, yaw_d=False, amperage=True))
    assert out.startswith(bbl.LOG_START)
    assert b"RECONSTRUCTED" in out
    assert out.count(b"H Field I name:") == 1
    want = full[:k + 1]
    assert out[:len(want)] == want  # identical to the original header start
    with pytest.raises(ValueError):
        rh.rebuild(b"garbage", rh.main_table())
