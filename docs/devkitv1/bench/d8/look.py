import numpy as np,sys,matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
fs=62500.0; n=sys.argv[1]; x=np.fromfile(f"/tmp/d8/{n}.sigmf-data",dtype=np.complex64)
print("max abs",np.abs(x).max(),"median",np.median(np.abs(x)))
x=x-x.mean(); p=np.convolve(np.abs(x)**2,np.ones(32)/32,mode="same")
fig,ax=plt.subplots(3,1,figsize=(14,11))
t=np.arange(len(p))/fs
ax[0].plot(t,10*np.log10(p+1e-9),lw=.3); ax[0].set_xlabel("time [s]"); ax[0].set_ylabel("power, 0.5 ms avg [dB re 1 LSB^2]"); ax[0].set_title(f"{n}: 2421.031 MHz, 62.5 kS/s, 20 s")
z=(t>=5)&(t<7); ax[1].plot(t[z],10*np.log10(p[z]+1e-9),lw=.5); ax[1].set_xlabel("time [s]"); ax[1].set_title("zoom 5-7 s")
ax[2].specgram(x[int(5*fs):int(6*fs)],NFFT=128,noverlap=96,Fs=fs,cmap="inferno"); ax[2].set_xlabel("time since 5 s [s]"); ax[2].set_ylabel("offset from 2421.031 MHz [Hz]"); ax[2].set_title("spectrogram 5-6 s (2 ms FFT)")
fig.tight_layout(); fig.savefig(f"png/{n}_look.png",dpi=80)
