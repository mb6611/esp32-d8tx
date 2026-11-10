#!/usr/bin/env python3
"""Read-only: resets board, waits for boot, sends ONLY 'I' twice (BBPLL 102/4 regs 10,11 + 0x3ff00024)."""
import serial, time
s = serial.Serial('/dev/cu.usbserial-0001', 921600, timeout=0.3)
s.dtr = False; s.rts = True; time.sleep(0.1); s.rts = False
t = time.time(); buf = b''
while time.time()-t < 8 and b'I,ready' not in buf: buf += s.read(512)
print('ready' if b'I,ready' in buf else 'NO READY', 'boot-lines:', buf.count(b'I,boot'))
for n in (1, 2):
    time.sleep(1); s.write(b'I\n'); time.sleep(0.3)
    print(f'reading{n}', s.read(300).decode(errors='replace').replace('\r','').replace('\n',' | '))
