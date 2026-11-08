#!/usr/bin/env python3
"""Capture Betaflight blackbox logs from the FC.

  bbcapture.py serial --port /dev/cu.usbmodem0x80000001 [--out DIR] [--sessions 1] [--idle 3]
                      [--wait-arm 600] [--max-seconds 0] [--no-volt-check] [--max-volts 0.5]
      blackbox_device = SERIAL on the USB VCP shared with MSP (see README). Betaflight releases MSP on that port
      when it arms and streams the log there; on disarm it writes the LOG_END event and gives MSP back.
      Records every byte to <out>/bb_<ts>.raw, then splits it into <out>/bb_<ts>.bbl (log sessions only)
      and reports MSP frames/noise found outside the sessions. Stops after --sessions complete logs, after
      --idle s of silence following log data, at --max-seconds, or on Ctrl-C (the capture is still split).
      Before recording it checks MSP_ANALOG and refuses if vbat > --max-volts (USB-only bench rule).
      Do NOT send MSP while armed: nothing answers, and the queued bytes are parsed after disarm.

  bbcapture.py flash --port PORT [--out DIR] [--chunk 4096]
      Generic download for boards with onboard dataflash (MSP_DATAFLASH_SUMMARY 70 / MSP_DATAFLASH_READ 71).
      Exits 2 with a 'no flash' message when the FC reports no flash (e.g. MATEKF411RX).

  bbcapture.py split RAW [--out DIR]      # re-run the offline splitter on a .raw capture
"""
import argparse, os, struct, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "d8-tx", "host"))
import bbl  # noqa: E402
import bf_msp  # noqa: E402  (frame(), parse_analog(), MSP_ANALOG, MSP_STATUS)

MSP_DATAFLASH_SUMMARY, MSP_DATAFLASH_READ = 70, 71
FLASH_READY, FLASH_SUPPORTED = 1, 2


# ---------------------------------------------------------------- MSP with jumbo replies

def msp_request(port, cmd, payload=b"", timeout=1.0):
    """Send an MSP v1 request and return the payload of the matching reply (jumbo-aware).
    Raises ValueError on an error reply ('$M!'), TimeoutError on no reply."""
    port.write(bf_msp.frame(cmd, payload))
    buf, end = bytearray(), time.time() + timeout
    while time.time() < end:
        b = port.read(max(1, getattr(port, "in_waiting", 0) or 1))
        if not b:
            continue
        buf += b
        while True:
            j = buf.find(b"$M")
            if j < 0:
                del buf[:-1]
                break
            f = bbl.parse_msp_at(buf, j)
            if f is None:
                # incomplete (wait for more) unless clearly garbage
                if len(buf) - j > 7 + 65535 or (len(buf) > j + 2 and buf[j + 2:j + 3] not in b"<>!"):
                    del buf[:j + 1]
                    continue
                break
            d, c, p, ln = f
            del buf[:j + ln]
            if c != cmd:
                continue
            if d == "!":
                raise ValueError("MSP error reply for cmd %d (unsupported on this firmware?)" % cmd)
            return p
    raise TimeoutError("no MSP reply for cmd %d" % cmd)


MSP_BATTERY_STATE = 130


def battery_readings(port):
    """Every vbat reading the FC offers, decoded here (not via bf_msp.parse_analog) per BF 4.2 msp.c:
    MSP_ANALOG (110): u8 vbat 0.1 V, u16 mAh, u16 rssi, s16 cA, u16 vbat 0.01 V.
    MSP_BATTERY_STATE (130): u8 cells, u16 capacity, u8 vbat 0.1 V, u16 mAh, s16 cA, u8 state, u16 vbat 0.01 V."""
    r = {}
    p = msp_request(port, bf_msp.MSP_ANALOG)
    r["analog_dv"] = p[0] / 10.0
    if len(p) >= 9:
        r["analog_cv"] = struct.unpack_from("<H", p, 7)[0] / 100.0
    try:
        p = msp_request(port, MSP_BATTERY_STATE)
    except (TimeoutError, ValueError):
        p = b""
    if len(p) >= 4:
        r["cells"] = p[0]
        r["batt_dv"] = p[3] / 10.0
    if len(p) >= 11:
        r["batt_state"] = p[8]
        r["batt_cv"] = struct.unpack_from("<H", p, 9)[0] / 100.0
    return r


