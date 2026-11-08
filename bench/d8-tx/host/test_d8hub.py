"""Offline tests: telemetry id ack/resend against a model of Betaflight appendFrSkyHubData, hub decoding.

    python -m pytest bench/d8-tx/host/test_d8hub.py
"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from d8hub import HubParser, acc_g, hub_frame, next_tid, patched_state  # noqa: E402


class BfRx:
    """Betaflight 4.2 appendFrSkyHubData (MAX_SERIAL_BYTES 64), fed by a byte source standing in for
    processFrSkyHubTelemetry."""

    def __init__(self, source: bytes, expected=0):
        self.src, self.pos = source, 0
        self.buf, self.gen = bytearray(64), 0
        self.sent = self.acked = 0
        self.expected = expected

    def reply(self, tid: int) -> bytes:
        if tid == self.expected:
            self.acked = self.sent
            self.expected = (tid + 1) & 0x1F
            if not self.gen:
                self.sent = 0
                chunk = self.src[self.pos:self.pos + 20]  # one "hub cycle"
                self.pos += len(chunk)
                self.buf[:len(chunk)] = chunk
                self.gen = len(chunk)
        else:
            self.sent = self.acked
        out = bytearray()
        for _ in range(10):
            if self.sent == self.gen:
                self.gen = 0
                break
            out.append(self.buf[self.sent])
            self.sent = (self.sent + 1) & 63
        return bytes(out)


def run_link(n, p_req_lost, p_rep_lost, expected0, seed, policy):
    rng = random.Random(seed)
    src = b"".join(hub_frame(0x24 + (i % 3), i * 7 - 300) for i in range(400))
    rx = BfRx(src, expected0)
    got = bytearray()
    tid = 0
    for _ in range(n):
        if rng.random() < p_req_lost:
            ids = []
        else:
            data = rx.reply(tid)
            if rng.random() < p_rep_lost:
                ids = []
            else:
                ids = [tid]
                got += data
        tid = policy(tid, ids)
    return src, bytes(got)


def test_next_tid_rule():
    assert next_tid(5, [5]) == 6
    assert next_tid(31, [31]) == 0
    assert next_tid(5, []) == 5
    assert next_tid(5, [4]) == 5


def good_frames(src, got):
    """Hub frames decoded from `got` that are real source frames, counted once, in source order."""
    want = HubParser().feed(src)
    idx = {(f[0], f[2]): i for i, f in enumerate(want)}  # values are unique per frame in run_link
    last, good = -1, 0
    for f in HubParser().feed(got):
        i = idx.get((f[0], f[2]))
        if i is not None and i > last:
            good, last = good + 1, i
    return good, len(want)


def test_lossless_link_delivers_exact_stream():
    src, got = run_link(300, 0.0, 0.0, 0, 0, next_tid)
    assert src.startswith(got) and len(got) > 1000


def test_ack_resend_beats_free_running_id_under_losses():
    free = lambda tid, ids: (tid + 1) & 0x1F  # noqa: E731  (old firmware: +1 every trigger)
    for seed in range(10):
        g_ack, n = good_frames(*run_link(600, 0.2, 0.2, 0, seed, next_tid))
        g_free, _ = good_frames(*run_link(600, 0.2, 0.2, 0, seed, free))
        assert g_ack > 2 * g_free, (seed, g_ack, g_free)
        assert g_ack > 0.6 * n, (seed, g_ack, n)


def test_ack_resend_syncs_from_unknown_expected():
    src, got = run_link(400, 0.0, 0.0, 17, 1, next_tid)
    # the first 17 requests use ids != expected and carry nothing; then the id is locked
    assert src.startswith(got) and len(got) > 1000


def test_hub_parser_stuffing_and_acc():
    data = hub_frame(0x24, 0) + hub_frame(0x25, -1000) + hub_frame(0x26, 1000) + hub_frame(0x10, 0x5E5D) + b"\x5e"
    assert b"\x5d\x3e" in data and b"\x5d\x3d" in data
    p = HubParser()
    # split at awkward places, including between escape bytes
    for i in range(0, len(data), 3):
        p.feed(data[i:i + 3])
    assert [(f[1], f[2]) for f in p.frames] == [("ACC_X", 0), ("ACC_Y", -1000), ("ACC_Z", 1000), ("ALT_BP", 0x5E5D)]
    assert acc_g(p.frames) == {"X": 0.0, "Y": -1.0, "Z": 1.0}


def test_hub_parser_ignores_leading_garbage():
    p = HubParser()
    p.feed(b"\x01\x02" + hub_frame(0x99, 3))
    assert p.frames == [(0x99, "0x99", 3)]


def test_patched_acc_true_milli_g():
    p = HubParser()
    p.feed(hub_frame(0x24, -37) + hub_frame(0x25, 0x5E5D & 0x7FFF) + hub_frame(0x26, 996) + b"\x5e")
    assert acc_g(p.frames) == {"X": -0.037, "Y": 0x5E5D / 1000.0, "Z": 0.996}


def test_patched_status_gyro_attitude():
    # one patched cycle: STATUS armed+acro (0x21), ARMING_DISABLE 0x2000, gyro, attitude (0x5E in yaw -> stuffed)
    yaw = 0x035E  # 862 = 86.2 deg, low byte 0x5E needs stuffing
    raw = (hub_frame(0x46, 0x21) + hub_frame(0x47, 0x2000) + hub_frame(0x40, -1234) + hub_frame(0x41, 5)
           + hub_frame(0x42, 20000) + hub_frame(0x43, -153) + hub_frame(0x44, 80) + hub_frame(0x45, yaw) + b"\x5e")
    assert b"\x5d\x3e" in raw
    p = HubParser()
    for i in range(0, len(raw), 10):  # D8 chunks of 10 bytes
        p.feed(raw[i:i + 10])
    s = patched_state(p.frames)
    assert s["status"] == {"armed": True, "angle": False, "horizon": False, "failsafe": False,
                           "arming_disabled": False, "acro": True}
    assert s["arming_disable_flags"] == 0x2000
    assert s["gyro"] == {"X": -123.4, "Y": 0.5, "Z": 2000.0}
    assert s["att"] == {"roll": -15.3, "pitch": 8.0, "yaw": 86.2}


def test_patched_state_empty_on_stock():
    p = HubParser()
    p.feed(hub_frame(0x24, 1000) + hub_frame(0x06, 1234) + b"\x5e")
    assert patched_state(p.frames) == {}
