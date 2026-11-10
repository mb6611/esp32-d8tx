#!/usr/bin/env python3
"""PRE-REGISTERED analysis for the in-band playback check (written and saved BEFORE any keying).

Question: with txeng K 0, PBUS (5,1)=127, TX 2412 MHz, does loading the existing +1.25 MHz pattern
(`F 1 16384 200 256`) produce more in-band energy at 2413.25 MHz than all-zero samples (`F 0 16384 0 0`)?
Detector: CC2500 `rxdiag events 2413250 100 203 203 66 1` (centre 2413.25 MHz, 203 kHz BW = +-101.6 kHz).
Session: pbcheck.py --conds pat,zero,unkey,idle --n 5 --seed 2413 --count 6143 --tmo 100 --km 0 --pwr 127
         --agc2 203 --agc1 66 --rx-khz 2413250 --rx-bw 203   (one session, 20 slots, no retry).

Per-slot statistics (fixed now):
  window   = mapped CC2500 burst rise time in [t_send + 1.5 ms, t_send + 4.5 ms]  (same as tight_window.py;
             clock map = analyze.clockmap lower envelope of C records).
  hit      = 1 if >= 1 B record in the window, else 0.
  peak     = max peak_raw over in-window B records with n_rssi > 0; -128 if no such record (no hit or too short).
Primary test: pat vs zero hits, one-sided Fisher exact (pat > zero), alpha 0.025.
Secondary test: pat vs zero peak, one-sided exact Mann-Whitney (pat > zero, ties averaged by exact
                enumeration of all 252 splits), alpha 0.025, and median(pat) - median(zero) >= 3 raw.
Outcome:
  ON       : primary OR secondary passes  -> pattern-dependent in-band energy seen above zero-sample playback.
  NO-DIFF  : neither passes -> no difference detected. NOT evidence of absence: there is no in-session in-slice
             positive control (no tone condition; detector sensitivity at 203 kHz/2413.25 MHz is only supported by
             the prior BLE A/B at 812 kHz/2402 MHz), the pattern sign/I-Q order is unverified (line could be at
             2410.75 MHz), and the ESP-vs-CC2500 crystal offset (tens of kHz) is not measured.
Reported alongside (descriptive only): unkey and idle hit rates/peaks (chance level), keyed_us per slot.
Validity (session INVALID, outcome not claimed, if any fails): H freq_word == freq_rb == expected word,
  bw_hz == 203125, gdo_ok == 1, ring_lost == 0 at end, meta abort is None, 20 slot records, no hang,
  every keyed slot keyed_us <= 400 and pb51 == 127.

  prereg.py SESSION_DIR [--json OUT]
"""
import argparse, itertools, json, math, os, statistics as st, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import analyze  # noqa: E402

FREQ_KHZ = 2413250
EXPECTED_WORD = (FREQ_KHZ * 1000 * 65536 + 13000000) // 26000000
BW_HZ = 203125
LO, HI = 0.0015, 0.0045
ALPHA = 0.025
MIN_MED_DIFF = 3
ABORT_US = 400


def fisher_one_sided(a, n1, b, n2):
    """P(X >= a) for hits in group 1 under the hypergeometric null (group-1 > group-2)."""
    k, n = a + b, n1 + n2
    tot = math.comb(n, k)
    return sum(math.comb(n1, x) * math.comb(n2, k - x) for x in range(a, min(n1, k) + 1)) / tot


def mwu_one_sided(x, y):
    """Exact permutation p for U(x>y) >= observed (ties count 0.5)."""
    def u(a, b):
        return sum(1.0 if i > j else 0.5 if i == j else 0.0 for i in a for j in b)
    obs, allv, n = u(x, y), list(x) + list(y), len(x)
    if math.comb(len(allv), n) > 200000:  # only for offline tests on big old sessions; the n=5 design is 252
        return None
    cnt = tot = 0
    for idx in itertools.combinations(range(len(allv)), n):
        s = set(idx)
        a = [allv[i] for i in idx]
        b = [allv[i] for i in range(len(allv)) if i not in s]
        tot += 1
        cnt += u(a, b) >= obs - 1e-9
    return cnt / tot


