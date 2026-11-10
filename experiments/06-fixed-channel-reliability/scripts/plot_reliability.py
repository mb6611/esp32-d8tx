#!/usr/bin/env python3
"""Figures 4-6 of the TX chapter: fixed-channel reliability (reads experiments/05-first-packet/data only).
    /tmp/mpl/bin/python experiments/06-fixed-channel-reliability/scripts/plot_reliability.py [--summary]
"""
import glob, json, math, os, re, statistics, sys
ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
PK = os.path.join(ROOT, "experiments", "06-fixed-channel-reliability", "data")
OUT = os.environ.get("FIGURES_OUT") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "figures")
BODY = "1142B2000001CACACACA8888CACACACA8888"
KHZ = 26e6 / 2**14 / 1e3  # kHz per FREQEST LSB
RE = re.compile(r"(\d+\.\d+) P,(\d+),(\d+),(\d+),([0-9A-F]*),(-?\d+),(\d+),(\d)(?:,(-?\d+))?$")

def recs(path):
    out = []
    for l in open(path):
        m = RE.match(l.strip())
        if m:
            out.append(dict(t=int(m[3]), len=int(m[4]), hex=m[5], crc=int(m[8]), fe=None if m[9] is None else int(m[9])))
    return out

def esp_valid(path):
    return [r for r in recs(path) if r["hex"] == BODY and r["crc"] == 1]

def e8_valid(path):
    return [r for r in recs(path) if r["len"] == 18 and r["hex"].startswith("1142B200") and r["crc"] == 1]

def wilson(k, n, z=1.96):
    p = k / n; d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d; h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h

REL = {"1b": (9, 1), 2: (None, None)}
for b in range(3, 11):
    REL[b] = None
def counts():
    rel = {}
    for f in glob.glob(os.path.join(PK, "reliability", "batch*_report.txt")):
        n = int(re.search(r"batch(\d+)_", f)[1]); m = re.search(r"valid=(\d+).*unobserved=(\d+)", open(f).read())
        rel[n] = (int(m[1]), int(m[2]))
    rel[1] = (9, 1)           # batch 1b: no report file; recount of batch1b_stm.txt
    fq = {}
    for n in range(1, 6):
        m = re.search(r"valid=(\d+).*unobserved=(\d+)", open(os.path.join(PK, "freqest", f"batch{n}_report.txt")).read())
        fq[n] = (int(m[1]), int(m[2]))
    return rel, fq

def e8_counts():
    files = [os.path.join(PK, "reliability", "control_e8_2421032.txt"), os.path.join(PK, "reliability", "control_e8_post10_2421032.txt"),
             os.path.join(PK, "freqest", "control_e8_pre.txt"), os.path.join(PK, "freqest", "control_e8_post.txt")]
    return [len(e8_valid(f)) for f in files], files

def summary():
    rel, fq = counts(); e8, files = e8_counts()
    esp_att = sum(v[0] + v[1] for k, v in rel.items() if k not in (2,))
    print("reliability attributable valid/unobs:", sum(v[0] for k, v in rel.items() if k != 2), sum(v[1] for k, v in rel.items() if k != 2),
          "(batch 2 report valid=%d unobs=%d; raw 8)" % rel[2])
    print("freqest:", fq, sum(v[0] for v in fq.values()))
    print("E8 controls:", e8, sum(e8), "expected at 422.7 ms in 20 s:", 20 / 0.4227, 4 * 20 / 0.4227)
    fe_esp = [r["fe"] * KHZ for n in range(1, 6) for r in esp_valid(os.path.join(PK, "freqest", f"batch{n}_stm.txt"))]
    fe_e8 = [r["fe"] * KHZ for f in files[2:] for r in e8_valid(f)]
    for nm, x in (("esp", fe_esp), ("e8", fe_e8)):
        print(nm, len(x), "mean %.1f sd %.1f min %.1f max %.1f" % (statistics.mean(x), statistics.pstdev(x), min(x), max(x)),
              "at +-33.3:", sum(abs(v) > 33 for v in x))
    return fe_esp, fe_e8, rel, fq, e8

def drift(n, missing):
    base = os.path.join(PK, "reliability")
    ps = recs(os.path.join(base, f"batch{n}_stm.txt")); H = None
    for l in open(os.path.join(base, f"batch{n}_stm.txt")):
        m = re.search(r"t0_us=(\d+)", l)
        if m: t0 = int(m[1]); break
    att = json.load(open(os.path.join(base, f"batch{n}_esp_out", "attempts.json")))["attempts"]
    anc = json.load(open(os.path.join(base, f"batch{n}_anchor.json")))["start_cmd_host"]
    mt = [p for p in ps if p["hex"] == BODY and p["crc"] == 1]
    pts = []
    for a in att:
        if a["i"] in missing: continue
        x = a["t_send"] - anc
        p = min(mt, key=lambda r: abs(anc + (r["t"] - t0) / 1e6 - a["t_send"]))
        pts.append((a["i"], x, (p["t"] - t0) / 1e3 - x * 1e3))   # device - host elapsed, ms
    xs = [p[1] for p in pts]; ys = [p[2] for p in pts]
    mx, my = statistics.mean(xs), statistics.mean(ys)
    R = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs); A = my - R * mx
    miss = [(i, att[i]["t_send"] - anc) for i in missing]
    return pts, A, R, miss, [abs(y - (A + R * x)) * 1e3 for _, x, y in pts]

