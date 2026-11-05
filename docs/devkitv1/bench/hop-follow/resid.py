# Slot-33 analysis: frequency residual (discriminator minus ideal GFSK of the expected packet,
# predicted from slot 32's CRC-valid packet with counter+1) for slot 33 vs slot 19.
# usage: host/.venv/bin/python resid.py REC.npz OUT.png   (REC from slotrec.py)
import numpy as np, sys, matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[4] / 'host'))
from types import SimpleNamespace as NS
from esp32sdr import d8
from esp32sdr.hopfollow import Segmenter
z=np.load(sys.argv[1]); FS=250e3; sps=FS/d8.BAUD
seg=Segmenter(); segs=[]; o=0
for i,fl,sh,n in zip(z['index'],z['flags'],z['shift'],z['lens']):
    segs+=seg.feed(NS(index=int(i),flags=int(fl),shift=int(sh),iq=z['iq'][o:o+n])); o+=n
dec=d8.StandardDecoder(FS); W=d8.StandardDecoder(FS,cutoff=75e3)
def resid(x, r, raw):
    bits=np.unpackbits(np.frombuffer(d8.PREAMBLE+d8.SYNC+bytes(raw),np.uint8))
    n=int(len(bits)*sps); i0=int(round(r.t*FS))
    xx=x-x.mean(); d=d8.fm_demod(np.convolve(xx,W.taps,'same'),FS)[i0:i0+n]
    fi=np.diff(np.concatenate([[0],d8.gfsk_phase(bits,sps,n=n)]))*FS/2/np.pi
    L=min(range(-4,5),key=lambda L: np.mean((d-np.roll(fi,L))**2)); e=d-np.roll(fi,L)
    k=int(sps); sm=np.convolve(e,np.ones(4*k)/(4*k),'same')  # 4-bit mean
    return sm[20:-20]
fig,ax=plt.subplots(2,1,figsize=(14,8)); out={}
last={}
for s in segs:
    x=s.iq[s.blank:]
    if s.slot not in (19,32,33): continue
    r=[q for q in dec.decode(x) if q.packet.raw[1:3]==b'\x42\xb2']
    if not r: continue
    r=r[0]
    if s.slot==32 and r.packet.crc_ok: last[32]=r.packet.raw; continue
    if s.slot==33 and 32 in last:
        exp=bytearray(last[32]); exp[4]=(exp[4]+1)%256; c=d8.crc16(bytes(exp[:18])); exp[18]=c>>8; exp[19]=c&255
        out.setdefault(33,[]).append(resid(x,r,exp)); del last[32]
    if s.slot==19 and r.packet.crc_ok: out.setdefault(19,[]).append(resid(x,r,r.packet.raw))
for j,sl in enumerate((19,33)):
    for e in out.get(sl,[])[:6]: ax[j].plot(np.arange(len(e))/FS*1e3,e/1e3,lw=.8)
    ax[j].set_title(f'slot {sl}: freq residual (kHz, 4-bit moving mean) vs ms'); ax[j].set_ylim(-20,20)
    E=[np.abs(np.fft.rfft(e-e.mean(),8192))**2 for e in out.get(sl,[])]
    if E:
        E=np.mean(E,0); f=np.fft.rfftfreq(8192,1/FS); m=f<15e3; k=np.argmax(E[m]); print(sl,len(E) if False else len(out[sl]),'resid rms kHz %.2f'%np.mean([e.std() for e in out[sl]]/np.float64(1e3)),'peak at %.2f kHz'%(f[m][k]/1e3))
plt.tight_layout(); plt.savefig(sys.argv[2],dpi=65)
