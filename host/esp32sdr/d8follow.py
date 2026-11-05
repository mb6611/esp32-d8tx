# SPDX-License-Identifier: GPL-3.0-or-later
"""Hop-following FrSky D8 receive (receive only): `esp32sdr d8follow`, `d8live --follow`.

The firmware owns the hop timing (hop_follow.h): it retunes on the stream's own
sample clock and tags each channel segment. This side
  acquire  holds one channel (ACQ_SLOT) and searches it continuously until a
           CRC-valid packet from the tx arrives (at most one 47-hop cycle);
  locked   schedules hops (`HS`) so each retune lands LEAD_S before the next
           predicted preamble, decodes each tagged segment on its own, fits
           packet time = a + m * P over the recent packets (m = hop number) and
           re-sends the schedule when the fit moves it by more than RESYNC_S;
  lost     no CRC-valid packet for LOST_HOPS hops: back to acquire.
Design and measurements: docs/devkitv1/hop-follow.md.
"""
from __future__ import annotations

import math
import signal
import threading
import time
from collections import deque
from dataclasses import dataclass, field

import numpy as np

from . import d8
from .d8_live import FS, DEC, BITS, MODE, LiveDecoder, packet_msg
from .hopfollow import (D8_TABLE, FLAG_HOP_ON, Commander, Segmenter, d8_channel_hz, load_table,
                        lo_khz)
from .iqs import STOP_BYTE, IqsSession, plan_tune

N_SLOTS = len(D8_TABLE)
ACQ_SLOT = 1                       # table[1] = channel 57 = 2421.032 MHz (measured)
PERIOD_S = 0.42255 / 47            # prior hop period (refined by the fit)


@dataclass
class FollowStats:
    hops: int = 0              # channel segments decoded while locked
    ok: int = 0                # CRC-valid packets (all states)
    ok_locked: int = 0         # ... in locked segments
    bad: int = 0               # sync found but CRC failed
    slot_mismatch: int = 0     # CRC-valid packet whose slot disagrees with the schedule
    counter_mismatch: int = 0  # packet counter disagrees with the hop number
    losses: int = 0
    reacq_s: list = field(default_factory=list)   # stream seconds from loss to lock
    first_lock_s: float | None = None
    schedules: int = 0         # HS commands sent
    decode_cpu_s: float = 0.0
    slot_hops: list = field(default_factory=lambda: [0] * N_SLOTS)
    slot_ok: list = field(default_factory=lambda: [0] * N_SLOTS)


