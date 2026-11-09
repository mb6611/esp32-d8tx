"""Offline: how coarse can the capture be and still decode? Re-decimates saved int8 captures."""
import glob, json, sys, numpy as np
sys.path.insert(0, "python")
from d8tx.telemetry import decode_capture, load_iq
runs = sorted(glob.glob("bench/d8-tx/results/telemetry/20261108-1*-link"))[-2:] + sorted(glob.glob("bench/d8-tx/results/telemetry/20261108-0*-link"))[-2:]
caps = []
for r in runs:
    for j in sorted(glob.glob(r + "/cap*.json")):
        m = json.load(open(j))
        if m.get("bits") != 8 or not m.get("crc_ok"): continue
        raw = open(j.replace(".json", ".iq16"), "rb").read()
        caps.append((m, raw))
print(len(caps), "captures")
def variant(iq, fs, f, skip_us, win_us, q):
    s = int(skip_us * 1e-6 * fs); e = int((skip_us + win_us) * 1e-6 * fs)
    x = iq[s:e]
    if f > 1:
        n = len(x) // f * f; x = x[:n].reshape(-1, f).mean(1)
    if q:  # requantize to q bits signed, per-capture scale
        pk = max(np.abs(x.real).max(), np.abs(x.imag).max()); sc = (2 ** (q - 1) - 1) / pk
        x = np.round(x.real * sc) + 1j * np.round(x.imag * sc)
    return x, fs / f
base = []
for m, raw in caps:
    iq = load_iq(raw, m["n"]); r = decode_capture(iq, m["fs"])
    base.append(r)
ok = [i for i, r in enumerate(base) if r]
print("baseline decoded", len(ok), "of", len(caps))
print("reply t_ms:", np.round(sorted(base[i]["t_ms"] for i in ok)[:3], 2), "..", np.round(sorted(base[i]["t_ms"] for i in ok)[-3:], 2))
ts = [base[i]["t_ms"] for i in ok]
print("t_ms mean", np.mean(ts), "min", min(ts), "max", max(ts))
for f, skip, win, q in [(1,0,9000,0),(2,0,9000,0),(4,0,9000,0),(2,0,9000,4),(4,0,9000,4),(2,1000,7600,0),(2,1000,7600,4),(4,1000,7600,4),(4,1000,7600,0)]:
    n = 0
    for i in ok:
        m, raw = caps[i]
        iq = load_iq(raw, m["n"]); x, fs = variant(iq, m["fs"], f, skip, win, q)
        n += decode_capture(x, fs) is not None
    print(f"dec x{f} skip{skip} win{win} q{q}: {n}/{len(ok)}", flush=True)
