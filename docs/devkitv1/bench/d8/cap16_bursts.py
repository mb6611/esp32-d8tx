import sys,time,numpy as np
sys.path.insert(0,"/Users/1unoe/Developer/personal/esp32-devkitv1-sdr/host")
from esp32sdr.device import Device
from esp32sdr.samples import decode_cap
lo=int(sys.argv[1]); n=int(sys.argv[2]); fofs=int(sys.argv[3]) if len(sys.argv)>3 else 0
dev=Device.open("/dev/cu.usbserial-0001")
print(dev.command(f"FOFS {fofs}")); dev.tune(lo)
print("GAIN?",dev.command("GAIN?"))
caps=[];ts=[]
t0=time.time()
for k in range(n):
    raw=dev.cap16(16380,6,8); caps.append(decode_cap(raw,8)); ts.append(time.time()-t0)
print("done",n,"in",round(time.time()-t0,1),"s")
np.savez(f"/tmp/d8/cap/lo{lo}_f{fofs}.npz",x=np.array(caps),t=np.array(ts))
dev.close()
