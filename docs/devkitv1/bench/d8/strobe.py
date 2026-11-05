import sys,numpy as np,matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
sys.path.insert(0,"/Users/1unoe/Developer/personal/esp32-devkitv1-sdr/host")
from esp32sdr.device import Device
from esp32sdr.spec_cmd import spectrum
tag=sys.argv[1]; P=0.42595
dev=Device.open("/dev/cu.usbserial-0001"); dev.tune(2441)
run=spectrum(dev,bins=2048,rate_code=0,ms=20000,detector=1)
fs=run.fs; f=run.rf_axis_hz(); o=np.argsort(f); f=f[o]/1e6
T=np.array([fr.first_sample/fs for fr in run.frames]); D=np.stack([fr.db()[o] for fr in run.frames])
np.savez(f"strobe_{tag}.npz",T=T,D=D,f=f)
print(tag,"frames",len(T),"span s %.1f"%(T[-1]-T[0]),"median dt ms %.1f"%(np.median(np.diff(T))*1e3))
