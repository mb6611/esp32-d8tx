#!/usr/bin/env python3
"""Figures 10-11 of the TX chapter: retune gate and per-channel rate (reads bench/d8-tx/results/hop only).
    /private/tmp/mplvenv/bin/python docs/devkitv1/writeup/plot_hop.py
"""
import os, re
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
HOP = os.path.join(ROOT, "bench", "d8-tx", "results", "hop")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "img", "tx-evidence")
G, B, R_ = "#2f855a", "#2b6cb0", "#c53030"
plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.alpha": .3})

def gate():  # parse the table in retune_gate/summary.md
    rows = []
    for l in open(os.path.join(HOP, "retune_gate", "summary.md")):
        c = [x.strip() for x in l.split("|")]
        if len(c) > 5 and c[1].isdigit():
            rows.append((int(c[1]) / 1000, int(re.match(r"-?\d+", c[2])[0]),
                         [int(x) for x in c[3].split(",")], [float(x) for x in c[4].split(",")]))
    return sorted(rows)

def perch(path):
    d = {}
    for l in open(path):
        m = re.match(r"\s+ch\s*(\d+)\s+(\d+)/\s*(\d+)", l)
        if m: d[int(m[1])] = (int(m[2]), int(m[3]))
    return d

def main():
    rows = gate()
    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    xs = range(len(rows))
    for i, (f, base, key, fe) in enumerate(rows):
        ax.scatter([i - .12], [base], color="0.45", s=40, zorder=3, label="baseline (tone off)" if i == 0 else None)
        ax.scatter([i + .12] * 3, key, color=G, s=40, zorder=3, label="tone keyed (3 repeats)" if i == 0 else None)
        ax.text(i, max(key) + 4, f"carrier within\n{max(abs(x) for x in fe):.0f} kHz", ha="center", fontsize=8.5)
    ax.set_xticks(list(xs)); ax.set_xticklabels([f"{r[0]:.0f}" for r in rows])
    ax.set_xlabel("retuned LO (MHz)"); ax.set_ylabel("max RSSI in window (raw counts)"); ax.set_ylim(-60, 50)
    ax.legend(loc="lower right", fontsize=8.5, frameon=False)
    fig.tight_layout()
    for e in ("png", "svg"): fig.savefig(os.path.join(OUT, "hop-retune-gate." + e), dpi=150)
    plt.close(fig)

    e8 = perch(os.path.join(HOP, "e8_control", "summary.md")); eb = perch(os.path.join(HOP, "esp_hop", "runB_stats.txt"))
    fig, ax = plt.subplots(figsize=(8, 3.8))
    fr = lambda ch: 2404 + ch * 0.299927
    chs = sorted(e8)
    ax.scatter([fr(c) for c in chs], [100 * e8[c][0] / e8[c][1] for c in chs], color=B, s=28, label="real E8 (47 visits/channel)", zorder=3)
    ax.scatter([fr(c) for c in chs], [100 * eb[c][0] / eb[c][1] for c in chs], color=G, marker="s", s=24, label="ESP32 run B (20 visits/channel)", zorder=3)
    for c in (25, 133):
        ax.annotate(f"ch{c}, {fr(c):.1f} MHz\nE8 {e8[c][0]}/{e8[c][1]}, ESP32 {eb[c][0]}/{eb[c][1]}", (fr(c), 100 * e8[c][0] / e8[c][1]),
                    xytext=(fr(c) + 4, 62), fontsize=8.5, arrowprops=dict(arrowstyle="-", color="0.4"))
    ax.set_xlabel("RF frequency (MHz)"); ax.set_ylabel("received CRC-valid (%)"); ax.set_ylim(40, 103)
    ax.legend(loc="lower right", fontsize=8.5, frameon=False)
    fig.tight_layout()
    for e in ("png", "svg"): fig.savefig(os.path.join(OUT, "hop-per-channel.%s" % e), dpi=150)

main()
