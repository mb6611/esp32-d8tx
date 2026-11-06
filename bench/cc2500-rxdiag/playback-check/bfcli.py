#!/usr/bin/env python3
"""Minimal Betaflight CLI helper for the Tinyhawk (raw fd, like rxdiag_events.py).

  bfcli.py capture OUT          # '#', then 'version', 'status', 'diff all' -> OUT (no changes)
  bfcli.py dfu                  # '#', then 'bl' (reboot to DFU bootloader)
  bfcli.py replay DIFF LOG      # paste a 'diff all' file line by line (skips comments, 'batch',
                                # 'defaults nosave' and 'save'), then 'save' (reboots)
Only these commands are sent. Port: first /dev/cu.usbmodem*.
"""
import glob, os, select, sys, termios, time, tty


def port():
    p = glob.glob("/dev/cu.usbmodem*")
    if not p:
        sys.exit("no /dev/cu.usbmodem*")
    return p[0]


def openp(p):
    fd = os.open(p, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    tty.setraw(fd)
    a = termios.tcgetattr(fd)
    a[2] |= termios.CLOCAL | termios.CREAD
    termios.tcsetattr(fd, termios.TCSANOW, a)
    return fd


def rd(fd, quiet=0.6, maxt=15.0):
    """Read until `quiet` s pass with no data (or maxt)."""
    out, t0, last = b"", time.time(), time.time()
    while time.time() - t0 < maxt and time.time() - last < quiet:
        r, _, _ = select.select([fd], [], [], 0.05)
        if r:
            try:
                d = os.read(fd, 65536)
            except BlockingIOError:
                d = b""
            if d:
                out += d
                last = time.time()
    return out


def cmd(fd, c, quiet=0.6, maxt=15.0):
    os.write(fd, (c + "\n").encode())
    return rd(fd, quiet, maxt).decode("latin1")


def cli(fd):
    for _ in range(4):
        os.write(fd, b"#\n")
        if b"#" in rd(fd, 0.8):
            return True
    return False


def main():
    m = sys.argv[1]
    fd = openp(port())
    try:
        if not cli(fd):
            sys.exit("no CLI prompt")
        if m == "capture":
            with open(sys.argv[2], "w") as f:
                for c in ("version", "status", "diff all"):
                    f.write(cmd(fd, c, quiet=1.0, maxt=30))
        elif m == "dfu":
            os.write(fd, b"bl\n")
            time.sleep(0.5)
        elif m == "replay":
            skip = ("#", "batch", "defaults", "save")
            with open(sys.argv[3], "w") as log:
                for ln in open(sys.argv[2]):
                    ln = ln.strip()
                    if not ln or ln.startswith(skip) or ln == "diff all":
                        continue
                    log.write(">> " + ln + "\n" + cmd(fd, ln, quiet=0.25, maxt=5))
                    log.flush()
                log.write(">> save\n")
                os.write(fd, b"save\n")
                time.sleep(1.0)
        else:
            sys.exit("bad mode")
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


if __name__ == "__main__":
    main()