class HopFollower:
    LEAD_S = 1.15e-3     # retune this long before the predicted preamble (gap is ~2.3 ms)
    AHEAD_S = 0.045      # first scheduled hop at least this far past the newest sample
    LOST_HOPS = 47       # hops without a CRC-valid packet before declaring the lock lost
    FIT_N = 141          # packets in the timing fit (~3 cycles when all decode)
    RESYNC_S = 15e-6     # re-send the schedule when the fit moved the next hops this much
    MIN_RESEND_S = 0.25  # ... but not more often than this (stream time)

    def __init__(self, cmd: Commander, *, fs: float = FS, n_slots: int = N_SLOTS, acq_slot: int = ACQ_SLOT,
                 period_s: float = PERIOD_S, tx_id: tuple | None = None, log=None):
        self.cmd, self.fs, self.n, self.acq_slot = cmd, fs, n_slots, acq_slot
        self.P0 = period_s * fs
        self.tx_id = tuple(tx_id) if tx_id else None
        self.log = log or (lambda *_: None)
        self.dec = d8.StandardDecoder(fs)
        self.seg_dec = d8.StandardDecoder(fs)   # locked segments: one packet each, first_ok
        self.seg = Segmenter()
        self.st = FollowStats()
        self.newest = 0
        self._acquire(None)

    # ---- state -------------------------------------------------------
    @property
    def mode(self) -> str:
        return self.state

    def _acquire(self, lost_at):
        self.state = "acquire"
        self.lost_at = lost_at
        self.ld = LiveDecoder(self.fs, decoder=self.dec)
        self.acq_next = None
        self.pts: deque[tuple[int, float, int]] = deque(maxlen=self.FIT_N)  # (m, t, counter)

    def _lock(self, t: float, counter: int):
        self.state = "locked"
        self.slot0, self.a, self.P = self.acq_slot, t, getattr(self, "P", self.P0)
        if not (0.995 * self.P0 < self.P < 1.005 * self.P0):
            self.P = self.P0
        self.pts.clear()
        self.pts.append((0, t, counter))
        self.last_ok_m = 0
        self.lock_at = t
        if self.st.first_lock_s is None:
            self.st.first_lock_s = t / self.fs
        if self.lost_at is not None:
            self.st.reacq_s.append((t - self.lost_at) / self.fs)
        self.first_hop = None
        self._schedule()

    def _schedule(self):
        lead = self.LEAD_S * self.fs
        m = math.ceil((self.newest + self.AHEAD_S * self.fs + lead - self.a) / self.P)
        t_hop = self.a + m * self.P - lead
        slot = (self.slot0 + m) % self.n
        self.cmd.start(slot, int(round(t_hop * DEC)), self.P / self.fs)
        self.fw = (m, self.a + m * self.P, self.P)   # firmware schedule: packet time at hop m, period
        self.fw_sent = self.newest
        if self.first_hop is None:
            self.first_hop = t_hop - 1
        self.st.schedules += 1

    def _fit(self):
        if len(self.pts) < 3:
            return
        m = np.array([p[0] for p in self.pts], float)
        t = np.array([p[1] for p in self.pts], float)
        if m[-1] - m[0] < 5:
            return
        P, a = np.polyfit(m, t, 1)
        if 0.995 * self.P0 < P < 1.005 * self.P0:
            self.P, self.a = float(P), float(a)

    # ---- input -------------------------------------------------------
    def feed(self, f) -> list[d8.Result]:
        """One IQS frame; returns new decode results (r.t absolute, seconds)."""
        self.newest = f.index + len(f.iq)
        segs = self.seg.feed(f)
        out: list[d8.Result] = []
        if self.state == "acquire":
            on_acq = not (f.flags & FLAG_HOP_ON) or f.shift == self.acq_slot
            if on_acq:
                if self.acq_next is not None and f.index != self.acq_next:
                    self.ld = LiveDecoder(self.fs, decoder=self.dec)
                self.acq_next = f.index + len(f.iq)
                c = time.process_time()
                res = self.ld.feed(f.index, f.iq)
                self.st.decode_cpu_s += time.process_time() - c
                for r in res:
                    out.append(r)
                    self._count(r)
                    if self._ours(r) and self.state == "acquire":
                        self._lock(r.t * self.fs, r.packet.raw[4])
            return out
        for s in segs:
            out += self._segment(s)
        if self.state == "locked":
            m_now = (self.newest - self.a) / self.P
            if m_now - self.last_ok_m > self.LOST_HOPS:
                self.st.losses += 1
                self.log(f"lock lost at {self.newest / self.fs:.2f} s (last packet hop {self.last_ok_m}, now {m_now:.0f})")
                self.cmd.hold(self.acq_slot)
                self._acquire(self.newest)
        return out

    def kick(self, dpairs: int) -> None:
        """Test aid: shift the firmware schedule off the tx (forces a loss and a re-acquire)."""
        if self.state == "locked":
            self.cmd.shift(dpairs)

    def _ours(self, r) -> bool:
        return r.packet.crc_ok and (self.tx_id is None or tuple(r.packet.tx_id) == self.tx_id)

    def _count(self, r):
        if r.packet.crc_ok:
            self.st.ok += 1
        else:
            self.st.bad += 1

    def decode_segment(self, x) -> list[d8.Result]:
        """Decode one locked channel segment (blank already cut; r.t relative to x[0]).
        A segment holds one packet, so the filter cutoffs are tried in order of past success
        and the first CRC-valid pass ends it (hop-follow.md, decoder CPU)."""
        return self.seg_dec.decode(x, first_ok=True)

    def _segment(self, s) -> list[d8.Result]:
        if s.slot < 0 or self.first_hop is None or s.start < self.first_hop:
            return []
        self.st.hops += 1
        if s.slot < len(self.st.slot_hops):
            self.st.slot_hops[s.slot] += 1
        x = s.iq[s.blank:]
        if len(x) < d8.AIR_BITS * self.fs / d8.BAUD:
            return []
        c = time.process_time()
        res = self.decode_segment(x)
        self.st.decode_cpu_s += time.process_time() - c
        out = []
        for r in res:
            r.t = (s.start + s.blank) / self.fs + r.t
            self._count(r)
            out.append(r)
            if not self._ours(r):
                continue
            t = r.t * self.fs
            m = int(round((t - self.a) / self.P))
            if (self.slot0 + m) % self.n != s.slot:
                self.st.slot_mismatch += 1
                continue
            self.st.ok_locked += 1
            if s.slot < len(self.st.slot_ok):
                self.st.slot_ok[s.slot] += 1
            m0, _, c0 = self.pts[0]
            if (c0 + (m - m0)) % 256 != r.packet.raw[4]:
                self.st.counter_mismatch += 1
            self.pts.append((m, t, r.packet.raw[4]))
            self.last_ok_m = max(self.last_ok_m, m)
            self._fit()
            m_fw, t_fw, P_fw = self.fw
            m_chk = m + 10
            drift = (self.a + m_chk * self.P) - (t_fw + (m_chk - m_fw) * P_fw)
            if abs(drift) > self.RESYNC_S * self.fs and self.newest - self.fw_sent > self.MIN_RESEND_S * self.fs:
                self._schedule()
        return out


