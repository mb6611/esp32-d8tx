#!/usr/bin/env python3
"""Offline emulation of txeng.c cmd_fill (kind 1) as pbcheck.py issues it, plus spectrum of the words
the engine would play (count 6143 -> N=6144 words from offset 0, assumed 80 MS/s, I=low 10 bits, Q=next 10, signed).
Checks only the FIRMWARE FILL semantics; not what the hardware engine does with the words."""
import numpy as np, json, sys
CAP, FS = 16384, 80e6
def fill(kind, n, p1, p2):
    s = np.zeros(CAP, dtype=np.uint32)
    j = np.arange(n)
    if kind == 0:
        s[:n] = p1 & 0xffffffff
    else:
        ph = 2*np.pi*p2*j/n
        i = np.rint(p1*np.cos(ph)).astype(np.int64)
        q = np.rint(p1*np.sin(ph)).astype(np.int64) if kind == 1 else 0*i
        s[:n] = ((i & 0x3ff) | ((q & 0x3ff) << 10)).astype(np.uint32)
    return s
def sx(v):
    v = v.astype(np.int64) & 0x3ff
    return np.where(v >= 512, v-1024, v)
out = {}
for name, args in (("pat156", (1,16384,200,32)), ("pat", (1,16384,200,256)), ("zero", (0,16384,0,0))):
    w = fill(*args)[:6144]
    i, q = sx(w & 0x3ff), sx((w >> 10) & 0x3ff)
    z = i + 1j*q
    F = np.fft.fftshift(np.fft.fft(z * np.hanning(len(z))))
    f = np.fft.fftshift(np.fft.fftfreq(len(z), 1/FS))
    k = int(np.argmax(abs(F)))
    p = abs(F[k])**2; tot = (abs(F)**2).sum()
    out[name] = {"args": args, "peak_hz": float(f[k]), "peak_frac_power": float(p/tot) if tot else 0,
                 "I_range": [int(i.min()), int(i.max())], "Q_range": [int(q.min()), int(q.max())],
                 "rms": float(np.sqrt((abs(z)**2).mean())), "words_0_3": [hex(int(x)) for x in w[:4]],
                 "period_samples": 16384/args[3] if args[3] else None,
                 "whole_cycles_in_6144": 6144*args[3]/16384 if args[3] else None,
                 "zero_all": bool((w == 0).all())}
print(json.dumps(out, indent=1))
# sign: +f means I leads Q (Q=sin) i.e. exp(+j wt); true RF sign depends on unverified hardware I/Q convention
