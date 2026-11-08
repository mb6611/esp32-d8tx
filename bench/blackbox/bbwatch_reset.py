#!/usr/bin/env python3
"""EXPERIMENTAL capture used for session1 (2026-11-08): poll MSP_STATUS until it stops answering (= armed, blackbox
took the VCP), then libusb-reset the FC so macOS re-enumerates, reopen and read raw bytes. Run from bench/blackbox with
DYLD_LIBRARY_PATH=/opt/homebrew/lib. Usage: bbwatch_reset.py OUT.raw SECONDS. Do NOT add repeated resets: that wedged the FC."""
import serial,time,sys
sys.path.insert(0,'.'); import bbcapture,bf_msp,usbreset,os
out=open(sys.argv[1],'wb'); T=float(sys.argv[2]); t0=time.time(); p=None; n=0; last=time.time(); msp=True
def ts(): return '%.2f'%time.time()
while time.time()-t0<T:
    if p is None:
        try: p=serial.Serial('/dev/cu.usbmodem0x80000001',115200,timeout=0.05); last=time.time(); print(ts(),'open',flush=True)
        except Exception as e: time.sleep(0.1); continue
    if msp:
        try:
            st=bf_msp.parse_status(bbcapture.msp_request(p,101,timeout=0.6))
            print(ts(),'status flags',st['mode_flags'],st['arming_disable_names'],flush=True); time.sleep(0.4); continue
        except Exception as e:
            print(ts(),'msp fail',e,'-> usb reset, raw mode',flush=True); msp=False; p.close(); p=None; print(ts(),usbreset.reset(),flush=True); time.sleep(0.8); continue
    try: d=p.read(65536)
    except Exception as e:
        print(ts(),'read err',e,flush=True); p.close(); p=None; continue
    if d:
        if n==0: print(ts(),'first bytes',repr(d[:80]),flush=True)
        n+=len(d); out.write(d); last=time.time()
print('total',n)