def channel_table_khz(ppm: float | None = None) -> list[int]:
    kw = {} if ppm is None else {"ppm": ppm}
    return [lo_khz(d8_channel_hz(n, **kw), MODE) for n in D8_TABLE]


class FollowRun:
    """Device side: load the table, stream, follow; same publish/stats shape as d8_live.LiveRun."""

    def __init__(self, dev, gain: int | None, publish=None, log=print, *, ppm: float | None = None,
                 tx_id: tuple | None = (0x42, 0xB2), acq_slot: int = ACQ_SLOT):
        self.dev, self.gain, self.publish, self.log = dev, gain, publish or (lambda m: None), log
        self.ppm, self.tx_id, self.acq_slot = ppm, tx_id, acq_slot
        khz = channel_table_khz(ppm)
        self.center = (khz[acq_slot] * 1e3 + 4e6) / 1e6
        self.khz = khz
        self.stop = threading.Event()
        self.session: IqsSession | None = None
        self.fol: HopFollower | None = None
        self.error: BaseException | None = None
        self.all_times: deque[tuple[float, bool]] = deque()
        self.n_ok = self.n_all = 0
        self.lat: deque[float] = deque(maxlen=200)
        self.t_start = time.monotonic()
        self.gain_index = None
        self.tap = None  # optional callable(frame), e.g. waterfall.Waterfall.tap
        self.cmd_log: list[str] = []
        self.kick_every = 0.0     # test aid (d8follow --kick): seconds between schedule kicks

    def stats(self) -> dict:
        now = time.monotonic()
        while self.all_times and now - self.all_times[0][0] > 10:
            self.all_times.popleft()
        win = min(10.0, max(now - self.t_start, 1e-3))
        ok = sum(1 for _, k in self.all_times if k)
        st = self.session.stats if self.session else None
        fs = self.fol.st if self.fol else FollowStats()
        mode = self.fol.mode if self.fol else "acquire"
        return {"type": "stats", "uptime": round(now - self.t_start, 1),
                "packets_per_s": round(ok / win, 2),
                "crc_rate": round(ok / len(self.all_times), 3) if self.all_times else None,
                "n_ok": self.n_ok, "n_all": self.n_all, "mode": mode,
                "period_ms": round(self.fol.P / FS * 1e3, 4) if self.fol and mode == "locked" else 0.0,
                "decode_frac": 0.0,
                "latency_ms": round(float(np.median(self.lat)), 1) if self.lat else None,
                "frames": st.frames if st else 0, "samples": st.samples if st else 0,
                "lost_samples": st.lost_samples if st else 0, "loss_frac": st.loss_fraction if st else 0,
                "bad_crc": st.bad_crc if st else 0, "short_frames": st.short_frames if st else 0,
                "center_mhz": round(self.center, 4), "gain": self.gain if self.gain is not None else "hw",
                "gain_index": self.gain_index, "process_cpu_s": round(time.process_time(), 2),
                "follow": {"hops": fs.hops, "ok_locked": fs.ok_locked,
                           "slot_pct": round(100 * fs.ok_locked / fs.hops, 1) if fs.hops else None,
                           "losses": fs.losses, "reacq_s": [round(x, 3) for x in fs.reacq_s[-10:]],
                           "first_lock_s": fs.first_lock_s, "schedules": fs.schedules,
                           "slot_mismatch": fs.slot_mismatch, "counter_mismatch": fs.counter_mismatch,
                           "decode_cpu_s": round(fs.decode_cpu_s, 2),
                           # per slot (index = hop slot): CRC-ok packets / locked segments, channel MHz
                           "slot_ok": list(fs.slot_ok), "slot_hops": list(fs.slot_hops),
                           "slot_mhz": [round(k / 1e3 + 4, 3) for k in self.khz]}}

    def run(self) -> None:
        d = self.dev
        try:
            if self.gain is not None:
                d.command(f"GAIN MANUAL {self.gain}")
            load_table(d, self.khz)
            mhz, fofs = plan_tune(self.center * 1e6, MODE)
            s = self.session = IqsSession(d, DEC, BITS, mhz, fofs, seconds=0, mode=MODE)
            cmd = Commander(d.t, log=lambda l: self.cmd_log.append(l))
            self.fol = HopFollower(cmd, acq_slot=self.acq_slot, tx_id=self.tx_id, log=self.log)
            stopping = False
            next_stats = time.monotonic() + 1
            next_kick = time.monotonic() + self.kick_every
            for iq, f in s.blocks():
                if stopping:
                    continue
                if self.stop.is_set():
                    d.t.write(STOP_BYTE)
                    stopping = True
                    continue
                self.gain_index = f.gain
                if self.tap:
                    self.tap(f)
                t_rx = time.monotonic()
                for r in self.fol.feed(f):
                    p_end = r.t * FS + d8.AIR_BITS * FS / d8.BAUD
                    lat = ((f.index + len(iq) - p_end) / FS + time.monotonic() - t_rx) * 1e3
                    if r.packet.crc_ok:
                        self.n_ok += 1
                        self.lat.append(lat)
                    self.n_all += 1
                    self.all_times.append((time.monotonic(), r.packet.crc_ok))
                    self.publish(packet_msg(r, self.fol.mode, lat))
                if self.kick_every and time.monotonic() >= next_kick and self.fol.mode == "locked":
                    next_kick = time.monotonic() + self.kick_every
                    self.log(f"kick: schedule shifted 4 ms at {f.index / FS:.2f} s")
                    self.fol.kick(4000 * 16)
                if time.monotonic() >= next_stats:
                    next_stats += 1
                    self.publish(self.stats())
        except BaseException as e:
            self.error = e
        finally:
            for c in ("GAIN HARDWARE", "HOPCLR"):
                try:
                    d.command(c)
                except Exception:
                    pass


