"""60 s D8Link.start(telemetry=True) smoke run; prints telemetry() once per second (arm low, throttle low).
Run: python/.venv/bin/python smoke.py [seconds]  (hardware mutex /tmp/d8tx-hw.lock must be held)"""
import json
import sys
import time

from d8tx import D8Link

secs = float(sys.argv[1]) if len(sys.argv) > 1 else 60
l = D8Link("/dev/cu.usbserial-0001")
print("INFO", l.info())
l.start(power=127, timeout_ms=1000, allow_arm=False, telemetry=True)
l.set_sticks([1000, 1500, 1500, 1500, 1000, 1000, 1000, 1000])
t0 = time.time()
try:
    while time.time() - t0 < secs:
        time.sleep(1.0)
        s = l.telemetry()
        print(json.dumps({"t": round(time.time() - t0, 1), **s}, sort_keys=True), flush=True)
    st = l.status()
    print("STATUS", json.dumps({k: st[k] for k in ("link", "slots", "late_max_us", "sender_hz", "sender_max_gap_ms", "skipped")}))
finally:
    l.stop()
    l.close()
