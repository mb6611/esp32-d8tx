"""FrSky hub byte-stream parser and field decoding (Betaflight 4.2.11 telemetry/frsky_hub.c).

Wire format (frsky_hub.c frSkyHubWriteFrame L158-165, serializeFrSkyHub): 0x5E id lo hi, lo/hi byte-stuffed
(0x5E -> 0x5D 0x3E, 0x5D -> 0x5D 0x3D); one 0x5E tail per 125 ms cycle.

Betaflight source paths below are relative to bench/cc2500-rxdiag/firmware/work/betaflight/src/main.
"""
from __future__ import annotations

from dataclasses import dataclass

HUB_IDS = {
    0x01: "GPS_ALT_BP", 0x09: "GPS_ALT_AP", 0x02: "TEMP1", 0x03: "RPM", 0x04: "FUEL", 0x05: "TEMP2",
    0x06: "VOLT", 0x10: "ALT_BP", 0x21: "ALT_AP", 0x11: "GPS_SPEED_BP", 0x19: "GPS_SPEED_AP",
    0x12: "LON_BP", 0x1A: "LON_AP", 0x22: "E_W", 0x13: "LAT_BP", 0x1B: "LAT_AP", 0x23: "N_S",
    0x14: "COURSE_BP", 0x1C: "COURSE_AP", 0x15: "DATE_MONTH", 0x16: "YEAR", 0x17: "HOUR_MINUTE",
    0x18: "SECOND", 0x24: "ACC_X", 0x25: "ACC_Y", 0x26: "ACC_Z", 0x28: "CURRENT", 0x30: "VERT_SPEED",
    0x39: "VOLTAGE_AMP", 0x3A: "VOLTAGE_AMP_BP", 0x3B: "VOLTAGE_AMP_AP", 0x40: "GYRO_X", 0x41: "GYRO_Y",
    0x42: "GYRO_Z",
}


class HubParser:
    """Feed hub bytes in arrival order; returns the (id, int16 value) frames completed by each feed()."""

    def __init__(self):
        self._id = None
        self._val: list[int] = []
        self._esc = False

    def reset(self):
        self._id, self._val, self._esc = None, [], False

    def feed(self, data: bytes) -> list[tuple[int, int]]:
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
                out.append((self._id, v))
                self._id, self._val = None, []
        return out


@dataclass(frozen=True)
class PatchedField:
    """One field of the patched Betaflight hub table (see "Patched Betaflight hub fields" in d8tx/PROTOCOL.md).

    key: name in hub["patched"]. index: None for a scalar, else the position in a vector field.
    size: vector length (with index). scale: value = raw * scale. kind: "int" | "float" | "bool" (bool: bit `bit` of
    the raw value, or raw != 0 when bit is None). Several rows may share a hub_id (bit fields)."""
    hub_id: int
    key: str
    index: int | None = None
    size: int = 1
    scale: float = 1.0
    kind: str = "int"
    bit: int | None = None


# Data-driven table: add rows here when the patched firmware gains hub IDs.
# Source of truth: "Patched Betaflight hub fields" in d8tx/PROTOCOL.md (bench/betaflight-patch).
PATCHED_FIELDS: list[PatchedField] = [
    PatchedField(0x46, "armed", kind="bool", bit=0),
    PatchedField(0x46, "angle", kind="bool", bit=1),
    PatchedField(0x46, "horizon", kind="bool", bit=2),
    PatchedField(0x46, "failsafe", kind="bool", bit=3),
    PatchedField(0x46, "arming_disabled", kind="bool", bit=4),
    PatchedField(0x46, "acro", kind="bool", bit=5),
    PatchedField(0x47, "arming_disable_flags"),
    *[PatchedField(0x40 + i, "gyro_dps", index=i, size=3, scale=0.1, kind="float") for i in range(3)],
    *[PatchedField(0x43 + i, "attitude_deg", index=i, size=3, scale=0.1, kind="float") for i in range(3)],
]

# Armed throttle range of the stock RPM field, see armed_from_rpm.
RPM_ARMED_MIN, RPM_ARMED_MAX = 200, 400


