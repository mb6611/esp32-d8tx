"""U7 helper. usage: pk.py rx FREQ MS OUT | pk.py esp FREQ MS NPKT TAG [--hold]"""
import sys,glob,os,time,json,serial
sys.path.insert(0,'bench/cc2500-rxdiag/host'); sys.path.insert(0,'bench/d8-tx/host')
import rxdiag_events as r
from bench_runner import Runner, Envelope, parse_pkt_record, compare_p_to_vector
import d8_vectors
O="bench/d8-tx/results/packet/"
VEC=d8_vectors.build(0)
def stm_open():
    fd=r.openp(glob.glob('/dev/cu.usbmodem*')[0]); assert r.cli(fd); r.rd(fd,.3); return fd
def stm_run(fd,freq,ms,out,pre=None):
    os.write(fd,f"rxdiag pkt {freq} {ms}\n".encode()); t0=time.time(); buf=b""; L=[]; called=False
    f=open(out,"a"); f.write(f"# cmd=rxdiag pkt {freq} {ms} utc={time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}\n")
    while time.time()-t0<ms/1000+6:
        buf+=r.rd(fd,0.02); *ls,buf=buf.split(b"\n")
        for l in ls:
            s=l.decode('latin1').rstrip("\r"); f.write(f"{time.time():.4f} {s}\n"); L.append(s)
            if s.startswith("H,") and pre and not called: called=True; pre()
        if any(s.startswith("X,") for s in L): break
    f.close()
    if not any(s.startswith("X,") for s in L): os.write(fd,b"q"); r.rd(fd,.4)
    r.cli(fd); return L
def ps(L):
    out=[]
    for l in L:
        if l.startswith("P,"):
            try: out.append(parse_pkt_record(l))
            except Exception as e:
                print("  PARSEFAIL",l,e); f=l.split(","); out.append({"kind":"P","data":bytes.fromhex(f[4]),"len":int(f[3]),"crc_ok":int(f[7]),"rssi":int(f[5]),"lqi":int(f[6]),"raw":l})
    return out
def show(L):
    P=ps(L); print("H:",[l for l in L if l.startswith("H,")][:1]); print("E/X:",[l for l in L if l[:2] in("E,","X,")])
    print("P records:",len(P),"crc_ok:",sum(p["crc_ok"] for p in P))
    for p in P: print(" ",p["data"].hex(),p["crc_ok"],p["rssi"],p["lqi"])
    return P
if __name__=="__main__":
    m=sys.argv[1]
    if m=="rx":
        fd=stm_open(); L=stm_run(fd,sys.argv[2],int(sys.argv[3]),sys.argv[4]); show(L)
    elif m=="esp":
        freq,ms,n,tag=sys.argv[2],int(sys.argv[3]),int(sys.argv[4]),sys.argv[5]
        fd=stm_open()
        s=serial.Serial('/dev/cu.usbserial-0001',921600,timeout=0.05); s.reset_input_buffer()
        run=Runner(s,O+"esp_runner_log.jsonl"); run.set_phase("esp32-test")
        assert run.command("STAT").records["keyed"]==0
        run.authorize(Envelope("U7 packet 2412 pwr127",6800,1,127,0,30,max_packets=30))
        hexv=VEC[:18].hex(); res=[]
        def pre():
            time.sleep(0.4)
            try:
                for i in range(n):
                    t=time.time(); rp=run.command(f"PKT {hexv} 127")
                    res.append((i,t,rp.lines)); open(O+f"{tag}_esp.txt","a").write(f"i={i} t_send={t:.4f}\n"+"\n".join(rp.lines)+"\n")
                    print("K",i,rp.lines,flush=True); time.sleep(0.5)
            except Exception as e:
                print("STOP",repr(e)); s.write(b"U\n"); res.append(("STOP",repr(e)))
        try: L=stm_run(fd,freq,ms,O+f"{tag}_stm.txt",pre)
        finally: s.write(b"U\n"); time.sleep(.3); print("U->",s.read(100))
        print("STAT",run.command("STAT").lines)
        P=show(L)
        for p in P: print(compare_p_to_vector(p,VEC))
