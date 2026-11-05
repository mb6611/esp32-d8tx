# SPDX-License-Identifier: GPL-3.0-or-later
"""Waterfall rows for the d8live web UI (`esp32sdr d8live`, tab "Waterfall").

The stream thread hands every IQS frame to `Waterfall.tap(f)`. With nobody
subscribed that is one attribute test; otherwise the frame is queued (bounded)
and a worker thread turns the samples into spectrogram rows with numpy's FFT
(Hann window, averaged Welch-style), so the decode path never waits on it.

Two views:
  base  the stream itself: +-fs/2 (+-125 kHz) around the tuned frequency,
        `nfft` bins. In --follow mode the tuning hops, so this shows whatever
        channel each moment was on.
  hop   (--follow only) a "hop map": one strip of `bins_per_ch` bins per hop
        channel, channels sorted by frequency; a channel is only lit in the rows
        during which the receiver was on it (0 = not visited in this row).

The input is 1-bit I/Q, so absolute level is lost: every sample has power 2.
Rows are dB relative to a flat (white) spectrum, 0 dB = noise-like, and are
quantised to uint8: 0 = no data, 1..255 = db_min..db_max.

Transport: WebSocket at /wf?view=base|hop on the d8live port (registered with
`attach(web)`). The server sends one JSON text frame
  {"type": "wf_meta", "view", "views", "width", "rate", "db_min", "db_max",
   "fs", "nfft", "center_mhz", "follow", "channels": [{"slot", "mhz"}...] (hop),
   "bins_per_ch"}
then binary rows: ROW_HDR (kind 0 base / 1 hop, 0, width, seq, t stream s)
followed by `width` uint8, plus {"type": "wf_stats", "cpu_frac", ...} once a
second. Closing the socket unsubscribes; with no subscribers no work is done.
"""
from __future__ import annotations

import asyncio
import json
import struct
import threading
import time
from collections import deque
from urllib.parse import parse_qs

import numpy as np

FLAG_HOP_START = 0x04   # same as hopfollow.FLAG_HOP_*
FLAG_HOP_ON = 0x08
ROW_HDR = struct.Struct("<BBHId")   # kind, reserved, width, seq, t (16 bytes)
VIEWS = ("base", "hop")


def ws_binary(payload: bytes) -> bytes:
    """One unmasked server-to-client binary frame."""
    n = len(payload)
    if n < 126:
        head = struct.pack("!BB", 0x82, n)
    elif n < 65536:
        head = struct.pack("!BBH", 0x82, 126, n)
    else:
        head = struct.pack("!BBQ", 0x82, 127, n)
    return head + payload


def ws_text(text: str) -> bytes:
    from .d8_live import ws_frame
    return ws_frame(text)


