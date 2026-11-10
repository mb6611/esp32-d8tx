#!/usr/bin/env python3
"""Plot blackbox logs: gyroADC[0..2], setpoint[0..3], rcCommand[0..3], motor[0..3] vs time, one PNG per log.

  bbplot.py LOG.bbl [--outdir DIR] [--engine auto|c|py]     # decode (bbdecode.py) then plot every log
  bbplot.py LOG.01.csv [LOG.02.csv ...] [--outdir DIR]       # plot already-decoded CSVs

Writes <outdir>/<csv stem>.png (e.g. capture.01.png, capture.02.png) and prints a one-line summary per log.
"""
import argparse, csv, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bbdecode  # noqa: E402

PANELS = [
    ("gyroADC", 3, "gyro (deg/s)", ["roll", "pitch", "yaw"]),
    ("setpoint", 3, "setpoint (deg/s)", ["roll", "pitch", "yaw"]),
    ("rcCommand", 4, "rcCommand", ["roll", "pitch", "yaw", "throttle"]),
    ("motor", 4, "motor (DShot/PWM out)", ["m1", "m2", "m3", "m4"]),
]


def read_csv(path):
    """Return {column: [float]} from a blackbox_decode-style CSV (', ' separated, unit suffixes in names)."""
    with open(path, newline="") as f:
        r = csv.reader(f, skipinitialspace=True)
        names = [n.strip() for n in next(r)]
        cols = {n: [] for n in names}
        for row in r:
            if len(row) != len(names):
                continue
            for n, v in zip(names, row):
                try:
                    cols[n].append(float(v))
                except ValueError:
                    cols[n].append(float("nan"))
    return cols


def time_s(cols):
    k = next((n for n in cols if n.startswith("time")), None)
    if k is None or not cols[k]:
        raise ValueError("no time column")
    t = cols[k]
    scale = 1.0 if "(s)" in k else 1e-6
    return [(x - t[0]) * scale for x in t]


def plot_csv(path, png, title=None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    cols = read_csv(path)
    t = time_s(cols)
    fig, axes = plt.subplots(len(PANELS), 1, figsize=(11, 10), sharex=True)
    for ax, (base, n, ylabel, labels) in zip(axes, PANELS):
        drawn = 0
        for i in range(n):
            k = "%s[%d]" % (base, i)
            if k in cols:
                ax.plot(t, cols[k], lw=0.8, label=labels[i])
                drawn += 1
        if not drawn:
            ax.text(0.5, 0.5, "%s not in log" % base, ha="center", va="center", transform=ax.transAxes)
        ax.set_ylabel(ylabel)
        ax.grid(alpha=0.3)
        if drawn:
            ax.legend(loc="upper right", fontsize=8, ncol=n)
    axes[-1].set_xlabel("time since log start (s)")
    dur = t[-1] if t else 0
    rate = (len(t) - 1) / dur if dur > 0 else 0
    fig.suptitle(title or "%s  (%d frames, %.2f s, %.0f Hz)" % (os.path.basename(path), len(t), dur, rate))
    fig.tight_layout()
    fig.savefig(png, dpi=110)
    plt.close(fig)
    return {"csv": path, "png": png, "frames": len(t), "duration_s": dur, "rate_hz": rate}


def plot(inputs, outdir=None, engine="auto"):
    csvs = []
    for p in inputs:
        if p.lower().endswith(".csv"):
            csvs.append(p)
        else:
            csvs += bbdecode.decode(p, outdir, engine)
    out = []
    for c in csvs:
        d = outdir or os.path.dirname(os.path.abspath(c))
        os.makedirs(d, exist_ok=True)
        png = os.path.join(d, os.path.splitext(os.path.basename(c))[0] + ".png")
        out.append(plot_csv(c, png))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help=".bbl/.bfl/.txt log(s) or decoded .csv file(s)")
    ap.add_argument("--outdir")
    ap.add_argument("--engine", choices=["auto", "c", "py"], default="auto")
    a = ap.parse_args(argv)
    for s in plot(a.inputs, a.outdir, a.engine):
        print("%s: %d frames, %.2f s, %.0f Hz" % (s["png"], s["frames"], s["duration_s"], s["rate_hz"]))


if __name__ == "__main__":
    main()
