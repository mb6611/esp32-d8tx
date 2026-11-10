#!/usr/bin/env python3
"""Run every experiment against the txeng firmware; write results.csv and results.log.

Usage: python run.py [--port /dev/cu.usbserial-0001] [--only A,B,...]
results.csv is long-format: exp, case, key, value (one measured quantity per row).
"""
import argparse
import csv
import sys
import time

import numpy as np

from dev import Dev, Hang
from iq import line_db, unpack

TXE, DC0, DC8, DCC, DBC = 0x60033D98, 0x60033DC0, 0x60033DC8, 0x60033DCC, 0x60033DBC
RATE = 1 << 15
RUN, HOLD, DONE = 1 << 31, 1 << 19, 1 << 18
F_ONEWRITE, F_NOCLR, F_KEY, F_CLR18, F_CAP, F_RXON, F_BYTES = 1, 2, 4, 8, 16, 32, 64
CPU_HZ = 240e6
SENT = 0xA55AA55A
rows = []


def rec(exp, case, **kv):
    for k, v in kv.items():
        rows.append((exp, case, k, v))
        print(f"  {exp} {case} {k}={v}", flush=True)


def us(c):
    return round(c / CPU_HZ * 1e6, 4)


def exp_A(d):
    """Timing: time from run write to done vs count, both rate settings, two grant modes."""
    fits = {}
    d.cmd("F 1 16384 200 256")
    counts = [1, 3, 15, 63, 255, 511, 1023, 2047, 4095, 8191, 12287, 16382, 16383]
    for gm in (0, 3):
        for rate in (0, 1):
            xs, ys = [], []
            for c in counts:
                e = d.tx(c | (RATE if rate else 0), reps=64, tmo=1000, gmode=gm)
                case = f"gmode{gm}_rate{rate}_count{c}"
                rec("A", case, ndone=e["ndone"], reps=64, cyc_min=e["cyc_min"], cyc_mean=e["cyc_mean"],
                    cyc_max=e["cyc_max"], us_min=us(e["cyc_min"]), per_mean_cyc=e["per_mean"],
                    ctrl_at_done=hex(e["ctrl_at_done"]), ctrl_after_clr=hex(e["ctrl_after_clr"]))
                if e["ndone"] == 64 and c >= 255:
                    xs.append(c + 1)
                    ys.append(e["cyc_min"])
            slope, icpt = np.polyfit(xs, ys, 1)
            resid = np.max(np.abs(np.polyval([slope, icpt], xs) - ys))
            fits[(gm, rate)] = (slope, icpt)
            rec("A", f"gmode{gm}_rate{rate}_fit", cyc_per_sample=round(slope, 5),
                msps=round(CPU_HZ / slope / 1e6, 4), intercept_cyc=round(icpt, 1),
                intercept_us=us(icpt), max_resid_cyc=round(resid, 1), points=len(xs))
    # count 0 (= 16384 if N = count+1 wrapped)
    for rate in (0, 1):
        e = d.tx(0 | (RATE if rate else 0), reps=2, tmo=2000, gmode=3)
        rec("A", f"rate{rate}_count0", ndone=e["ndone"], ctrl_at_timeout=hex(e["ctrl_at_done"]))
    return fits


def exp_B(d):
    """Control bits: hold (19), 27:20, one-write vs two-write, re-arm without clear."""
    c = 1023 | RATE
    e = d.tx(c | HOLD, reps=2, tmo=2000, gmode=3)
    rec("B", "hold_set_with_run", ndone=e["ndone"], ctrl_at_timeout=hex(e["ctrl_at_done"]))
    # hold then release with run kept set
    d.wr(TXE, c)
    d.wr(TXE, c | HOLD | RUN)
    time.sleep(0.01)
    held = d.rd(TXE)
    d.wr(TXE, c | RUN)  # drop hold, keep run
    time.sleep(0.01)
    released = d.rd(TXE)
    d.wr(TXE, 0)
    rec("B", "hold_then_release", while_held=hex(held), after_release=hex(released),
        done_while_held=int(bool(held & DONE)), done_after_release=int(bool(released & DONE)))
    # set hold while running a long buffer: does it pause? (done time vs. plain)
    for f in (0xFF, 0x01, 0x80):
        e = d.tx(c | (f << 20), reps=16, gmode=3)
        rec("B", f"bits27_20={f:#x}", ndone=e["ndone"], cyc_mean=e["cyc_mean"], ctrl_at_done=hex(e["ctrl_at_done"]))
    for fl, name in ((0, "two_writes"), (F_ONEWRITE, "one_write"), (F_NOCLR, "noclr_two_writes"),
                     (F_ONEWRITE | F_NOCLR, "noclr_one_write_rearm")):
        e = d.tx(c, reps=32, flags=fl, gmode=3)
        rec("B", name, ndone=e["ndone"], cyc_min=e["cyc_min"], cyc_mean=e["cyc_mean"], cyc_max=e["cyc_max"],
            ctrl_after=hex(e["ctrl_after_clr"]))
    # does writing 0 (run cleared) mid-playback stop it? run long buffer, stop via host after a write
    d.wr(TXE, 0x3FFF)
    d.wr(TXE, 0x3FFF | RUN)
    v1 = d.rd(TXE)
    time.sleep(0.002)
    v2 = d.rd(TXE)
    d.wr(TXE, 0)
    rec("B", "run_from_host_16384_rate0", read_soon=hex(v1), read_after_2ms=hex(v2))


