#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Retune during an IQS stream: transient length and stream integrity (receive only).

docs/devkitv1/hop-follow.md, step 1. Needs the default devkitv1 build (HOPTAB).
The board's 40 MHz crystal harmonic at 2400.000 MHz is the reference line: slot
0 centres the stream 50 kHz above it (line at -50 kHz), slot 1 is 10 MHz away
(no line). The schedule alternates them every PERIOD; the line's amplitude in
8-sample windows from each tagged segment start shows when the LO has arrived.

    .venv/bin/python tools/probe_hopstream.py [--seconds 5] [--gain 40] [--period-ms 9]
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from esp32sdr.device import Device  # noqa: E402
from esp32sdr.hopfollow import Commander, Segmenter, load_table, lo_khz  # noqa: E402
from esp32sdr.iqs import IqsSession, STOP_BYTE, plan_tune  # noqa: E402

DEC, BITS, MODE = 64, 1, 2
FS = 16e6 / DEC


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=5.0)
    ap.add_argument("--gain", type=int, default=40)
    ap.add_argument("--period-ms", type=float, default=9.0)
    ap.add_argument("--ref", type=float, default=2400.05, help="slot 0 centre MHz")
    ap.add_argument("--other", type=float, default=2410.05, help="slot 1 centre MHz")
    ap.add_argument("--port", default="/dev/cu.usbserial-0001")
    a = ap.parse_args()
    segs = []
    with Device.open(a.port) as d:
        d.command(f"GAIN MANUAL {a.gain}")
        load_table(d, [lo_khz(a.ref * 1e6), lo_khz(a.other * 1e6)])
        mhz, fofs = plan_tune(a.ref * 1e6, MODE)
        s = IqsSession(d, DEC, BITS, mhz, fofs, seconds=0, mode=MODE)
        cmd = Commander(d.t)
        sg = Segmenter()
        t0 = time.monotonic()
        started = stopping = False
        for iq, f in s.blocks():
            segs += sg.feed(f)
            if stopping:
                continue
            el = time.monotonic() - t0
            if not started and el > 0.3:
                cmd.start(0, (f.index + len(iq)) * DEC + 16_000_00, a.period_ms / 1e3)  # +100 ms
                started = True
            if el > a.seconds:
                d.t.write(STOP_BYTE)
                stopping = True
        segs += sg.flush()
        print("IQSEND", s.stats.end)
        st = s.stats
        print(f"frames {st.frames} samples {st.samples} gaps {st.gap_samples} in {st.gap_events} "
              f"bad_crc {st.bad_crc} resync {st.resync_bytes} short {st.short_frames}")
        print(d.command("HOPSTAT?").strip())
        d.command("GAIN HARDWARE")
        d.command("HOPCLR")
    hop = [g for g in segs if g.slot >= 0]
    print(f"segments {len(segs)} tagged {len(hop)}; slots seen {sorted(set(g.slot for g in hop))}")
    if len(hop) < 4:
        return 1
    starts = np.array([g.start for g in hop])
    dp = np.diff(starts)
    print(f"segment start spacing (samples): median {np.median(dp):.1f} min {dp.min()} max {dp.max()} "
          f"(expect {a.period_ms * 1e-3 * FS:.1f})")
    print(f"blank (samples) from tags: {sorted(set(g.blank for g in hop))}")
    ref = [g for g in hop[1:-1] if g.slot == 0]
    oth = [g for g in hop[1:-1] if g.slot == 1]
    n = min(len(g.iq) for g in ref + oth)
    # line frequency from the steady part of the slot-0 segments
    spec = sum(np.abs(np.fft.fft(g.iq[300:300 + 1024])) ** 2 for g in ref)
    fr = np.fft.fftfreq(1024, 1 / FS)
    k = int(np.argmax(spec))
    fline = fr[k]
    print(f"line at {fline / 1e3:+.1f} kHz, {10 * np.log10(spec[k] / np.median(spec)):.1f} dB over median bin")
    W = 8

    def prof(gs):
        m = []
        for g in gs:
            x = g.iq[:n] * np.exp(-2j * np.pi * fline * np.arange(n) / FS)
            m.append(np.abs(x[: n // W * W].reshape(-1, W).mean(1)))
        return np.median(np.array(m), 0)

    pr, po = prof(ref), prof(oth)
    steady = np.median(pr[40:])
    print(f"line amplitude (8-sample windows, median over {len(ref)} ref / {len(oth)} other segments); "
          f"steady {steady:.3f}, other-channel floor {np.median(po[40:]):.3f}")
    for j in range(0, 24):
        print(f"  samples {j * W:4d}-{j * W + W - 1:4d}  ({j * W / FS * 1e6:6.0f} us)  ref {pr[j]:.3f}  other {po[j]:.3f}")
    i90 = next((j for j in range(len(pr)) if pr[j] >= 0.9 * steady and all(pr[j:j + 4] >= 0.8 * steady)), None)
    if i90 is not None:
        print(f"ref line within 10% of steady from sample {i90 * W} ({i90 * W / FS * 1e6:.0f} us after the tag)")
    # old line must be gone in 'other' segments
    return 0


if __name__ == "__main__":
    sys.exit(main())
