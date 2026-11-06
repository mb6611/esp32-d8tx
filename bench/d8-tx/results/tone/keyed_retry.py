import sys,glob,os,time,json,serial; sys.path.insert(0,'bench/d8-tx/results/tone'); sys.path.insert(0,'bench/d8-tx/host')
import stmfreq as m, rxdiag_events as r
from bench_runner import Runner, Envelope
O="bench/d8-tx/results/tone/"
fd=r.openp(glob.glob('/dev/cu.usbmodem*')[0]); assert r.cli(fd); r.rd(fd,.3)
s=serial.Serial('/dev/cu.usbserial-0001',921600,timeout=0.05)
time.sleep(4); s.reset_input_buffer()
run=Runner(s,O+"esp_runner_log_retry.jsonl",reply_timeout_s=2.0)
run.set_phase("esp32-test")
rp=run.command("PING"); assert rp.ok; print(rp.lines)
rp=run.command("STAT"); assert rp.ok and rp.records["keyed"]==0, rp.lines
run.authorize(Envelope("U4 tone 2412 pwr32",150000,16,32,20,12))
seq=[]
for rep in range(1,4):
    for f in (0,16,-16): seq.append((f"tone_f{f}_r{rep}",f"TONE {f} 150000 32",150000))
for rep in range(1,4): seq.append((f"alt_r{rep}","ALT 16 -16 5000 100000 32",100000))
summ=[]
try:
  for name,cmd,dur in seq:
    res={}
    def pre():
        time.sleep(0.4)
        t=time.time(); rp=run.command(cmd); res["rp"]=rp; res["t"]=t
    L=m.run(fd,"rxdiag freq 2412000 100 812 251 64 1200",1.2,O+f"retry_{name}_stm.txt",pre)
    os.write(fd,b"q"); r.rd(fd,.4); r.cli(fd)
    rp=res["rp"]; open(O+f"retry_{name}_esp.txt","w").write(f"cmd={cmd} t_send={res['t']:.4f}\n"+"\n".join(rp.lines)+"\nOK\n")
    st=run.command("STAT"); assert st.records["keyed"]==0
    F=[l.split(",") for l in L if l.startswith("F,")]
    hit=[(int(x[0 +1]),int(x[5]),int(x[9]),int(x[14]),x[15]) for x in F if int(x[5])>0]
    print(name,rp.lines[0],"| windows",len(F),"CS windows",hit,flush=True)
    time.sleep(1)
except Exception as e:
    print("STOP:",repr(e)); s.write(b"U\n")
    raise
finally:
    s.write(b"U\n"); time.sleep(.3); print(s.read(200))
