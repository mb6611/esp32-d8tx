"""Measure one TLM recipe for N seconds: replies/s, request->decoded latency, drone data-link health (MSP).
usage: run_cadence.py NAME "TLM ..." SECS   (run from repo root with python/.venv; backend must be stopped)"""
import json, sys, threading, time, statistics as st
sys.path.insert(0, "python"); sys.path.insert(0, "tools/d8-tx-host")
import serial, bf_msp
import d8tx.link as L
from d8tx.link import D8Link
name, recipe, secs = sys.argv[1], sys.argv[2], float(sys.argv[3])
L.TLM_RECIPE = recipe
ESP, FC = "/dev/cu.usbserial-0001", "/dev/cu.usbmodem0x80000001"
caps = []  # (t_decoded, k, ok, tid)
class Link(D8Link):
    def _process_capture(self, meta, payload):
        tr0 = self._tlm.t_reply; t = time.monotonic()
        super()._process_capture(meta, payload)
        caps.append((time.monotonic(), meta.get("k"), meta.get("tid"), self._tlm.t_reply != tr0, meta.get("try", 0), meta.get("bytes"), time.monotonic() - t))
events = []
lk = Link(ESP); lk._p.dtr = False; lk._p.rts = True; time.sleep(0.1); lk._p.rts = False; time.sleep(2.5); lk.on_event(lambda e: events.append((time.monotonic(), e)))
fc = serial.Serial(FC, 115200, timeout=0.05)
v = bf_msp.parse_analog(bf_msp.request(fc, bf_msp.MSP_ANALOG)); print("analog", v, flush=True)
assert v["vbat_cv"] < 100 and v["vbat_dv"] < 10, "battery present?"
ctr = {"n": 0, "t": 0.0, "stop": False}
def sticks():
    while not ctr["stop"]:
        ctr["n"] += 1; ctr["t"] = time.monotonic()
        lk.set_sticks([1000, 1500, 1500, 1500, 1000, 1000, 1000, 1000 + ctr["n"] % 100])
        time.sleep(0.02)
samples = []
def msp():
    while not ctr["stop"]:
        try:
            t = time.monotonic(); n = ctr["n"]
            rc = bf_msp.parse_rc(bf_msp.request(fc, bf_msp.MSP_RC, 0.1)); a = bf_msp.parse_analog(bf_msp.request(fc, bf_msp.MSP_ANALOG, 0.1))
            s = bf_msp.parse_status(bf_msp.request(fc, bf_msp.MSP_STATUS, 0.1))
            samples.append({"t": t, "rc": rc, "rssi": a["rssi"], "fs": s["rx_failsafe"], "names": s["arming_disable_names"], "n": n})
        except Exception as e:
            samples.append({"t": time.monotonic(), "err": str(e)})
        time.sleep(0.03)
lk.start(power=127, timeout_ms=300, telemetry=True)
t0 = time.monotonic()
th = [threading.Thread(target=sticks, daemon=True), threading.Thread(target=msp, daemon=True)]
[t.start() for t in th]
time.sleep(secs)
ctr["stop"] = True; [t.join() for t in th]
tel = lk.telemetry(); lk.stop(); time.sleep(0.5); t1 = time.monotonic()
# health
lag = []
for s in samples:
    if "rc" in s and len(s["rc"]) >= 8 and s["rc"][7] >= 1000:
        lag.append(((s["n"] - (s["rc"][7] - 1000)) % 100) * 0.02)
rc_bad = sum(1 for s in samples if "rc" in s and t0 + 3 < s["t"] and (abs(s["rc"][0] - 1500) > 5 or abs(s["rc"][1] - 1500) > 5 or abs(s["rc"][2] - 1500) > 5 or abs(s["rc"][3] - 1000) > 5))
okc = [c for c in caps if c[3]]
lat = [c[0] - t0 - c[1] * 0.008994 for c in okc if c[1] is not None]
drops = sum(1 for _, e in events if isinstance(e, dict) and e.get("name") == "tlm_drop")
res = {"name": name, "recipe": recipe, "secs": secs, "captures": len(caps), "captures_per_s": len(caps) / secs,
       "decoded": len(okc), "decoded_per_s": len(okc) / secs, "decode_fail": len(caps) - len(okc), "tlm_drop": drops,
       "latency_s": {"p50": st.median(lat), "p95": sorted(lat)[int(.95 * len(lat))], "max": max(lat)} if lat else None,
       "median_decode_s": st.median(c[6] for c in caps) if caps else None, "median_bytes": st.median(c[5] for c in caps) if caps else None,
       "msp_samples": len(samples), "msp_err": sum(1 for s in samples if "err" in s),
       "rssi_min_mean_max": [min(s["rssi"] for s in samples if "rssi" in s), st.mean(s["rssi"] for s in samples if "rssi" in s), max(s["rssi"] for s in samples if "rssi" in s)],
       "failsafe_samples": sum(1 for s in samples if s.get("fs") and s["t"] > t0 + 3), "rc_bad": rc_bad,
       "arming_flags": sorted({n for s in samples for n in s.get("names", [])}),
       "msp_samples_after_3s": sum(1 for s in samples if s["t"] > t0 + 3), "ch8_lag_s": {"p50": st.median(lag) if lag else None, "p95": sorted(lag)[int(.95 * len(lag))] if lag else None, "max": max(lag) if lag else None, "n": len(lag)},
       "link_end": [e for _, e in events if isinstance(e, dict) and e.get("name") == "link_end"][-1:]}
json.dump({"res": res, "caps": caps, "samples": samples, "events": [(t, e) for t, e in events][-50:]}, open(f"experiments/13-fast-attitude-telemetry/data/{name}.json", "w"), default=str)
print(json.dumps(res, indent=1, default=str))