def _sigterm(*_):
    raise KeyboardInterrupt


def report(run: FollowRun, out) -> None:
    s = run.stats()
    f = s["follow"]
    st = run.session.stats if run.session else None
    up = s["uptime"]
    print(f"\nd8follow: {up:.1f} s, {run.n_ok} CRC-ok packets ({run.n_ok / max(up, 1e-3):.1f}/s), "
          f"{run.n_all - run.n_ok} failed CRC", file=out)
    print(f"  locked segments {f['hops']}, CRC-ok in them {f['ok_locked']} ({f['slot_pct']}% of slots); "
          f"first lock at {f['first_lock_s']} s stream time", file=out)
    print(f"  lock losses {f['losses']}, re-acquire s {f['reacq_s']}; schedules sent {f['schedules']}; "
          f"slot mismatches {f['slot_mismatch']}, counter mismatches {f['counter_mismatch']}", file=out)
    print(f"  period {s['period_ms']} ms; decode CPU {f['decode_cpu_s']} s; median latency {s['latency_ms']} ms",
          file=out)
    fs = run.fol.st if run.fol else None
    if fs and fs.hops:
        pct = [(100 * o / h if h else 0.0, i) for i, (o, h) in enumerate(zip(fs.slot_ok, fs.slot_hops))]
        worst = sorted(pct)[:6]
        print("  worst slots (slot:channel MHz:% ok): " + ", ".join(
            f"{i}:{d8_channel_hz(D8_TABLE[i]) / 1e6:.3f}:{p:.0f}%" for p, i in worst), file=out)
    if st:
        print(f"  stream: frames {st.frames} samples {st.samples} lost {st.lost_samples:.0f} bad_crc {st.bad_crc} "
              f"short {st.short_frames}; IQSEND {st.end or 'missing'}", file=out)


