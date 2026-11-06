#!/usr/bin/env python3
"""Hop map PNG: slot vs channel (CC2500 channel number), colour = RSSI dBm; misses marked.
    /private/tmp/mplvenv/bin/python hop_plot.py LOG OUT.png [--slots N]
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hop_capture as hc  # noqa: E402


def plot(recs, table, out, title="D8 hop map", total_slots=None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    st = hc.analyze(recs, table, total_slots)
    n = len(table)
    lo = 0 if total_slots is not None else (min(r.slot for r in recs) if recs else 0)
    hi = lo + st["slots"] - 1
    got = {r.slot for r in recs if r.valid}
    miss = [s for s in range(lo, hi + 1) if s not in got]
    fig, ax = plt.subplots(1, 2, figsize=(14, 5), gridspec_kw=dict(width_ratios=[2.2, 1]))
    a = ax[0]
    v = [r for r in recs if r.valid]
    sc = a.scatter([r.slot for r in v], [r.chan for r in v], c=[hc.rssi_dbm(r.rssi) for r in v], s=14, cmap="viridis")
    a.scatter(miss, [table[s % n] for s in miss], marker="x", s=14, color="#c53030", linewidths=0.8, label=f"no valid packet ({len(miss)})")
    fig.colorbar(sc, ax=a, label="RSSI [dBm]")
    a.set_xlabel("hop slot"); a.set_ylabel("CC2500 channel"); a.legend(loc="upper right", fontsize=8.5, frameon=False)
    a.set_title(f"A. {title}: {st['received']}/{st['slots']} slots, longest loss run {st['longest_loss_run']}")
    b = ax[1]
    chans = sorted(table)
    rates = [100 * (st["per_channel"][c]["rate"] or 0) for c in chans]
    b.barh(range(len(chans)), rates, color="#2f855a")
    b.set_yticks(range(0, len(chans), 4)); b.set_yticklabels([chans[i] for i in range(0, len(chans), 4)], fontsize=8)
    b.set_xlim(0, 100); b.set_xlabel("CRC-valid, % of slots"); b.set_ylabel("channel (sorted)"); b.set_title("B. per-channel rate")
    fig.tight_layout(); fig.savefig(out, dpi=130); plt.close(fig)
    return st


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("log"); ap.add_argument("out")
    ap.add_argument("--slots", type=int, default=None)
    ap.add_argument("--table-start", type=int, default=2); ap.add_argument("--table-step", type=int, default=55)
    a = ap.parse_args(argv)
    plot(hc.parse_log(open(a.log)), hc.default_table(a.table_start, a.table_step), a.out, total_slots=a.slots)


if __name__ == "__main__":
    main()
