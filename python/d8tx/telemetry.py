"""D8 radio telemetry: capture payload parsing, reply decoding, TID rule and the rolling state behind D8Link.telemetry().

The ESP32 firmware (TLM stream=1) ships an int8 I/Q capture after each trigger as `EV tlm ... bytes=N` + N raw
bytes + "\\n". decode_capture() demodulates it with the vendored D8 decoder; Tracker keeps the state.
Betaflight source paths are relative to tools/cc2500-rxdiag/firmware/work/betaflight/src/main (4.2.11).
"""
from __future__ import annotations

import re
import threading
import zlib
from collections import deque

import numpy as np

from .demod import StandardDecoder
from .hub import HubParser, HubState, armed_from_rpm
from .protocol import TXID

RE_KV = re.compile(r"(\w+)=(-?[0-9a-fA-F]+)")
REPLY_LEN = 0x11  # frame[0], cc2500_frsky_d.c L134
POWERED_S, LINK_S, CATCH_WINDOW_S = 3.0, 1.0, 10.0
RPM_FRESH_S = 5.0
SHIFTS = tuple(float(s) for s in range(-150000, 150001, 25000))  # carrier shifts searched (FOFS + receiver offset)


def parse_tlm_header(line: str) -> dict:
    """`EV tlm k=.. tid=.. bytes=..` -> ints (crc stays a hex string)."""
    out = {}
    for k, v in RE_KV.findall(line):
        out[k] = v if k == "crc" else int(v)
    return out


def load_iq(payload: bytes, n: int, bits: int = 8) -> np.ndarray:
    """int8 (stream=1) or int16 LE I,Q interleaved -> complex with Q negated (RF = LO + f)."""
    a = np.frombuffer(payload, "<i2" if bits == 16 else "i1").astype(np.float64).reshape(-1, 2)[:n]
    return a[:, 0] - 1j * a[:, 1]


def payload_ok(meta: dict, payload: bytes) -> bool:
    return len(payload) == meta.get("bytes", -1) and (zlib.crc32(payload) & 0xFFFFFFFF) == int(meta.get("crc", "0"), 16)


FAST_FLAG = 0x80  # reply cnt byte bit 7: payload is a FAST block, not hub bytes (.ru/plans/fast-telemetry.md)
FAST_WINDOW_S = 5.0


def _sx(v: int, bits: int) -> int:
    v &= (1 << bits) - 1
    return v - (1 << bits) if v >> (bits - 1) else v


def parse_fast(block: bytes) -> dict:
    """10-byte FAST block = little-endian 80-bit integer: roll s12, pitch s12 (deci-deg), yaw u12 (deci-deg 0..3599),
    gyro x/y/z s14 (0.25 deg/s), seq u2 at bits 78-79."""
    v = int.from_bytes(bytes(block[:10]), "little")
    yaw = (v >> 24) & 0xFFF
    return {
        "attitude_deg": [_sx(v, 12) / 10.0, _sx(v >> 12, 12) / 10.0, yaw / 10.0],
        "gyro_dps": [_sx(v >> 36, 14) * 0.25, _sx(v >> 50, 14) * 0.25, _sx(v >> 64, 14) * 0.25],
        "seq": (v >> 78) & 3,
    }


def parse_reply(raw: bytes) -> dict:
    """18-byte D8 telemetry frame (cc2500_frsky_d.c buildTelemetryFrame L117-148):
    [0]=0x11 [1,2]=bind txid [3]=A1 [4]=A2 [5]=(uint8)rssiDbm [6]=hub byte count [7]=echoed tid [8..]=hub bytes."""
    out = {"a1": raw[3], "a2": raw[4], "rssi": raw[5], "hub_count": raw[6], "tid": raw[7]}
    if raw[6] & FAST_FLAG:
        out["hub"] = b""
        out["fast"] = parse_fast(raw[8:18])
    else:
        out["hub"] = bytes(raw[8:8 + min(raw[6], 10)])
    return out


