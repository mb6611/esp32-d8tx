# SPDX-License-Identifier: GPL-3.0-or-later
"""Host CPU of the hop-follow segment decode, on recorded single-channel D8 captures.

A locked follower hands the decoder one channel segment per hop: from the retune
(LEAD_S = 1.15 ms before the predicted preamble) to the next retune, minus the
blanked transient. This rebuilds exactly those segments from 1-bit dec 64 mode 2
recordings of one channel (the tx comes round every 422.5 ms):
  1. find the packets once (wide search) and fit t = a + k * cycle over them;
  2. cut a follow-shaped segment at every k of the fit (whether or not the
     reference search decoded it), so misses count too;
  3. time HopFollower's per-segment decode over all segments and count CRC-ok.

Usage: cd host && .venv/bin/python ../docs/devkitv1/bench/hop-follow/decode_cpu.py /tmp/d8/*.sigmf-data
"""
import sys
import time

import numpy as np

from esp32sdr import d8
from esp32sdr.d8follow import HopFollower

FS = 250_000.0
CYCLE = 0.42250 * FS
HOP = int(round(CYCLE / 47))        # ~2247 samples
LEAD = int(round(HopFollower.LEAD_S * FS))
BLANK = 96                          # typical tag blank (72-120 seen)


def segments(path):
    iq = np.fromfile(path, np.complex64)
    ref = d8.StandardDecoder(FS)
    ts = []
    step = int(2 * CYCLE)
    for a in range(0, len(iq), step):
        for r in ref.decode(iq[a:a + step + 2000]):
            if r.packet.crc_ok:
                ts.append(a + r.t * FS)
    ts = np.unique(np.round(ts))
    if len(ts) < 3:
        return []
    k = np.round((ts - ts[0]) / CYCLE)
    P, a0 = np.polyfit(k, ts, 1)
    out = []
    for kk in range(int(np.ceil(-a0 / P)), int((len(iq) - a0) / P) + 1):
        s = int(round(a0 + kk * P)) - LEAD
        if s < 0 or s + HOP > len(iq):
            continue
        out.append(iq[s + BLANK:s + HOP])
    return out


def run(segs, follower_decode):
    ok = 0
    c = time.process_time()
    for x in segs:
        ok += sum(r.packet.crc_ok for r in follower_decode(x))
    return ok, time.process_time() - c


def main(paths):
    segs = []
    for p in paths:
        s = segments(p)
        print(f"{p}: {len(s)} segments")
        segs += s
    fol = HopFollower(type("C", (), {"start": lambda *a: None, "hold": lambda *a: None})())
    dec = getattr(fol, "decode_segment", None) or fol.dec.decode
    for rep in range(2):
        ok, cpu = run(segs, dec)
        print(f"rep {rep}: {len(segs)} segments, CRC-ok {ok} ({100 * ok / len(segs):.1f} %), "
              f"CPU {1e3 * cpu / len(segs):.3f} ms/segment = {cpu / (len(segs) * HOP / FS):.3f} s per stream s")


if __name__ == "__main__":
    main(sys.argv[1:])
