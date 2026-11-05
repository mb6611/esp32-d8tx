# Record 1-bit dec 64 mode-2 I/Q with a MANUAL gain index (the stream CLI has no gain option).
# usage: host/.venv/bin/python rec_centred.py BASE CENTRE_MHZ GAIN|hw SECONDS  -> BASE.sigmf-data/.sigmf-meta
import sys,json,numpy as np
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[4] / "host"))
from esp32sdr.device import Device
from esp32sdr.iqs import IqsSession, plan_tune
tag,center,gain,secs=sys.argv[1],float(sys.argv[2]),sys.argv[3],float(sys.argv[4])
mhz,fofs=plan_tune(center*1e6,2)
dev=Device.open("/dev/cu.usbserial-0001")
print(dev.command("GAIN HARDWARE" if gain=="hw" else f"GAIN MANUAL {gain}"))
s=IqsSession(dev,64,1,mhz,fofs,seconds=secs,mode=2)
x=np.concatenate([iq for iq,fr in s.blocks()]).astype(np.complex64)
g=dev.command("GAIN?"); dev.command("GAIN HARDWARE"); dev.close()
x.tofile(f"{tag}.sigmf-data")
json.dump({"global":{"core:datatype":"cf32_le","core:sample_rate":250000.0,"core:version":"1.0.0","core:hw":"ESP32 DevKit V1 (esp-sdr firmware)","esp32sdr:bits":1,"esp32sdr:decimation":64,"esp32sdr:mode":2,"esp32sdr:lo_mhz":mhz,"esp32sdr:fofs_khz":fofs,"esp32sdr:gain":g,"esp32sdr:capture":"stream","core:description":f"E8 FrSky D8, centre {center} MHz, 1-bit dec 64 mode 2"},"captures":[{"core:sample_start":0,"core:frequency":center*1e6}],"annotations":[]},open(f"{tag}.sigmf-meta","w"))
st=s.stats; print(tag,g,"samples",len(x),"gap",st.gap_samples,"badcrc",st.bad_crc)
