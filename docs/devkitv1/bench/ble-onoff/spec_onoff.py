import numpy as np, matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
fs=31250.0
def load(n):
    x=np.fromfile(f"/tmp/ble/{n}.sigmf-data",dtype=np.complex64)/127.0; return x-x.mean()  # remove LO leakage (DC)
def stft(x,nfft=16,hop=4):
    w=np.hanning(nfft); n=(len(x)-nfft)//hop
    idx=np.arange(nfft)[None,:]+hop*np.arange(n)[:,None]
    S=np.fft.fftshift(np.fft.fft(x[idx]*w,axis=1),axes=1)
    return 10*np.log10(np.abs(S)**2/(fs*np.sum(w**2))+1e-15).T, np.arange(n)*hop/fs, np.fft.fftshift(np.fft.fftfreq(nfft,1/fs))
t0,dur=5.0,1.0
fig,ax=plt.subplots(2,1,figsize=(14,8),sharex=True)
specs={}
for n in ["off","on"]:
    x=load(n); specs[n]=stft(x[int(t0*fs):int((t0+dur)*fs)])
ref=np.percentile(specs["off"][0],50)
for a,n in zip(ax,["off","on"]):
    S,t,f=specs[n]
    im=a.imshow(S,aspect="auto",origin="lower",extent=[t[0]*1e3,t[-1]*1e3,f[0]/1e3,f[-1]/1e3],vmin=ref+3,vmax=ref+30,cmap="inferno",interpolation="nearest")
    a.set_title(f"advertiser {n.upper()}: spectrogram at 2480 MHz (BLE ch39), t = {t0:.0f}-{t0+dur:.0f} s  |  16-pt FFT = 0.5 ms, hop 0.128 ms, DC (LO leakage) removed")
    a.set_ylabel("frequency offset\nfrom 2480 MHz [kHz]")
    cb=fig.colorbar(im,ax=a,pad=0.01); cb.set_label("PSD [dBFS/Hz]")
ax[1].set_xlabel(f"time since t = {t0:.0f} s [ms]")
fig.tight_layout(); fig.savefig("/tmp/ble/png/spectrogram_on_vs_off.png",dpi=90)
# 200 ms zoom of ON to show individual pulses
S,t,f=specs["on"]; m=t<0.2
fig,a=plt.subplots(figsize=(14,4))
im=a.imshow(S[:,m],aspect="auto",origin="lower",extent=[0,t[m][-1]*1e3,f[0]/1e3,f[-1]/1e3],vmin=ref+3,vmax=ref+30,cmap="inferno",interpolation="nearest")
a.set_title("advertiser ON, 200 ms zoom: each vertical line = one BLE advertising packet (~0.1-0.4 ms, 1 MHz wide so it fills the 31 kHz window)")
a.set_xlabel(f"time since t = {t0:.0f} s [ms]"); a.set_ylabel("frequency offset\nfrom 2480 MHz [kHz]"); fig.colorbar(im,ax=a,pad=0.01).set_label("PSD [dBFS/Hz]")
fig.tight_layout(); fig.savefig("/tmp/ble/png/spectrogram_on_zoom200ms.png",dpi=90)
