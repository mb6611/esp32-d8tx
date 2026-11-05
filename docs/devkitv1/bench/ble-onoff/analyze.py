import numpy as np, json, matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
fs=31250.0; out="/tmp/ble/png"; res={}
def load(n):
    x=np.fromfile(f"/tmp/ble/{n}.sigmf-data",dtype=np.complex64); return x-x.mean()
data={n:load(n) for n in ["off","on","first_unsure"]}
# common threshold from OFF: power smoothed over 3 samples (~96 us)
FS2=127.0**2  # 8-bit full scale
def pw(x): return np.convolve(np.abs(x)**2,np.ones(3)/3,mode="same")/FS2
p_off=pw(data["off"]); med=np.median(p_off)
thr=np.percentile(p_off,99.99)  # off-recording 99.99th pct -> ~6 false hits per 20 s if stationary
for n,x in data.items():
    p=pw(x); hit=p>thr
    e=np.flatnonzero(np.diff(hit.astype(int))==1)+1
    # merge events closer than 2 ms
    ev=[];
    for i in e:
        if not ev or i-ev[-1]>int(0.002*fs): ev.append(i)
    ev=np.array(ev); t=ev/fs; iv=np.diff(t)*1e3
    res[n]=dict(events=len(ev),rate_per_s=len(ev)/(len(x)/fs),median_interval_ms=float(np.median(iv)) if len(iv) else None,
                p_median_db=float(10*np.log10(np.median(p))),p_9999_db=float(10*np.log10(np.percentile(p,99.99))),thr_db=float(10*np.log10(thr)))
    fig,ax=plt.subplots(4,1,figsize=(13,15))
    tt=np.arange(len(p))/fs; db=10*np.log10(p+1e-12); tdb=10*np.log10(thr)
    ax[0].plot(tt,db,lw=0.3); ax[0].axhline(tdb,color="r",label="detection threshold")
    ax[0].set_title(f"{n}: TIME DOMAIN - received power in the 31 kHz window at 2480 MHz (96 us moving average); events={len(ev)}")
    ax[0].set_xlabel("time since start of recording [s]"); ax[0].set_ylabel("power [dBFS, re 8-bit full scale]"); ax[0].legend(loc="lower right")
    z=(tt>=5)&(tt<6); ax[1].plot((tt[z]-5)*1e3,db[z],lw=0.5); ax[1].axhline(tdb,color="r")
    ax[1].set_title("TIME DOMAIN zoom: 1 s window starting at t = 5 s (each spike = one burst)"); ax[1].set_xlabel("time since t = 5 s [ms]"); ax[1].set_ylabel("power [dBFS]")
    seg=x[int(5*fs):int(7*fs)]/127.0
    Pxx,f,tb,im=ax[2].specgram(seg,NFFT=64,noverlap=48,Fs=fs,Fc=0,cmap="viridis",scale="dB")
    ax[2].set_title("TIME-FREQUENCY (spectrogram), t = 5-7 s, 2 ms FFT, 0.5 ms hop\nvertical lines = wideband bursts; line at 0 Hz = chip LO leakage")
    ax[2].set_xlabel("time since t = 5 s [s]"); ax[2].set_ylabel("frequency offset from 2480 MHz [Hz]")
    cb=fig.colorbar(im,ax=ax[2],pad=0.01); cb.set_label("power spectral density [dBFS/Hz]")
    if len(iv):
        ax[3].hist(np.clip(iv,0,300),bins=100); ax[3].set_title("time between consecutive detected bursts (peaks at multiples of the advertising interval)")
        ax[3].set_xlabel("interval between bursts [ms] (clipped at 300)"); ax[3].set_ylabel("count [bursts]")
    fig.tight_layout(); fig.savefig(f"{out}/{n}.png",dpi=90); plt.close(fig)
# side by side comparison
fig,ax=plt.subplots(2,1,figsize=(13,7),sharex=True,sharey=True)
for a,n in zip(ax,["off","on"]):
    p=pw(data[n]); a.plot(np.arange(len(p))/fs,10*np.log10(p+1e-12),lw=0.3); a.axhline(10*np.log10(thr),color="r",label="detection threshold")
    a.set_title(f"advertiser {n.upper()}: received power at 2480 MHz (BLE ch39), 31 kHz window, 96 us average; bursts above threshold = {res[n]['events']}")
    a.set_ylabel("power [dBFS]"); a.legend(loc="lower right")
ax[1].set_xlabel("time since start of recording [s]"); fig.tight_layout(); fig.savefig(f"{out}/compare_on_off.png",dpi=90)
print(json.dumps(res,indent=1))
