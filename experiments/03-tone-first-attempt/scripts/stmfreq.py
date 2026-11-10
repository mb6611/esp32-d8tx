import sys,os,time,glob
sys.path.insert(0,'tools/cc2500-rxdiag/host'); sys.path.insert(0,'tools/d8-tx-host')
import rxdiag_events as r
from bench_runner import parse_report
def run(fd,cmd,secs,out,pre=None):
    """send cmd; read until X; log raw lines with host timestamps. pre(): callback after H seen"""
    os.write(fd,(cmd+"\n").encode()); t0=time.time(); buf=b""; lines=[]
    f=open(out,"a"); f.write(f"# cmd={cmd} utc={time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}\n")
    called=False
    while time.time()-t0<secs+5:
        d=r.rd(fd,0.05); buf+=d
        *ls,buf=buf.split(b"\n")
        for l in ls:
            s=l.decode('latin1').rstrip("\r"); f.write(f"{time.time():.4f} {s}\n"); lines.append(s)
            if s.startswith("H,") and pre and not called: called=True; pre()
        if any(s.startswith("X,") for s in lines): break
    f.close(); return lines
