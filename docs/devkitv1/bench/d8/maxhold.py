import sys, numpy as np
sys.path.insert(0,"/Users/1unoe/Developer/personal/esp32-devkitv1-sdr/host")
from esp32sdr.device import Device
from esp32sdr.spec_cmd import spectrum
tag=sys.argv[1]; ms=int(sys.argv[2]) if len(sys.argv)>2 else 5000
dev=Device.open("/dev/cu.usbserial-0001")
out={}
for det,name in ((1,"max"),(0,"mean")):
    dev.tune(2441)
    run=spectrum(dev,bins=2048,rate_code=0,ms=ms,detector=det)
    f,p=run.sorted_db(); out[name]=p; out["f"]=f
    print(tag,name,"frames",len(run.frames),"ffts",run.ffts,"end",run.end)
np.savez(f"/tmp/d8/spec_{tag}.npz",**out)
dev.t.close() if hasattr(dev.t,"close") else None
