#!/usr/bin/env python3
"""Figures 14-17 of the TX chapter (Section 9): radio telemetry, patched hub fields, blackbox.
Reads only committed evidence:
  bench/d8-tx/results/telemetry-stack/e2e/{fc_10min_b,fc_idle}.jsonl.gz  (d8tx backend WebSocket logs)
  bench/d8-tx/results/betaflight-patch/armtest_log.csv                   (arm test: switch, MSP, hub STATUS)
  bench/blackbox/results/bench/bb_session1_reconstructed.01.csv          (blackbox_decode output)
    /tmp/mpl/bin/python docs/devkitv1/writeup/plot_telemetry.py [--summary]
"""
import csv, gzip, json, pathlib, sys
R = pathlib.Path(__file__).resolve().parents[3]
OUT = R / "docs/devkitv1/writeup/img/tx-evidence"
E2E = R / "bench/d8-tx/results/telemetry-stack/e2e"
ARM = R / "bench/d8-tx/results/betaflight-patch/armtest_log.csv"
BB = R / "bench/blackbox/results/bench/bb_session1_reconstructed.01.csv"


def jsonl(name):
    return [json.loads(l) for l in gzip.open(E2E / name)]


def q(v, p):
    v = sorted(v)
    return v[min(len(v) - 1, int(p * len(v)))]


