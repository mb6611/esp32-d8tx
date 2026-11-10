"""Minimal read-only MSP v1 client for Betaflight (ported from tools/d8-tx-host/bf_msp.py)."""
import struct
import threading
import time

MSP_STATUS, MSP_MOTOR, MSP_RC, MSP_ATTITUDE, MSP_ANALOG = 101, 104, 105, 108, 110
ARMING_DISABLE = ["NO_GYRO", "FAILSAFE", "RX_FAILSAFE", "BAD_RX_RECOVERY", "BOXFAILSAFE", "RUNAWAY_TAKEOFF",
                  "CRASH_DETECTED", "THROTTLE", "ANGLE", "BOOT_GRACE_TIME", "NOPREARM", "LOAD", "CALIBRATING",
                  "CLI", "CMS_MENU", "BST", "MSP", "PARALYZE", "GPS", "RESC", "RPMFILTER", "REBOOT_REQUIRED",
                  "DSHOT_BBANG", "ACC_CALIBRATION", "MOTOR_PROTOCOL", "ARM_SWITCH"]
ARMED_FLAG = 1  # box 0 (ARM) in the active mode flags


def frame(cmd, payload=b""):
    body = bytes([len(payload), cmd]) + payload
    c = 0
    for b in body:
        c ^= b
    return b"$M<" + body + bytes([c])


def read_frame(port, timeout=1.0):
    end, buf = time.time() + timeout, b""
    while time.time() < end:
        b = port.read(1)
        if not b:
            continue
        buf += b
        i = buf.find(b"$M")
        if i < 0:
            buf = buf[-1:]
            continue
        buf = buf[i:]
        if len(buf) >= 5:
            n = buf[3]
            if len(buf) >= 6 + n:
                d, body = buf[2:3], buf[3:5 + n]
                c = 0
                for x in body:
                    c ^= x
                if c != buf[5 + n]:
                    raise ValueError("bad MSP checksum")
                if d == b"!":
                    raise ValueError("MSP error reply cmd=%d" % buf[4])
                return buf[4], bytes(buf[5:5 + n])
    raise TimeoutError("MSP timeout")


def request(port, cmd, timeout=1.0):
    port.write(frame(cmd))
    while True:
        c, p = read_frame(port, timeout)
        if c == cmd:
            return p


def parse_rc(p):
    return list(struct.unpack("<%dH" % (len(p) // 2), p[:len(p) // 2 * 2]))


def parse_attitude(p):
    roll, pitch, yaw = struct.unpack("<hhh", p[:6])
    return [roll / 10.0, pitch / 10.0, float(yaw)]


def parse_analog(p):
    v8, mah, rssi, amp, v16 = struct.unpack("<BHHhH", p[:9])
    return {"vbat_dv": v8, "mah": mah, "rssi": rssi, "amps_cA": amp, "vbat_cv": v16}


def parse_status(p):
    cycle, i2c, sens, flags, prof, load, gyro = struct.unpack("<HHHIBHH", p[:15])
    n = p[15]
    o = 16 + n
    cnt = p[o]
    arm = struct.unpack("<I", p[o + 1:o + 5])[0]
    names = [ARMING_DISABLE[i] for i in range(min(cnt, len(ARMING_DISABLE))) if arm >> i & 1]
    return {"cycle_us": cycle, "mode_flags": flags, "load": load, "arming_disable": names,
            "arming_disable_mask": arm, "armed": bool(flags & ARMED_FLAG),
            "failsafe": "RX_FAILSAFE" in names or "FAILSAFE" in names}


def parse_motors(p):
    """MSP_MOTOR: 8 x uint16, 1000-2000 (DShot already converted by firmware); first 4, 0 = unused/off."""
    v = struct.unpack("<%dH" % (len(p) // 2), p[:len(p) // 2 * 2])
    return [int(x) for x in v[:4]]


class BetaflightMSP:
    def __init__(self, port, baud=115200, timeout=0.2, serial_obj=None):
        if serial_obj is None:
            import serial
            serial_obj = serial.Serial(port, baud, timeout=0.05)
        self._p, self._timeout = serial_obj, timeout
        self._lock = threading.Lock()

    def _req(self, cmd):
        with self._lock:
            return request(self._p, cmd, self._timeout)

    def rc(self):
        return parse_rc(self._req(MSP_RC))

    def attitude(self):
        return parse_attitude(self._req(MSP_ATTITUDE))

    def status(self):
        return parse_status(self._req(MSP_STATUS))

    def motors(self):
        return parse_motors(self._req(MSP_MOTOR))

    def rssi(self):
        return parse_analog(self._req(MSP_ANALOG))["rssi"]

    def close(self):
        self._p.close()
