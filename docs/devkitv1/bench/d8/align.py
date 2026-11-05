import numpy as np, matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
from scipy.ndimage import median_filter
fx=26e6; f0=fx*0x5C7627/2**16; sp=fx/2**18*(256+0x7A)*2**3
hop=[0,57,112,167,222,21,76,131,186,241,40,95,150,205,4,59,114,169,224,23,78,133,188,243,42,97,152,207,6,61,116,171,226,25,80,135,190,245,44,99,154,209,8,63,118,173,228]
exp=np.array(sorted(f0+c*sp for c in hop))/1e6
unused=np.array([f0/1e6+c*sp/1e6 for c in range(0,246) if c not in hop])
res={}
for tag in ("on","off"):
    z=np.load(f"spec_{tag}.npz"); f=z["f"]/1e6; p=z["max"]
    pk=p-median_filter(p,size=51,mode="nearest")   # peakiness: dB above local (2 MHz) median, removes gain/shape
    res[tag]=(f,pk)
f=res["on"][0]
def score(fr,pk): return np.array([pk[np.argmin(np.abs(f-x))] for x in fr])
deltas=np.arange(-0.15,0.1501,0.005)
S={t:[score(exp+d,res[t][1]).mean() for d in deltas] for t in ("on","off")}
SU={t:[score(unused+d,res[t][1]).mean() for d in deltas] for t in ("on","off")}
bd=deltas[int(np.argmax(S["on"]))]
print("best offset %.0f kHz"%(bd*1e3))
for t in ("on","off"):
    print(t,"mean peakiness at 47 hop freqs (best offset): %.1f dB; at the 199 unused grid channels: %.1f dB"%(score(exp+bd,res[t][1]).mean(),score(unused+bd,res[t][1]).mean()))
fig,ax=plt.subplots(2,1,figsize=(15,9))
a=ax[0]
for t,c in (("on","C3"),("off","C0")):
    a.plot(deltas*1e3,S[t],c,label=f"E8 {t.upper()}: 47 hop-table channels"); a.plot(deltas*1e3,SU[t],c,ls=":",label=f"E8 {t.upper()}: 199 unused channels on the same 300 kHz grid")
a.set_xlabel("assumed frequency error (shift applied to the predicted channel frequencies) [kHz]"); a.set_ylabel("mean peak height above\nlocal 2 MHz median [dB]")
a.set_title("Do the max-hold peaks sit on the drone's 47 hop channels? (gain-independent: peak height relative to local median)"); a.legend(fontsize=8)
a=ax[1]; fo,pko=res["off"]; fn,pkn=res["on"]
a.plot(fn,pkn,lw=.6,color="C3",label="E8 ON"); a.plot(fo,pko-25,lw=.6,color="C0",label="E8 OFF (shifted down 25 dB)")
for x in exp+bd: a.axvline(x,color="k",alpha=.3,lw=.8)
a.set_xlim(2414,2430); a.set_xlabel("RF frequency [MHz]"); a.set_ylabel("peak height above local median [dB]")
a.set_title(f"zoom 2414-2430 MHz; grey lines = hop channels shifted by best offset {bd*1e3:.0f} kHz"); a.legend(fontsize=8)
fig.tight_layout(); fig.savefig("png/hop_alignment.png",dpi=80)