def cmd_d8follow(args, out) -> int:
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, _sigterm)
        signal.signal(signal.SIGINT, signal.default_int_handler)
    gain = None if str(args.gain).lower() in ("hw", "hardware") else int(args.gain)
    with args.device_factory(args.port) as dev:
        run = FollowRun(dev, gain, log=lambda m: print(m, file=out, flush=True), ppm=args.ppm)
        run.kick_every = args.kick
        th = threading.Thread(target=run.run, daemon=True, name="d8follow")
        th.start()
        t0 = time.monotonic()
        last = t0
        try:
            while th.is_alive():
                th.join(0.5)
                now = time.monotonic()
                if args.seconds and now - t0 >= args.seconds:
                    break
                if args.status and now - last >= args.status:
                    last = now
                    s = run.stats()
                    f = s["follow"]
                    print(f"[{s['uptime']:7.1f}s] {s['mode']:7} ok {s['n_ok']:6d} {s['packets_per_s']:6.1f}/s "
                          f"slots {f['slot_pct']}% losses {f['losses']} P {s['period_ms']} ms "
                          f"cpu {f['decode_cpu_s']}s", file=out, flush=True)
        except KeyboardInterrupt:
            pass
        finally:
            run.stop.set()
            th.join(10)
        report(run, out)
        if run.error and not isinstance(run.error, KeyboardInterrupt):
            raise run.error
    return 0


def register(sub) -> None:
    p = sub.add_parser("d8follow", help="follow the FrSky D8 hop sequence and report decode statistics")
    p.add_argument("--seconds", type=float, default=0, help="run this long (0 = until Ctrl-C)")
    p.add_argument("--gain", default="40", help="manual gain index, or 'hw' (default 40)")
    p.add_argument("--ppm", type=float, default=None, help="tx+board frequency offset, ppm (default measured -26.4)")
    p.add_argument("--status", type=float, default=5.0, metavar="S", help="status line every S seconds")
    p.add_argument("--kick", type=float, default=0, metavar="S",
                   help="test aid: every S s shift the hop schedule 4 ms off the tx to force a loss + re-acquire")
    p.set_defaults(func=cmd_d8follow)
