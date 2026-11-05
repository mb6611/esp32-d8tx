import numpy as np, matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
fx=26e6; f0=fx*0x5C7627/2**16; sp=fx/2**18*(256+0x7A)*2**3
hop=[0,57,112,167,222,21,76,131,186,241,40,95,150,205,4,59,114,169,224,23,78,133,188,243,42,97,152,207,6,61,116,171,226,25,80,135,190,245,44,99,154,209,8,63,118,173,228]
exp=np.array(sorted(f0+c*sp for c in hop))/1e6
on,off=np.load("spec_on.npz"),np.load("spec_off.npz"); f=on["f"]/1e6
d=on["max"]-off["max"]
# score: for each expected channel, max excess within +-150 kHz; compare to random positions
def excess_at(fr): return np.array([d[np.abs(f-x)<=0.15].max() for x in fr])
ex=excess_at(exp); rng=np.random.default_rng(0)
ctrl=excess_at(rng.uniform(2402,2480,2000))
print("expected-channel excess dB: median %.1f, >6dB: %d/47"%(np.median(ex),(ex>6).sum()))
print("random-position excess dB: median %.1f, >6dB: %.1f%%"%(np.median(ctrl),100*(ctrl>6).mean()))
# peaks in d that are NOT near expected
fig,ax=plt.subplots(3,1,figsize=(15,12),sharex=True)
ax[0].plot(f,off["max"],lw=.6,color="C0",label="E8 OFF"); ax[0].plot(f,on["max"],lw=.6,color="C3",label="E8 ON")
ax[0].set_ylabel("max-hold power [dB, firmware FFT scale]"); ax[0].set_title("Full band, 80 MS/s snapshots, 2048-bin FFT (39 kHz/bin), max over 5 s (~690 FFTs)"); ax[0].legend()
ax[1].plot(f,d,lw=.6,color="k"); ax[1].axhline(0,color="grey",lw=.5)
for x in exp: ax[1].axvline(x,color="red",alpha=.35,lw=1)
ax[1].set_ylabel("ON minus OFF [dB]"); ax[1].set_title("difference; red lines = the 47 D8 hop frequencies from the drone's bind table (2404 MHz + n x 299.93 kHz)")
ax[2].plot(f,on["mean"]-off["mean"],lw=.6,color="k")
for x in exp: ax[2].axvline(x,color="red",alpha=.35,lw=1)
ax[2].set_ylabel("mean ON - OFF [dB]"); ax[2].set_xlabel("RF frequency [MHz]"); ax[2].set_title("same with the mean detector")
fig.tight_layout(); fig.savefig("png/maxhold_on_off.png",dpi=80)
