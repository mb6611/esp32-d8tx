#!/usr/bin/env python3
"""Keyed-state read: 2 keyed bursts (PBUS 127 then 0), count 6143, tmo 100us, F_KEY|F_CLR18|F_KREAD,
>=0.5s apart, stops on keyed_us>400 or any hang. Reads only; no RF controls beyond existing txeng key path."""
import sys, time, json
sys.path.insert(0, '/Users/1unoe/Developer/personal/auto-drone/stage2')
from dev import Dev, Hang
RATE = 1 << 15
PH = ["after_key(pre_clr18)", "after_F_CLR18", "mid_run", "at_done", "after_unkey"]
REGS = ["b8", "bc", "c4", "a0", "50f0"]
log = open('/Users/1unoe/Developer/personal/esp32-devkitv1-sdr/bench/register-map/keyed-read/logs/session.log', 'a')
d = Dev(log=log)
print(d.reset())
out = []
for pwr in (127, 0):
    time.sleep(0.5)
    raw = d.cmd(f"T 0x{(6143 | RATE):08x} 1 100 {4|8|128} 3 {pwr}")
    for l in raw: print(l)
    e = [l.split(',') for l in raw if l.startswith('E,')][0]
    keyed = int(e[16]); print(f"pwr={pwr} keyed_us={keyed} ndone={e[5]}")
    out.append(dict(pwr=pwr, raw=raw))
    if keyed > 400: print("OVERRUN, stop"); break
json.dump(out, open('/Users/1unoe/Developer/personal/esp32-devkitv1-sdr/bench/register-map/keyed-read/keyed_read.json', 'w'), indent=1)
