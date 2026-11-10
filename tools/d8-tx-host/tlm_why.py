#!/usr/bin/env python3
"""Why did the drone not reply? Per-attempt join of a tlm_listen.py link run (offline, no hardware).

Needs a run made with --mark (ch8 = 1500 us on trigger packets, 1600 on re-triggers) and --msp-rc-hz (MSP_RC poll
into msp_rc.csv). For every trigger attempt (shipped capture or EV tlm_drop line) it reports:
  hit      CRC-valid telemetry frame decoded (shipped captures only; a dropped attempt is a miss by construction)
  marker   an MSP_RC sample read the attempt's ch8 marker within [k, k+MARK_SLOTS) slots of its send time, i.e. the
           drone's Betaflight decoded that trigger packet. MSP samples every ~16-19 ms, the marker stays in rcData
           until the next received packet (>= 2 slots), so 'no marker' on one attempt is weak evidence; the hit rows
           give the sampling coverage.
  gap/pgap packet start of the trigger (and of the slot before) vs the previous packet start minus 8994 us
  probes   (TLMX probe=1) one plain data packet half-way between triggers, ch8 1400, followed by a silent slot like
           a listen slot: the same marker test on a non-trigger packet, i.e. the drone's data-packet receipt rate
  sl/rt    slot lateness and retune time of the trigger slot (us)

    python tlm_why.py experiments/09-telemetry/data/<run> [...]
"""
from __future__ import annotations

import argparse
import glob
import json
import os

SLOT_S = 0.008994
MARK_SLOTS = 6


def load_msp(run: str):
    rows = []
    path = os.path.join(run, "msp_rc.csv")
    if not os.path.exists(path):
        return rows
    for ln in open(path).read().splitlines()[1:]:
        f = ln.split(",")
        if len(f) < 11 or "ERR" in ln:
            continue
        rows.append((float(f[0]), float(f[1]), int(f[10])))
    return rows


def attempts(run: str) -> list[dict]:
    res = json.load(open(os.path.join(run, "result.json")))
    out = []
    for j in sorted(glob.glob(os.path.join(run, "cap*.json"))):
        r = json.load(open(j))
        out.append({"k": r["k"], "ch": r["ch"], "tid": r["tid"], "try": r.get("try", 0),
                    "hit": any(h["telemetry"] for h in r["frames"]), "nb": r.get("nb"), "sl": r.get("sl"),
                    "rt": r.get("rt"), "gap": r.get("gap"), "pgap": r.get("pgap"), "shipped": True})
    for d in res.get("drops", []):
        out.append({"k": d["k"], "ch": d["ch"], "tid": d["tid"], "try": d["try"], "hit": False, "nb": d["nb"],
                    "sl": d["sl"], "rt": d["rt"], "gap": d["gap"], "pgap": d["pgap"], "shipped": False})
    out.sort(key=lambda a: a["k"])
    return out, res


def join(run: str) -> list[dict]:
    att, res = attempts(run)
    msp = load_msp(run)
    t0 = res.get("t_link0")
    if not msp or t0 is None:
        for a in att:
            a["marker"] = None
        return att
    # host clock offset of slot 0: fit so the hit attempts (drone surely got them) see their marker most often
    best = (-1, 0.0)
    for off_ms in range(-60, 61, 2):
        off = off_ms / 1e3
        n = sum(_seen(msp, t0 + off, a) for a in att if a["hit"])
        if n > best[0]:
            best = (n, off)
    for a in att:
        a["marker"] = _seen(msp, t0 + best[1], a)
    probes = [{"k": p["k"], "ch": p["ch"], "try": 0, "want": 1400, "gap": p.get("gap"), "pgap": p.get("pgap")}
              for p in res.get("probes", [])]
    for p in probes:
        p["marker"] = _seen(msp, t0 + best[1], p)
    join.probes = probes
    return att


def _seen(msp, t0, a) -> bool:
    want = a.get("want") or (1600 if a["try"] else 1500)
    lo = t0 + a["k"] * SLOT_S
    hi = lo + MARK_SLOTS * SLOT_S
    return any(abs(v - want) < 30 and ts < hi and tr > lo for ts, tr, v in msp)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--list", action="store_true", help="print every miss")
    a = ap.parse_args(argv)
    for run in a.runs:
        att = join(run)
        hits = [x for x in att if x["hit"]]
        miss = [x for x in att if not x["hit"]]
        print(f"== {os.path.basename(run)}: attempts={len(att)} hits={len(hits)} misses={len(miss)}")
        if att and att[0]["marker"] is not None:
            hm = sum(x["marker"] for x in hits)
            mm = sum(x["marker"] for x in miss)
            print(f"  marker seen: hits {hm}/{len(hits)} (= MSP sampling coverage), misses {mm}/{len(miss)}")
        pr = getattr(join, "probes", [])
        if pr:
            print(f"  probes (data packet, ch8 1400, silent slot after): marker seen {sum(p['marker'] for p in pr)}/{len(pr)}")
        for name, sel in (("hits", hits), ("misses", miss)):
            g = sorted(abs(x["gap"]) for x in sel if x["gap"] is not None and abs(x["gap"]) < 9999)
            pg = sorted(abs(x["pgap"]) for x in sel if x["pgap"] is not None and abs(x["pgap"]) < 9999)
            if g:
                print(f"  {name}: |gap| median {g[len(g) // 2]} max {g[-1]}  >100us {sum(v > 100 for v in g)}/{len(g)}"
                      f"  |pgap| median {pg[len(pg) // 2] if pg else '-'}")
            sg = sorted(x["gap"] for x in sel if x["gap"] is not None and abs(x["gap"]) < 9999)
            if sg:
                print(f"  {name}: signed gap (late>0) >+100 {sum(v > 100 for v in sg)}, <-100 {sum(v < -100 for v in sg)}")
        if a.list:
            for x in miss:
                print("  miss", {k: x[k] for k in ("k", "ch", "tid", "try", "nb", "sl", "rt", "gap", "pgap", "marker",
                                                   "shipped")})


if __name__ == "__main__":
    main()
