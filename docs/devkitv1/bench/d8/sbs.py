import numpy as np,matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
from scipy.ndimage import median_filter
fx=26e6; f0=fx*0x5C7627/2**16; sp=fx/2**18*(256+0x7A)*2**3
hop=[0,57,112,167,222,21,76,131,186,241,40,95,150,205,4,59,114,169,224,23,78,133,188,243,42,97,152,207,6,61,116,171,226,25,80,135,190,245,44,99,154,209,8,63,118,173,228]
hf=(f0+np.array(hop)*sp)/1e6-0.05; P=0.42270; phases={"on":0.3861,"off":0.0531}
fig,ax=plt.subplots(2,2,figsize=(18,14),gridspec_kw=dict(width_ratios=[1.5,1]))
for row,tag in enumerate(("on","off")):
    z=np.load(f"strobe_{tag}.npz"); T,D,f=z["T"],z["D"],z["f"]; Dn=D-median_filter(D,size=(1,51),mode="nearest")
    J=np.array([np.argmin(np.abs(f-x)) for x in hf]); H=np.stack([Dn[:,max(0,j-2):j+3].max(1) for j in J],1)
    slot=np.floor(((T-phases[tag])%P)/P*47).astype(int)%47
    S=np.array([np.nanmean(Dn[slot==k],0) for k in range(47)]).T
    M=np.array([[H[slot==k,c].mean() for c in range(47)] for k in range(47)])
    a=ax[row,0]; im=a.imshow(S,aspect="auto",origin="lower",extent=[0,47,f[0],f[-1]],cmap="inferno",vmin=0,vmax=10,interpolation="nearest")
    a.step(np.arange(48),np.r_[hf,hf[-1]],where="post",color="cyan",lw=.8,alpha=.5,label="predicted hop (drone's bind table)")
    a.set_title(f"E8 {tag.upper()}: one 47-hop cycle rebuilt from ~835 wideband snapshots (20 s)"); a.set_ylabel("RF frequency [MHz]")
    a.set_xlabel("hop slot in cycle (1 slot = 8.994 ms, cycle = 422.70 ms)"); a.legend(loc="upper right",fontsize=8)
    fig.colorbar(im,ax=a,pad=.01).set_label("mean power above local median [dB]")
    a=ax[row,1]; im=a.imshow(M,origin="lower",cmap="viridis",vmin=0,vmax=26)
    a.set_title(f"E8 {tag.upper()}: power at each table channel per time slot"); a.set_xlabel("bind-table entry (0-46)"); a.set_ylabel("time slot in cycle (0-46)")
    fig.colorbar(im,ax=a,pad=.01).set_label("dB above local median (same scale both rows)")
fig.suptitle("FrSky D8 hop sequence seen by the ESP32 DevKit V1: E8 ON (top) vs OFF (bottom), identical colour scales",fontsize=14)
fig.tight_layout(); fig.savefig("png/hop_cycle_on_vs_off.png",dpi=75)
