#!/usr/bin/env python3
"""Betaflight CLI helper: bfcli.py PORT capture OUT cmd... | paste FILE | bl"""
import sys, time, serial
def open_cli(port):
    s = serial.Serial(port, 115200, timeout=0.2); s.write(b"#"); time.sleep(0.5); s.read(65536); return s
def run(s, cmd, quiet=1.0, maxt=60):
    s.write(cmd.encode() + b"\r\n"); out = b""; last = time.time(); end = last + maxt
    while time.time() < end and time.time() - last < quiet:
        d = s.read(4096)
        if d: out += d; last = time.time()
    return out.decode(errors="replace")
if __name__ == "__main__":
    port, mode = sys.argv[1], sys.argv[2]; s = open_cli(port)
    if mode == "capture":
        with open(sys.argv[3], "w") as f:
            for c in sys.argv[4:]: f.write(run(s, c, 1.5).replace("\r", ""))
    elif mode == "paste":
        for line in open(sys.argv[3]):
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("defaults") or line == "save": continue
            o = run(s, line, 0.15, 5)
            if "Invalid" in o or "ERROR" in o.upper(): print("!!", line, o.strip()[-80:])
        print("pasted")
    elif mode == "cmd":
        print(run(s, sys.argv[3], 1.0).replace("\r", ""))
    elif mode == "bl":
        s.write(b"bl\r\n"); time.sleep(1)