def armed_from_rpm(rpm, baseline=None):
    """Radio-confirmed armed state on stock firmware from the RPM hub field, or None when ambiguous.

    frsky_hub.c L186-207 sendThrottleOrBatterySizeAsRpm (no ESC sensor): armed -> rcCommand[THROTTLE] / 5
    (BLADE_NUMBER_DIVIDER L133), forced to 0 at THROTTLE_LOW with FEATURE_MOTOR_STOP; disarmed ->
    batteryCapacity / 5. rcCommand[THROTTLE] is 1000..2000, so armed values are 0 or 200..400.
    - rpm outside {0} + [200, 400]: cannot be armed -> False.
    - baseline (the disarmed value, learned while the link sent ch7 low): rpm != baseline -> True;
      rpm == baseline -> False if the baseline is outside the armed range, else None.
    - no baseline, rpm in the armed range -> None (battery capacity/5 may overlap).
    With USE_ESC_SENSOR_TELEMETRY (L190-193) the field is the ESC RPM/10 instead, so this inference does not apply.
    Limit: an armed drone at idle throttle with motor_stop reads 0, as does capacity 0 (the default).
    """
    if rpm is None:
        return None
    in_range = rpm == 0 or RPM_ARMED_MIN <= rpm <= RPM_ARMED_MAX
    if not in_range:
        return False
    if baseline is not None:
        if rpm != baseline:
            return True
        return None if (baseline == 0 or RPM_ARMED_MIN <= baseline <= RPM_ARMED_MAX) else False
    return None


class HubState:
    """Last value of every hub id plus the decoded convenience fields. Not thread-safe (caller locks)."""

    def __init__(self, patched=None):
        self.patched_fields: dict[int, list[PatchedField]] = {}
        for f in (PATCHED_FIELDS if patched is None else patched):
            self.patched_fields.setdefault(f.hub_id, []).append(f)
        self.raw: dict[int, int] = {}
        self.t_id: dict[int, float] = {}
        self.patched: dict = {}
        self.t_last = None

    def update(self, hub_id: int, value: int, now: float):
        self.raw[hub_id] = value
        self.t_id[hub_id] = now
        self.t_last = now
        for pf in self.patched_fields.get(hub_id, ()):
            if pf.kind == "bool":
                v = bool((value >> pf.bit) & 1) if pf.bit is not None else bool(value)
            elif pf.kind == "float":
                v = value * pf.scale
            else:
                v = value
            if pf.index is None:
                self.patched[pf.key] = v
            else:
                vec = self.patched.setdefault(pf.key, [None] * pf.size)
                vec[pf.index] = v
        p = self.patched
        if "angle" in p:  # derived: STATUS flight mode
            p["flight_mode"] = "angle" if p["angle"] else "horizon" if p["horizon"] else "acro"

    def get(self, hub_id):
        return self.raw.get(hub_id)

    def age_s(self, hub_id, now):
        t = self.t_id.get(hub_id)
        return None if t is None else now - t

    def vfas_v(self):
        """frsky_hub.c L394-411 sendVoltageAmp: ID 0x39 = 0.1 V units (high precision), else 0x3A/0x3B
        carry voltage*(110/21) as BP (/100) and AP (tenths); 110/21 is integer 5 in C, so V = (BP + AP/10) * 2."""
        v = self.raw.get(0x39)
        if v is not None:
            return v / 10.0
        bp, ap = self.raw.get(0x3A), self.raw.get(0x3B)
        if bp is not None and ap is not None:
            return round((bp + ap / 10.0) * 2.0, 2)
        return None

    def snapshot(self, now, armed_baseline=None):
        r = self.raw
        acc = [r.get(0x24), r.get(0x25), r.get(0x26)]
        cur = r.get(0x28)
        return {
            # ACC: stock firmware truncates to whole g before x1000 (frsky_hub.c L181); patched = true milli-g.
            "acc_mg": acc if any(a is not None for a in acc) else None,
            "heading_deg": float(r[0x14]) if 0x14 in r else None,  # sendHeading L443-446: yaw in whole degrees
            "rpm": r.get(0x03),
            "vfas_v": self.vfas_v(),
            "current_a": None if cur is None else cur / 10.0,  # L417: getAmperage() (0.01 A) / 10
            "fuel": r.get(0x04),  # L421-428: percent if battery capacity set, else mAh drawn
            "temp1": r.get(0x02), "temp2": r.get(0x05),
            "patched": {k: (list(v) if isinstance(v, list) else v) for k, v in self.patched.items()},
            "raw": {"0x%02X" % k: v for k, v in sorted(r.items())},
            "age_ms": None if self.t_last is None else int((now - self.t_last) * 1000),
        }
