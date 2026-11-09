#!/usr/bin/env python3
"""No-battery arming test over the D8 link: link 12 s disarmed, arm 10 s, disarm 10 s. Logs MSP truth + hub snapshot (CSV)."""
import sys, time, json, threading, csv
sys.path[:0] = ["python", "bench/d8-tx/host"]
import serial, bf_msp
E = "bench/d8-tx/results/betaflight-patch"
from d8tx.link import D8Link

msp = serial.Serial("/dev/cu.usbmodem0x80000001", 115200, timeout=0.05)
an = bf_msp.parse_analog(bf_msp.request(msp, bf_msp.MSP_ANALOG))
print("analog", an)
if an["vbat_cv"] > 20 or an["vbat_dv"] > 2:
    sys.exit("battery present, abort")
link = D8Link("/dev/cu.usbserial-0001")
rows, ev = [], []
t0 = time.time()
def log(tag):
    ev.append((round(time.time() - t0, 3), tag)); print(ev[-1], flush=True)
link.start(power=127, timeout_ms=300, allow_arm=True, fofs_hz=-75000, telemetry=True)
log("link_start")
phases = [(14, False, "disarmed"), (10, True, "ARM_sent"), (10, False, "DISARM_sent")]
out = open(E + "/armtest_log.csv", "w", newline=""); w = csv.writer(out)
w.writerow(["t", "arm_switch", "msp_armflag", "msp_arm_dis", "tlm_armed", "tlm_src", "roll", "pitch", "acc"])
state = {"sw": False}
def poll(stop):
    while not stop.is_set():
        try:
            s = bf_msp.parse_status(bf_msp.request(msp, bf_msp.MSP_STATUS, 0.3))
            snap = link.telemetry()
            hub = snap.get("hub", {})
            w.writerow([round(time.time() - t0, 3), int(state["sw"]), s["mode_flags"] & 1,
                        "|".join(s["arming_disable_names"]) or "-", snap.get("armed"), snap.get("armed_source"),
                        json.dumps(hub.get("patched", {}).get("attitude_deg")), "", json.dumps(hub.get("acc"))]); out.flush()
        except Exception as e:
            w.writerow([round(time.time() - t0, 3), int(state["sw"]), "ERR", str(e)])
        time.sleep(0.1)
stop = threading.Event(); th = threading.Thread(target=poll, args=(stop,)); th.start()
try:
    for dur, arm, name in phases:
        state["sw"] = arm
        link.set_sticks([1000, 1500, 1500, 1500, 1500, 1500, 2000 if arm else 1000, 1500])
        log(name)
        time.sleep(dur)
    snap = link.telemetry()
    json.dump(snap, open(E + "/armtest_final_snapshot.json", "w"), indent=1, default=str)
finally:
    link.set_sticks([1000, 1500, 1500, 1500, 1500, 1500, 1000, 1500])
    time.sleep(0.3); stop.set(); th.join(); link.stop(); link.close()
    json.dump(ev, open(E + "/armtest_events.json", "w"))
