import json
import os
import threading
import time
import zlib

import numpy as np
import pytest

from d8tx import D8Link
from d8tx.hub import HubParser, HubState, PatchedField, armed_from_rpm
from d8tx.protocol import DEFAULT_FOFS_HZ, TLM_RECIPE
from d8tx.telemetry import (Tracker, decode_capture, load_iq, next_tid, parse_reply, payload_ok, rssi_dbm,
                            vbat_from_a1)

DATA = os.path.join(os.path.dirname(__file__), "data", "telemetry")
CAPS = json.load(open(os.path.join(DATA, "index.json")))


def load(i):
    m = CAPS[i]
    return m, open(os.path.join(DATA, m["file"]), "rb").read()


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


class TlmPort:
    """Fake ESP32 speaking protocol v1 + TLM/TID; captures are injected by the test."""
    def __init__(self, tlm_ok=True):
        self.lines, self.out_waiting = [], 0
        self._rx, self._lk = bytearray(), threading.Lock()
        self.linked, self.tlm_ok = False, tlm_ok

    def emit(self, b):
        with self._lk:
            self._rx += b if isinstance(b, bytes) else (b + "\n").encode()

    def inject(self, meta, payload):
        hdr = ("EV tlm k=%d ch=1 tid=%d fs=%d n=%d dec=%d bits=8 bytes=%d crc=%08x" %
               (meta["k"], meta["tid"], meta["fs"], meta["n"], meta["dec"], len(payload), zlib.crc32(payload) & 0xFFFFFFFF))
        self.emit(hdr.encode() + b"\n" + payload + b"\n")

    def read(self, n=1):
        with self._lk:
            d = bytes(self._rx[:n]); del self._rx[:n]
        if not d:
            time.sleep(0.002)
        return d

    def write(self, b):
        for ln in b.decode().splitlines():
            self.lines.append(ln)
            w = ln.split()
            if w[0] == "S":
                if not self.linked:
                    self.emit("OK")
            elif w[0] == "TID":
                if not self.linked:
                    self.emit("OK tid=%s" % w[1])
            elif w[0] == "TLM":
                self.emit("OK every=48" if self.tlm_ok else "ERR unknown cmd")
            elif w[0] == "LINK":
                self.linked = True; self.emit("OK")
            elif w[0] in ("STOP", "U"):
                if self.linked:
                    self.emit("EV link_end why=stop slots=5 late_max_us=7 retune_max_us=3")
                self.linked = False; self.emit("OK")
            else:
                self.emit("OK")
        return len(b)

    def close(self):
        pass


def wait(cond, t=3.0):
    end = time.time() + t
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


# ---- decode of real saved captures (bench/d8-tx/results/telemetry/20261108-002423-link, FOFS -75000)
@pytest.mark.parametrize("i", range(len(CAPS)))
def test_decode_real_captures(i):
    m, payload = load(i)
    assert payload_ok({"bytes": m["bytes"], "crc": m["crc"]}, payload)
    rep = decode_capture(load_iq(payload, m["n"], m["bits"]), m["fs"])
    e = m["expect"][0]
    assert rep is not None
    assert (rep["a1"], rep["a2"], rep["rssi"], rep["tid"]) == (e["a1"], e["a2"], e["rssi"], e["telemetry_id"])
    assert rep["hub"].hex() == e["hub"] and rep["hub_count"] == e["hub_count"]
    assert abs(rep["cfo_hz"] - e["cfo_hz"]) < 500


def test_noise_capture_is_a_miss():
    rng = np.random.default_rng(1)
    iq = rng.normal(0, 20, 5000) + 1j * rng.normal(0, 20, 5000)
    assert decode_capture(iq, 500000.0) is None


def test_parse_reply_layout():
    raw = bytes([0x11, 66, 178, 75, 26, 71, 3, 9, 0x5E, 0x03, 0x00, 0x1B, 0, 0, 0, 0, 0, 0, 0, 0])
    r = parse_reply(raw)
    assert (r["a1"], r["a2"], r["rssi"], r["hub_count"], r["tid"], r["hub"].hex()) == (75, 26, 71, 3, 9, "5e0300")


# ---- ack / TID rule
def test_tid_rule():
    assert next_tid(5, 5) == 6
    assert next_tid(5, None) == 5
    assert next_tid(5, 4) == 5  # reply to some other id: do not advance
    assert next_tid(31, 31) == 0


