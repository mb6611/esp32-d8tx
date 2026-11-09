#!/usr/bin/env python3
"""esp.py [--reset] CMD... : send d8tx protocol lines to the DevKit, print replies (B3 bench helper)."""
import sys, time, serial
args = sys.argv[1:]
s = serial.Serial("/dev/cu.usbserial-0001", 921600, timeout=0.2, dsrdtr=False, rtscts=False)
if args and args[0] == "--reset":
    args = args[1:]; s.dtr = False; s.rts = True; time.sleep(0.1); s.rts = False; time.sleep(1.5)
else:
    s.dtr = False; s.rts = False; time.sleep(0.2)
print(s.read(65536).decode(errors="replace").strip())
for c in args:
    if c.startswith("sleep="): time.sleep(float(c[6:])); print(s.read(65536).decode(errors="replace").strip()); continue
    s.write(c.encode() + b"\n"); time.sleep(0.4)
    print(">", c); print(s.read(65536).decode(errors="replace").strip())
