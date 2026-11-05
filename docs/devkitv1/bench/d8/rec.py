import sys,numpy as np
sys.path.insert(0,"/Users/1unoe/Developer/personal/esp32-devkitv1-sdr/host")
from esp32sdr.device import Device
from esp32sdr.iqs import IqsSession
tag,mhz,fofs,sh=sys.argv[1],int(sys.argv[2]),int(sys.argv[3]),int(sys.argv[4])
dev=Device.open("/dev/cu.usbserial-0001")
s=IqsSession(dev,256,4,mhz,fofs,seconds=20,shift=sh)
out=[iq for iq,fr in s.blocks()]
x=np.concatenate(out).astype(np.complex64); x.tofile(f"/tmp/d8/{tag}.sigmf-data")
print(tag,len(x),"lost",s.stats.lost if hasattr(s.stats,"lost") else s.stats, "max",np.abs(x).max(),"median",np.median(np.abs(x)))
