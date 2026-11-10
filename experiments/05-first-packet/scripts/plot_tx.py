#!/usr/bin/env python3
"""Regenerate the TX write-up figures from the raw logs in experiments.

    python3 experiments/05-first-packet/scripts/plot_tx.py            # writes SVG+PNG, prints the derived numbers
    python3 experiments/05-first-packet/scripts/plot_tx.py --summary  # numbers only, no matplotlib needed

Needs matplotlib (>=3.5) for the figures; offline, no other dependency.
Every number quoted in docs/lab-log/tx.md is printed by summary().
"""
import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
EXP = os.path.join(ROOT, "experiments")
TONE1 = os.path.join(EXP, "03-tone-first-attempt", "data")
TONE2 = os.path.join(EXP, "04-tone-scan", "data")
PKT = os.path.join(EXP, "05-first-packet", "data")
# each figure goes to the figures/ folder of the experiment it belongs to; FIGURES_OUT overrides (one folder for all)
FIG = {"tone-scan": "04-tone-scan", "null-and-trap": "04-tone-scan", "packet-outcome": "05-first-packet"}
OUT = os.environ.get("FIGURES_OUT")
VECTOR_BODY = "1142B2000001CACACACA8888CACACACA8888"  # d8_vectors.build(0)[:18]


def jl(path):
    with open(path) as f:
        return [json.loads(l) for l in f if l.strip()]


def f_windows(path):
    """rxdiag freq F records -> list of dicts (seq, ncs, rssi_max_raw)."""
    rows = []
    for line in open(path):
        p = line.strip().split(" ", 1)[-1].split(",")
        if p[0] == "F" and len(p) >= 16:
            rows.append({"seq": int(p[1]), "ncs": int(p[5]), "rssi": int(p[11])})
    return rows


def p_records(path):
    """rxdiag pkt P records -> list of dicts (hex, len, rssi, lqi, crc_ok)."""
    rows = []
    for line in open(path):
        p = line.strip().split(" ", 1)[-1].split(",")
        if p[0] == "P" and len(p) == 8:
            rows.append({"len": int(p[3]), "hex": p[4], "rssi": int(p[5]),
                         "lqi": int(p[6]), "crc": int(p[7])})
    return rows


def classify(rec):
    body = rec["len"] == 18 and rec["hex"] == VECTOR_BODY
    if body and rec["crc"] == 1:
        return "valid"
    if body:
        return "body-match, CRC flag 0"
    return "other fragment"


def retry_null():
    """12 keyed commands of the pwr32 / agc251/64 / bw812 retry: max ncs over all windows."""
    out = []
    for stm in sorted(glob.glob(os.path.join(TONE1, "retry_*_stm.txt"))):
        w = f_windows(stm)
        name = os.path.basename(stm)[len("retry_"):-len("_stm.txt")]
        out.append((name, max(x["ncs"] for x in w), len(w)))
    return out


def control_ncs(path):
    return [w["ncs"] for w in f_windows(path)]


def summary():
    S = {}
    rn = retry_null()
    S["retry_cmds"] = len(rn)
    S["retry_max_ncs_overall"] = max(r[1] for r in rn)
    S["retry_cmds_with_any_cs"] = [r[0] for r in rn if r[1] > 0]
    e8 = f_windows(os.path.join(TONE1, "control_real_e8.txt"))
    S["e8_freq_control_windows_with_cs"] = (sum(1 for w in e8 if w["ncs"] > 0), len(e8))
    c812 = control_ncs(os.path.join(TONE2, "rerun2", "control_source_off_2412000.txt"))
    S["srcoff_203_66_bw812_cs_windows"] = (sum(1 for n in c812 if n > 0), len(c812))
    c203 = f_windows(os.path.join(TONE2, "rerun3", "control_bw203.txt"))
    c102 = f_windows(os.path.join(TONE2, "rerun3", "control_bw102.txt"))
    S["srcoff_bw203_cs_windows"] = (sum(1 for w in c203 if w["ncs"] > 0), len(c203))
    S["srcoff_bw102_cs_windows"] = (sum(1 for w in c102 if w["ncs"] > 0), len(c102))
    wide = jl(os.path.join(TONE2, "scan-wide", "results.jsonl"))
    S["wide_keyings"] = len(wide)
    S["wide_stageA_hits"] = [(r["fc"], r["tone"], r["ncs_pk"]) for r in wide
                             if r["ncs_pk"] >= 700 and r["fc"] % 500 == 0 and r["ncs_pk"] > 5 * r["base_ncs"]]
    S["wide_bw102_hits"] = [(r["fc"], r["tone"], r["ncs_pk"], r["rssi_max"]) for r in wide
                            if r["ncs_pk"] >= 1500]
    fine = jl(os.path.join(TONE2, "fine", "results.jsonl"))
    S["fine"] = [(r["tone"], r["fc"], r["ncs_pk"], r["rssi_max"]) for r in fine]
    stm = p_records(os.path.join(PKT, "batch1_2412000_stm.txt"))
    cls = [classify(r) for r in stm]
    S["batch1_P_records"] = len(stm)
    S["batch1_valid"] = cls.count("valid")
    S["batch1_body_match_crc0"] = cls.count("body-match, CRC flag 0")
    S["batch1_other_fragments"] = cls.count("other fragment")
    S["batch1_valid_rssi"] = (min(r["rssi"] for r, c in zip(stm, cls) if c == "valid"),
                              max(r["rssi"] for r, c in zip(stm, cls) if c == "valid"))
    esp = [l for l in open(os.path.join(PKT, "batch1_2412000_esp.txt")) if l.startswith("K,pkt")]
    S["batch1_pkt_sent"] = len(esp)
    on = [int(l.split("on_us=")[1].split(",")[0]) for l in esp]
    S["batch1_on_us_range"] = (min(on), max(on))
    ctl = p_records(os.path.join(PKT, "control_e8_2421032.txt"))
    S["e8_control_P_records"] = len(ctl)
    S["e8_control_crc_ok"] = sum(r["crc"] for r in ctl)
    S["e8_control_valid_len18_prefix"] = sum(1 for r in ctl if r["crc"] and r["hex"].startswith("1142B200"))
    for nm in ("source_off_2412000", "source_off_2421032", "source_off_recheck_2412000"):
        p = p_records(os.path.join(PKT, nm + ".txt"))
        S[nm] = (len(p), sum(r["crc"] for r in p))
    return S