def vbat_volts(port, readings=None):
    """Worst case (highest) of all vbat readings; any detected cell counts as a battery (returns inf)."""
    r = battery_readings(port) if readings is None else readings
    if r.get("cells", 0) > 0:
        return float("inf")
    return max(v for k, v in r.items() if k.endswith(("_dv", "_cv")))


# ---------------------------------------------------------------- serial capture

def split_and_write(raw, base):
    """Split a raw capture; write <base>.bbl if any session. Returns a summary dict."""
    sessions, outside = bbl.split_stream(raw)
    nframes, junk = 0, 0
    for c in outside:
        f, j = bbl.msp_frames(c)
        nframes += len(f)
        junk += j
    out = None
    if sessions:
        out = base + ".bbl"
        with open(out, "wb") as f:
            f.write(bbl.sessions_bytes(raw, sessions))
    return {"bbl": out, "sessions": len(sessions), "complete": sum(s.complete for s in sessions),
            "session_bytes": sum(s.end - s.start for s in sessions), "msp_frames_outside": nframes,
            "noise_bytes_outside": junk, "raw_bytes": len(raw)}


def record(port, raw_path, sessions=1, idle=3.0, wait_arm=600.0, max_seconds=0.0, log=print, clock=time.time):
    """Read the port into raw_path until a stop condition; returns the raw bytes."""
    raw = bytearray()
    t0 = last = clock()
    started = False
    with open(raw_path, "wb") as f:
        try:
            while True:
                n = getattr(port, "in_waiting", 0) or 1
                d = port.read(min(max(n, 1), 65536))
                now = clock()
                if d:
                    f.write(d)
                    raw += d
                    last = now
                    if not started and bbl.LOG_START in raw:
                        started = True
                        log("log started (armed) at +%.1f s" % (now - t0))
                    if started and raw.count(bbl.LOG_END) >= sessions:
                        log("LOG_END seen (%d session(s)), stopping" % sessions)
                        break
                if started and idle and now - last > idle:
                    log("idle %.1f s after log data, stopping (disarmed without LOG_END, or link lost)" % idle)
                    break
                if not started and wait_arm and now - t0 > wait_arm:
                    log("no log start within %.0f s (not armed? blackbox not on this port?)" % wait_arm)
                    break
                if max_seconds and now - t0 > max_seconds:
                    log("max-seconds reached")
                    break
                if d is None or d == b"":
                    if not getattr(port, "is_fake", False):
                        time.sleep(0.005)
        except KeyboardInterrupt:
            log("Ctrl-C, stopping")
    return bytes(raw)


def cmd_serial(a):
    import serial
    os.makedirs(a.out, exist_ok=True)
    base = os.path.join(a.out, "bb_" + time.strftime("%Y%m%d_%H%M%S"))
    port = serial.Serial(a.port, 115200, timeout=0.05)  # VCP: baud is ignored by the FC
    try:
        port.reset_input_buffer()
        if not a.no_volt_check:
            r = battery_readings(port)
            v = vbat_volts(port, r)
            print("battery readings %s -> worst %.2f V" % (r, v))
            if v > a.max_volts:
                sys.exit("vbat %.2f V > %.2f V: battery connected? refusing (USB-only rule)" % (v, a.max_volts))
            time.sleep(0.1)
            port.reset_input_buffer()
        print("recording %s.raw; arm now (Ctrl-C to stop)" % base)
        raw = record(port, base + ".raw", a.sessions, a.idle, a.wait_arm, a.max_seconds)
        if a.confirm_msp:
            time.sleep(0.5)  # BLACKBOX_SHUTDOWN_TIMEOUT_MILLIS is 200 ms
            try:
                st = bf_msp.parse_status(msp_request(port, bf_msp.MSP_STATUS, timeout=2.0))
                print("MSP back after disarm: arming_disable=%s" % ("|".join(st["arming_disable_names"]) or "-"))
            except (TimeoutError, ValueError) as e:
                print("MSP not answering after capture: %s" % e)
    finally:
        port.close()
    s = split_and_write(raw, base)
    print(s)
    return s


