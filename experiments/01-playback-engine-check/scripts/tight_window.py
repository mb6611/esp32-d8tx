#!/usr/bin/env python3
"""Tight-window per-condition statistics quoted in README.md (reads raw sessions, writes nothing).

  tight_window.py [--lo 0.0015] [--hi 0.0045] [--overlong-us 440] SESSION_DIR ...

For each slot, CC2500 bursts whose mapped host time (analyze.py clock map) lies in
[t_send+lo, t_send+hi] are "in-window bursts".  Two statistics are printed per condition:
  * per-slot max : for each slot with >=1 in-window burst, the longest burst duration (us) and
                   (if a burst has a valid RSSI peak) the peak raw of that slot's longest burst;
                   median/min/max are over slots.  This is what README's table quotes.
  * all bursts   : every in-window burst (a slot can contribute several), 'npk' = number of
                   bursts with a valid peak.  Peak columns here are over ALL bursts, so they
                   can differ from the per-slot max (e.g. zero in A: 21 peaks for 20 slots).
Then the same per-slot-max statistics are repeated EXCLUDING slots whose keyed_us exceeds
--overlong-us (sensitivity check; the three overlong keyed slots are 445 (B dc), 448 (pilot tone), 483 (A zero) us).
"""
import argparse, json, os, statistics as st, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyze


def collect(dirs, lo, hi):
    rows = []
    for sd in dirs:
        slots, meta, H, B, C = analyze.load(sd)
        slope, off, _ = analyze.clockmap(C)
        bh = [(off + slope * b[1] / 1e6, b) for b in B]
        for s in slots:
            bs = [(t - s["t_send"], b[2], b[3] if b[4] else None)
                  for t, b in bh if s["t_send"] + lo <= t <= s["t_send"] + hi]
            rows.append({"sess": os.path.basename(sd.rstrip("/")), "cond": s["cond"], "i": s["i"],
                         "keyed_us": s.get("keyed_us"), "bursts": bs})
    return rows


def summ(rows, keep=lambda r: True):
    out = {}
    for c in dict.fromkeys(r["cond"] for r in rows):
        rs = [r for r in rows if r["cond"] == c and keep(r)]
        hit = [r for r in rs if r["bursts"]]
        mx = [max(r["bursts"], key=lambda b: b[1]) for r in hit]       # per-slot max-duration burst
        allb = [b for r in hit for b in r["bursts"]]
        def stats(v):
            return (st.median(v), min(v), max(v)) if v else None
        kus = [r["keyed_us"] for r in rs if r["keyed_us"] is not None]
        out[c] = {"slots": len(rs), "hit": len(hit),
                  "slotmax_dur": stats([b[1] for b in mx]),
                  "slotmax_peak": stats([b[2] for b in mx if b[2] is not None]),
                  "all_dur": stats([b[1] for b in allb]), "all_n": len(allb),
                  "all_peak": stats([b[2] for b in allb if b[2] is not None]),
                  "all_npk": sum(b[2] is not None for b in allb),
                  "keyed_us": (min(kus), max(kus)) if kus else None}
    return out


def show(title, d):
    print(title)
    for c, v in d.items():
        print(f"  {c:6s} slots {v['slots']:2d} hit {v['hit']:2d} | per-slot max dur med/min/max {v['slotmax_dur']}"
              f" peak {v['slotmax_peak']} | all bursts n={v['all_n']} dur {v['all_dur']} peak {v['all_peak']} npk {v['all_npk']}"
              f" | keyed_us {v['keyed_us']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="*", default=["sessions/pilot2-km0", "sessions/A-km0-p127", "sessions/B-km0-p127-dc"])
    ap.add_argument("--lo", type=float, default=0.0015)
    ap.add_argument("--hi", type=float, default=0.0045)
    ap.add_argument("--overlong-us", type=int, default=440)
    a = ap.parse_args()
    rows = collect(a.dirs, a.lo, a.hi)
    for sess in dict.fromkeys(r["sess"] for r in rows):
        sub = [r for r in rows if r["sess"] == sess]
        show(f"== {sess}: window [t_send+{a.lo*1e3:g}, t_send+{a.hi*1e3:g}] ms", summ(sub))
        show(f"-- {sess}: excluding slots with keyed_us > {a.overlong_us}",
             summ(sub, lambda r: r["keyed_us"] is None or r["keyed_us"] <= a.overlong_us))
        ov = [(r["cond"], r["i"], r["keyed_us"]) for r in sub if r["keyed_us"] and r["keyed_us"] > a.overlong_us]
        print("   overlong slots (cond, i, keyed_us):", ov)
        # detections longer than keyed_us (+tolerance), any condition
        lg = [(r["cond"], r["i"], r["keyed_us"], max(b[1] for b in r["bursts"]), len(r["bursts"]))
              for r in sub if r["bursts"] and r["keyed_us"] and max(b[1] for b in r["bursts"]) > r["keyed_us"]]
        print("   slots where longest in-window detection > keyed_us (cond,i,keyed,det,nbursts):", lg)
        mb = [(r["cond"], r["i"], len(r["bursts"])) for r in sub if len(r["bursts"]) > 1]
        print("   slots with >1 in-window burst:", mb)


if __name__ == "__main__":
    main()
