#!/usr/bin/env python3
"""Read-only idle readback via stage2 txeng 'R' command. Sends ONLY R lines."""
import serial, time, sys
ADDRS = [0x600060b8,0x600060bc,0x600060c4,0x600060a0,0x600050a8,0x600050f0,0x600050dc,0x60006004,0x60006000,0x6000608c]
s = serial.Serial('/dev/cu.usbserial-0001', 921600, timeout=0.3)
s.dtr = False; s.rts = True; time.sleep(0.1); s.rts = False   # reset
t = time.time(); buf = b''
while time.time()-t < 8 and b'I,ready' not in buf: buf += s.read(512)
print(buf.decode(errors='replace'))
for rnd in (1, 2):
    for a in ADDRS:
        s.write(b'R 0x%x\n' % a); time.sleep(0.15)
        print(f'pass{rnd}', s.read(200).decode(errors='replace').replace('\r','').replace('\n',' | '))