def per_minute(rows):
    """(triggers, replies) per minute from the cumulative counters in the WS log."""
    out, prev, i = [], (0, 0), 0
    for m in range(1, int(rows[-1]["t"] // 60) + 1):
        while i + 1 < len(rows) and rows[i + 1]["t"] <= m * 60:
            i += 1
        c = (rows[i]["radio"]["triggers"], rows[i]["radio"]["replies"])
        out.append((c[0] - prev[0], c[1] - prev[1]))
        prev = c
    return out


def hub_updates(rows):
    """One row per distinct hub update time (the WS log repeats the last value at 50 Hz)."""
    seen, out = set(), []
    for r in rows:
        h = r["radio"]["hub"]
        if h["age_ms"] is None:
            continue
        tu = round(r["t"] - h["age_ms"] / 1000, 1)
        if tu not in seen:
            seen.add(tu)
            out.append((tu, h))
    return out


def edges(t, v):
    return [(t[i], v[i - 1], v[i]) for i in range(1, len(v)) if v[i] != v[i - 1]]


def arm_log():
    rows = list(csv.DictReader(open(ARM)))
    t = [float(r["t"]) for r in rows]
    sw = [int(r["arm_switch"]) for r in rows]
    msp = [int(r["msp_armflag"]) for r in rows]
    tl = [{"True": 1, "False": 0}.get(r["tlm_armed"]) for r in rows]
    return t, sw, msp, tl


def bb_log():
    rd = csv.reader(open(BB))
    hdr = [h.strip() for h in next(rd)]
    cols = {h: [] for h in hdr}
    for row in rd:
        for h, x in zip(hdr, row):
            cols[h].append(float(x))
    t0 = cols["time (us)"][0]
    cols["t"] = [(x - t0) / 1e6 for x in cols["time (us)"]]
    return cols


def summary():
    rows = jsonl("fc_10min_b.jsonl.gz")
    ages = [r["radio"]["age_ms"] for r in rows if r["radio"]["age_ms"] is not None]
    pm = per_minute(rows)
    last = rows[-1]["radio"]
    print(f"10-min run: {last['replies']}/{last['triggers']} replies, per minute",
          [round(b / a, 3) for a, b in pm], f"age p50/p95/max {q(ages,.5)}/{q(ages,.95)}/{max(ages)} ms")
    hu = hub_updates(rows)
    print(f"10-min run: hub updates {len(hu)}, last at t={hu[-1][0]} s of {rows[-1]['t']:.0f} s")
    idle = hub_updates(jsonl("fc_idle.jsonl.gz"))
    acc = [h["acc_mg"] for _, h in idle if h["acc_mg"]]
    print("idle run: hub updates", len(idle), "acc mean", [round(sum(v) / len(v), 1) for v in ([a[i] for a in acc if a[i] is not None] for i in range(3))])
    t, sw, msp, tl = arm_log()
    for name, v in (("switch", sw), ("MSP", msp), ("hub STATUS", tl)):
        print("arm test", name, [(round(a, 3), b, c) for a, b, c in edges(t, v) if b is not None and c is not None])
    bb = bb_log()
    n = len(bb["t"])
    print(f"blackbox: {n} rows, {bb['t'][-1]:.2f} s, rcCommand0 {min(bb['rcCommand[0]']):.0f}..{max(bb['rcCommand[0]']):.0f}")


def main():
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    OUT.mkdir(parents=True, exist_ok=True)

    def save(fig, name):
        fig.tight_layout(); fig.savefig(OUT / f"{name}.png", dpi=130); fig.savefig(OUT / f"{name}.svg"); plt.close(fig)

    # Figure 14: 10-minute run, catch rate per minute and reply age
    rows = jsonl("fc_10min_b.jsonl.gz")
    pm = per_minute(rows)
    ages = [r["radio"]["age_ms"] for r in rows if r["radio"]["age_ms"] is not None]
    fig, (a, b) = plt.subplots(1, 2, figsize=(9, 3.2), gridspec_kw={"width_ratios": [1.2, 1]})
    a.bar(range(1, len(pm) + 1), [100 * r / t for t, r in pm], color="#1f77b4")
    for i, (t, r) in enumerate(pm, 1):
        a.text(i, 100 * r / t - 0.25, f"{r}/{t}", ha="center", va="top", fontsize=6, rotation=90, color="w")
    a.set_ylim(95, 100.5); a.set_xlabel("minute"); a.set_ylabel("replies / triggers (%)")
    a.set_xticks(range(1, len(pm) + 1))
    b.hist(ages, bins=range(0, 900, 20), color="#888")
    for p, ls in ((.5, "-"), (.95, "--")):
        b.axvline(q(ages, p), color="k", ls=ls, lw=1, label=f"p{int(p*100)} {q(ages, p)} ms")
    b.set_xlabel("reply age in each 50 Hz status message (ms)"); b.set_ylabel("messages"); b.set_yscale("log"); b.legend(fontsize=8)
    save(fig, "tlm-catch-age")

    # Figure 16: arm test, switch vs MSP vs hub STATUS armed bit. The switch trace uses the script's ARM_sent and
    # DISARM_sent times (armtest_events.json: 14.015, 24.019 s); the CSV only samples it every ~0.12 s.
    t, sw, msp, tl = arm_log()
    fig, ax = plt.subplots(figsize=(9, 2.8))
    ax.step([t[0], 14.015, 24.019, t[-1]], [2.4, 3.2, 2.4, 2.4], where="post", color="#888", label="ch7 arm switch (sent)")
    ax.step(t, [1.2 + 0.8 * v for v in msp], where="post", color="#1f77b4", label="Betaflight armed (MSP, USB)")
    ax.step(t, [0.8 * v if v is not None else float("nan") for v in tl], where="post", color="#d62728",
            label="hub STATUS bit0 (radio)")
    ax.set_yticks([0.4, 1.6, 2.8], ["radio", "MSP", "switch"])
    for x0, x1, y in ((14.015, 14.169, 1.4), (14.015, 14.649, 0.2), (24.019, 24.201, 1.4), (24.019, 25.033, 0.2)):
        ax.annotate(f"+{x1 - x0:.2f} s", (x1, y), xytext=(x1 + 0.25, y), fontsize=7, va="center")
    ax.set_xlim(10, 28); ax.set_xlabel("time in arm test (s)"); ax.legend(fontsize=7, loc="upper left")
    save(fig, "tlm-armed-bit")

    # Figure 15: patched hub ACC and gyro over the 60 s idle run
    hu = hub_updates(jsonl("fc_idle.jsonl.gz"))
    fig, (a, b) = plt.subplots(2, 1, figsize=(9, 4), sharex=True)
    for i, (lab, c) in enumerate((("X", "#1f77b4"), ("Y", "#2ca02c"), ("Z", "#d62728"))):
        pa = [(tu, h["acc_mg"][i]) for tu, h in hu if h["acc_mg"] and h["acc_mg"][i] is not None]
        pg = [(tu, h["patched"]["gyro_dps"][i]) for tu, h in hu
              if h["patched"].get("gyro_dps") and h["patched"]["gyro_dps"][i] is not None]
        a.plot(*zip(*pa), ".", ms=3, color=c, label=f"ACC {lab}")
        b.plot(*zip(*pg), ".", ms=3, color=c, label=f"gyro {lab}")
    a.set_ylabel("ACC (milli-g)"); a.legend(fontsize=7, ncol=3, loc="center right")
    b.set_ylabel("gyro (deg/s)"); b.set_xlabel("time in run (s)"); b.legend(fontsize=7, ncol=3)
    save(fig, "tlm-hub-acc-gyro")

    # Figure 17: blackbox session1
    bb = bb_log()
    fig, axs = plt.subplots(3, 1, figsize=(9, 5.5), sharex=True)
    for i, (lab, c) in enumerate((("roll", "#1f77b4"), ("pitch", "#2ca02c"), ("yaw", "#d62728"))):
        axs[0].plot(bb["t"], bb[f"rcCommand[{i}]"], color=c, lw=0.8, label=lab)
        axs[1].plot(bb["t"], bb[f"setpoint[{i}]"], color=c, lw=0.8, label=lab)
    for i in range(4):
        axs[2].plot(bb["t"], bb[f"motor[{i}]"], lw=0.6, label=f"motor {i}")
    axs[0].set_ylabel("rcCommand"); axs[0].legend(fontsize=7, ncol=3)
    axs[1].set_ylabel("setpoint (deg/s)"); axs[1].legend(fontsize=7, ncol=3)
    axs[2].set_ylabel("motor (raw)"); axs[2].set_xlabel("time in log (s)"); axs[2].legend(fontsize=7, ncol=4)
    save(fig, "blackbox-session1")


if __name__ == "__main__":
    summary() if "--summary" in sys.argv else main()
