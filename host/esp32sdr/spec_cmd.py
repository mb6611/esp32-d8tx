# SPDX-License-Identifier: GPL-3.0-or-later
"""On-chip snapshot spectra (`SPEC`, docs/spectrum.md) driven through a Device.

Kept outside device.py: `spectrum(dev, ...)` sends `SPEC`, reads SPC1 frames
(skipping optional SPS1 statistics) until `SPECEND`, and sends the stop byte
when it ends a run early.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .protocol import DeviceError, TransferError, check_err
from .samples import RATES
from .spectrum import SpecError, SpecFrame, parse_spc1, parse_specend

STOP_BYTE = b"\n"  # any byte stops a run; the firmware discards up to the newline
DETECTORS = {"mean": 0, "max": 1}


@dataclass
class SpecRun:
    bins: int
    fs: int
    mhz: int
    frames: list[SpecFrame] = field(default_factory=list)
    end: dict = field(default_factory=dict)

    @property
    def ffts(self) -> int:
        return sum(f.ffts for f in self.frames)

    def average_db(self) -> np.ndarray:
        """Power per bin in dB (Q15 FFT domain), natural FFT order.

        Mean detector: FFT-count-weighted mean of linear power across frames.
        Max detector: per-bin maximum."""
        if not self.frames:
            raise SpecError("no spectrum frames")
        db = np.stack([f.db() for f in self.frames]).astype(np.float64)
        if all(f.max_detector for f in self.frames):
            return db.max(axis=0)
        w = np.array([max(f.ffts, 1) for f in self.frames], dtype=np.float64)
        lin = (10 ** (db / 10) * w[:, None]).sum(axis=0) / w.sum()
        return 10 * np.log10(lin + 1e-30)

    def rf_axis_hz(self) -> np.ndarray:
        """RF frequency of each natural-order bin.

        The firmware FFTs the raw (I, -Q) words, i.e. the conjugate of standard
        I/Q, so baseband bin +f sits at LO - f (see tools/s3_ring.py)."""
        f_bb = np.fft.fftfreq(self.bins, 1.0 / self.fs)
        return self.mhz * 1e6 - f_bb

    def sorted_db(self) -> tuple[np.ndarray, np.ndarray]:
        """(rf_hz ascending, power_db) for plotting and CSV."""
        f = self.rf_axis_hz()
        p = self.average_db()
        order = np.argsort(f)
        return f[order], p[order]


def rate_code_for(fs_hz: int) -> int:
    for code, hz in RATES.items():
        if hz == fs_hz:
            return code
    raise ValueError(f"unknown sample rate {fs_hz}")


def spectrum(dev, bins: int = 1024, rate_code: int = 1, ms: int = 300, *,
             detector: int = 0, max_frames: int | None = None) -> SpecRun:
    """Run one SPEC snapshot sweep and return its frames and end report.

    ms=0 runs until stopped and therefore needs max_frames. When max_frames
    is reached before the firmware ends the run, the stop byte is sent and the
    remaining frames are drained up to SPECEND.
    Raises DeviceError for ERR replies, TransferError (after resyncing) when
    framing or a CRC is lost, ValueError for bad arguments.
    """
    if bins < 256 or bins > 2048 or bins & (bins - 1):
        raise ValueError("bins must be a power of two in 256..2048")
    if rate_code not in RATES:
        raise ValueError(f"unknown rate code {rate_code}")
    if detector not in (0, 1):
        raise ValueError("detector must be 0 (mean) or 1 (max)")
    if ms < 0 or (ms == 0 and not max_frames):
        raise ValueError("ms=0 (until stopped) needs max_frames")

    t = dev.t
    cmd = f"SPEC {ms} 1 1 {detector} {rate_code} {bins}"
    reply = dev.command(cmd)
    check_err(reply)
    p = reply.split()
    if len(p) != 5 or p[0] != "SPEC" or int(p[1]) != bins:
        raise dev._resync_after(f"unexpected SPEC start: {reply!r}")
    run = SpecRun(bins=bins, fs=int(p[2]), mhz=int(p[4]))
    timeout = dev.data_timeout + ms / 1000.0
    stopped = False
    try:
        while True:
            magic = t.read_exact(4, timeout)
            if magic == b"SPEC":
                run.end = parse_specend(b"SPEC" + t.readline(timeout))
                break
            if magic == b"SPS1":
                t.read_exact(36, timeout)
                continue
            if magic != b"SPC1":
                raise SpecError(f"lost framing: {magic!r}")
            run.frames.append(parse_spc1(magic + t.read_exact(bins + 28, timeout)))
            if max_frames and not stopped and len(run.frames) >= max_frames:
                t.write(STOP_BYTE)
                stopped = True
    except (TimeoutError, SpecError) as e:
        raise dev._resync_after(f"spectrum transfer failed: {e}") from e
    if run.end.get("status", 0) != 0:
        raise DeviceError(f"SPECEND status {run.end['status']}")
    if not run.frames:
        raise TransferError("SPEC returned no frames")
    return run
