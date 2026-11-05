import numpy as np
fs=16e6
h=np.sinc(2*100e3/fs*(np.arange(801)-400))*np.hamming(801); h/=h.sum()
res={}
for fn,lo in [("lo2420_f0",2420e6),("lo2417_f140",2417.14e6)]:
    X=np.load(f"/tmp/d8/cap/{fn}.npz")["x"].astype(complex); X-=X.mean(1,keepdims=True); N=X.shape[1]
    f=np.fft.fftfreq(N,1/fs)+lo
    S=np.abs(np.fft.fft(X*np.hanning(N),axis=1))**2; S/=np.median(S,1,keepdims=True)
    for fc,lab in [(2421.031e6,"031"),(2421.137e6,"137")]:
        m=np.abs(f-fc)<40e3; mo=(np.abs(f-fc)>70e3)&(np.abs(f-fc)<150e3)
        E=S[:,m].mean(1); Eo=S[:,mo].mean(1)
        for k in np.flatnonzero((E>200)&(E>4*Eo)):
            n=np.arange(N); y=np.convolve(X[k]*np.exp(-2j*np.pi*(fc-lo)*n/fs),h,"same")[400:-400:16]
            d=np.angle(y[1:]*np.conj(y[:-1]))*1e6/2/np.pi; d=d[np.abs(d)<60e3]
            # tones: 2-means
            a,b=-30e3,30e3
            for _ in range(20):
                lo_=d[np.abs(d-a)<np.abs(d-b)]; hi=d[np.abs(d-a)>=np.abs(d-b)]
                a,b=np.median(lo_),np.median(hi)
            # use plateau samples: within 8 kHz of cluster median
            a=np.mean(lo_[np.abs(lo_-a)<8e3]); b=np.mean(hi[np.abs(hi-b)<8e3])
            res.setdefault(lab,[]).append((fn,k,fc+a,fc+b))
for lab,v in res.items():
    A=np.array([[r[2],r[3]] for r in v])/1e6; mid=A.mean(1)
    print(lab,"n",len(v),"lo tone med %.4f  hi tone med %.4f  mid med %.4f MHz  spread(IQR) %.1f kHz, sep med %.1f kHz"%(np.median(A[:,0]),np.median(A[:,1]),np.median(mid),1e3*np.subtract(*np.percentile(mid,[75,25])),1e3*np.median(A[:,1]-A[:,0])))
    for r,m in zip(v,mid): print("   ",r[0],r[1],"%.4f %.4f mid %.4f"%(r[2]/1e6,r[3]/1e6,m))
