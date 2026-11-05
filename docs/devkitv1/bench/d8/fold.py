import numpy as np,sys,matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
fs=62500.0; n=sys.argv[1]; x=np.fromfile(f"/tmp/d8/{n}.sigmf-data",dtype=np.complex64); x=x-x.mean()
p=np.abs(x)**2; k=int(0.0005*fs); e=p[:len(p)//k*k].reshape(-1,k).mean(1); db=10*np.log10(e+1e-6)
def fold(P):
    m=int(P/0.5e-3); idx=(np.arange(len(db))*0.5e-3 % P)/0.5e-3
    rows=len(db)*0.5e-3/P
    prof=np.bincount(idx.astype(int),weights=db,minlength=m+1)/np.maximum(np.bincount(idx.astype(int),minlength=m+1),1)
    return prof
Ps=np.arange(0.415,0.435,0.00005); c=[np.std(fold(P)) for P in Ps]; P=Ps[int(np.argmax(c))]
print(n,"best fold period %.2f ms (= 47 x %.3f ms), contrast %.2f dB vs median %.2f"%(P*1e3,P*1e3/47,max(c),np.median(c)))
m=int(round(P/0.5e-3)); rows=int(len(db)*0.5e-3/P)
R=np.array([db[int(round(r*P/0.5e-3)):int(round(r*P/0.5e-3))+m] for r in range(rows-1)])
fig,ax=plt.subplots(2,1,figsize=(14,10),gridspec_kw=dict(height_ratios=[3,1]))
im=ax[0].imshow(R,aspect="auto",cmap="inferno",extent=[0,m*0.5,rows-1,0],vmin=0,vmax=20,interpolation="nearest")
ax[0].set_xlabel(f"time within one {P*1e3:.2f} ms cycle [ms]"); ax[0].set_ylabel("cycle number (each row = next 47-hop cycle)")
ax[0].set_title(f"{n}: received power at 2421.031 MHz folded at the D8 hop-cycle period ({P*1e3:.2f} ms = 47 hops x {P*1e3/47:.3f} ms). Vertical stripes = bursts that repeat every cycle")
fig.colorbar(im,ax=ax[0],pad=.01).set_label("power, 0.5 ms avg [dB re 1 LSB^2]")
ax[1].plot(np.arange(len(fold(P)))*0.5,fold(P)); ax[1].set_xlabel(f"time within cycle [ms]"); ax[1].set_ylabel("mean power over\nall cycles [dB]"); ax[1].set_xlim(0,m*0.5)
for j in range(48): ax[1].axvline(j*P*1e3/47,color="grey",lw=.3)
ax[1].set_title("average over all cycles; grey lines = 47 hop slots")
fig.tight_layout(); fig.savefig(f"png/{n}_fold.png",dpi=80)
