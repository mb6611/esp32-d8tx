# SPDX-License-Identifier: GPL-3.0-or-later
"""Bench check for 1-bit IQS (docs/devkitv1/iq-stream-uart.md): run one IQS
stream, read the raw bytes, parse every IQS1 frame and any text lines
(IQSPROF from an -DIQS_PROF build, IQSEND), report loss and budget fields.

    .venv/bin/python tools/bench_iqs1bit.py --dec 64 --seconds 20 --freq 2440
"""
from __future__ import annotations

import argparse
import time

import numpy as np

from esp32sdr import iqs
from esp32sdr.device import Device


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/cu.usbserial-0001")
    ap.add_argument("--dec", type=int, default=64)
    ap.add_argument("--bits", type=int, default=1)
    ap.add_argument("--seconds", type=float, default=20.0)
    ap.add_argument("--freq", type=int, default=2440)
    ap.add_argument("--save", help="write decoded complex64 samples here (.npy)")
    a = ap.parse_args()
    with Device.open(a.port) as d:
        d.tune(a.freq)
        print(d.command("FOFS 0"))
        ms = int(a.seconds * 1000)
        reply = d.command(f"IQS {ms} {a.dec} {a.bits} 6")
        print("start:", reply)
        if not reply.startswith("IQS "):
            return 1
        buf = bytearray()
        t0 = time.monotonic()
        while b"IQSEND" not in buf and time.monotonic() - t0 < a.seconds + 15:
            try:
                buf += d.t.read_some(65536, 0.5)
            except TimeoutError:
                pass
        if b"IQSEND" in buf and not buf.endswith(b"\n"):
            try:
                buf += d.t.readline(1.0)
            except TimeoutError:
                pass
    pos, frames, samples, junk, bad = 0, [], 0, 0, 0
    lines: list[str] = []
    blocks = []
    while pos < len(buf):
        if buf[pos:pos + 4] == iqs.MAGIC and pos + iqs.HEADER <= len(buf):
            try:
                _, _, n, bits, *_ = iqs.parse_header(bytes(buf[pos:pos + iqs.HEADER]))
                L = iqs.frame_length(n, bits)
                f = iqs.parse_iqs1(bytes(buf[pos:pos + L]))
            except iqs.IqsError:
                bad += 1
                pos += 1
                continue
            frames.append(f)
            blocks.append(f.iq)
            pos += L
            continue
        if buf[pos:pos + 4] in (b"IQSE", b"IQSP"):
            e = buf.find(b"\n", pos)
            e = len(buf) if e < 0 else e + 1
            lines.append(buf[pos:e].decode("ascii", "replace").strip())
            pos = e
            continue
        junk += 1
        pos += 1
    gaps = gap_samples = 0
    for p, q in zip(frames, frames[1:]):
        if q.index != p.index + p.samples:
            gaps += 1
            gap_samples += q.index - (p.index + p.samples)
            if gaps <= 5:
                print(f"gap after seq {p.seq} (frame {p.seq} of {frames[-1].seq}): "
                      f"seq jumps to {q.seq}, index +{q.index - (p.index + p.samples)}")
    samples = sum(f.samples for f in frames)
    flags = sum(1 for f in frames if f.flags)
    print(f"bytes {len(buf)}  frames {len(frames)}  samples {samples}  bad_crc {bad}  junk {junk}")
    print(f"index gaps {gaps} ({gap_samples} samples)  flagged frames {flags}  "
          f"expected samples ~{a.seconds * 16e6 / a.dec:.0f}")
    if frames:
        print(f"first index {frames[0].index}  last end {frames[-1].index + frames[-1].samples}  "
              f"seq {frames[0].seq}..{frames[-1].seq}")
        iq = np.concatenate(blocks)
        print(f"I mean {iq.real.mean():+.3f}  Q mean {iq.imag.mean():+.3f}  "
              f"values {sorted(set(np.unique(iq.real)) | set(np.unique(iq.imag)))}")
        if a.save:
            np.save(a.save, iq)
    for ln in lines:
        print(ln)
        if ln.startswith("IQSEND"):
            print(iqs.parse_iqsend(ln))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
