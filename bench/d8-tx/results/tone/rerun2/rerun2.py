import sys,glob,os,time,json,serial
sys.path.insert(0,'bench/d8-tx/results/tone'); sys.path.insert(0,'bench/d8-tx/host')
import stmfreq as m, rxdiag_events as r
from bench_runner import Runner, Envelope
O="bench/d8-tx/results/tone/rerun2/"
RX="rxdiag freq 2412000 100 812 203 66 "
stage=sys.argv[1]
fd=r.openp(glob.glob('/dev/cu.usbmodem*')[0]); assert r.cli(fd); r.rd(fd,.3)
s=serial.Serial('/dev/cu.usbserial-0001',921600,timeout=0.05)
time.sleep(4); s.reset_input_buffer()
run=Runner(s,O+"esp_runner_log_%s.jsonl"%stage,reply_timeout_s=2.0)
run.set_phase("esp32-test")
rp=run.command("PING"); assert rp.ok; print(rp.lines)
rp=run.command("STAT"); assert rp.ok and rp.records["keyed"]==0, rp.lines
def summarize(name,L,t0cmd=None):
    F=[l.split(",") for l in L if l.startswith("F,")]
    hit=[(int(x[1]),int(x[5]),int(x[7]),int(x[8]),int(x[10])) for x in F if int(x[5])>0]
    print(name,"windows",len(F),"CS windows (seq,ncs,fe_min,fe_max,fe_mean_hz)",hit,flush=True); return F,hit
if stage=="control":
    L=m.run(fd,RX+"3000",3.0,O+"control_source_off_2412000.txt",None)
    os.write(fd,b"q"); r.rd(fd,.4); summarize("control",L); sys.exit()
run.authorize(Envelope("U4 rerun2 pwr127",150000,16,127,20,12))
seq=[]
for f,reps in [(int(a),3) for a in sys.argv[2].split(",")] if stage=="tone" else []:
    for rep in range(1,reps+1): seq.append((f"tone_f{f}_r{rep}",f"TONE {f} 150000 127",150000))
if stage=="alt":
    for rep in range(1,4): seq.append((f"alt_r{rep}","ALT 16 -16 5000 100000 127",100000))
try:
  for name,cmd,dur in seq:
    res={}
    def pre():
        time.sleep(0.4); t=time.time(); res["rp"]=run.command(cmd); res["t"]=t
    L=m.run(fd,RX+"1200",1.2,O+f"{name}_stm.txt",pre)
    os.write(fd,b"q"); r.rd(fd,.4); r.cli(fd)
    rp=res["rp"]; open(O+f"{name}_esp.txt","w").write(f"cmd={cmd} t_send={res['t']:.4f}\n"+"\n".join(rp.lines)+"\n")
    st=run.command("STAT"); assert st.records["keyed"]==0
    print(rp.lines[:2]); summarize(name,L); time.sleep(1)
except Exception as e:
    print("STOP:",repr(e)); raise
finally:
    s.write(b"U\n"); time.sleep(.3)
