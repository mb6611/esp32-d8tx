import numpy as np, matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
import importlib.util; spec=importlib.util.spec_from_file_location("iso","/tmp/ble/isolate.py")
import contextlib,io
with contextlib.redirect_stdout(io.StringIO()):
    iso=importlib.util.module_from_spec(spec); spec.loader.exec_module(iso)
fs=iso.fs; r=iso.res["on"]; T=iso.T
x=np.fromfile("/tmp/ble/on.sigmf-data",dtype=np.complex64)/127.0; x=x-x.mean()
def stft(x,nfft=16,hop=4):
    w=np.hanning(nfft); n=(len(x)-nfft)//hop; idx=np.arange(nfft)[None,:]+hop*np.arange(n)[:,None]
    S=np.fft.fftshift(np.fft.fft(x[idx]*w,axis=1),axes=1)
    return 10*np.log10(np.abs(S)**2/(fs*np.sum(w**2))+1e-15).T, (np.arange(n)*hop+nfft/2)/fs, np.fft.fftshift(np.fft.fftfreq(nfft,1/fs))
HALF=0.0006  # keep +-0.6 ms around each pulse peak
def gate(times):
    m=np.zeros(len(x),bool)
    for t in times: m[max(0,int((t-HALF)*fs)):int((t+HALF)*fs)]=True
    return m
ph=r["t"][r["isph"]]; ot=r["t"][~r["isph"]]
mph,mot=gate(ph),gate(ot)
for t0,dur,name in ((5.0,0.2,"200ms"),(5.0,1.0,"1s")):
    sl=slice(int(t0*fs),int((t0+dur)*fs))
    S,t,f=stft(x[sl]); ref=np.percentile(S,50)
    fig,ax=plt.subplots(3,1,figsize=(14,10),sharex=True)
    panels=[("ALL signal (advertiser ON)",np.ones(len(t),bool)),
            (f"PHONE ONLY: pulses on the {T*1e3:.1f} ms + 0-10 ms train (+-0.6 ms around each)",mph[sl][(t*fs).astype(int)]),
            ("EVERYTHING ELSE: all signal with the phone pulses removed (other devices, weaker pulses, LO leakage)",~mph[sl][(t*fs).astype(int)])]
    for a,(title,keep) in zip(ax,panels):
        S2=np.where(keep[None,:],S,ref-20)
        im=a.imshow(S2,aspect="auto",origin="lower",extent=[t[0]*1e3,t[-1]*1e3,f[0]/1e3,f[-1]/1e3],vmin=ref+3,vmax=ref+30,cmap="inferno",interpolation="nearest")
        a.set_title(title); a.set_ylabel("frequency offset\nfrom 2480 MHz [kHz]"); fig.colorbar(im,ax=a,pad=0.01).set_label("PSD [dBFS/Hz]")
    for tp in ph[(ph>=t0)&(ph<t0+dur)]: ax[0].axvline((tp-t0)*1e3,ymin=0.93,ymax=1.0,color="cyan",lw=1.5)
    ax[0].set_title("ALL signal (advertiser ON); cyan ticks at top = pulses attributed to the phone")
    ax[2].set_xlabel(f"time since t = {t0:.0f} s [ms]  (spectrogram: 16-pt FFT = 0.5 ms, hop 0.128 ms; LO leakage at 0 Hz partly removed)")
    fig.tight_layout(); fig.savefig(f"/tmp/ble/png/spectrogram_phone_isolated_{name}.png",dpi=85); plt.close(fig)
print(len(ph),len(ot))
