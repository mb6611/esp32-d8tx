#!/usr/bin/env python3
"""Commanded vs Betaflight-received roll, live-sticks run (Figure 12)."""
import csv, os, pathlib
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
r = pathlib.Path(__file__).resolve().parents[3]
b = r / "experiments/08-first-flight-cloned-e8/data/live_sticks"
S = [(float(x[0]), float(x[2])) for x in list(csv.reader(open(b/"live_sender.csv")))[1:]]
M = [(float(x[1]), float(x[3])) for x in list(csv.reader(open(b/"live_msp.csv")))[1:]]
t0 = S[0][0]
fig, ax = plt.subplots(figsize=(9, 3.2))
ax.step([t-t0 for t, _ in S], [v for _, v in S], where="post", label="commanded (host sender, ch2)", color="#888")
ax.plot([t-t0 for t, _ in M], [v for _, v in M], ".", ms=2.5, label="received (Betaflight, MSP_RC)", color="#1f77b4")
ax.set_xlabel("time (s)"); ax.set_ylabel("roll (µs)"); ax.legend(loc="upper right", fontsize=8)
ax.set_xlim(-1, 17)
fig.tight_layout()
o = pathlib.Path(os.environ.get("FIGURES_OUT") or r / "experiments/08-first-flight-cloned-e8/figures")
fig.savefig(o/"live-roll-latency.png", dpi=130); fig.savefig(o/"live-roll-latency.svg")