def decode_capture(iq: np.ndarray, fs: float, hint=None, txid=TXID, shifts=SHIFTS):
    """Search carrier shifts (hint first) for a CRC-valid telemetry frame. Returns dict(parse_reply + cfo_hz,
    shift_hz) or None."""
    x = iq - iq.mean()
    if not np.any(x):
        return None
    order = list(shifts)
    if hint is not None:
        order = [hint] + [s for s in order if s != hint]
    for s in order:
        if abs(s) + 40e3 > fs / 2:
            continue
        dec = StandardDecoder(fs, shift_hz=float(s))
        for r in dec.decode(x, fix1=False, first_ok=True):
            p = r.packet
            if p.crc_ok and tuple(p.tx_id) == tuple(txid) and p.raw[0] == REPLY_LEN:
                out = parse_reply(p.raw)
                out.update(cfo_hz=float(r.cfo) + float(s), shift_hz=float(s), t_ms=r.t * 1e3)
                return out
    return None


def next_tid(sent: int, reply_tid) -> int:
    """Betaflight re-request rule (cc2500_frsky_d.c appendFrSkyHubData L76-107): the receiver acks its previous hub
    bytes only when the request id equals its expected id (last + 1, mod 32). The id advances only after a reply
    that echoed it came back; after a miss the same id is sent again."""
    return (sent + 1) & 0x1F if reply_tid == sent else sent & 0x1F


def rssi_dbm(byte: int):
    """Invert cc2500setRssiDbm (rx/cc2500_common.c L62-69) and convert the CC2500 RSSI register to dBm
    (datasheet 17.3: <128: v/2-72; >=128: (v-256)/2-72). The reply byte is (uint8)rssiDbm, where
    rssiDbm = v*18/32 + 65 for v < 128 (65..136) and v*18/32 - 82 for v >= 128 (-10..61); the ranges do not
    overlap, so the register value v is recoverable (to ~2 steps). None for bytes outside both ranges."""
    s = byte - 256 if byte >= 246 else byte
    if 65 <= s <= 136:
        v = (s - 65) * 32.0 / 18.0
        return round(v / 2.0 - 72.0, 1)
    if -10 <= s <= 61:
        v = (s + 82) * 32.0 / 18.0
        return round((v - 256.0) / 2.0 - 72.0, 1)
    return None


def vbat_from_a1(a1: int) -> float:
    """cc2500_frsky_d.c L129 (FRSKY_SPI_A1_SOURCE_VBAT): a1 = (getBatteryVoltage() / 5) & 0xff with
    getBatteryVoltage in 0.01 V (sensors/battery.c L505-508, voltage.h L44) -> 0.05 V per count.
    Wraps above 12.75 V (4S reads low); the hub VFAS field has no such limit."""
    return round(a1 * 0.05, 2)


