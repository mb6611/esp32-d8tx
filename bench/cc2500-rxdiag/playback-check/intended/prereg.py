#!/usr/bin/env python3
"""PRE-REGISTERED analysis, intended-waveform (+/-156 kHz) check. Saved with sha256 BEFORE any keying.

Fill validated offline (fillcheck.txt): `F 1 16384 200 32` = I=200cos,Q=200sin, 12 whole cycles in the 6144 words
played at count 6143, +156.25 kHz at 80 MS/s *if* the engine plays 10-bit I/Q at 80 MS/s (UNVERIFIED on hardware).
Limits fixed by the owner earlier: ch1 2412 MHz, K 0, pwr 127, count 6143, tmo 100, abort > 400 us keyed, spacing >=0.35 s.
Receiver (all sessions): `rxdiag events <khz> 100 203 203 66 1` (203 kHz BW, agc2 203, agc1 66).

Stage C (control, in-session): RX 2412000, conds tone,zero,unkey,idle, n=5 (seed 1001). 'tone' = keyed with CW tone
  bit left on = known radiator at the LO, centre of the slice. Control PASSES iff tone hits >= 4/5 AND unkey+idle hits <= 1/10
  AND session valid. If it fails: STOP, no further keying.
Stage P1: RX 2412156, conds pat156,zero,unkey,idle, n=8 (seed 1002). Stage P2 (only if P1 outcome is NO-DIFF): RX 2411844, same
  (seed 1003). Stop after P1 if ON. No retries, no longer/stronger runs.
Per slot (as inband/prereg.py): window = [t_send+1.5 ms, t_send+4.5 ms] via C-record clock map; hit = >=1 B record in
  window; peak = max peak_raw of in-window B records with n_rssi>0 else -128; also dur = max in-window duration.
Primary (per P session): pat156 vs zero hits, one-sided Fisher, alpha 0.0125 (2 sessions, Bonferroni).
Secondary: one-sided exact MWU on peak, alpha 0.0125, and median(pat156)-median(zero) >= 3 raw.
ON = primary or secondary passes -> sample-dependent detected response at that RX offset. Else NO-DIFF.
Saturation: flag if peak>=120 raw for >=75% of keyed slots (RSSI s8 ceiling 127) or tone/zero/pat all hit 100% with
  identical peaks -> outcome SATURATED-uninterpretable for the hit/peak tests (then only durations are considered).
Validity (INVALID if any fails): H freq_word==freq_rb==expected for the session RX, bw_hz==203125, gdo_ok==1, ring_lost==0,
  abort None, slot count == conds*n, no hang, every keyed slot keyed_us<=400 and pb51==127.
Even a positive ON shows that programmed samples change the radiated energy within the CC2500 slice; it does not establish
the exact waveform, the sign, or the frequency (CC2500 only gives energy/RSSI-over-threshold events).

  prereg.py SESSION_DIR RX_KHZ STAGE(C|P) [--json OUT]
"""
import argparse, json, math, os, statistics as st, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "inband")); sys.path.insert(0, os.path.join(HERE, ".."))
import prereg as base  # inband/prereg.py: per_slot, fisher, mwu (module globals reused below)
ALPHA = 0.0125


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("sd"); ap.add_argument("rx_khz", type=int)
    ap.add_argument("stage", choices="CP"); ap.add_argument("--json"); a = ap.parse_args()
    base.FREQ_KHZ = a.rx_khz
    word = (a.rx_khz * 1000 * 65536 + 13000000) // 26000000
    base.EXPECTED_WORD = word
    rows, meta, H, C, cm = base.per_slot(a.sd)
    bad = []
    if not H: bad.append("no H")
    else:
        if int(H["freq_word"], 16) != word or H["freq_word"] != H.get("freq_rb"): bad.append("freq word")
        if int(H.get("bw_hz", 0)) != base.BW_HZ: bad.append("bw")
        if H.get("gdo_ok") != "1": bad.append("gdo")
    if C and C[-1][1][4] != 0: bad.append("ring_lost")
    if meta.get("abort"): bad.append("abort " + meta["abort"])
    keyed = ("tone", "zero") if a.stage == "C" else ("pat156", "zero")
    nexp = (4 if a.stage == "C" else 4) * meta["args"]["n"]
    if len(rows) != nexp: bad.append(f"{len(rows)} slots != {nexp}")
    for r in rows:
        if r["hang"]: bad.append(f"hang {r['i']}")
        if r["cond"] in keyed and (not r["keyed_us"] or r["keyed_us"] > 400 or r["pb51"] != 127):
            bad.append(f"slot {r['i']} keyed_us {r['keyed_us']} pb51 {r['pb51']}")
    g = {}
    for r in rows: g.setdefault(r["cond"], []).append(r)
    out = {"rx_khz": a.rx_khz, "expected_word": hex(word), "invalid": bad, "clock": cm, "cond": {}}
    for c, rs in g.items():
        pk = [r["peak"] for r in rs]
        out["cond"][c] = {"n": len(rs), "hits": sum(r["hit"] for r in rs), "peaks": pk, "peak_median": st.median(pk),
                          "durs": [max(r["durs"]) if r["durs"] else 0 for r in rs], "keyed_us": [r["keyed_us"] for r in rs]}
    kr = [r for c in keyed for r in g.get(c, [])]
    sat = bool(kr) and (sum(r["peak"] >= 120 for r in kr) / len(kr) >= 0.75)
    out["saturated"] = sat
    if a.stage == "C":
        t = out["cond"]["tone"]["hits"]; ni = out["cond"]["unkey"]["hits"] + out["cond"]["idle"]["hits"]
        out["control_pass"] = (not bad) and t >= 4 and ni <= 1
        out["outcome"] = "INVALID" if bad else ("CONTROL-PASS" if out["control_pass"] else "CONTROL-FAIL")
    else:
        P, Z = g["pat156"], g["zero"]
        hp, hz = sum(r["hit"] for r in P), sum(r["hit"] for r in Z)
        p1 = base.fisher_one_sided(hp, len(P), hz, len(Z))
        p2 = base.mwu_one_sided([r["peak"] for r in P], [r["peak"] for r in Z])
        md = st.median([r["peak"] for r in P]) - st.median([r["peak"] for r in Z])
        prim = p1 <= ALPHA; sec = p2 is not None and p2 <= ALPHA and md >= 3
        out.update(fisher_p=p1, mwu_p=p2, median_peak_diff=md, primary=prim, secondary=sec,
                   outcome="INVALID" if bad else ("SATURATED" if sat else ("ON" if prim or sec else "NO-DIFF")))
    print(json.dumps(out, indent=1))
    if a.json: json.dump({"summary": out, "rows": rows}, open(a.json, "w"), indent=1)


if __name__ == "__main__":
    main()