# ---- A1 / RSSI scaling (Betaflight 4.2.11)
def test_a1_scaling_and_battery():
    assert vbat_from_a1(0) == 0.0
    assert vbat_from_a1(75) == 3.75  # 1S at 3.75 V: getBatteryVoltage 375 (0.01 V) / 5
    assert vbat_from_a1(252) == 12.6
    clk = Clock()
    t = Tracker(clk)
    t.note_reply({"a1": 0, "a2": 1, "rssi": 71, "hub_count": 0, "tid": 0, "hub": b"", "cfo_hz": -12345.0})
    s = t.snapshot()
    assert s["vbat_v"] == 0.0 and s["battery"] == "absent" and s["a1_raw"] == 0
    t.note_reply({"a1": 252, "a2": 1, "rssi": 71, "hub_count": 0, "tid": 1, "hub": b""})
    s = t.snapshot()
    assert s["battery"] == "present" and s["vbat_v"] == 12.6


def test_rssi_inverse():
    assert rssi_dbm(71) == pytest.approx(-66.7, abs=1.0)  # bench replies 67..80
    assert rssi_dbm(80) < rssi_dbm(66) + 20 and rssi_dbm(66) < rssi_dbm(80)
    assert rssi_dbm(200) is None
    # round trip through the Betaflight forward map for every register value
    for v in range(256):
        fwd = (((v * 18) >> 5) - 82) if v >= 128 else (((v * 18) >> 5) + 65)
        want = (v - 256) / 2 - 72 if v >= 128 else v / 2 - 72
        assert abs(rssi_dbm(fwd & 0xFF) - want) <= 1.0, v


# ---- hub decoding and armed inference
def hubframes(*pairs):
    out = b""
    for fid, val in pairs:
        v = val & 0xFFFF
        body = bytes([v & 0xFF, v >> 8])
        body = body.replace(b"\x5d", b"\x5d\x3d").replace(b"\x5e", b"\x5d\x3e")
        out += bytes([0x5E, fid]) + body
    return out + b"\x5e"


def test_hub_parser_stuffing_and_split_chunks():
    data = hubframes((0x24, 0x5E5D), (0x03, 300), (0x28, -5))
    p = HubParser()
    got = []
    for i in range(0, len(data), 3):  # arbitrary chunking, as 10-byte reply chunks
        got += p.feed(data[i:i + 3])
    assert got == [(0x24, 0x5E5D), (0x03, 300), (0x28, -5)]


def test_armed_from_rpm_rules():
    assert armed_from_rpm(None) is None
    assert armed_from_rpm(500) is False          # capacity/5 outside the armed range: certainly disarmed
    assert armed_from_rpm(50) is False
    assert armed_from_rpm(300) is None           # could be capacity/5 or throttle/5
    assert armed_from_rpm(0) is None             # capacity 0 or motor_stop idle
    assert armed_from_rpm(260, baseline=0) is True
    assert armed_from_rpm(0, baseline=0) is None
    assert armed_from_rpm(300, baseline=300) is None
    assert armed_from_rpm(300, baseline=500) is True   # != baseline
    assert armed_from_rpm(500, baseline=500) is False
    assert armed_from_rpm(0, baseline=500) is True


def test_tracker_hub_and_armed_inference():
    clk = Clock()
    t = Tracker(clk)
    t.note_arm_on_air(False)

    def reply(tid, hub):
        t.note_reply({"a1": 75, "a2": 0, "rssi": 71, "hub_count": len(hub), "tid": tid, "hub": hub})

    reply(0, hubframes((0x03, 300), (0x02, 31), (0x24, 0), (0x25, 0), (0x26, 1000))[:10])
    s = t.snapshot()
    assert s["hub"]["rpm"] == 300 and s["armed"] is None  # ambiguous: no baseline yet, in range
    assert s["hub"]["raw"]["0x03"] == 300 and s["hub"]["temp1"] == 31 and s["hub"]["age_ms"] == 0
    clk.t += 3.0
    reply(1, hubframes((0x02, 30), (0x03, 300)))   # baseline learned (>= 2 s of ch7 low), twice
    clk.t += 0.5
    reply(2, hubframes((0x02, 32), (0x03, 300)))
    assert t.snapshot()["armed"] is None  # equal to baseline inside armed range: still ambiguous
    clk.t += 0.5
    t.note_arm_on_air(True)
    reply(3, hubframes((0x02, 33), (0x03, 260)))
    s = t.snapshot()
    assert s["armed"] is True and s["armed_source"] == "rpm"
    clk.t += 6.0  # stale rpm
    assert t.snapshot()["armed"] is None and t.snapshot()["armed_source"] is None


