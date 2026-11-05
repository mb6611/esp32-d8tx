import numpy as np, json, matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
from scipy.ndimage import median_filter
fs=31250.0; JIT=0.0105  # BLE advDelay 0-10 ms (+ slack)
def pulses(n, snr_thr=18.0):
    x=np.fromfile(f"/tmp/ble/{n}.sigmf-data",dtype=np.complex64); x=x-x.mean()
    p=np.convolve(np.abs(x)**2,np.ones(3)/3,mode="same")
    floor=median_filter(p[::16],size=int(0.05*fs/16)+1,mode="nearest").repeat(16)[:len(p)]  # 50 ms running median noise floor
    snr=10*np.log10(p/floor+1e-12)
    hit=np.flatnonzero(snr>snr_thr); ev=[]
    for i in hit:
        if ev and i-ev[-1][0]<int(0.001*fs):
            if snr[i]>ev[-1][1]: ev[-1]=(i,snr[i])
        else: ev.append((i,snr[i]))
    t=np.array([e[0] for e in ev])/fs; s=np.array([e[1] for e in ev]); return t,s,len(x)/fs
def best_T(t):
    Ts=np.arange(0.020,0.300,0.00025); score=[]
    for T in Ts:
        d=t[None,:]-t[:,None]; score.append(np.sum((d>=T)&(d<=T+JIT)))
    score=np.array(score); return Ts, score
def chain(t,s,T):
    # greedy: grow a chain from each seed, allowing up to 2 misses; keep the longest
    best=[]
    order=np.argsort(-s)[:40]
    for seed in order:
        ch=[seed]
        for direction in (1,-1):
            cur=seed
            while True:
                nxt=None
                for k in (1,2,3):
                    lo,hi=(t[cur]+k*T, t[cur]+k*(T+JIT)) if direction>0 else (t[cur]-k*(T+JIT), t[cur]-k*T)
                    c=np.flatnonzero((t>=lo)&(t<=hi))
                    if len(c): nxt=c[np.argmax(s[c])]; break
                if nxt is None: break
                ch.append(nxt); cur=nxt
        ch=sorted(set(ch))
        if len(ch)>len(best): best=ch
    return np.array(best)
res={}
for n in ["off","on"]:
    t,s,dur=pulses(n); Ts,score=best_T(t); 
    # normalise score by chance level (pairs expected for random pulses)
    T=Ts[np.argmax(score)] if n=="on" else None
    res[n]=dict(t=t,s=s,dur=dur,Ts=Ts,score=score)
T=res["on"]["Ts"][np.argmax(res["on"]["score"])]
summary={}
for n in ["off","on"]:
    r=res[n]; ch=chain(r["t"],r["s"],T); r["ch"]=ch
    isph=np.zeros(len(r["t"]),bool); isph[ch]=True; r["isph"]=isph
    gaps=np.diff(r["t"][ch])*1e3
    summary[n]=dict(pulses=int(len(r["t"])),train_pulses=int(len(ch)),train_span_s=float(r["t"][ch][-1]-r["t"][ch][0]) if len(ch) else 0,
        train_fraction_of_expected=float(len(ch)/(r["dur"]/(T+JIT/2))),
        snr_train_median_db=float(np.median(r["s"][isph])) if isph.any() else None,
        snr_other_median_db=float(np.median(r["s"][~isph])) if (~isph).any() else None)
summary["T_ms"]=float(T*1e3)
print(json.dumps(summary,indent=1))
fig=plt.figure(figsize=(14,15)); gs=fig.add_gridspec(4,2)
a=fig.add_subplot(gs[0,:])
for n,c in (("on","C1"),("off","C0")):
    sc=res[n]["score"]; a.plot(res[n]["Ts"]*1e3,sc,c,label=f"advertiser {n}")
a.axvline(T*1e3,color="k",ls="--",label=f"best T = {T*1e3:.2f} ms")
a.set_title("STEP 1 - periodicity search: number of pulse pairs whose gap is in [T, T+10.5 ms] (BLE adds a random 0-10 ms delay to every advertising event)")
a.set_xlabel("candidate advertising interval T [ms]"); a.set_ylabel("matching pulse pairs [count]"); a.legend()
for row,n in ((1,"on"),(2,"off")):
    r=res[n]; a=fig.add_subplot(gs[row,:])
    a.scatter(r["t"][~r["isph"]],r["s"][~r["isph"]],s=10,c="grey",label="other pulses (other devices / noise)")
    a.scatter(r["t"][r["isph"]],r["s"][r["isph"]],s=14,c="red",label=f"pulses on the {T*1e3:.1f} ms train (phone)")
    a.set_title(f"STEP 2 - advertiser {n.upper()}: every detected pulse at 2480 MHz; red = longest chain with gaps in [T, T+10.5 ms] (up to 2 misses allowed)")
    a.set_xlabel("time since start of recording [s]"); a.set_ylabel("pulse SNR over local\nnoise floor [dB]"); a.legend(loc="upper right"); a.set_ylim(10,40)
a=fig.add_subplot(gs[3,0]); r=res["on"]
bins=np.arange(10,40,1)
a.hist(r["s"][r["isph"]],bins=bins,alpha=.7,color="red",label="on the train (phone)"); a.hist(r["s"][~r["isph"]],bins=bins,alpha=.6,color="grey",label="other")
a.set_title("advertiser ON: pulse strength, phone vs other"); a.set_xlabel("pulse SNR over local noise floor [dB] (gain-independent)"); a.set_ylabel("count [pulses]"); a.legend()
a=fig.add_subplot(gs[3,1]); g=np.diff(r["t"][r["ch"]])*1e3
a.hist(g,bins=np.arange(0,4*T*1e3,1),color="red"); a.set_title("advertiser ON: gaps inside the phone train"); a.set_xlabel("gap between consecutive phone pulses [ms]"); a.set_ylabel("count")
fig.tight_layout(); fig.savefig("/tmp/ble/png/phone_isolation.png",dpi=85)
