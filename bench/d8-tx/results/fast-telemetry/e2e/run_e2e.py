"""E2E fast-telemetry check: default recipe, N s. usage: run_e2e.py NAME SECS (repo root, d8tx venv, backend stopped)"""
import json, sys, threading, time, struct, statistics as st
sys.path.insert(0, "d8tx/python"); sys.path.insert(0, "bench/d8-tx/host")
import serial, bf_msp
from d8tx.link import D8Link
name, secs = sys.argv[1], float(sys.argv[2])
ESP, FC = "/dev/cu.usbserial-0001", "/dev/cu.usbmodem0x80000001"
caps = []; fastev = []  # (t, seq, att, gyro)
class Link(D8Link):
    def _process_capture(self, meta, payload):
        tr0 = self._tlm.t_reply
        super()._process_capture(meta, payload)
        if self._tlm.t_reply != tr0:
            caps.append((time.monotonic(), meta.get("k"), self._tlm.last.get("cnt"), "fast" in self._tlm.last, self._tlm.last.get("tid")))
            if "fast" in self._tlm.last:
                f = self._tlm.last["fast"]; fastev.append((time.monotonic(), f))
events = []
lk = Link(ESP); lk._p.dtr = False; lk._p.rts = True; time.sleep(0.1); lk._p.rts = False; time.sleep(2.5); lk.on_event(lambda e: events.append((time.monotonic(), e)))
fc = serial.Serial(FC, 115200, timeout=0.05)
v = bf_msp.parse_analog(bf_msp.request(fc, bf_msp.MSP_ANALOG)); print("analog", v, flush=True)
assert v["vbat_cv"] < 100 and v["vbat_dv"] < 10, "battery present?"
ctr = {"n": 0, "stop": False}
def sticks():
    while not ctr["stop"]:
        ctr["n"] += 1
        lk.set_sticks([1000, 1500, 1500, 1500, 1000, 1000, 1000, 1000 + ctr["n"] % 100]); time.sleep(0.02)
samples = []; hubt = []  # hubt: (t, {id: t_id})
def msp():
    while not ctr["stop"]:
        try:
            t = time.monotonic(); n = ctr["n"]
            rc = bf_msp.parse_rc(bf_msp.request(fc, bf_msp.MSP_RC, 0.1)); a = bf_msp.parse_analog(bf_msp.request(fc, bf_msp.MSP_ANALOG, 0.1))
            s = bf_msp.parse_status(bf_msp.request(fc, bf_msp.MSP_STATUS, 0.1))
            att = struct.unpack("<hhh", bf_msp.request(fc, 108, 0.1)[:6])
            imu = struct.unpack("<9h", bf_msp.request(fc, 102, 0.1)[:18])
            samples.append({"t": t, "rc": rc, "rssi": a["rssi"], "fs": s["rx_failsafe"], "names": s["arming_disable_names"], "n": n, "att": att, "imu": imu, "tf": time.monotonic()})
        except Exception as e:
            samples.append({"t": time.monotonic(), "err": str(e)})
        time.sleep(0.03)
def hubpoll():
    prev = {}
    while not ctr["stop"]:
        with lk._tlm._lk: d = dict(lk._tlm.hub.t_id)
        for k, t in d.items():
            if prev.get(k) != t: hubt.append((k, t))
        prev = d; time.sleep(0.005)
lk.start(power=127, timeout_ms=300, telemetry=True)
t0 = time.monotonic()
th = [threading.Thread(target=f, daemon=True) for f in (sticks, msp, hubpoll)]
[t.start() for t in th]
time.sleep(secs)
ctr["stop"] = True; [t.join() for t in th]
tel = lk.telemetry(); lk.stop(); time.sleep(0.5)
def ints(ts): return [b - a for a, b in zip(ts, ts[1:])]
def stat(x): return {"n": len(x), "mean": st.mean(x), "p50": st.median(x), "p95": sorted(x)[int(.95 * len(x))], "max": max(x)} if x else None
ft = [c[0] for c in caps if c[3]]; allt = [c[0] for c in caps]
hubids = {}
for k, t in hubt: hubids.setdefault("0x%02X" % k, []).append(t)
seqs = [f["seq"] if "seq" in f else None for _, f in fastev]
lag = [((s["n"] - (s["rc"][7] - 1000)) % 100) * 0.02 for s in samples if "rc" in s and len(s["rc"]) >= 8 and s["rc"][7] >= 1000]
res = {"name": name, "secs": secs, "replies": len(caps), "replies_per_s": len(caps) / secs, "fast_replies": len(ft), "fast_hz": len(ft) / secs,
       "hub_replies": len(caps) - len(ft), "hub_hz": (len(caps) - len(ft)) / secs, "fast_interval_s": stat(ints(ft)), "reply_interval_s": stat(ints(allt)),
       "hub_id_interval_s": {k: stat(ints(v)) for k, v in sorted(hubids.items())}, "hub_id_count": {k: len(v) for k, v in sorted(hubids.items())},
       "seq_continuity_gaps": sum(1 for a, b in zip(seqs, seqs[1:]) if a is not None and (b - a) % 4 != 1),
       "msp_samples": len(samples), "msp_err": sum(1 for s in samples if "err" in s),
       "failsafe_samples": sum(1 for s in samples if s.get("fs") and s["t"] > t0 + 3), "msp_samples_after_3s": sum(1 for s in samples if s["t"] > t0 + 3),
       "rssi_mean": st.mean(s["rssi"] for s in samples if "rssi" in s), "arming_flags": sorted({n for s in samples for n in s.get("names", [])}),
       "ch8_lag_s": stat(lag), "final_telemetry": tel, "fast_keys": list(fastev[-1][1].keys()) if fastev else None,
       "link_end": [e for _, e in events if isinstance(e, dict) and e.get("name") == "link_end"][-1:]}
# agreement: last 20 MSP att vs fast decoded nearest in time
ag = []
for s in samples:
    if "att" in s and s["t"] > t0 + 3 and fastev:
        _, f = min(fastev, key=lambda e: abs(e[0] - s["tf"]))
        ag.append({"msp_att": s["att"], "fast_att": f["attitude_deg"], "msp_imu": s["imu"], "fast_gyro": f["gyro_dps"]})
res["agree_samples"] = ag[::max(1, len(ag) // 8)]
json.dump({"res": res, "caps": caps, "fast": [(t, f) for t, f in fastev], "hubt": hubt, "samples": samples, "events": events[-50:]}, open(f"bench/d8-tx/results/fast-telemetry/e2e/{name}.json", "w"), default=str)
print(json.dumps(res, indent=1, default=str))