def test_hub_other_fields():
    st = HubState()
    now = 5.0
    for fid, v in [(0x24, -1000), (0x25, 0), (0x26, 1000), (0x14, 123), (0x39, 117), (0x28, 25), (0x04, 80), (0x05, 9)]:
        st.update(fid, v, now)
    s = st.snapshot(now + 0.2)
    assert s["acc_mg"] == [-1000, 0, 1000] and s["heading_deg"] == 123.0
    assert s["vfas_v"] == 11.7 and s["current_a"] == 2.5 and s["fuel"] == 80 and s["temp2"] == 9
    assert s["age_ms"] == 200 and s["patched"] == {}
    st2 = HubState()
    st2.update(0x3A, 6, now); st2.update(0x3B, 3, now)
    assert st2.vfas_v() == pytest.approx(12.6, abs=0.01)  # (6 + 0.3) * 2 (integer 110/21 = 5)


def test_patched_table_is_data_driven():
    table = [PatchedField(0x50, "armed", kind="bool"), PatchedField(0x50, "bit1", kind="bool", bit=1), PatchedField(0x51, "flight_mode"),
             PatchedField(0x52, "gyro_dps", index=0, size=3, scale=0.1, kind="float"),
             PatchedField(0x53, "gyro_dps", index=1, size=3, scale=0.1, kind="float")]
    clk = Clock()
    t = Tracker(clk, patched=table)
    rep = {"a1": 75, "a2": 0, "rssi": 71, "tid": 0, "hub_count": 0,
           "hub": hubframes((0x50, 1), (0x51, 4), (0x52, 123), (0x03, 500))}
    t.note_reply(rep)
    s = t.snapshot()
    assert s["hub"]["patched"]["armed"] is True and s["hub"]["patched"]["flight_mode"] == 4
    assert s["hub"]["patched"]["gyro_dps"] == [pytest.approx(12.3), None, None]
    assert s["armed"] is True and s["armed_source"] == "patched"  # beats the RPM rule (500 -> False)


# ---- catch rate / age windows
def test_catch_rate_and_age_windows():
    clk = Clock()
    t = Tracker(clk)
    s = t.snapshot()
    assert s["catch_rate"] is None and s["age_ms"] is None and not s["powered"] and not s["link"]
    rep = {"a1": 75, "a2": 0, "rssi": 71, "tid": 0, "hub_count": 0, "hub": b""}
    for _ in range(3):
        t.note_reply(rep); clk.t += 0.4
    t.note_trigger_miss()
    s = t.snapshot()
    assert s["triggers"] == 4 and s["replies"] == 3 and s["catch_rate"] == 0.75 and s["link"] and s["powered"]
    clk.t += 1.5  # last reply 1.9 s ago
    s = t.snapshot()
    assert not s["link"] and s["powered"] and 1800 <= s["age_ms"] <= 2100
    clk.t += 1.5
    assert not t.snapshot()["powered"]
    clk.t += 10.0  # all triggers fell out of the 10 s window; totals stay
    s = t.snapshot()
    assert s["catch_rate"] is None and s["triggers"] == 4
    t.reset(enabled=True)
    s = t.snapshot()
    assert s["enabled"] and s["triggers"] == 0 and s["rssi"] is None


# ---- D8Link integration through a fake serial
def test_start_sends_recipe_before_link_and_default_fofs():
    p = TlmPort()
    l = D8Link("x", serial_obj=p)
    l.start(power=100)
    assert p.lines.index(TLM_RECIPE) < next(i for i, x in enumerate(p.lines) if x.startswith("LINK"))
    assert "FOFS %d" % DEFAULT_FOFS_HZ in p.lines and DEFAULT_FOFS_HZ == -75000
    assert l.telemetry()["enabled"] is True and l.status()["tlm_enabled"] == 1
    l.stop()
    l.start(power=100, telemetry=False, fofs_hz=-1000)
    assert "TLM 0" in p.lines and "FOFS -1000" in p.lines
    assert l.telemetry()["enabled"] is False
    l.close()


def test_old_firmware_without_tlm_still_links():
    p = TlmPort(tlm_ok=False)
    l = D8Link("x", serial_obj=p)
    l.start()
    assert l.status()["link"] == 1 and l.telemetry()["enabled"] is False
    l.close()