def print_summary(S):
    for k, v in S.items():
        print(f"{k}: {v}")


def style(plt):
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                         "axes.grid": True, "grid.alpha": 0.25, "figure.dpi": 100,
                         "svg.fonttype": "none"})


def save(fig, name):
    out = OUT or os.path.join(EXP, FIG[name], "figures")
    os.makedirs(out, exist_ok=True)
    for ext in ("svg", "png"):
        fig.savefig(os.path.join(out, f"{name}.{ext}"), dpi=160, bbox_inches="tight")


def fig_tone_scan(plt):
    wide = jl(os.path.join(TONE2, "scan-wide", "results.jsonl"))
    # scan2.py order: row 0 = reference (tone 0), rows 1..28 = stage A (bw 812), rest = stage B (bw 102)
    stageA, stageB = wide[1:29], wide[29:]
    fig, ax = plt.subplots(1, 3, figsize=(13, 3.9), gridspec_kw={"width_ratios": [1.5, 1, 1]})
    col = {16: "#d95f02", -16: "#1b7fb5"}
    a = ax[0]
    for t in (16, -16):
        rs = sorted([r for r in stageA if r["tone"] == t], key=lambda r: r["fc"])
        a.plot([(r["fc"] - 2412000) / 1000 for r in rs], [max(r["ncs_pk"], 1) for r in rs], "o-", ms=4,
               color=col[t], label=f"tone {t:+d}")
    a.plot([0], [wide[0]["ncs_pk"]], "k*", ms=11, label="tone 0 reference (centre)")
    a.set_yscale("log")
    a.set_xlabel("receiver centre minus 2412.000 MHz (MHz)")
    a.set_ylabel("peak carrier-sense windows (ncs)")
    a.set_title("A. coarse: 0.5 MHz steps, bw 812 kHz", fontsize=10)
    a.legend(fontsize=8, loc="upper left")
    for k, (t, ttl) in enumerate(((16, "B. +16 zoom, bw 102 kHz"), (-16, "C. -16 zoom, bw 102 kHz")), 1):
        b = ax[k]
        rs = sorted([r for r in stageB if r["tone"] == t], key=lambda r: r["fc"])
        hit = [r for r in rs if r["ncs_pk"] >= 1500]
        miss = [r for r in rs if r["ncs_pk"] < 1500]
        b.scatter([r["fc"] / 1000 for r in miss], [max(r["ncs_pk"], 1) for r in miss], color="0.55", s=18,
                  label="no response")
        b.scatter([r["fc"] / 1000 for r in hit], [r["ncs_pk"] for r in hit], color=col[t], s=30,
                  label="response (ncs ≥ 1500)")
        b.set_yscale("log")
        b.set_xlabel("receiver centre (MHz)")
        b.set_title(ttl, fontsize=10)
        b.legend(fontsize=8, loc="center left")
    fig.suptitle("Tone scan: ±16-step tones, 150 ms, power 127, AGC 203/66 "
                 "(raw: results/tone/scan-wide/results.jsonl)", fontsize=10)
    fig.tight_layout()
    save(fig, "tone-scan")
    plt.close(fig)


