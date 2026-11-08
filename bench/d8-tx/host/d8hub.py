"""FrSky D8 telemetry helpers: telemetry-id ack rule and FrSky hub byte-stream decoder.

Betaflight 4.2 cc2500_frsky_d.c appendFrSkyHubData: the receiver keeps telemetryIdExpected. A
request whose packet[4] equals it acknowledges the previous hub bytes, sets expected = id + 1 (mod 32)
and sends new bytes; any other id makes it resend from the last acknowledged byte without moving
expected. The reply echoes the request id in frame[7]. So the transmitter advances the id only after
it received a reply to that id and repeats the same id after a miss (next_tid). Starting out of step,
the id moves +1 per received reply until it meets expected, then stays locked.

Hub stream (telemetry/frsky_hub.c): frames 0x5E id lo hi (int16 LE), lo/hi byte-stuffed
(0x5E -> 0x5D 0x3E, 0x5D -> 0x5D 0x3D); one 0x5E tail per 125 ms cycle. Hub bytes are only sent when
the receiver's FEATURE_TELEMETRY is on (frSkyDInit); with it off, frame[6] (hub count) is always 0.
"""
from __future__ import annotations

HUB_IDS = {
    0x01: "GPS_ALT_BP", 0x09: "GPS_ALT_AP", 0x02: "TEMP1", 0x03: "RPM", 0x04: "FUEL", 0x05: "TEMP2",
    0x06: "VOLT", 0x10: "ALT_BP", 0x21: "ALT_AP", 0x11: "GPS_SPEED_BP", 0x19: "GPS_SPEED_AP",
    0x12: "LON_BP", 0x1A: "LON_AP", 0x22: "E_W", 0x13: "LAT_BP", 0x1B: "LAT_AP", 0x23: "N_S",
    0x14: "COURSE_BP", 0x1C: "COURSE_AP", 0x15: "DATE_MONTH", 0x16: "YEAR", 0x17: "HOUR_MINUTE",
    0x18: "SECOND", 0x24: "ACC_X", 0x25: "ACC_Y", 0x26: "ACC_Z", 0x28: "CURRENT", 0x30: "VERT_SPEED",
    0x39: "VOLTAGE_AMP", 0x3A: "VOLTAGE_AMP_BP", 0x3B: "VOLTAGE_AMP_AP", 0x40: "GYRO_X", 0x41: "GYRO_Y",
    0x42: "GYRO_Z",
    # patched Betaflight (bench/betaflight-patch): not sent by stock
    0x43: "ATT_ROLL", 0x44: "ATT_PITCH", 0x45: "ATT_YAW", 0x46: "STATUS", 0x47: "ARMING_DISABLE",
}

STATUS_BITS = {0: "armed", 1: "angle", 2: "horizon", 3: "failsafe", 4: "arming_disabled", 5: "acro"}


def next_tid(sent: int, reply_ids) -> int:
    """Id for the next request: sent+1 if a reply echoing `sent` came back, else `sent` again."""
    return (sent + 1) & 0x1F if sent in set(reply_ids) else sent & 0x1F


class HubParser:
    """Feed hub bytes in arrival order; collects (id, name, int16 value) frames."""

    def __init__(self):
        self.frames: list[tuple[int, str, int]] = []
        self._id = None
        self._val: list[int] = []
        self._esc = False

    def feed(self, data: bytes) -> list[tuple[int, str, int]]:
        out = []
        for b in data:
            if b == 0x5E:  # header or tail: (re)start
                self._id, self._val, self._esc = -1, [], False
                continue
            if self._id is None:
                continue  # no header seen yet
            if self._id == -1:
                self._id = b
                continue
            if self._esc:
                b ^= 0x60  # 0x3E -> 0x5E, 0x3D -> 0x5D
                self._esc = False
            elif b == 0x5D:
                self._esc = True
                continue
            self._val.append(b)
            if len(self._val) == 2:
                v = self._val[0] | self._val[1] << 8
                v = v - 0x10000 if v & 0x8000 else v
                f = (self._id, HUB_IDS.get(self._id, "0x%02X" % self._id), v)
                out.append(f)
                self._id, self._val = None, []
        self.frames += out
        return out


def acc_g(frames) -> dict:
    """Latest ACC X/Y/Z in g. Works for both firmwares: the patched one sends true milli-g, stock the
    truncated whole-g*1000 values described next (both are just value/1000). Betaflight 4.2 sends (int16_t)(accADC * acc_1G_rec) * 1000: the value is
    truncated toward zero to whole g before the x1000, so it is only ever 0, +-1000, +-2000 ... A level
    drone reads Z = 0 whenever its measured Z is a hair under 1 g (bench: 0.996 g -> 0)."""
    d = {}
    for i, name, v in frames:
        if name.startswith("ACC_"):
            d[name[-1]] = v / 1000.0
    return d


def patched_state(frames) -> dict:
    """Latest values of the patched-Betaflight fields (empty keys if the firmware is stock).
    gyro in deg/s (wire: 0.1 deg/s), att roll/pitch/yaw in degrees (wire: deci-degrees, yaw 0..359.9),
    status flags as bools, arming_disable_flags = low 16 bits of armingDisableFlags."""
    d = {}
    for _, name, v in frames:
        if name.startswith("GYRO_"):
            d.setdefault("gyro", {})[name[-1]] = v / 10.0
        elif name.startswith("ATT_"):
            d.setdefault("att", {})[name[4:].lower()] = v / 10.0
        elif name == "STATUS":
            u = v & 0xFFFF
            d["status"] = {n: bool(u >> b & 1) for b, n in STATUS_BITS.items()}
        elif name == "ARMING_DISABLE":
            d["arming_disable_flags"] = v & 0xFFFF
    return d


def stuff(data: bytes) -> bytes:
    """Byte stuffing as Betaflight serializeFrSkyHub (for tests)."""
    o = bytearray()
    for b in data:
        o += b"\x5d\x3e" if b == 0x5E else b"\x5d\x3d" if b == 0x5D else bytes([b])
    return bytes(o)


def hub_frame(fid: int, value: int) -> bytes:
    v = value & 0xFFFF
    return bytes([0x5E, fid]) + stuff(bytes([v & 0xFF, v >> 8]))