def test_reader_interleaved_captures_events_and_tid_acks():
    p = TlmPort()
    l = D8Link("x", serial_obj=p)
    evs = []
    l.on_event(evs.append)
    l.start()
    for i in (0, 1):  # real captures; the int8 payloads contain 0x0a bytes
        m, payload = load(i)
        assert b"\n" in payload
        p.emit("EV link k=1")
        p.inject(m, payload)
        p.emit("EV tlm_drop k=5 ch=3 tid=%d try=0" % m["tid"])
        # a payload that decodes to nothing
        noise = np.random.default_rng(i).integers(-20, 20, 10000).astype(np.int8).tobytes()
        p.inject(dict(m, tid=m["tid"] + 1), noise)
    assert wait(lambda: l.telemetry()["triggers"] >= 6)
    s = l.telemetry()
    assert s["replies"] == 2 and s["triggers"] == 6 and s["catch_rate"] == pytest.approx(2 / 6, abs=0.01)
    assert s["a1_raw"] == 0 and s["rssi"] in (m["expect"][0]["rssi"] for m in CAPS) and s["rssi_dbm"] is not None
    assert s["link"] and s["powered"] and s["cfo_khz"] is not None
    assert s["hub"]["age_ms"] is not None or s["hub"]["raw"] == {}
    # ack rule: reply echoing tid 0 -> TID 1; miss on tid 1 -> TID 1 again; reply tid 1 -> TID 2; miss on tid 2 -> TID 2
    tids = [x for x in p.lines if x.startswith("TID ") and p.lines.index(x) > p.lines.index(TLM_RECIPE)]
    assert wait(lambda: len([x for x in p.lines if x.startswith("TID ")]) >= 3)
    tids = [x for x in p.lines if x.startswith("TID ")][1:]  # [0] is the idle TID before the recipe
    assert tids[:4] == ["TID 1", "TID 1", "TID 2", "TID 2"]
    assert any(e["name"] == "tlm_drop" for e in evs) and any(e["name"] == "link" for e in evs)
    # OK/EV lines still reach the request path after payloads
    assert l.stat() is not None
    l.close()


def test_tid_not_sent_after_link_end():
    p = TlmPort()
    l = D8Link("x", serial_obj=p)
    l.start()
    l.stop()
    n = len(p.lines)
    m, payload = load(0)
    p.inject(m, payload)
    assert wait(lambda: l.telemetry()["replies"] == 1)
    assert len(p.lines) == n
    l.close()


def test_default_patched_table_decodes_status_gyro_att():
    t = Tracker(Clock())
    # STATUS: armed + angle; gyro X = -12.5 deg/s; attitude yaw 90.0 deg; ARMING_DISABLE flags 0x0840; stock ACC id
    hub = hubframes((0x46, 0b000011), (0x47, 0x0840), (0x40, -125), (0x45, 900), (0x24, -1017))
    t.note_reply({"a1": 75, "a2": 0, "rssi": 71, "tid": 0, "hub_count": len(hub), "hub": hub})
    s = t.snapshot()
    p = s["hub"]["patched"]
    assert p["armed"] is True and p["angle"] is True and p["horizon"] is False and p["flight_mode"] == "angle"
    assert p["arming_disable_flags"] == 0x0840
    assert p["gyro_dps"] == [pytest.approx(-12.5), None, None] and p["attitude_deg"] == [None, None, pytest.approx(90.0)]
    assert s["hub"]["acc_mg"] == [-1017, None, None] and s["armed"] is True and s["armed_source"] == "patched"


def test_constant_hub_stream_keeps_refreshing():
    clk = Clock()
    t = Tracker(clk)
    hub = hubframes((0x03, 300))
    for tid in range(8):
        clk.t += 1.0
        t.note_reply({"a1": 75, "a2": 0, "rssi": 71, "hub_count": len(hub), "tid": tid, "hub": hub})
    assert t.snapshot()["hub"]["age_ms"] == 0
    clk.t += 1.0
    t.note_reply({"a1": 75, "a2": 0, "rssi": 71, "hub_count": len(hub), "tid": 7, "hub": hub})  # resend: skipped
    assert t.snapshot()["hub"]["age_ms"] == 1000


def test_vfas_low_precision_matches_betaflight_integer_ratio():
    h = HubState()
    h.update(0x3A, 7, 0.0)
    h.update(0x3B, 5, 0.0)
    assert h.vfas_v() == 15.0