def exp_C(d, fits):
    """Retrigger gap: start-to-start period of back-to-back runs (poll done, clear, re-run)."""
    for rate in (0, 1):
        slope, icpt = fits[(3, rate)]
        for c in (1023, 16383):
            e = d.tx(c | (RATE if rate else 0), reps=64, tmo=1000, gmode=3)
            ideal = slope * (c + 1)
            rec("C", f"rate{rate}_count{c}", per_mean_cyc=e["per_mean"], per_min_cyc=e["per_min"],
                play_cyc=round(ideal, 1), gap_min_us=us(e["per_min"] - ideal),
                gap_mean_us=us(e["per_mean"] - ideal), gap_min_samples=round((e["per_min"] - ideal) / slope, 1),
                start_to_done_overhead_us=us(e["cyc_min"] - ideal))


def pointer_region(d, txc, capc, flags=F_CAP | F_BYTES):
    """Fill a pattern, run the engine with a concurrent capture, return the address range the
    capture wrote (capture words have nonzero upper bits; pattern words do not)."""
    d.cmd("F 1 16384 200 256")
    d.cmd(f"C 0x{capc:x}")
    e = d.tx(txc, reps=1, tmo=1000, flags=flags, gmode=3)
    w = np.array(d.dump(0, 16384))
    idx = np.flatnonzero((w >> 20) != 0)
    return e, w, idx


def exp_D(d):
    """Memory: does the engine write? Does a capture follow the engine's address pointer?
    Does 0x60033dc0 (and dc8/dcc/dbc) move it?"""
    for gm in (0, 2, 3):
        d.cmd("F 2 0 0 0")
        e = d.tx(0x3FFF | RATE, reps=1, gmode=gm)
        w = np.array(d.dump(0, 16384))
        rec("D", f"engine_alone_sentinel_gmode{gm}", ndone=e["ndone"], words_changed=int((w != SENT).sum()))
    d.cmd("F 2 0 0 0")
    d.cmd("P 1000 2")
    w = np.array(d.dump(0, 16384))
    rec("D", "capture_alone_1000", words_changed=int((w != SENT).sum()),
        first=int(np.argmax(w != SENT)), last=int(16383 - np.argmax((w != SENT)[::-1])))
    for txc, capc in ((0x3FFF | RATE, 8000 | RATE), (0x3FFF | RATE, 2000 | RATE), (4095 | RATE, 8000 | RATE),
                      (1023 | RATE, 8000 | RATE), (4095, 8000 | RATE), (0x3FFF, 8000 | RATE), (4095 | RATE, 8000)):
        e, w, idx = pointer_region(d, txc, capc)
        rec("D", f"follow_tx{txc:#x}_cap{capc:#x}", tx_done=e["ndone"], cap_status=e["cap_status"],
            written=len(idx), first=int(idx[0]) if len(idx) else -1, last=int(idx[-1]) if len(idx) else -1,
            contiguous=int(len(idx) > 0 and idx[-1] - idx[0] + 1 == len(idx)))
    # capture without the engine but with the engine register holding a count (not running)
    d.wr(TXE, 4095 | RATE)
    d.cmd("F 1 16384 200 256")
    d.cmd("P 8000 2")
    d.wr(TXE, 0)
    w = np.array(d.dump(0, 16384))
    idx = np.flatnonzero(w != SENT)
    rec("D", "capture_alone_8000_txe_loaded_not_running", written=len(idx), last=int(idx[-1]))
    # candidate config registers: effect on timing and on the pointer range
    for reg, vals in ((DC0, (0x1, 0x100, 0x1000, 0x3FFF, 0x8000, 0x10000, 0x1000000, 0x3FFF0000, 0x80000000,
                             0xBFFFBFFF)),
                      (DC8, (0x1, 0x1000, 0x3FFEC000)), (DCC, (0x1, 0x1000, 0x8000, 0xC0000000)), (DBC, (1, 0x3F))):
        orig = d.rd(reg)
        for v in vals:
            try:
                rb = d.wr(reg, v)
                e = d.tx(1023 | RATE, reps=8, gmode=3)
                e2, w, idx = pointer_region(d, 4095 | RATE, 8000 | RATE)
                rec("D", f"reg{reg:#x}={v:#x}", readback=hex(rb), ndone=e["ndone"], cyc_mean_1024r1=e["cyc_mean"],
                    follow_written=len(idx), follow_first=int(idx[0]) if len(idx) else -1,
                    follow_last=int(idx[-1]) if len(idx) else -1, dc0_at_done=hex(e["snaps"]["done"][9]))
            except Hang:
                rec("D", f"reg{reg:#x}={v:#x}", status="HANG")
            finally:
                try:
                    d.wr(reg, orig)
                except Hang:
                    pass


