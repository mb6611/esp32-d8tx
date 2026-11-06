import sys,glob,os,time,json,serial
sys.path.insert(0,'bench/d8-tx/results/tone'); sys.path.insert(0,'bench/d8-tx/host')
import stmfreq as m, rxdiag_events as r
from bench_runner import Runner, Envelope
O="bench/d8-tx/results/tone/scan/"
# usage: scan.py label tone fc,fc,... [nrep]
label=sys.argv[1]; tone=int(sys.argv[2]); fcs=[int(x) for x in sys.argv[3].split(",")]
nrep=int(sys.argv[4]) if len(sys.argv)>4 else 1
fd=r.openp(glob.glob('/dev/cu.usbmodem*')[0]); assert r.cli(fd); r.rd(fd,.3)
s=serial.Serial('/dev/cu.usbserial-0001',921600,timeout=0.05)
time.sleep(4); s.reset_input_buffer()
run=Runner(s,O+"esp_runner_log_%s.jsonl"%label,reply_timeout_s=2.0)
run.set_phase("esp32-test")
assert run.command("PING").ok
rp=run.command("STAT"); assert rp.ok and rp.records["keyed"]==0
run.authorize(Envelope("U4 scan pwr127",150000,16,127,20,len(fcs)*nrep))
cmd=f"TONE {tone} 150000 127"
try:
  for fc in fcs:
   for rep in range(1,nrep+1):
    res={}
    def pre():
        time.sleep(0.4); res["rp"]=run.command(cmd)
    name=f"{label}_fc{fc}_r{rep}"
    L=m.run(fd,f"rxdiag freq {fc} 100 102 203 66 1200",1.2,O+name+"_stm.txt",pre)
    os.write(fd,b"q"); r.rd(fd,.4); r.cli(fd)
    open(O+name+"_esp.txt","w").write(f"cmd={cmd}\n"+"\n".join(res["rp"].lines)+"\n")
    st=run.command("STAT"); assert st.records["keyed"]==0
    F=[[int(v) for v in l.split(",")[1:]] for l in L if l.startswith("F,")]
    K=[x for x in F if 4<=x[0]<=6]; base=[x for x in F if x[0]<4]
    pk=max(K,key=lambda x:x[4]) if K else None
    out=dict(fc=fc,tone=tone,rep=rep,nwin=len(F),ncs_pk=pk[4],rssi_max=max(x[10] for x in K),fe_min=pk[6],fe_max=pk[7],fe_mean_hz=pk[9],stable=pk[6]==pk[7],base_ncs=max(x[4] for x in base) if base else None,rssi_k=[x[10] for x in K])
    print(json.dumps(out),flush=True)
    open(O+"results.jsonl","a").write(json.dumps(out)+"\n"); time.sleep(1)
finally:
    s.write(b"U\n"); time.sleep(.3)
