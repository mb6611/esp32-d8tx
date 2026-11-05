# SPDX-License-Identifier: GPL-3.0-or-later
"""Hop-following receive helpers (firmware HOPTAB / in-stream HS HA HP HX).

Protocol and measurements: docs/devkitv1/hop-follow.md. Receive only.

While a hop table is loaded, an IQS run accepts in-stream lines (no replies);
an empty line stops it. Every retune tags the stream: the frame that starts a
channel segment has flag bit 2 set and flag bits 4..7 = samples to blank / 8;
while tagging is active every frame has flag bit 3 and its `shift` byte is the
channel slot.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .iqs import MODE2_IF_HZ

PAIR_HZ = 16_000_000                   # stream pair clock (16 MS/s ring)
FLAG_HOP_START = 0x04
FLAG_HOP_ON = 0x08

# FrSky D8 bind table of the tx (diff_all.txt frsky_spi_bind_hop_data, first 47)
D8_TABLE = [0, 57, 112, 167, 222, 21, 76, 131, 186, 241, 40, 95, 150, 205, 4, 59, 114, 169, 224, 23,
            78, 133, 188, 243, 42, 97, 152, 207, 6, 61, 116, 171, 226, 25, 80, 135, 190, 245, 44, 99,
            154, 209, 8, 63, 118, 173, 228]
D8_BASE_HZ = 2404.000e6
D8_STEP_HZ = 299.93e3
D8_PPM = (2421.032 - 2421.096) / 2421.096 * 1e6   # measured on this tx + board: about -26.4 ppm


def d8_channel_hz(n: int, ppm: float = D8_PPM) -> float:
    return (D8_BASE_HZ + n * D8_STEP_HZ) * (1 + ppm * 1e-6)


def lo_khz(center_hz: float, mode: int = 2) -> int:
    """LO (absolute kHz) that puts center_hz at 0 Hz of the stream."""
    return int(round(center_hz / 1e3)) - (MODE2_IF_HZ // 1000 if mode == 2 else 0)


def load_table(dev, khz: list[int], chunk: int = 10) -> None:
    """Send HOPCLR + HOPTAB lines; raises on any non-OK reply."""
    r = dev.command("HOPCLR")
    if r.strip() != "OK":
        raise RuntimeError(f"HOPCLR: {r!r}")
    for i in range(0, len(khz), chunk):
        r = dev.command("HOPTAB " + " ".join(str(v) for v in [i, *khz[i:i + chunk]]))
        if r.strip() != "OK":
            raise RuntimeError(f"HOPTAB: {r!r}")
    r = dev.command("HOPTAB?").split()
    if r != ["HOPTAB", str(len(khz))]:
        raise RuntimeError(f"HOPTAB? -> {r}")


def period_mp(period_s: float) -> int:
    """Hop period in milli-pairs for HS / HP."""
    return int(round(period_s * PAIR_HZ * 1000))


class Commander:
    """In-stream hop commands (fire and forget, newline terminated)."""

    def __init__(self, transport, log=None):
        self.t, self.log = transport, log

    def send(self, line: str) -> None:
        if self.log:
            self.log(line)
        self.t.write((line + "\n").encode())

    def start(self, slot: int, pair: int, period_s: float) -> None:
        self.send(f"HS {slot} {int(pair)} {period_mp(period_s)}")

    def shift(self, dpairs: int) -> None:
        if dpairs:
            self.send(f"HA {int(dpairs)}")

    def period(self, period_s: float) -> None:
        self.send(f"HP {period_mp(period_s)}")

    def hold(self, slot: int) -> None:
        self.send(f"HX {slot}")


@dataclass
class Segment:
    """Samples received on one channel slot, from one retune to the next."""
    slot: int            # -1 before the first retune
    start: int           # stream sample index of the retune (first sample of the segment)
    blank: int           # samples from `start` that are retune transient
    iq: np.ndarray       # complex64, from `start`


class Segmenter:
    """Splits the IQS frame sequence into channel segments using the hop tags."""

    def __init__(self):
        self.slot, self.start, self.blank = -1, None, 0
        self.parts: list[np.ndarray] = []
        self.next = None

    def feed(self, f) -> list[Segment]:
        out = []
        tagged = bool(f.flags & FLAG_HOP_ON)
        if (tagged and f.flags & FLAG_HOP_START) or (self.next is not None and f.index != self.next):
            out += self.flush()
            self.start = f.index
            self.slot = f.shift if tagged else -1
            self.blank = ((f.flags >> 4) & 15) * 8 if f.flags & FLAG_HOP_START else 0
        if self.start is None:
            self.start, self.slot = f.index, f.shift if tagged else -1
        self.parts.append(f.iq)
        self.next = f.index + len(f.iq)
        return out

    def flush(self) -> list[Segment]:
        if not self.parts:
            return []
        seg = Segment(self.slot, self.start, self.blank, np.concatenate(self.parts))
        self.parts = []
        self.start = None
        return [seg]
