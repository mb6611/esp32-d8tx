#!/usr/bin/env python3
"""Analyse pbcheck.py sessions: map CC2500 burst rise times (drone micros) to host monotonic time,
then count detector bursts near each slot's T command, per condition.

  analyze.py SESSION_DIR [SESSION_DIR ...] [--lo -0.01] [--hi 0.03] [--json out.json]

Clock map: each C record carries drone t_us and is stamped with the host receive time. The host
time is always later than the event (USB latency), so the map is the lower envelope:
host = t_us/1e6*slope + off, with slope from a least-squares fit and off moved down to the
minimum residual. A match window [t_send+lo, t_reply+hi] is fixed up front; lag statistics
(B host time - t_send) for all bursts within -0.2..+0.3 s are reported so the window can be judged.
Chance level: idle slots (no command) and the 'unkey' control.
"""
import argparse, json, math, os, statistics as st


def load(sd):
    slots = [json.loads(l) for l in open(os.path.join(sd, "slots.jsonl"))]
    meta = json.load(open(os.path.join(sd, "meta.json")))
    H, B, C = None, [], []
    for ln in open(os.path.join(sd, "rx.txt")):
        if ln.startswith("#"):
            continue
        p = ln.split(" ", 1)
        if len(p) < 2:
            continue
        t, rec = float(p[0]), p[1].strip()
        try:
            if rec.startswith("H,"):
                H = dict(kv.split("=", 1) for kv in rec[2:].split(",") if "=" in kv)
            elif rec.startswith("B,"):
                v = [int(x) for x in rec[2:].split(",")]
                if len(v) >= 6:
                    B.append(v)
            elif rec.startswith("C,"):
                v = [int(x) for x in rec[2:].split(",")]
                if len(v) >= 20:
                    C.append((t, v))
        except ValueError:
            pass
    return slots, meta, H, B, C


def clockmap(C):
    xs = [v[1] / 1e6 for _, v in C]
    ys = [t for t, _ in C]
    mx, my = st.mean(xs), st.mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    res = [y - (my + slope * (x - mx)) for x, y in zip(xs, ys)]
    off = my - slope * mx + min(res)
    spread = sorted(r - min(res) for r in res)
    return slope, off, {"slope_ppm": round((slope - 1) * 1e6, 1), "lat_p50_ms": round(spread[len(spread) // 2] * 1e3, 2),
                        "lat_p90_ms": round(spread[int(len(spread) * .9)] * 1e3, 2), "nC": len(C)}


def wilson(k, n, z=1.96):
    if n == 0:
        return (None, None)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(c - h, 3), round(c + h, 3))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--lo", type=float, default=-0.010)
    ap.add_argument("--hi", type=float, default=0.030)
    ap.add_argument("--json")
    a = ap.parse_args()
    per = {}
    out = {"window": [a.lo, a.hi], "sessions": []}
    for sd in a.dirs:
        slots, meta, H, B, C = load(sd)
        slope, off, cm = clockmap(C)
        bh = [(off + slope * b[1] / 1e6, b) for b in B]
        last = C[-1][1]
        span = sum(v[2] for _, v in C) / 1e6
        sess = {"dir": sd, "H": H and {k: H.get(k) for k in ("freq_req_khz", "freq_word", "freq_rb", "agcctrl2", "agcctrl1",
                                                                "gdo_ok", "fscal1", "ant")},
                "clock": cm, "bursts_total": last[5], "B_records": len(B), "ring_lost": last[4], "B_tx_fail": last[6],
                "seconds": round(span, 2), "ambient_rate_per_s": round(last[5] / span, 2) if span else None,
                "rssi_maxLow": max(v[13] for _, v in C), "rssi_minHigh": min(v[14] for _, v in C),
                "km": meta["args"]["km"], "pwr": meta["args"]["pwr"], "gmode": meta["args"]["gmode"],
                "pb51_before": meta["pb51_before"], "pb51_after": meta["pb51_after"], "Q": meta["Q"], "Q_after": meta["Q_after"],
                "hangs": meta["hangs"], "slots": []}
        for s in slots:
            w0, w1 = s["t_send"] + a.lo, s["t_reply"] + a.hi
            hit = [(round(t - s["t_send"], 4), b[2], b[3], b[4]) for t, b in bh if w0 <= t <= w1]
            near = [round(t - s["t_send"], 4) for t, b in bh if -0.2 <= t - s["t_send"] <= 0.3]
            r = {"i": s["i"], "cond": s["cond"], "keyed_us": s.get("keyed_us"), "ndone": s.get("ndone"),
                 "pb51": s.get("pb51"), "tone_before": s.get("tone_before"), "tone_after": s.get("tone_after"),
                 "t_send": round(s["t_send"], 4), "cmd_ms": round((s["t_reply"] - s["t_send"]) * 1e3, 1),
                 "hits": hit, "near_lags": near}
            sess["slots"].append(r)
            pc = per.setdefault(s["cond"], {"n": 0, "hit": 0, "lags": [], "durs": [], "peaks": [], "keyed_us": [], "ndone": 0,
                                            "pb51": set(), "near": 0})
            pc["n"] += 1
            pc["hit"] += bool(hit)
            pc["near"] += len(near)
            for lag, dur, peak, nr in hit:
                pc["lags"].append(lag); pc["durs"].append(dur); pc["peaks"].append(peak if nr else None)
            if s.get("keyed_us") is not None:
                pc["keyed_us"].append(s["keyed_us"]); pc["ndone"] += s["ndone"]; pc["pb51"].add(s["pb51"])
        out["sessions"].append(sess)
    summ = {}
    for c, pc in per.items():
        summ[c] = {"slots": pc["n"], "slots_with_hit": pc["hit"], "hit_frac": round(pc["hit"] / pc["n"], 3),
                   "hit_frac_95ci": wilson(pc["hit"], pc["n"]), "bursts_in_0.5s_around_per_slot": round(pc["near"] / pc["n"], 2),
                   "hit_lag_s": sorted(pc["lags"]), "hit_dur_us": sorted(pc["durs"]), "hit_peak_raw": pc["peaks"],
                   "keyed_us_min_max": [min(pc["keyed_us"]), max(pc["keyed_us"])] if pc["keyed_us"] else None,
                   "engine_done": pc["ndone"], "pb51_values": sorted(pc["pb51"]) if pc["pb51"] else None}
    out["per_condition"] = summ
    if a.json:
        json.dump(out, open(a.json, "w"), indent=1)
    for s in out["sessions"]:
        print(json.dumps({k: v for k, v in s.items() if k != "slots"}))
    for c, v in summ.items():
        print(c, json.dumps(v))


if __name__ == "__main__":
    main()
