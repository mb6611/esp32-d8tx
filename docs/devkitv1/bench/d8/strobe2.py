import numpy as np,sys,matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
from scipy.ndimage import median_filter
tag=sys.argv[1]; z=np.load(f"strobe_{tag}.npz"); T,D,f=z["T"],z["D"],z["f"]
Dn=D-median_filter(D,size=(1,51),mode="nearest")
fx=26e6; f0=fx*0x5C7627/2**16; sp=fx/2**18*(256+0x7A)*2**3
hop=[0,57,112,167,222,21,76,131,186,241,40,95,150,205,4,59,114,169,224,23,78,133,188,243,42,97,152,207,6,61,116,171,226,25,80,135,190,245,44,99,154,209,8,63,118,173,228]
hf=(f0+np.array(hop)*sp)/1e6-0.05
J=np.array([np.argmin(np.abs(f-x)) for x in hf])
H=np.stack([Dn[:,max(0,j-2):j+3].max(1) for j in J],1)   # power at each of 47 hop freqs, per snapshot
def sc(P,phi):
    slot=np.floor(((T-phi)%P)/P*47).astype(int)%47; return H[np.arange(len(T)),slot].mean()
best=max((sc(P,phi),P,phi) for P in np.arange(0.415,0.435,0.0001) for phi in np.arange(0,0.428,0.0009))
s,P,phi=best
rng=np.random.default_rng(1); null=[H[np.arange(len(T)),rng.integers(0,47,len(T))].mean() for _ in range(200)]
print(tag,"P %.2f ms phase %.1f ms: %.2f dB vs random %.2f+-%.2f dB (z=%.0f)"%(P*1e3,phi*1e3,s,np.mean(null),np.std(null),(s-np.mean(null))/np.std(null)))
slot=np.floor(((T-phi)%P)/P*47).astype(int)%47
M=np.array([[H[slot==k,c].mean() if np.any(slot==k) else np.nan for c in range(47)] for k in range(47)])
S=np.array([np.nanmean(Dn[slot==k],0) if np.any(slot==k) else np.full(len(f),np.nan) for k in range(47)]).T
fig,ax=plt.subplots(1,2,figsize=(18,8),gridspec_kw=dict(width_ratios=[1.6,1]))
a=ax[0]; im=a.imshow(S,aspect="auto",origin="lower",extent=[0,47,f[0],f[-1]],cmap="inferno",vmin=0,vmax=10,interpolation="nearest")
a.step(np.arange(48),np.r_[hf,hf[-1]],where="post",color="cyan",lw=1,alpha=.7,label="predicted: bind-table frequency for each slot")
a.set_xlabel(f"hop slot within the cycle (1 slot = {P*1e3/47:.3f} ms; cycle = {P*1e3:.2f} ms)"); a.set_ylabel("RF frequency [MHz]")
a.set_title(f"E8 {tag.upper()}: spectrogram of one hop cycle, rebuilt from {len(T)} snapshots over 20 s\n(each column = mean over the ~{len(T)//47} snapshots that fell in that 9 ms slot; colour = dB above local median)")
a.legend(loc="upper right",fontsize=8); fig.colorbar(im,ax=a,pad=.01).set_label("power above local median [dB]")
a=ax[1]; im=a.imshow(M,origin="lower",cmap="viridis",vmin=0,vmax=np.nanpercentile(M,99))
a.set_xlabel("bind-table entry (channel position 0-46)"); a.set_ylabel("measured time slot in the cycle (0-46)")
a.set_title("mean power at each table channel, per time slot\nbright diagonal = the E8 visits the table in order, one entry per slot"); fig.colorbar(im,ax=a,pad=.01).set_label("dB above local median")
fig.tight_layout(); fig.savefig(f"png/hop_cycle_{tag}.png",dpi=80)
