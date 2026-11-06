#!/usr/bin/env python3
"""Hop map PNG: time vs RF MHz, hop-sequence line, received dots, red X misses.
    /private/tmp/mplvenv/bin/python hop_plot.py LOG OUT.png [--slots N]
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hop_capture as hc  # noqa: E402


SLOT_S = 0.008994


def mhz(ch):
    return 2404.0 + ch * 0.29993


def plot(recs, table, out, title="D8 hop map", total_slots=None, window=None, zoom=0.45):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    st = hc.analyze(recs, table, total_slots)
    n = len(table)
    lo = 0 if total_slots is not None else (min(r.slot for r in recs) if recs else 0)
    hi = lo + st["slots"] - 1
    got = {r.slot: r for r in recs if r.valid}
    miss = [s for s in range(lo, hi + 1) if s not in got]
    t = lambda s: (s - lo) * SLOT_S
    ink, grid, red, grn = "#1a202c", "#e2e8f0", "#c53030", "#2f855a"
    fig = plt.figure(figsize=(14, 7), facecolor="white")
    gs = fig.add_gridspec(2, 2, width_ratios=[2.2, 1])
    top, bot, b = fig.add_subplot(gs[0, 0]), fig.add_subplot(gs[1, 0]), fig.add_subplot(gs[:, 1])

    def draw(a, t0, t1, ms, lab):
        s0, s1 = lo + int(t0 / SLOT_S), min(hi, lo + int(t1 / SLOT_S))
        ss = list(range(s0, s1 + 1))
        a.step([t(s) for s in ss], [mhz(table[s % n]) for s in ss], where="mid", color="#0891b2", lw=0.6, alpha=0.8, label="hop sequence", zorder=1)
        g = [s for s in ss if s in got]; m = [s for s in miss if s0 <= s <= s1]
        a.scatter([t(s) for s in g], [mhz(table[s % n]) for s in g], s=ms, color="#2b6cb0", label=f"received ({len(g)})", zorder=2)
        a.scatter([t(s) for s in m], [mhz(table[s % n]) for s in m], marker="x", s=ms * 3, color=red, linewidths=1.2, label=f"no valid packet ({len(m)})", zorder=3)
        a.set_xlim(t0, t1 + SLOT_S); a.set_facecolor("white"); a.grid(color=grid, lw=0.6)
        a.set_xlabel("time [s]"); a.set_ylabel("RF frequency [MHz]")
        a.legend(loc="upper right", fontsize=8.5, frameon=True, framealpha=0.9)
        a.set_title(lab, fontsize=10, color=ink)
        sec = a.secondary_yaxis("right", functions=(lambda f: (f - 2404.0) / 0.29993, lambda c: 2404.0 + c * 0.29993))
        sec.set_ylabel("channel", fontsize=8)

    tmax = (hi - lo + 1) * SLOT_S
    w = min(window, tmax) if window else tmax
    draw(top, 0, w, 10, f"A. whole run: {st['received']}/{st['slots']} slots, longest loss run {st['longest_loss_run']}")
    draw(bot, 0, min(zoom, w), 26, f"B. first {min(zoom, w):.2f} s (one 47-hop cycle)")
    chans = sorted(table)
    rates = [100 * (st["per_channel"][c]["rate"] or 0) for c in chans]
    b.barh(range(len(chans)), rates, color=[grn if r >= 90 else red for r in rates])
    b.axvline(90, color="#718096", lw=0.8, ls=":")
    b.set_yticks(range(0, len(chans), 4)); b.set_yticklabels([f"{chans[i]} ({mhz(chans[i]):.1f})" for i in range(0, len(chans), 4)], fontsize=8)
    b.set_xlim(0, 100); b.set_xlabel("CRC-valid, % of slots (red <90%)"); b.set_ylabel("channel (MHz), sorted"); b.set_title("C. per-channel rate", fontsize=10, color=ink)
    fig.suptitle(title, fontsize=12.5, color=ink, fontweight="bold")
    fig.tight_layout(); fig.savefig(out, dpi=130, facecolor="white"); plt.close(fig)
    return st


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("log"); ap.add_argument("out")
    ap.add_argument("--slots", type=int, default=None)
    ap.add_argument("--title", default="D8 hop map")
    ap.add_argument("--window", type=float, default=None, help="plot only first S seconds")
    ap.add_argument("--table-start", type=int, default=2); ap.add_argument("--table-step", type=int, default=55)
    a = ap.parse_args(argv)
    plot(hc.parse_log(open(a.log)), hc.default_table(a.table_start, a.table_step), a.out, title=a.title, total_slots=a.slots, window=a.window)


if __name__ == "__main__":
    main()
