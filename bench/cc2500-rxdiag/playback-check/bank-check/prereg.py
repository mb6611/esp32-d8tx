#!/usr/bin/env python3
"""PRE-REGISTERED analysis, bank-grant check (saved with sha256 BEFORE any keying).

Design: one session per bank grant (gmode 2 = lower 32 KiB bank, then gmode 1 = upper bank only if the gmode 2 outcome is NO-DIFF and valid).
Receiver: RX 2412000 kHz, `rxdiag events 2412000 100 203 203 66 1` (same BW/agc as intended/ctrl, where keyed tone 5/5 and keyed zero 5/5 were seen, no saturation).
Conditions n=8 each (40 slots, 24 keyed, seeds 2001 gmode2 / 2002 gmode1), shuffled: tone (CW bit on = known radiator),
 dc (fill I=200,Q=0, tone bit cleared), zero (all-zero words, tone bit cleared), unkey (engine only, no key), idle (no command).
Fixed limits: ch1 2412, K 0, pwr 127/0, count 6143, tmo 100, abort > 400 us keyed, spacing >= 0.35 s (guard.py).
Per slot (as intended/prereg.py): window [t_send+1.5 ms, t_send+4.5 ms]; hit = >=1 B record; peak = max peak_raw (else -128).
Control (this session): tone hits >= 7/8 AND unkey+idle hits <= 1/16 AND zero hits >= 6/8 (so the zero baseline is measurable) AND valid.
  If it fails -> outcome NO-CONTROL / INVALID, no inference, no further keying.
Primary (sample dependence): dc vs zero peak, TWO-sided exact permutation MWU p <= 0.025 (2 sessions, Bonferroni) AND |median(dc)-median(zero)| >= 3 raw.
Secondary: dc vs zero hits, two-sided Fisher p <= 0.025.  ON = primary or secondary passes (direction reported, either sign counts: DC may add or cancel leakage).
Saturation: peak >= 120 for >= 75% of keyed slots -> SATURATED-uninterpretable.
Validity (INVALID if any fails): H freq_word==freq_rb==0x5cc4ec, bw_hz==203125, gdo_ok==1, ring_lost==0, no abort, 40 slots, no hang,
 every keyed slot keyed_us<=400 and pb51==127.
Interpretation: dc and zero are keyed identically (same tone-bit-cleared key path, same bank grant); only the sample words differ, so an ON result
 is sample-dependent RF energy in the slice. NO-DIFF is not proof of no radiation (LO leakage may mask, 77 us burst, format unverified).
  prereg.py SESSION_DIR [--json OUT]
"""
import argparse, json, math, os, statistics as st, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "inband")); sys.path.insert(0, os.path.join(HERE, ".."))
import prereg as base
ALPHA = 0.025
WORD = 0x5CC4EC


def cp(k, n, a=0.05):
    from math import comb
    def tail_lo(p): return sum(comb(n, i) * p**i * (1-p)**(n-i) for i in range(k, n+1))
    def tail_hi(p): return sum(comb(n, i) * p**i * (1-p)**(n-i) for i in range(0, k+1))
    def solve(f, target, inc):
        lo, hi = 0.0, 1.0
        for _ in range(60):
            m = (lo+hi)/2
            if (f(m) < target) == inc: lo = m
            else: hi = m
        return (lo+hi)/2
    L = 0.0 if k == 0 else solve(tail_lo, a/2, True)
    U = 1.0 if k == n else solve(tail_hi, a/2, False)
    return round(L, 3), round(U, 3)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("sd"); ap.add_argument("--json"); a = ap.parse_args()
    base.FREQ_KHZ = 2412000; base.EXPECTED_WORD = WORD
    rows, meta, H, C, cm = base.per_slot(a.sd)
    bad = []
    if not H: bad.append("no H")
    else:
        if int(H["freq_word"], 16) != WORD or H["freq_word"] != H.get("freq_rb"): bad.append("freq word")
        if int(H.get("bw_hz", 0)) != base.BW_HZ: bad.append("bw")
        if H.get("gdo_ok") != "1": bad.append("gdo")
    if C and C[-1][1][4] != 0: bad.append("ring_lost")
    if meta.get("abort"): bad.append("abort " + meta["abort"])
    if len(rows) != 5 * meta["args"]["n"]: bad.append(f"{len(rows)} slots")
    for r in rows:
        if r["hang"]: bad.append(f"hang {r['i']}")
        if r["cond"] in ("tone", "dc", "zero") and (not r["keyed_us"] or r["keyed_us"] > 400 or r["pb51"] != 127):
            bad.append(f"slot {r['i']} keyed_us {r['keyed_us']} pb51 {r['pb51']}")
    g = {}
    for r in rows: g.setdefault(r["cond"], []).append(r)
    out = {"gmode": meta["args"]["gmode"], "invalid": bad, "clock": cm, "cond": {}}
    for c, rs in g.items():
        pk = [r["peak"] for r in rs]; h = sum(r["hit"] for r in rs)
        out["cond"][c] = {"n": len(rs), "hits": h, "hit_CP95": cp(h, len(rs)), "peaks": pk, "peak_median": st.median(pk),
                          "durs": [max(r["durs"]) if r["durs"] else 0 for r in rs], "keyed_us": [r["keyed_us"] for r in rs]}
    kr = [r for c in ("tone", "dc", "zero") for r in g.get(c, [])]
    sat = bool(kr) and sum(r["peak"] >= 120 for r in kr) / len(kr) >= 0.75
    n = meta["args"]["n"]
    ctrl = (out["cond"]["tone"]["hits"] >= 7 and out["cond"]["unkey"]["hits"] + out["cond"]["idle"]["hits"] <= 1
            and out["cond"]["zero"]["hits"] >= 6)
    D, Z = g["dc"], g["zero"]
    pd = [r["peak"] for r in D]; pz = [r["peak"] for r in Z]
    m1 = base.mwu_one_sided(pd, pz); m2 = base.mwu_one_sided(pz, pd)
    pm = min(1.0, 2 * min(m1, m2)) if m1 is not None else None
    hd, hz = sum(r["hit"] for r in D), sum(r["hit"] for r in Z)
    pf = min(1.0, 2 * min(base.fisher_one_sided(hd, n, hz, n), base.fisher_one_sided(hz, n, hd, n)))
    md = st.median(pd) - st.median(pz)
    prim = pm is not None and pm <= ALPHA and abs(md) >= 3; sec = pf <= ALPHA
    out.update(control_pass=ctrl, saturated=sat, mwu_two_sided_p=pm, median_peak_diff_dc_minus_zero=md, fisher_two_sided_p=pf,
               primary=prim, secondary=sec,
               outcome="INVALID" if bad else ("NO-CONTROL" if not ctrl else ("SATURATED" if sat else ("ON" if prim or sec else "NO-DIFF"))))
    print(json.dumps(out, indent=1))
    if a.json: json.dump({"summary": out, "rows": rows}, open(a.json, "w"), indent=1)


if __name__ == "__main__":
    main()