def main():
    fe_esp, fe_e8, rel, fq, e8 = summary()
    if "--summary" in sys.argv: return
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.alpha": .3})
    G, R_, Y, GR = "#2e8b57", "#c0392b", "#e6a817", "0.6"
    # --- Figure 4: outcomes
    fig, ax = plt.subplots(1, 2, figsize=(12.5, 4.3), gridspec_kw={"width_ratios": [1.9, 1]})
    a = ax[0]; labels = []; x = 0; xs = {}
    order = [("rel", k) for k in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10)] + [("fq", k) for k in range(1, 6)]
    for i, (g, k) in enumerate(order):
        v, u = (rel if g == "rel" else fq)[k]
        xpos = i + (0.6 if g == "fq" else 0)
        if g == "rel" and k == 2:
            a.bar(xpos, 8, color=Y, hatch="//", edgecolor="w"); a.bar(xpos, 2, bottom=8, color="0.85", hatch="//", edgecolor="w")
        else:
            a.bar(xpos, v, color=G); a.bar(xpos, u, bottom=v, color=R_)
        labels.append((xpos, ("1b" if k == 1 and g == "rel" else str(k))))
    a.set_xticks([p for p, _ in labels]); a.set_xticklabels([l for _, l in labels]); a.set_ylim(0, 11.5); a.set_yticks([0, 2, 4, 6, 8, 10])
    a.set_ylabel("PKT commands per batch"); a.set_xlabel("batch (left: reliability 10×10 · right: FREQEST session 5×10)")
    a.set_title("A. what the receiver saw, per batch")
    from matplotlib.patches import Patch
    fig.legend(handles=[Patch(color=G, label="received CRC-valid, attributed to its command"), Patch(color=R_, label="no record (unobserved)"),
                      Patch(facecolor=Y, hatch="//", edgecolor="w", label="batch 2: 8 valid, not attributable to commands")],
             loc="lower left", bbox_to_anchor=(0.06, 0.0), ncol=3, fontsize=8.5, frameon=False)
    b = ax[1]
    sr = sum(v[0] for k, v in rel.items() if k != 2); sa = sum(v[0] + v[1] for k, v in rel.items() if k != 2)
    rows = [("ESP32 reliability\n(batches ≠ 2)", sr, sa, G), ("ESP32 FREQEST\nsession", sum(v[0] for v in fq.values()), 50, G),
            ("Real E8\n(4 × 20 s controls)", sum(e8), round(4 * 20 / 0.4227), "#2b6cb0")]
    for i, (nm, k, n, c) in enumerate(rows):
        lo, hi = wilson(k, n)
        b.errorbar(100 * k / n, i, xerr=[[100 * k / n - 100 * lo], [100 * hi - 100 * k / n]], fmt="o", color=c, capsize=4)
        b.text(100 * hi + 1.2, i, f"{k}/{n}", va="center", fontsize=9)
    b.set_yticks(range(3)); b.set_yticklabels([r[0] for r in rows], fontsize=9); b.set_xlim(75, 110); b.set_xticks([80, 90, 100]); b.invert_yaxis()
    b.set_xlabel("received, % (95% Wilson interval)"); b.set_title("B. rate, ESP32 vs real E8")
    fig.tight_layout(rect=[0, 0.08, 1, 1]); fig.savefig(os.path.join(OUT, "reliability-outcome.png"), dpi=130); fig.savefig(os.path.join(OUT, "reliability-outcome.svg")); plt.close(fig)
    # --- Figure 5: FREQEST
    fig, ax = plt.subplots(figsize=(8, 3.8))
    bins = [(-34 + 4 * i) for i in range(18)]
    ax.hist([fe_esp, fe_e8], bins=bins, color=[G, "#2b6cb0"], label=[f"ESP32 (n={len(fe_esp)})", f"real E8 (n={len(fe_e8)})"], weights=[[1 / len(fe_esp)] * len(fe_esp), [1 / len(fe_e8)] * len(fe_e8)])
    for s in (-1, 1): ax.axvline(s * 21 * KHZ, color="#e6a817", ls="--", lw=1)
    ax.text(21 * KHZ - 0.5, ax.get_ylim()[1] * .93, "±33.3 kHz\n(±21 LSB)", ha="right", va="top", fontsize=8.5, color="#a07800")
    ax.set_xlabel("FREQEST per received packet (kHz; int8 × 26 MHz/2¹⁴)"); ax.set_ylabel("fraction of packets per 4 kHz bin")
    ax.legend(frameon=False, loc="upper left"); ax.set_title("Receiver frequency estimate, ESP32 vs real E8 (same receiver)")
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "freqest-hist.png"), dpi=130); fig.savefig(os.path.join(OUT, "freqest-hist.svg")); plt.close(fig)
    # --- Figure 6: timing/drift
    fig, ax = plt.subplots(1, 3, figsize=(12.5, 3.6))
    for a, (n, miss) in zip(ax, ((3, [0]), (6, [5, 6]), (9, [2]))):
        pts, A, R, ms, res = drift(n, miss)
        a.plot([0, 5.3], [A, A + R * 5.3], color="0.5", lw=1)
        a.scatter([p[1] for p in pts], [p[2] for p in pts], color=G, s=24, zorder=3, label="received")
        a.scatter([x for _, x in ms], [A + R * x for _, x in ms], marker="x", color=R_, s=55, zorder=3, label="expected time of unobserved send")
        a.set_title(f"batch {n}: max fit residual {max(res):.0f} µs", fontsize=10); a.set_xlabel("time since start command (s)")
        a.set_ylabel("receiver clock − host clock (ms)") if a is ax[0] else None
    ax[0].legend(frameon=False, fontsize=8, loc="upper left")
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "reliability-timing.png"), dpi=130); fig.savefig(os.path.join(OUT, "reliability-timing.svg")); plt.close(fig)

main()
