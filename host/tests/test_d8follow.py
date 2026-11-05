# SPDX-License-Identifier: GPL-3.0-or-later
"""HopFollower against a simulated hopping tx and a simulated firmware schedule."""
from dataclasses import dataclass

import numpy as np

from esp32sdr import d8
from esp32sdr.d8follow import HopFollower
from esp32sdr.hopfollow import FLAG_HOP_ON, FLAG_HOP_START, Segmenter

FS = 250_000.0
DEC = 64


@dataclass
class F:
    index: int
    iq: np.ndarray
    flags: int
    shift: int
    gain: int = 40
    seq: int = 0


class SimBoard:
    """Tx: packet m starts at t0 + m * ptx on slot (s0 + m) % n. Rx: firmware HS/HX semantics,
    commands take effect `delay` samples after the newest emitted sample."""

    def __init__(self, *, ptx_s, t0_s=0.05, s0=0, n=47, acq_slot=1, delay_s=0.03, amp=5.0, seed=1,
                 dead=()):
        self.rng = np.random.default_rng(seed)
        self.ptx, self.t0, self.s0, self.n = ptx_s * FS, t0_s * FS, s0, n
        self.delay = int(delay_s * FS)
        self.amp = amp
        self.dead = set(dead)       # tx hop numbers that are not received (fades)
        self.idx = 0
        self.slot, self.tagged = acq_slot, False
        self.sched = None           # (next hop sample, slot, period samples)
        self.pending = []           # (apply_at, line)
        self.waves = {}
        self.pend_tag = None
        self.sent = []

    # Commander's transport
    def write(self, b: bytes):
        for line in b.decode().splitlines():
            self.pending.append((self.idx + self.delay, line))
            self.sent.append(line)

    def _apply(self, line):
        p = line.split()
        if p[0] == "HS":
            nxt, slot, per = int(p[2]) / DEC, int(p[1]), int(p[3]) / 1000 / DEC
            while self.idx - nxt > per / 2:
                nxt += per
                slot = (slot + 1) % self.n
            self.sched = [nxt, slot, per]
        elif p[0] == "HX":
            self.sched = None
            self._hop(self.idx, int(p[1]))

    def _hop(self, k, slot):
        self.pend_tag = (k, slot)

    def _wave(self, m):
        if m not in self.waves:
            pkt = d8.build_packet(counter=0, extra=(m & 0xFF, 1), channels=(1500 + m % 500,) * 8)
            bits = d8.air_bits(pkt)
            sps = 1e6 / d8.BAUD
            ph = d8.gfsk_phase(bits, sps, 2 * d8.DEVIATION / d8.BAUD, t0=0.0, n=int((len(bits) + 1) * sps))
            x = np.exp(1j * (ph + self.rng.uniform(0, 2 * np.pi)))
            self.waves[m] = d8.esp32_chain(x, DEC)
        return self.waves[m]

    def frame(self, max_n=4096) -> F:
        while self.pending and self.pending[0][0] <= self.idx:
            self._apply(self.pending.pop(0)[1])
        start = self.idx
        flags = 0
        if self.pend_tag and self.pend_tag[0] <= start:
            self.slot = self.pend_tag[1]
            self.tagged = True
            self.pend_tag = None
            flags = FLAG_HOP_START | (13 << 4)
        n = max_n
        if self.sched:
            nxt = int(np.ceil(self.sched[0]))
            if nxt <= start:
                self.pend_tag = (start, self.sched[1])
                self.sched[0] += self.sched[2]
                self.sched[1] = (self.sched[1] + 1) % self.n
                return self.frame(max_n)
            n = min(n, nxt - start)
        if self.pending:
            n = max(1, min(n, self.pending[0][0] - start))
        y = (self.rng.standard_normal(n) + 1j * self.rng.standard_normal(n)) * 0.7
        m_lo = int(np.floor((start - self.t0) / self.ptx)) - 1
        for m in range(m_lo, m_lo + 3 + int(n // self.ptx)):
            if m < 0 or m in self.dead or (self.s0 + m) % self.n != self.slot:
                continue
            w = self._wave(m)
            a = int(round(self.t0 + m * self.ptx))
            lo, hi = max(a, start), min(a + len(w), start + n)
            if lo < hi:
                y[lo - start:hi - start] += self.amp * w[lo - a:hi - a]
        if flags & FLAG_HOP_START:
            y[:104] = (self.rng.standard_normal(min(104, n)) + 1j * self.rng.standard_normal(min(104, n)))
        self.idx += n
        if self.tagged:
            flags |= FLAG_HOP_ON
        return F(start, d8.quantize(y, 1), flags, self.slot if self.tagged else 0)


def run(board, seconds, period_s=0.42255 / 47):
    from esp32sdr.hopfollow import Commander
    fol = HopFollower(Commander(board), period_s=period_s)
    res = []
    while board.idx < seconds * FS:
        res += fol.feed(board.frame())
    return fol, res


def test_segmenter_splits_on_tags():
    sg = Segmenter()
    z = np.zeros(10, np.complex64)
    assert sg.feed(F(0, z, 0, 0)) == []
    assert sg.feed(F(10, z, FLAG_HOP_ON | FLAG_HOP_START | (2 << 4), 5)) != []
    out = sg.feed(F(20, z, FLAG_HOP_ON, 5)) + sg.feed(F(30, z, FLAG_HOP_ON | FLAG_HOP_START, 6))
    assert len(out) == 1 and out[0].slot == 5 and out[0].start == 10 and out[0].blank == 16 and len(out[0].iq) == 20


def test_follower_locks_tracks_and_decodes_every_slot():
    ptx = 0.42255 / 47 * (1 + 3e-4)   # tx period off the prior by 300 ppm
    b = SimBoard(ptx_s=ptx)
    fol, res = run(b, 4.0)
    st = fol.st
    assert st.first_lock_s is not None and st.first_lock_s < 0.1
    assert st.hops > 300
    assert st.slot_mismatch == 0 and st.counter_mismatch == 0
    assert st.ok_locked >= 0.97 * st.hops, (st.ok_locked, st.hops)
    assert abs(fol.P / FS - ptx) < 1e-6
    assert st.losses == 0


def test_follower_reacquires_after_a_fade():
    ptx = 0.42255 / 47
    b = SimBoard(ptx_s=ptx, dead=range(150, 200))   # 0.45 s with nothing received
    fol, res = run(b, 4.5)
    st = fol.st
    assert st.losses == 1
    assert len(st.reacq_s) == 1 and st.reacq_s[0] < 0.45 + 0.05
    assert fol.mode == "locked"
    assert st.ok_locked > 200


def test_follow_stats_has_per_slot_counts():
    from esp32sdr.d8follow import FollowRun, N_SLOTS
    f = FollowRun(None, 40).stats()["follow"]
    assert len(f["slot_ok"]) == len(f["slot_hops"]) == len(f["slot_mhz"]) == N_SLOTS
    assert abs(f["slot_mhz"][1] - 2421.032) < 0.001
