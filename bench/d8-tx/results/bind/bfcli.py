#!/usr/bin/env python3
"""Betaflight CLI helper for the bind bench (B3).
bfcli.py PORT capture OUT cmd...   run cmds, write output to OUT (stays in CLI unless a cmd exits)
bfcli.py PORT cmd "cmd" [quiet_s]   run one cmd, print output
The first line after '#' is a dummy (it can be swallowed). Does not send exit/save unless asked."""
import sys, time, serial
def open_cli(port):
    s = serial.Serial(port, 115200, timeout=0.2); s.write(b"#"); time.sleep(0.5); s.read(65536)
    s.write(b"\r\n"); time.sleep(0.3); s.read(65536); return s
def run(s, cmd, quiet=1.0, maxt=60):
    s.write(cmd.encode() + b"\r\n"); out = b""; last = time.time(); end = last + maxt
    while time.time() < end and time.time() - last < quiet:
        d = s.read(4096)
        if d: out += d; last = time.time()
    return out.decode(errors="replace").replace("\r", "")
if __name__ == "__main__":
    port, mode = sys.argv[1], sys.argv[2]; s = open_cli(port)
    if mode == "capture":
        with open(sys.argv[3], "w") as f:
            for c in sys.argv[4:]: f.write(run(s, c, 1.5))
    elif mode == "cmd":
        print(run(s, sys.argv[3], float(sys.argv[4]) if len(sys.argv) > 4 else 1.0))
