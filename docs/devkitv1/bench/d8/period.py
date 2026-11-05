import numpy as np,sys
fs=62500.0; x=np.fromfile(f"/tmp/d8/{sys.argv[1]}.sigmf-data",dtype=np.complex64); x=x-x.mean()
p=np.abs(x)**2; k=int(0.0005*fs); e=p[:len(p)//k*k].reshape(-1,k).mean(1)   # 0.5 ms bins
db=10*np.log10(e+1e-6)
for thr in (15,17):
    b=(db>thr).astype(float)
    on=np.flatnonzero(np.diff(b)==1); 
    print(sys.argv[1],"thr",thr,"bursts",len(on),"per s %.2f"%(len(on)/20))
    if len(on)>2:
        d=np.diff(on)*0.5
        print("  median gap ms %.1f; gaps within 423+-3 or multiples: %d / %d"%(np.median(d), sum(np.min(np.abs(d[:,None]-423*np.arange(1,6)[None,:]),1)<3), len(d)))
    bb=b-b.mean(); ac=np.correlate(bb,bb,"full")[len(bb)-1:]; ac/=ac[0]
    lags=np.arange(len(ac))*0.5
    sel=(lags>20)&(lags<1000); i=np.argmax(ac[sel]); print("  autocorr peak at %.1f ms (%.3f); at 423ms: %.3f; median 20-1000: %.3f"%(lags[sel][i],ac[sel][i],ac[int(423/0.5)],np.median(ac[sel])))
