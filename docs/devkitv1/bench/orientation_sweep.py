#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Orientation check (plan U5.5): sweep the LO 2407..2477 MHz in 5 MHz steps, max-hold
host PSDs (25 CAP16 bursts) and on-chip SPEC (2 s max) per LO, then test which RF mapping
keeps ambient features fixed as the LO moves. Run from host/: .venv/bin/python ../docs/devkitv1/bench/orientation_sweep.py"""
import numpy as np, json
from esp32sdr.device import Device
from esp32sdr.samples import decode_cap
from esp32sdr.spectrum import psd
from esp32sdr.spec_cmd import spectrum
d=Device.open()
LOS=list(range(2407,2478,5)); NB=256; fs=40e6
cap={}; spc={}
for lo in LOS:
    d.tune(lo)
    ps=[psd(decode_cap(d.cap16(16380,1),8),fs,NB)[1] for _ in range(25)]
    cap[lo]=np.max(ps,axis=0)            # baseband, ascending f (fftshifted), standard I/Q
    r=spectrum(d,256,1,2000,detector=1)
    spc[lo]=np.fft.fftshift(r.average_db())  # baseband of raw FFT, ascending raw bin freq
    print(lo, flush=True)
d.close()
fb=np.fft.fftshift(np.fft.fftfreq(NB,1/fs))
np.savez("sweep.npz",los=LOS,fb=fb,cap=np.array([cap[l] for l in LOS]),spc=np.array([spc[l] for l in LOS]))
def score(S,s):
    S=np.array([S[l] for l in LOS]); S=S-np.median(S,axis=0)  # remove fixed baseband shape
    m=np.abs(fb)<16e6
    grid=np.arange(2395e6,2490e6,fs/NB)
    rows=[]
    for i,lo in enumerate(LOS):
        rf=lo*1e6+s*fb[m]; o=np.argsort(rf)
        rows.append(np.interp(grid,rf[o],S[i][m][o],left=np.nan,right=np.nan))
    rows=np.array(rows); cs=[]
    for i in range(len(LOS)):
        for j in range(i+1,min(i+4,len(LOS))):
            k=~np.isnan(rows[i])&~np.isnan(rows[j])
            if k.sum()>20: cs.append(np.corrcoef(rows[i][k],rows[j][k])[0,1])
    return np.mean(cs)
for name,S in (("host capture PSD (decode_cap)",cap),("on-chip SPEC raw bins",spc)):
    print(f"{name}: RF=LO+f corr {score(S,+1):+.3f}   RF=LO-f corr {score(S,-1):+.3f}")