class Tracker:
    """Thread-safe rolling telemetry state. Time comes from `clock` (seconds)."""

    def __init__(self, clock, patched=None):
        self._clock = clock
        self._lk = threading.Lock()
        self._patched = patched
        self.reset(enabled=False)

    def reset(self, enabled: bool):
        with self._lk:
            self.enabled = enabled
            self.triggers = self.replies = 0
            self.window: deque = deque()  # (t, hit)
            self.t_reply = None
            self.last: dict | None = None
            self.hub = HubState(self._patched)
            self.parser = HubParser()
            self.prev_chunk = None
            self.prev_tid = None
            self.fast_last: dict | None = None
            self.t_fast = None
            self.fast_times: deque = deque()
            self.armed_low_since = None
            self.rpm_base = None
            self.rpm_base_n = 0

    # --- inputs
    def note_trigger_miss(self):
        now = self._clock()
        with self._lk:
            self.triggers += 1
            self.window.append((now, False))

    def note_reply(self, rep: dict) -> None:
        """rep from decode_capture (a CRC-valid reply to a trigger)."""
        now = self._clock()
        with self._lk:
            self.triggers += 1
            self.replies += 1
            self.window.append((now, True))
            self.t_reply = now
            self.last = rep
            if "fast" in rep:  # fast block: never touches hub data or the resend filter
                self.fast_last, self.t_fast = rep["fast"], now
                self.fast_times.append(now)
                return
            chunk = rep["hub"]
            # A resend (same echoed tid and same bytes, after a miss) is skipped; equal content on a new tid is fresh.
            if chunk and not (rep["tid"] == self.prev_tid and chunk == self.prev_chunk):
                for hid, val in self.parser.feed(chunk):
                    self.hub.update(hid, val, now)
                    if hid == 0x03:
                        self._learn_rpm(val, now)
            if chunk:
                self.prev_chunk, self.prev_tid = chunk, rep["tid"]

    def note_arm_on_air(self, high: bool):
        now = self._clock()
        with self._lk:
            if high:
                self.armed_low_since = None  # stop learning; the learned baseline stays valid for this link
            elif self.armed_low_since is None:
                self.armed_low_since = now

    def _learn_rpm(self, val, now):
        # Disarmed baseline: RPM values received >= 2 s after the link began sending ch7 low (arm switch low disarms).
        if self.armed_low_since is not None and now - self.armed_low_since >= 2.0:
            if self.rpm_base_n >= 2:
                pass  # locked: a disarmed receiver reports a constant (capacity / 5)
            elif self.rpm_base == val:
                self.rpm_base_n += 1
            else:
                self.rpm_base, self.rpm_base_n = val, 1

    # --- output
    def snapshot(self) -> dict:
        now = self._clock()
        with self._lk:
            while self.window and now - self.window[0][0] > CATCH_WINDOW_S:
                self.window.popleft()
            n = len(self.window)
            catch = (sum(1 for _, h in self.window if h) / n) if n else None
            age = None if self.t_reply is None else now - self.t_reply
            last = self.last or {}
            hub = self.hub.snapshot(now)
            a1 = last.get("a1")
            vbat = None if a1 is None else vbat_from_a1(a1)
            vfas, vfas_age = hub["vfas_v"], self.hub.age_s(0x39, now)
            if vfas is not None and vfas_age is not None and vfas_age <= POWERED_S:
                vbat = vfas  # not wrapped at 12.75 V
            armed, src = None, None
            pa = hub["patched"].get("armed")
            if pa is not None and (self.hub.age_s(self._armed_id(), now) or 0) <= RPM_FRESH_S:
                armed, src = bool(pa), "patched"
            else:
                rage = self.hub.age_s(0x03, now)
                if rage is not None and rage <= RPM_FRESH_S:
                    base = self.rpm_base if self.rpm_base_n >= 2 else None
                    a = armed_from_rpm(hub["rpm"], base)
                    if a is not None:
                        armed, src = a, "rpm"
            while self.fast_times and now - self.fast_times[0] > FAST_WINDOW_S:
                self.fast_times.popleft()
            fast = None
            if self.fast_last is not None:
                n, t0 = len(self.fast_times), (self.fast_times[0] if self.fast_times else now)
                rate = (n - 1) / (now - t0) if n > 1 and now > t0 else 0.0  # intervals per second over the window
                fast = dict(self.fast_last, age_ms=int((now - self.t_fast) * 1000),
                            rate_hz=round(rate, 2))
            return {
                "fast": fast,
                "enabled": self.enabled,
                "powered": age is not None and age <= POWERED_S,
                "link": age is not None and age <= LINK_S,
                "age_ms": None if age is None else int(age * 1000),
                "catch_rate": None if catch is None else round(catch, 3),
                "triggers": self.triggers, "replies": self.replies,
                "rssi": last.get("rssi"),
                "rssi_dbm": None if "rssi" not in last else rssi_dbm(last["rssi"]),
                "a1_raw": a1, "a2_raw": last.get("a2"),
                "vbat_v": vbat,
                "battery": None if vbat is None else ("absent" if vbat < 2.0 else "present"),
                "cfo_khz": None if "cfo_hz" not in last else round(last["cfo_hz"] / 1000.0, 2),
                "hub": hub,
                "armed": armed, "armed_source": src,
            }

    def _armed_id(self):
        for fs in self.hub.patched_fields.values():
            for f in fs:
                if f.key == "armed":
                    return f.hub_id
        return -1


def idle_snapshot(enabled: bool = False) -> dict:
    """All keys present, nothing known (used by tests and by callers without telemetry)."""
    return Tracker(lambda: 0.0).snapshot() | {"enabled": enabled}