def fig_null_trap(plt):
    fig, ax = plt.subplots(1, 3, figsize=(13, 3.6), gridspec_kw={"width_ratios": [1.3, 1.1, 1.1]})
    rn = retry_null()
    a = ax[0]
    names = [n.replace("tone_", "").replace("alt_", "alt ") for n, _, _ in rn]
    a.bar(range(len(rn)), [m for _, m, _ in rn], color="0.5")
    a.set_xticks(range(len(rn)))
    a.set_xticklabels(names, rotation=90, fontsize=7)
    a.set_ylabel("max ncs in any 100 ms window")
    a.set_ylim(0, 10)
    a.set_title("A. first attempt: pwr 32, AGC 251/64\n12 keyings, none seen (one stray ncs=1)", fontsize=9)
    for idx, (ttl, path) in enumerate((("B. source off, bw 812 kHz, AGC 203/66", os.path.join("rerun2", "control_source_off_2412000.txt")),
                                       ("C. source off, bw 102 kHz, AGC 203/66", os.path.join("rerun3", "control_bw102.txt"))), 1):
        n = control_ncs(os.path.join(TONE2, path))
        b = ax[idx]
        b.bar(range(len(n)), n, color="#c0392b" if idx == 1 else "#2e8b57")
        if idx == 1:
            b.set_yscale("symlog", linthresh=10)
        else:
            b.set_ylim(0, 150)
            b.set_yscale("symlog", linthresh=10)
        b.set_xlabel("100 ms window")
        b.set_ylabel("ncs")
        cs = sum(1 for x in n if x > 0)
        b.set_title(f"{ttl}\n{cs}/{len(n)} windows carrier-sense with nothing keyed", fontsize=9)
    fig.tight_layout()
    save(fig, "null-and-trap")
    plt.close(fig)


def fig_packets(plt):
    stm = p_records(os.path.join(PKT, "batch1_2412000_stm.txt"))
    ctl = p_records(os.path.join(PKT, "control_e8_2421032.txt"))
    fig, ax = plt.subplots(1, 2, figsize=(11, 3.8), gridspec_kw={"width_ratios": [1.2, 1]})
    a = ax[0]
    cats = ["valid", "body-match, CRC flag 0", "other fragment"]
    colors = ["#2e8b57", "#e6a817", "0.6"]
    cs = [classify(r) for r in stm]
    vals = [cs.count(c) for c in cats]
    a.barh(["ESP32, 10 PKT\n(2412.000 MHz)"], [vals[0]], color=colors[0], label=f"CRC-valid, body = vector ({vals[0]})")
    a.barh(["ESP32, 10 PKT\n(2412.000 MHz)"], [vals[1]], left=[vals[0]], color=colors[1], label=f"body matches, CRC flag 0 ({vals[1]})")
    a.barh(["ESP32, 10 PKT\n(2412.000 MHz)"], [vals[2]], left=[vals[0] + vals[1]], color=colors[2], label=f"other/noise fragments ({vals[2]})")
    ok = sum(r["crc"] for r in ctl)
    a.barh(["Real E8\n(2421.032 MHz, 20 s)"], [ok], color=colors[0])
    a.barh(["Real E8\n(2421.032 MHz, 20 s)"], [len(ctl) - ok], left=[ok], color="0.6")
    a.text(ok / 2, 1, f"{ok} CRC-valid", ha="center", va="center", color="w", fontsize=9)
    a.text(ok + (len(ctl) - ok) / 2, 1, f"{len(ctl) - ok} other P records", ha="center", va="center", fontsize=9)
    a.set_xlabel("rxdiag pkt P records")
    a.legend(fontsize=7.5, loc="upper center", bbox_to_anchor=(0.5, -0.2))
    a.set_title("A. what the CC2500 reported", fontsize=10)
    b = ax[1]
    labels, tot, good = [], [], []
    for nm, lab in (("source_off_2412000", "source off\n2412.000"), ("source_off_recheck_2412000", "source off\nrecheck"),
                    ("source_off_2421032", "source off\n2421.032")):
        p = p_records(os.path.join(PKT, nm + ".txt"))
        labels.append(lab); tot.append(len(p)); good.append(sum(r["crc"] for r in p))
    labels += ["ESP32\nbatch 1", "real E8\ncontrol"]
    tot += [len(stm), len(ctl)]
    good += [sum(r["crc"] for r in stm), sum(r["crc"] for r in ctl)]
    x = range(len(labels))
    b.bar([i - 0.2 for i in x], tot, 0.4, color="0.6", label="all P records")
    b.bar([i + 0.2 for i in x], good, 0.4, color="#2e8b57", label="crc_ok = 1")
    for i in x:
        b.text(i + 0.2, good[i] + 1, str(good[i]), ha="center", fontsize=8)
        b.text(i - 0.2, tot[i] + 1, str(tot[i]), ha="center", fontsize=8)
    b.set_xticks(list(x)); b.set_xticklabels(labels, fontsize=7.5)
    b.set_ylabel("P records")
    b.set_title("B. controls: noise never sets CRC-valid", fontsize=10)
    b.legend(fontsize=8)
    fig.tight_layout()
    save(fig, "packet-outcome")
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", action="store_true", help="print derived numbers only")
    a = ap.parse_args()
    S = summary()
    print_summary(S)
    if a.summary:
        return
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        sys.exit("matplotlib is required: pip install matplotlib")
    style(plt)
    fig_tone_scan(plt)
    fig_null_trap(plt)
    fig_packets(plt)
    print("wrote", OUT or ", ".join(sorted({os.path.join(EXP, d, "figures") for d in FIG.values()})))


if __name__ == "__main__":
    main()