# ---- FAST block (cnt bit 0x80), .ru/plans/fast-telemetry.md
def pack_fast(roll, pitch, yaw, gx, gy, gz, seq=0):
    m12, m14 = (1 << 12) - 1, (1 << 14) - 1
    v = (roll & m12) | ((pitch & m12) << 12) | (yaw << 24) | ((gx & m14) << 36) | ((gy & m14) << 50) \
        | ((gz & m14) << 64) | (seq << 78)
    return v.to_bytes(10, "little")


def fast_raw(block, tid=0, cnt=0x8A):
    return bytes([0x11, 0, 0, 60, 7, 70, cnt, tid]) + block


def test_fast_decode_signs_clamps_yaw():
    r = parse_reply(fast_raw(pack_fast(-1800, -900, 3599, -8191, 8191, -1, seq=3)))
    f = r["fast"]
    assert f["attitude_deg"] == [-180.0, -90.0, 359.9]
    assert f["gyro_dps"] == [-8191 * 0.25, 8191 * 0.25, -0.25] and f["seq"] == 3 and r["hub"] == b""
    f = parse_reply(fast_raw(pack_fast(1800, 900, 0, 8191, -8192, 0, seq=1)))["fast"]
    assert f["attitude_deg"] == [180.0, 90.0, 0.0] and f["gyro_dps"][1] == -2048.0 and f["seq"] == 1
    assert parse_reply(fast_raw(pack_fast(-1, 1, 1, 1, 1, 1)))["fast"]["attitude_deg"][:2] == [-0.1, 0.1]


def test_hub_cnt_unchanged():
    r = parse_reply(bytes([0x11, 0, 0, 1, 2, 3, 3, 5]) + b"\x5e\x24\x01\x00\x00\x00\x00\x00\x00\x00")
    assert "fast" not in r and r["hub"] == b"\x5e\x24\x01"


def test_tracker_fast_mixed_with_hub():
    clk = Clock(); t = Tracker(clk)
    assert t.snapshot()["fast"] is None
    hubrep = parse_reply(bytes([0x11, 0, 0, 1, 2, 3, 4, 0]) + bytes([0x5E, 0x39, 0x7B, 0x00]) + bytes(6))
    for i in range(6):
        clk.t += 0.25
        t.note_reply(parse_reply(fast_raw(pack_fast(10 * i, 0, 100, 4, 8, 12, seq=i & 3), tid=i)))
        if i == 2:
            t.note_reply(dict(hubrep, tid=9))
    s = t.snapshot()
    f = s["fast"]
    assert f["attitude_deg"][0] == 5.0 and f["gyro_dps"] == [1.0, 2.0, 3.0] and f["seq"] == 1 and f["age_ms"] == 0
    assert 3.5 < f["rate_hz"] < 4.5
    assert s["hub"]["vfas_v"] == pytest.approx(12.3) and s["replies"] == 7
    clk.t += 2
    assert t.snapshot()["fast"]["age_ms"] == 2000


def test_fast_does_not_disturb_hub_resend_filter():
    clk = Clock(); t = Tracker(clk)
    h = dict(parse_reply(bytes([0x11, 0, 0, 1, 2, 3, 4, 7]) + bytes([0x5E, 0x39, 0x7B, 0x00]) + bytes(6)))
    t.note_reply(h)
    t.note_reply(parse_reply(fast_raw(pack_fast(0, 0, 0, 0, 0, 0), tid=8)))
    t.note_reply(h)  # same tid+bytes as the last hub chunk: still a resend
    assert t.parser is not None and t.hub.age_s(0x39, clk()) is not None


def test_fast_replies_ack_tid_and_expose_fast(monkeypatch):
    import d8tx.link as lk
    seq = iter([0, 1, 2])
    def fake(iq, fs, hint=None, **kw):
        i = next(seq)
        return dict(parse_reply(fast_raw(pack_fast(15, -15, 900, 40, 0, 0, seq=i), tid=i)), shift_hz=0.0, cfo_hz=0.0)
    monkeypatch.setattr(lk, "decode_capture", fake)
    p = TlmPort(); l = D8Link("x", serial_obj=p); l.start()
    m, payload = load(0)
    for i in range(3):
        p.inject(dict(m, tid=i), payload)
    assert wait(lambda: len([x for x in p.lines if x.startswith("TID ")]) >= 4)
    assert [x for x in p.lines if x.startswith("TID ")][1:4] == ["TID 1", "TID 2", "TID 3"]
    f = l.telemetry()["fast"]
    assert f["attitude_deg"] == [1.5, -1.5, 90.0] and f["gyro_dps"] == [10.0, 0.0, 0.0] and f["seq"] == 2
    l.close()