class RowMaker:
    """Pure part: frames in, uint8 rows out. Rows are cut on the stream sample
    clock (every fs/rate samples), so their timing does not depend on how fast
    frames arrive."""

    def __init__(self, fs: float, *, rate: float = 25.0, nfft: int = 256, db_min: float = -10.0,
                 db_max: float = 25.0, slots_mhz: list[float] | None = None, bins_per_ch: int = 16,
                 default_slot: int = 0):
        assert nfft % bins_per_ch == 0
        self.fs, self.nfft, self.db_min, self.db_max = fs, nfft, db_min, db_max
        self.row_len = int(round(fs / rate))
        self.win = np.hanning(nfft).astype(np.float32)
        # 1-bit samples have power 2: scale so a flat spectrum is 1 (0 dB)
        self.scale = 1.0 / (2.0 * float(np.sum(self.win.astype(np.float64) ** 2)))
        self.slots_mhz = slots_mhz
        self.bins_per_ch = bins_per_ch
        self.default_slot = default_slot
        n_slots = len(slots_mhz) if slots_mhz else 0
        self.order = np.argsort(slots_mhz) if slots_mhz else np.zeros(0, int)  # x position -> slot
        self.views = {"base": True, "hop": bool(slots_mhz)}
        self.enabled = {"base": False, "hop": False}
        # base accumulators
        self.b_acc = np.zeros(nfft, np.float64)
        self.b_n = 0
        # hop accumulators
        self.h_acc = np.zeros((max(n_slots, 1), nfft), np.float64)
        self.h_n = np.zeros(max(n_slots, 1), np.int64)
        self.rest = np.zeros(0, np.complex64)  # < nfft samples carried to the next frame
        self.rest_slot = None
        self.next_idx = None
        self.row_end = None
        self.seq = {"base": 0, "hop": 0}

    def width(self, view: str) -> int:
        return self.nfft if view == "base" else len(self.order) * self.bins_per_ch

    def _quant(self, p: np.ndarray) -> np.ndarray:
        db = 10.0 * np.log10(np.maximum(p, 1e-12))
        v = (db - self.db_min) * (254.0 / (self.db_max - self.db_min))
        return (1 + np.clip(v, 0, 254)).astype(np.uint8)

    def _spectra(self, x: np.ndarray) -> np.ndarray:
        """Summed power over the whole nfft blocks of x (fftshifted, scaled)."""
        k = len(x) // self.nfft
        blk = x[: k * self.nfft].reshape(k, self.nfft) * self.win
        X = np.fft.fft(blk, axis=1)
        p = (X.real * X.real + X.imag * X.imag).sum(axis=0)
        return np.fft.fftshift(p) * self.scale, k

    def _emit(self, t: float) -> list[tuple[str, int, float, np.ndarray]]:
        out = []
        if self.enabled["base"] and self.b_n:
            out.append(("base", self.seq["base"], t, self._quant(self.b_acc / self.b_n)))
            self.seq["base"] += 1
        if self.enabled["hop"] and self.views["hop"]:
            row = np.zeros(self.width("hop"), np.uint8)
            hit = self.h_n > 0
            if hit.any():
                p = self.h_acc[hit] / self.h_n[hit, None]
                pooled = p.reshape(len(p), self.bins_per_ch, -1).mean(axis=2)
                q = self._quant(pooled)
                pos = np.empty(len(self.order), int)
                pos[self.order] = np.arange(len(self.order))
                for s, r in zip(np.nonzero(hit)[0], q):
                    x0 = pos[s] * self.bins_per_ch
                    row[x0:x0 + self.bins_per_ch] = r
            out.append(("hop", self.seq["hop"], t, row))
            self.seq["hop"] += 1
        self.b_acc[:] = 0
        self.b_n = 0
        self.h_acc[:] = 0
        self.h_n[:] = 0
        return out

    def feed(self, index: int, iq: np.ndarray, flags: int = 0, shift: int = 0):
        """One frame; returns finished rows [(view, seq, t_s, uint8 row)]."""
        if not (self.enabled["base"] or self.enabled["hop"]):
            self.next_idx = None
            return []
        slot = shift if flags & FLAG_HOP_ON else self.default_slot
        blank = ((flags >> 4) & 15) * 8 if flags & FLAG_HOP_START else 0
        if self.row_end is None:
            self.row_end = index + self.row_len
        # gaps and retunes break the carried partial block
        if self.next_idx != index or slot != self.rest_slot or blank:
            self.rest = self.rest[:0]
        self.next_idx = index + len(iq)
        self.rest_slot = slot
        out = []
        pos = index + blank
        x = np.asarray(iq[blank:], np.complex64)
        while len(x):
            if pos >= self.row_end:  # a gap (or the view was off): close the row, skip empty ones
                out += self._emit(self.row_end / self.fs)
                self.row_end += ((pos - self.row_end) // self.row_len + 1) * self.row_len
                continue
            take = min(len(x), self.row_end - pos)
            part = x[:take]
            x, pos = x[take:], pos + take
            if len(self.rest):
                part = np.concatenate([self.rest, part])
            k = len(part) // self.nfft
            self.rest = part[k * self.nfft:].copy()
            if k:
                p, k = self._spectra(part)
                if self.enabled["base"]:
                    self.b_acc += p
                    self.b_n += k
                if self.enabled["hop"] and self.views["hop"] and 0 <= slot < len(self.h_n):
                    self.h_acc[slot] += p
                    self.h_n[slot] += k
            if pos >= self.row_end:
                out += self._emit(self.row_end / self.fs)
                self.row_end += self.row_len
        return out


class Waterfall:
    """Thread wrapper around RowMaker plus the /wf WebSocket endpoint."""

    QUEUE_FRAMES = 1024   # bounded hand-off (a few seconds of stream); oldest dropped
    CLIENT_QUEUE = 128    # per-client rows; a slow client loses rows, never blocks

    def __init__(self, fs: float, *, center_mhz: float | None = None, slots_mhz: list[float] | None = None,
                 default_slot: int = 0, **kw):
        self.rm = RowMaker(fs, slots_mhz=slots_mhz, default_slot=default_slot, **kw)
        self.fs, self.center_mhz, self.slots_mhz = fs, center_mhz, slots_mhz
        self.q: deque = deque(maxlen=self.QUEUE_FRAMES)
        self.subs: dict[str, set[asyncio.Queue]] = {v: set() for v in VIEWS}
        self.active = False           # read lock-free by tap()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.stop_ev = threading.Event()
        self.wake = threading.Event()
        self.cpu_s = 0.0              # worker thread CPU
        self.samples = 0              # samples turned into rows
        self.dropped = 0
        self.thread = threading.Thread(target=self._work, daemon=True, name="d8live-waterfall")

    @classmethod
    def for_run(cls, run, fs: float, **kw) -> "Waterfall":
        """Views for a d8_live.LiveRun or d8follow.FollowRun (has .khz: LO kHz per slot)."""
        khz = getattr(run, "khz", None)
        if khz:
            from .iqs import MODE2_IF_HZ
            slots = [(k * 1e3 + MODE2_IF_HZ) / 1e6 for k in khz]
            return cls(fs, center_mhz=None, slots_mhz=slots, default_slot=getattr(run, "acq_slot", 0), **kw)
        return cls(fs, center_mhz=getattr(run, "center", None), **kw)

    # ---- stream thread -------------------------------------------------
    def tap(self, f) -> None:
        if not self.active:
            return
        if len(self.q) == self.q.maxlen:
            self.dropped += 1
        self.q.append((f.index, f.iq, f.flags, f.shift))
        if len(self.q) >= 8:
            self.wake.set()

    # ---- worker --------------------------------------------------------
    def start(self) -> "Waterfall":
        self.thread.start()
        return self

    def stop(self) -> None:
        self.stop_ev.set()
        self.wake.set()
        self.thread.join(2)

    def _work(self) -> None:
        next_stats = time.monotonic() + 1
        cpu0, wall0 = time.thread_time(), time.monotonic()
        while not self.stop_ev.is_set():
            self.wake.wait(0.04)
            self.wake.clear()
            c = time.thread_time()
            for v in VIEWS:
                self.rm.enabled[v] = bool(self.subs[v])
            rows = []
            while self.q:
                idx, iq, flags, shift = self.q.popleft()
                self.samples += len(iq)
                rows += self.rm.feed(idx, iq, flags, shift)
            self.cpu_s += time.thread_time() - c
            for view, seq, t, row in rows:
                w = self.rm.width(view)
                data = ws_binary(ROW_HDR.pack(VIEWS.index(view), 0, w, seq & 0xFFFFFFFF, t) + row.tobytes())
                self._send(view, data)
            now = time.monotonic()
            if now >= next_stats:
                next_stats = now + 1
                c1 = time.thread_time()
                st = {"type": "wf_stats", "cpu_frac": round((c1 - cpu0) / max(now - wall0, 1e-3), 4),
                      "cpu_s": round(self.cpu_s, 3), "dropped": self.dropped, "queued": len(self.q)}
                cpu0, wall0 = c1, now
                for v in VIEWS:
                    self._send(v, ws_text(json.dumps(st)))

    def _send(self, view: str, data: bytes) -> None:
        if self.loop and self.subs[view]:
            self.loop.call_soon_threadsafe(self._put, view, data)

    def _put(self, view: str, data: bytes) -> None:
        for q in list(self.subs[view]):
            if q.qsize() < self.CLIENT_QUEUE:
                q.put_nowait(data)

    # ---- WebSocket endpoint (runs on the WebServer loop) ----------------
    def attach(self, web, path: str = "/wf") -> "Waterfall":
        self.loop = web.loop
        web.ws_routes[path] = self.handle_ws
        return self

    def meta(self, view: str) -> dict:
        m = {"type": "wf_meta", "view": view, "views": [v for v in VIEWS if self.rm.views[v]],
             "width": self.rm.width(view), "rate": self.fs / self.rm.row_len, "db_min": self.rm.db_min,
             "db_max": self.rm.db_max, "fs": self.fs, "nfft": self.rm.nfft, "center_mhz": self.center_mhz,
             "follow": bool(self.slots_mhz)}
        if view == "hop":
            m["bins_per_ch"] = self.rm.bins_per_ch
            m["channels"] = [{"slot": int(s), "mhz": round(self.slots_mhz[s], 4)} for s in self.rm.order]
        return m

    async def handle_ws(self, reader, writer, hdr: dict, query: str) -> None:
        from .d8_live import ws_accept
        view = (parse_qs(query).get("view") or [""])[0]
        if not self.rm.views.get(view):
            view = "hop" if self.rm.views["hop"] else "base"
        writer.write(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                      f"Sec-WebSocket-Accept: {ws_accept(hdr['sec-websocket-key'])}\r\n\r\n").encode())
        writer.write(ws_text(json.dumps(self.meta(view))))
        await writer.drain()
        q: asyncio.Queue = asyncio.Queue()
        self.subs[view].add(q)
        self.active = True

        async def read_client():  # close and ping only; payloads ignored
            while True:
                b0, b1 = await reader.readexactly(2)
                n = b1 & 0x7F
                if n == 126:
                    n = struct.unpack("!H", await reader.readexactly(2))[0]
                elif n == 127:
                    n = struct.unpack("!Q", await reader.readexactly(8))[0]
                mask = await reader.readexactly(4) if b1 & 0x80 else b"\0\0\0\0"
                data = bytes(c ^ mask[i % 4] for i, c in enumerate(await reader.readexactly(n)))
                if b0 & 0x0F == 0x8:
                    return
                if b0 & 0x0F == 0x9:
                    q.put_nowait(struct.pack("!BB", 0x8A, len(data[:125])) + data[:125])

        rx = asyncio.ensure_future(read_client())
        try:
            while not rx.done():
                get = asyncio.ensure_future(q.get())
                done, _ = await asyncio.wait({get, rx}, return_when=asyncio.FIRST_COMPLETED)
                if get not in done:
                    get.cancel()
                    break
                writer.write(get.result())
                await writer.drain()
        finally:
            self.subs[view].discard(q)
            self.active = any(self.subs.values())
            if not self.active:
                self.q.clear()
            rx.cancel()
