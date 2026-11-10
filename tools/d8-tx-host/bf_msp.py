#!/usr/bin/env python3
"""Minimal MSP v1 client for Betaflight 4.2.x (read-only: RC, STATUS, ANALOG) and a watch logger."""
import argparse, struct, sys, time

MSP_STATUS, MSP_RC, MSP_ANALOG = 101, 105, 110
# Betaflight 4.2 arming disable flag names, bit order
ARMING_DISABLE = ["NO_GYRO", "FAILSAFE", "RX_FAILSAFE", "BAD_RX_RECOVERY", "BOXFAILSAFE", "RUNAWAY_TAKEOFF",
                  "CRASH_DETECTED", "THROTTLE", "ANGLE", "BOOT_GRACE_TIME", "NOPREARM", "LOAD", "CALIBRATING",
                  "CLI", "CMS_MENU", "BST", "MSP", "PARALYZE", "GPS", "RESC", "RPMFILTER", "REBOOT_REQUIRED",
                  "DSHOT_BBANG", "ACC_CALIBRATION", "MOTOR_PROTOCOL", "ARM_SWITCH"]


def frame(cmd, payload=b""):
    body = bytes([len(payload), cmd]) + payload
    c = 0
    for b in body:
        c ^= b
    return b"$M<" + body + bytes([c])


def read_frame(port, timeout=1.0):
    """Return (cmd, payload) from the next '$M>' reply; raises on error reply, bad checksum or timeout."""
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
    return {"cycle_us": cycle, "mode_flags": flags, "load": load, "arming_disable": arm,
            "arming_disable_names": names, "rx_failsafe": "RX_FAILSAFE" in names or "FAILSAFE" in names}


def sample(port):
    return {"t": time.time(), "rc": parse_rc(request(port, MSP_RC)),
            "analog": parse_analog(request(port, MSP_ANALOG)), "status": parse_status(request(port, MSP_STATUS))}


def row(s):
    a, st = s["analog"], s["status"]
    return "%.3f rc=%s rssi=%d arm_dis=%s failsafe=%d" % (
        s["t"], ",".join(map(str, s["rc"])), a["rssi"], "|".join(st["arming_disable_names"]) or "-",
        int(st["rx_failsafe"]))


def watch(port, out, seconds, period=0.1):
    end = time.time() + seconds
    while time.time() < end:
        try:
            line = row(sample(port))
        except (TimeoutError, ValueError) as e:
            line = "%.3f ERR %s" % (time.time(), e)
        out.write(line + "\n")
        out.flush()
        time.sleep(period)


def fast(port, out, seconds, hz=100.0, clock=time.time, sleep=time.sleep):
    """RC-only poll at ~hz. CSV rows: t_send,t_recv,rtt_ms,ch1..chN (or ERR). Fixed-rate schedule, no drift."""
    out.write("t_send,t_recv,rtt_ms,rc\n")
    period, t0 = 1.0 / hz, clock()
    n = 0
    while True:
        due = t0 + n * period
        if due - t0 >= seconds:
            break
        d = due - clock()
        if d > 0:
            sleep(d)
        n += 1
        ts = clock()
        try:
            rc = parse_rc(request(port, MSP_RC, 0.05))
            tr = clock()
            out.write("%.4f,%.4f,%.2f,%s\n" % (ts, tr, (tr - ts) * 1e3, ",".join(map(str, rc))))
        except (TimeoutError, ValueError) as e:
            out.write("%.4f,,,ERR %s\n" % (ts, e))
    out.flush()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cmd", choices=["once", "watch", "fast"])
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--seconds", type=float, default=10)
    ap.add_argument("--period", type=float, default=0.1)
    ap.add_argument("--hz", type=float, default=100)
    ap.add_argument("--log", help="append rows to this file (watch)")
    a = ap.parse_args(argv)
    import serial
    port = serial.Serial(a.port, a.baud, timeout=0.05)
    try:
        if a.cmd == "once":
            print(row(sample(port)))
        elif a.cmd == "fast":
            f = open(a.log, "a") if a.log else sys.stdout
            fast(port, f, a.seconds, a.hz)
        else:
            f = open(a.log, "a") if a.log else sys.stdout
            watch(port, f, a.seconds, a.period)
    finally:
        port.close()


if __name__ == "__main__":
    main()