# ---------------------------------------------------------------- dataflash download (flash-equipped boards)

def flash_summary(port):
    p = msp_request(port, MSP_DATAFLASH_SUMMARY)
    flags, sectors, total, used = struct.unpack("<BIII", p[:13])
    return {"flags": flags, "supported": bool(flags & FLASH_SUPPORTED), "ready": bool(flags & FLASH_READY),
            "sectors": sectors, "total": total, "used": used}


def flash_download(port, out_path, chunk=4096, log=print):
    s = flash_summary(port)
    if not s["supported"] or s["total"] == 0:
        log("no onboard dataflash (MSP_DATAFLASH_SUMMARY flags=%d size=%d): use 'serial' capture" %
            (s["flags"], s["total"]))
        return None
    if not s["ready"]:
        log("flash busy (erasing?), try again")
        return None
    data, addr = bytearray(), 0
    while addr < s["used"]:
        want = min(chunk, s["used"] - addr)
        p = msp_request(port, MSP_DATAFLASH_READ, struct.pack("<IHB", addr, want, 0), timeout=2.0)
        raddr, n, comp = struct.unpack("<IHB", p[:7])
        if raddr != addr or comp != 0:
            raise ValueError("unexpected read reply addr=%d comp=%d" % (raddr, comp))
        if n == 0:
            break
        data += p[7:7 + n]
        addr += n
    with open(out_path, "wb") as f:
        f.write(data)
    log("read %d of %d used bytes -> %s (%d log(s))" % (len(data), s["used"], out_path, len(bbl.find_logs(data))))
    return out_path


def cmd_flash(a):
    import serial
    os.makedirs(a.out, exist_ok=True)
    port = serial.Serial(a.port, 115200, timeout=0.05)
    try:
        r = flash_download(port, os.path.join(a.out, "flash_" + time.strftime("%Y%m%d_%H%M%S") + ".bbl"), a.chunk)
    finally:
        port.close()
    if r is None:
        sys.exit(2)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serial")
    s.add_argument("--port", default="/dev/cu.usbmodem0x80000001")
    s.add_argument("--out", default=os.path.join(HERE, "captures"))
    s.add_argument("--sessions", type=int, default=1, help="stop after this many complete logs (arm/disarm cycles)")
    s.add_argument("--idle", type=float, default=3.0)
    s.add_argument("--wait-arm", type=float, default=600.0)
    s.add_argument("--max-seconds", type=float, default=0.0)
    s.add_argument("--no-volt-check", action="store_true")
    s.add_argument("--max-volts", type=float, default=0.5)
    s.add_argument("--confirm-msp", action="store_true", help="after the capture, check MSP_STATUS answers again")
    f = sub.add_parser("flash")
    f.add_argument("--port", default="/dev/cu.usbmodem0x80000001")
    f.add_argument("--out", default=os.path.join(HERE, "captures"))
    f.add_argument("--chunk", type=int, default=4096)
    sp = sub.add_parser("split")
    sp.add_argument("raw")
    sp.add_argument("--out")
    a = ap.parse_args(argv)
    if a.cmd == "serial":
        cmd_serial(a)
    elif a.cmd == "flash":
        cmd_flash(a)
    else:
        raw = open(a.raw, "rb").read()
        base = os.path.join(a.out or os.path.dirname(os.path.abspath(a.raw)),
                            os.path.splitext(os.path.basename(a.raw))[0])
        print(split_and_write(raw, base))


if __name__ == "__main__":
    main()