def exp_E(d):
    """Self-loopback attempts (keyed TX, bursts < 1 ms, >= 0.3 s apart)."""
    gm = int(d.cmd("K 0")[0].split("gain_max=")[1])
    d.cmd(f"C 0x{8000 | RATE:x}")
    # E1: engine playback + concurrent capture (capture lands at the engine's pointer).
    for km in (0, 1):
        d.cmd(f"K {km}")
        for cyc in (256, -512):
            f = cyc / 16384 * 80e6
            for name, fill, fl, pwr in (("unkeyed_pat", f"F 1 16384 200 {cyc}", F_CAP | F_BYTES, -1),
                                        ("key_clr18_pat", f"F 1 16384 200 {cyc}",
                                         F_KEY | F_CLR18 | F_CAP | F_RXON | F_BYTES, 127),
                                        ("key_clr18_zero", "F 0 16384 0 0",
                                         F_KEY | F_CLR18 | F_CAP | F_RXON | F_BYTES, 127),
                                        ("key_tone_pat", f"F 1 16384 200 {cyc}",
                                         F_KEY | F_CAP | F_RXON | F_BYTES, 127),
                                        ("key_clr18_pat_pwr0", f"F 1 16384 200 {cyc}",
                                         F_KEY | F_CLR18 | F_CAP | F_RXON | F_BYTES, 0)):
                d.cmd(fill)
                e = d.tx(0x3FFF | RATE, reps=1, tmo=400, flags=fl, gmode=3, pwr=pwr)
                w = np.array(d.dump(0, 16384))
                idx = np.flatnonzero((w >> 20) != 0)
                x = unpack(w[idx[0]:idx[-1] + 1]).conj()
                r = line_db(x, 80e6, f)
                rec("E1", f"km{km}_{name}_f{f / 1e6:+.2f}MHz", rms=round(r["rms"], 1), line_db=round(r["pos"], 1),
                    mirror_db=round(r["neg"], 1), dc_db=round(r["dc"], 1), peak_mhz=round(r["peak_f"] / 1e6, 3),
                    peak_db=round(r["peak_db"], 1), keyed_us=e["keyed_us"], tx_done=e["ndone"])
                time.sleep(0.3)
    # E2: positive control: CPU toggles the tone generator at 250 kHz during a plain capture.
    for km in (0, 1, 2):
        for g in (-1, gm):
            d.cmd(f"K {km} {g}")
            for mode in (3, 0, 1, 2):
                out = d.cmd(f"M 8000 480 {mode} 127")[0].split(",")
                x = unpack(np.array(d.dump(0, 8000)))
                r = line_db(x, 40e6, 250e3)
                r3 = line_db(x, 40e6, 750e3)
                rec("E2", f"km{km}_gain{g}_mode{mode}", toggles=out[3], keyed_us=out[4], rms=round(r["rms"], 1),
                    dc_db=round(r["dc"], 1), l250k_db=round(max(r["pos"], r["neg"]), 1),
                    l750k_db=round(max(r3["pos"], r3["neg"]), 1), peak_khz=round(r["peak_f"] / 1e3),
                    peak_db=round(r["peak_db"], 1))
                time.sleep(0.3)
    d.cmd("K 0")
    for k in range(3):
        d.cmd("P 8000 2")
        x = unpack(np.array(d.dump(0, 8000)))
        r = line_db(x, 40e6, 250e3)
        rec("E2", f"unkeyed_ambient_{k}", rms=round(r["rms"], 1), dc_db=round(r["dc"], 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/cu.usbserial-0001")
    ap.add_argument("--only", default="A,B,C,D,E")
    ap.add_argument("--csv", default="results.csv")
    ap.add_argument("--log", default="results.log")
    a = ap.parse_args()
    only = a.only.split(",")
    d = Dev(a.port, log=open(a.log, "w"))
    print(d.reset())
    print(d.cmd("P 256 2"))
    fits = None
    if "A" in only or "C" in only:
        fits = exp_A(d)
    if "B" in only:
        exp_B(d)
    if "C" in only:
        exp_C(d, fits)
    if "D" in only:
        exp_D(d)
    if "E" in only:
        exp_E(d)
    print(d.cmd("P 256 2"))
    with open(a.csv, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["exp", "case", "key", "value"])
        w.writerows(rows)
    print(f"rows={len(rows)} hangs={d.hangs}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
