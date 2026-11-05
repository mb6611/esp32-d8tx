# SPDX-License-Identifier: GPL-3.0-or-later
"""Power spectra: host PSD and on-chip SPC1 frame parsing (docs/spectrum.md)."""
from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

import numpy as np

_HDR = struct.Struct("<4sIQIHBBHBB")  # 28 bytes
assert _HDR.size == 28

Q15_FULL_SCALE_DB = 20 * np.log10(32768.0)


def psd(iq: np.ndarray, fs: float, nfft: int = 1024):
    """Welch-style averaged Hann PSD. Returns (freqs_hz, power_db), fftshifted.

    power_db is dB relative to full scale 1.0 per bin (uncalibrated, not dBm).
    """
    iq = np.asarray(iq, dtype=np.complex64)
    if iq.size < nfft:
        iq = np.pad(iq, (0, nfft - iq.size))
    w = np.hanning(nfft).astype(np.float32)
    nseg = iq.size // nfft
    segs = iq[: nseg * nfft].reshape(nseg, nfft) * w
    spec = np.abs(np.fft.fft(segs, axis=1)) ** 2
    p = spec.mean(axis=0) / (w.sum() ** 2)
    p = np.fft.fftshift(p)
    freqs = np.fft.fftshift(np.fft.fftfreq(nfft, 1.0 / fs))
    return freqs, 10 * np.log10(p + 1e-20)


class SpecError(ValueError):
    pass


@dataclass
class SpecFrame:
    seq: int
    first_sample: int
    span: int
    ffts: int
    flags: int
    gain: int
    drops: int
    log2_bins: int
    mult: int
    codes: np.ndarray  # uint8, natural FFT order

    @property
    def bins(self) -> int:
        return 1 << self.log2_bins

    @property
    def max_detector(self) -> bool:
        return bool(self.flags & 1)

    @property
    def skipped(self) -> bool:
        return bool(self.flags & 2)

    @property
    def output_drop(self) -> bool:
        return bool(self.flags & 4)

    @property
    def snapshot_gaps(self) -> bool:
        return bool(self.flags & 8)

    def db(self) -> np.ndarray:
        """20*log10(power) in the normalized Q15 FFT domain (code / multiplier).
        Zero codes are a quantized floor. Window normalization is not applied."""
        return self.codes.astype(np.float32) / self.mult

    def dbfs_approx(self) -> np.ndarray:
        """Rough dBFS: db() minus Q15 full scale. Uncalibrated."""
        return self.db() - Q15_FULL_SCALE_DB


def frame_size(log2_bins: int) -> int:
    return 28 + (1 << log2_bins) + 4


def parse_spc1(frame: bytes) -> SpecFrame:
    if len(frame) < 32:
        raise SpecError("frame too short")
    magic, seq, first, span, ffts, flags, gain, drops, lg, mult = _HDR.unpack_from(frame)
    if magic != b"SPC1":
        raise SpecError("bad magic")
    if not 1 <= lg <= 15:
        raise SpecError("bad log2 bins")
    n = 1 << lg
    if len(frame) != 28 + n + 4:
        raise SpecError(f"length {len(frame)} != {28 + n + 4}")
    (crc,) = struct.unpack_from("<I", frame, 28 + n)
    if zlib.crc32(frame[: 28 + n]) & 0xFFFFFFFF != crc:
        raise SpecError("CRC mismatch")
    codes = np.frombuffer(frame, dtype=np.uint8, count=n, offset=28).copy()
    return SpecFrame(seq, first, span, ffts, flags, gain, drops, lg, mult, codes)


_END_FIELDS = (
    "status detail units pairs elapsed_us late_max work_max_cycles "
    "frames drops abandoned ffts stopped_by_host"
).split()


def parse_specend(line: str | bytes) -> dict:
    if isinstance(line, bytes):
        line = line.decode("ascii", "replace")
    parts = line.split()
    if not parts or parts[0] != "SPECEND" or len(parts) != 1 + len(_END_FIELDS):
        raise SpecError(f"bad SPECEND line: {line!r}")
    try:
        return {k: int(v) for k, v in zip(_END_FIELDS, parts[1:])}
    except ValueError as e:
        raise SpecError(f"bad SPECEND field: {line!r}") from e