def per_slot(sd):
    slots, meta, H, B, C = analyze.load(sd)
    slope, off, cm = analyze.clockmap(C)
    bh = [(off + slope * b[1] / 1e6, b) for b in B]
    rows = []
    for s in slots:
        inw = [b for t, b in bh if s["t_send"] + LO <= t <= s["t_send"] + HI]
        pk = [b[3] for b in inw if b[4] > 0]
        rows.append({"i": s["i"], "cond": s["cond"], "hit": int(bool(inw)), "peak": max(pk) if pk else -128,
                     "n_bursts": len(inw), "durs": [b[2] for b in inw], "keyed_us": s.get("keyed_us"),
                     "pb51": s.get("pb51"), "hang": s.get("hang", False)})
    return rows, meta, H, C, cm


def validity(rows, meta, H, C):
    bad = []
    if not H:
        bad.append("no H record")
    else:
        if int(H.get("freq_word", "0"), 16) != EXPECTED_WORD or H.get("freq_word") != H.get("freq_rb"):
            bad.append(f"freq word {H.get('freq_word')} rb {H.get('freq_rb')} expected {EXPECTED_WORD:#08x}")
        if int(H.get("bw_hz", 0)) != BW_HZ:
            bad.append(f"bw_hz {H.get('bw_hz')}")
        if H.get("gdo_ok") != "1":
            bad.append("gdo_ok")
    if C and C[-1][1][4] != 0:
        bad.append(f"ring_lost {C[-1][1][4]}")
    if meta.get("abort"):
        bad.append(f"abort {meta['abort']}")
    if len(rows) != 20:
        bad.append(f"{len(rows)} slot records")
    for r in rows:
        if r["hang"]:
            bad.append(f"hang slot {r['i']}")
        if r["cond"] in ("pat", "zero"):
            if not r["keyed_us"] or r["keyed_us"] > ABORT_US or r["pb51"] != 127:
                bad.append(f"slot {r['i']} keyed_us {r['keyed_us']} pb51 {r['pb51']}")
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sd")
    ap.add_argument("--json")
    a = ap.parse_args()
    rows, meta, H, C, cm = per_slot(a.sd)
    bad = validity(rows, meta, H, C)
    g = {c: [r for r in rows if r["cond"] == c] for c in ("pat", "zero", "unkey", "idle")}
    out = {"expected_word": f"{EXPECTED_WORD:#08x}", "H": H and {k: H.get(k) for k in
           ("freq_req_khz", "freq_set_hz", "freq_word", "freq_rb", "bw_hz", "agcctrl2", "agcctrl1", "gdo_ok", "fscal1")},
           "clock": cm, "invalid": bad, "cond": {}}
    for c, rs in g.items():
        pk = [r["peak"] for r in rs]
        out["cond"][c] = {"n": len(rs), "hits": sum(r["hit"] for r in rs), "peaks": pk,
                          "peak_median": st.median(pk) if pk else None,
                          "keyed_us": [r["keyed_us"] for r in rs], "durs": [r["durs"] for r in rs]}
    P, Z = g["pat"], g["zero"]
    hp, hz = sum(r["hit"] for r in P), sum(r["hit"] for r in Z)
    p1 = fisher_one_sided(hp, len(P), hz, len(Z)) if P and Z else None
    p2 = mwu_one_sided([r["peak"] for r in P], [r["peak"] for r in Z]) if P and Z else None
    md = (st.median([r["peak"] for r in P]) - st.median([r["peak"] for r in Z])) if P and Z else None
    prim = p1 is not None and p1 <= ALPHA
    sec = p2 is not None and p2 <= ALPHA and md is not None and md >= MIN_MED_DIFF
    out.update(fisher_p=p1, mwu_p=p2, median_peak_diff=md, primary=prim, secondary=sec,
               outcome="INVALID" if bad else ("ON" if prim or sec else "NO-DIFF"))
    print(json.dumps(out, indent=1))
    if a.json:
        json.dump({"summary": out, "rows": rows}, open(a.json, "w"), indent=1)


if __name__ == "__main__":
    main()
