import numpy as np, matplotlib, contextlib, io, importlib.util; matplotlib.use("Agg"); import matplotlib.pyplot as plt
spec=importlib.util.spec_from_file_location("iso","/tmp/ble/isolate.py")
with contextlib.redirect_stdout(io.StringIO()):
    iso=importlib.util.module_from_spec(spec); spec.loader.exec_module(iso)
fs=iso.fs; HALF=0.0006
def load(n): x=np.fromfile(f"/tmp/ble/{n}.sigmf-data",dtype=np.complex64)/127.0; return x-x.mean()
def frames(x,nfft=16,hop=4):
    w=np.hanning(nfft); n=(len(x)-nfft)//hop; idx=np.arange(nfft)[None,:]+hop*np.arange(n)[:,None]
    S=np.abs(np.fft.fftshift(np.fft.fft(x[idx]*w,axis=1),axes=1))**2/(fs*np.sum(w**2)); return S, idx[:,nfft//2]
xon,xoff=load("on"),load("off")
r=iso.res["on"]; ph=r["t"][r["isph"]]
m=np.zeros(len(xon),bool)
for t in ph: m[max(0,int((t-HALF)*fs)):int((t+HALF)*fs)]=True
Son,c_on=frames(xon); Soff,_=frames(xoff)
keep=~m[c_on]
f=np.fft.fftshift(np.fft.fftfreq(16,1/fs))/1e3
psd_res=10*np.log10(Son[keep].mean(0)); psd_off=10*np.log10(Soff.mean(0)); psd_on=10*np.log10(Son.mean(0)); psd_ph=10*np.log10(Son[~keep].mean(0))
# pulse counts per second
n_off=len(iso.res["off"]["t"]); n_res=int((~r["isph"]).sum()); dur=r["dur"]; dur_res=dur-m.sum()/fs
fig,ax=plt.subplots(2,2,figsize=(14,9))
a=ax[0,0]; a.plot(f,psd_off,"C0",label="advertiser OFF recording"); a.plot(f,psd_res,"C2",label="ON recording with phone pulses removed"); a.plot(f,psd_on,"C1",ls="--",label="ON recording, everything")
a.set_xlabel("frequency offset from 2480 MHz [kHz]"); a.set_ylabel("time-averaged PSD [dBFS/Hz]"); a.set_title("average spectrum (20 s, 0.5 ms FFTs)"); a.legend(fontsize=8)
a=ax[0,1]; a.plot(f,psd_res-psd_off,"C2",label="(ON minus phone) - OFF"); a.plot(f,psd_on-psd_off,"C1",ls="--",label="ON - OFF"); a.axhline(0,color="k",lw=.5)
a.set_xlabel("frequency offset from 2480 MHz [kHz]"); a.set_ylabel("difference [dB]"); a.set_title("spectrum difference vs OFF (0 dB = identical)"); a.legend(fontsize=8)
a=ax[1,0]; bins=np.arange(18,32,0.5)
a.hist(iso.res["off"]["s"],bins=bins,histtype="step",lw=2,color="C0",density=True,label=f"OFF: all pulses ({n_off/dur:.1f}/s)")
a.hist(r["s"][~r["isph"]],bins=bins,histtype="step",lw=2,color="C2",density=True,label=f"ON minus phone ({n_res/dur_res:.1f}/s)")
a.hist(r["s"][r["isph"]],bins=bins,histtype="step",lw=2,color="red",density=True,label=f"phone pulses ({len(ph)/dur:.1f}/s)")
a.set_xlabel("pulse SNR over local noise floor [dB]"); a.set_ylabel("fraction of pulses [1/dB]"); a.set_title("pulse strength distributions"); a.legend(fontsize=8)
a=ax[1,1]; a.bar(["OFF\nall pulses","ON minus\nphone","phone"],[n_off/dur,n_res/dur_res,len(ph)/dur],color=["C0","C2","red"]); a.set_ylabel("pulses per second (>= 18 dB SNR)"); a.set_title("pulse rate")
fig.suptitle("Is 'ON with the phone removed' the same as 'OFF'? (statistical comparison; two separate recordings cannot be subtracted sample by sample)")
fig.tight_layout(); fig.savefig("/tmp/ble/png/residual_vs_off.png",dpi=85)
print("rates /s off, res, phone:",round(n_off/dur,1),round(n_res/dur_res,1),round(len(ph)/dur,1))
print("PSD diff (res-off) dB per bin:",np.round(psd_res-psd_off,1)); print("PSD diff (on-off):",np.round(psd_on-psd_off,1))
