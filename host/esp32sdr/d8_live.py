# SPDX-License-Identifier: GPL-3.0-or-later
"""Live FrSky D8 channel viewer: `esp32sdr d8live [--center 2421.032 --gain 40]`.

Streams 1-bit I/Q at dec 64 (250 kS/s, mode 2) from the board, decodes D8
packets in real time and publishes them over a local WebSocket; the same
port serves the web UI (host/web/d8live, built with `npm run build`).

Decoding keeps up by not decoding most of the stream. `LiveDecoder` starts in
*search*: it runs `d8.StandardDecoder` over every sample, in overlapping
chunks (~25% of one core). After a CRC-valid packet it *locks*: the E8 visits
one channel once per 47-hop cycle (~422.6 ms), so only a ~20 ms window around
the predicted next arrival is decoded, and each hit corrects the phase and
period. After MISS_LIMIT missed cycles it falls back to search.

Messages (JSON text frames on ws://HOST:PORT/ws):
  {"type": "packet", "t", "tx_id", "counter", "ch" (8 us), "raw" (8 x 12-bit),
   "crc_ok", "cfo", "mode", "latency_ms"}
  {"type": "stats", ...}  about once a second (see LiveRun.stats)
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import mimetypes
import signal
import struct
import sys
import threading
import time
from collections import deque
from pathlib import Path

import numpy as np

from . import d8
from .iqs import STOP_BYTE, IqsError, IqsSession, plan_tune

FS = 250_000.0  # 16 MS/s / dec 64
DEC, BITS, MODE = 64, 1, 2
CYCLE_S = 0.4226  # 47 hops of ~9 ms
WEB_DIR = Path(__file__).resolve().parents[1] / "web" / "d8live" / "dist"


class LiveDecoder:
    """Incremental D8 decoder over a sample stream with absolute sample indices.

    `feed(index, iq)` appends a block (gaps are zero-filled) and returns the new
    `d8.Result`s, their `t` in seconds from stream index 0."""

    CHUNK_S = 0.25      # search: decode this much at a time
    OVERLAP_S = 0.012   # search: chunks overlap by more than one packet (6.7 ms)
    PRE_S = 0.006       # locked: window opens this long before the predicted start
    POST_S = 0.014      # ... and closes this long after it (packet 6.7 ms + slack)
    MISS_LIMIT = 6      # locked: missed cycles before going back to search
    KEEP_S = 1.5        # buffer length

    def __init__(self, fs: float = FS, *, cycle_s: float = CYCLE_S, decoder=None):
        self.fs = fs
        self.dec = decoder or d8.StandardDecoder(fs)
        self.buf = np.zeros(0, np.complex64)
        self.base = 0              # absolute index of buf[0]
        self.done = 0              # search: absolute index searched up to
        self.period = cycle_s * fs  # samples
        self.cycle0 = cycle_s * fs
        self.next: float | None = None  # locked: predicted start (absolute samples)
        self.misses = 0
        self.last_emit: deque[float] = deque(maxlen=16)  # absolute start samples
        self.decoded_samples = 0   # CPU accounting: samples given to the decoder
        self.attempts = 0          # bursts with a sync word (CRC ok or not)

    @property
    def end(self) -> int:
        return self.base + len(self.buf)

    @property
    def mode(self) -> str:
        return "search" if self.next is None else "locked"

    def _append(self, index: int, iq: np.ndarray) -> None:
        if not len(self.buf):
            self.base = self.done = index
        gap = index - self.end
        parts = [self.buf]
        if gap > 0:
            parts.append(np.zeros(gap, np.complex64))
        elif gap < 0:  # overlap/backwards: drop what we already have
            iq = iq[-gap:]
        parts.append(np.asarray(iq, np.complex64))
        self.buf = np.concatenate(parts)
        keep = int(self.KEEP_S * self.fs)
        if len(self.buf) > keep:
            cut = len(self.buf) - keep
            self.buf = self.buf[cut:]
            self.base += cut

    def _decode(self, a: int, b: int) -> list[d8.Result]:
        a = max(a, self.base)
        x = self.buf[a - self.base : b - self.base]
        self.decoded_samples += len(x)
        res = self.dec.decode(x)
        for r in res:
            r.t += a / self.fs
        self.attempts += len(res)
        return res

    def _new(self, res: list[d8.Result]) -> list[d8.Result]:
        out = []
        for r in res:
            s = r.t * self.fs
            if any(abs(s - e) < 0.002 * self.fs for e in self.last_emit):
                continue
            self.last_emit.append(s)
            out.append(r)
        return out

    def feed(self, index: int, iq: np.ndarray) -> list[d8.Result]:
        self._append(index, iq)
        out: list[d8.Result] = []
        while True:
            if self.next is None:
                chunk = int(self.CHUNK_S * self.fs)
                if self.end - self.done < chunk:
                    break
                ov = int(self.OVERLAP_S * self.fs)
                a, b = self.done - ov, self.end
                res = self._new([r for r in self._decode(a, b) if r.t * self.fs < b - ov])
                self.done = b - ov
                out += res
                ok = [r for r in res if r.packet.crc_ok]
                if ok:
                    self.next = ok[-1].t * self.fs + self.period
                    self.misses = 0
            else:
                b = int(self.next + self.POST_S * self.fs)
                if self.end < b:
                    break
                a = int(self.next - self.PRE_S * self.fs)
                res = self._new(self._decode(a, b))
                out += res
                ok = [r for r in res if r.packet.crc_ok]
                if ok:
                    err = ok[0].t * self.fs - self.next
                    self.period += 0.1 * err / (self.misses + 1)
                    # the period cannot be far from one hop cycle
                    self.period = min(max(self.period, 0.99 * self.cycle0), 1.01 * self.cycle0)
                    self.next = ok[0].t * self.fs + self.period
                    self.misses = 0
                else:
                    self.misses += 1
                    self.next += self.period
                    if self.misses >= self.MISS_LIMIT:
                        self.next = None
                        self.done = max(self.base, self.end - int(self.CHUNK_S * self.fs))
                        self.period = self.cycle0
        return out


# ------------------------------------------------------------ web server ----

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def ws_accept(key: str) -> str:
    return base64.b64encode(hashlib.sha1((key + _WS_GUID).encode()).digest()).decode()


def ws_frame(text: str) -> bytes:
    """One unmasked server-to-client text frame."""
    p = text.encode()
    n = len(p)
    if n < 126:
        head = struct.pack("!BB", 0x81, n)
    elif n < 65536:
        head = struct.pack("!BBH", 0x81, 126, n)
    else:
        head = struct.pack("!BBQ", 0x81, 127, n)
    return head + p


class WebServer:
    """Static files from `web_dir` plus a broadcast-only WebSocket at /ws, on
    an asyncio loop in a daemon thread. `publish(obj)` is thread safe."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8765, web_dir: Path = WEB_DIR):
        self.host, self.port, self.web_dir = host, port, Path(web_dir)
        self.loop = asyncio.new_event_loop()
        self.clients: set[asyncio.Queue] = set()
        self.latest: dict[str, str] = {}  # last message per type, sent to new clients
        self._ready = threading.Event()
        self._err: BaseException | None = None
        self.thread = threading.Thread(target=self._run, daemon=True, name="d8live-web")

    def start(self) -> "WebServer":
        self.thread.start()
        self._ready.wait(5)
        if self._err:
            raise self._err
        return self

    def _run(self):
        asyncio.set_event_loop(self.loop)
        try:
            self.server = self.loop.run_until_complete(
                asyncio.start_server(self._handle, self.host, self.port))
            self.port = self.server.sockets[0].getsockname()[1]
        except OSError as e:
            self._err = e
            self._ready.set()
            return
        self._ready.set()
        self.loop.run_forever()
        self.loop.close()

    def stop(self):
        if self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self._shutdown(), self.loop)
        self.thread.join(2)

    async def _shutdown(self):
        self.server.close()
        me = asyncio.current_task()
        tasks = [t for t in asyncio.all_tasks() if t is not me]
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.loop.stop()

    def publish(self, obj: dict) -> None:
        text = json.dumps(obj, separators=(",", ":"))
        if self.loop.is_running():
            self.loop.call_soon_threadsafe(self._broadcast, obj.get("type", ""), text)

    def _broadcast(self, kind: str, text: str):
        self.latest[kind] = text
        for q in list(self.clients):
            if q.qsize() < 256:  # a stalled client loses messages, never blocks us
                q.put_nowait(text)

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 10)
            lines = head.decode("latin-1").split("\r\n")
            method, path, *_ = lines[0].split(" ") + ["", ""]
            hdr = {k.strip().lower(): v.strip() for k, _, v in (l.partition(":") for l in lines[1:] if l)}
            path = path.split("?")[0]
            if hdr.get("upgrade", "").lower() == "websocket" and "sec-websocket-key" in hdr:
                await self._ws(reader, writer, hdr["sec-websocket-key"])
            else:
                await self._static(writer, method, path)
        except (asyncio.IncompleteReadError, asyncio.TimeoutError, ConnectionError, asyncio.LimitOverrunError):
            pass
        finally:
            try:
                writer.close()
            except Exception:
                pass

    async def _static(self, writer, method: str, path: str):
        root = self.web_dir.resolve()
        f = (root / path.lstrip("/")).resolve()
        if f.is_dir():
            f = f / "index.html"
        if method not in ("GET", "HEAD") or root not in f.parents and f != root or not f.is_file():
            if not (root / "index.html").is_file():
                body = (b"d8live: web UI not built. Run: cd host/web/d8live && npm install && npm run build\n")
                status = "503 Service Unavailable"
            else:
                body, status = b"not found\n", "404 Not Found"
            ctype = "text/plain"
        else:
            body, status = f.read_bytes(), "200 OK"
            ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        writer.write(f"HTTP/1.1 {status}\r\nContent-Type: {ctype}\r\nContent-Length: {len(body)}\r\n"
                     "Cache-Control: no-cache\r\nConnection: close\r\n\r\n".encode())
        if method != "HEAD":
            writer.write(body)
        await writer.drain()

    async def _ws(self, reader, writer, key: str):
        writer.write(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                      f"Sec-WebSocket-Accept: {ws_accept(key)}\r\n\r\n").encode())
        q: asyncio.Queue = asyncio.Queue()
        for text in self.latest.values():
            q.put_nowait(text)
        self.clients.add(q)

        async def drain_client():  # only close/ping matter; payloads are ignored
            while True:
                b0, b1 = await reader.readexactly(2)
                n = b1 & 0x7F
                if n == 126:
                    n = struct.unpack("!H", await reader.readexactly(2))[0]
                elif n == 127:
                    n = struct.unpack("!Q", await reader.readexactly(8))[0]
                mask = await reader.readexactly(4) if b1 & 0x80 else b"\0\0\0\0"
                data = bytes(c ^ mask[i % 4] for i, c in enumerate(await reader.readexactly(n)))
                op = b0 & 0x0F
                if op == 0x8:
                    return
                if op == 0x9:
                    q.put_nowait(("pong", data))

        rx = asyncio.ensure_future(drain_client())
        try:
            while not rx.done():
                get = asyncio.ensure_future(q.get())
                done, _ = await asyncio.wait({get, rx}, return_when=asyncio.FIRST_COMPLETED)
                if get not in done:
                    get.cancel()
                    break
                m = get.result()
                if isinstance(m, tuple):
                    writer.write(struct.pack("!BB", 0x8A, len(m[1][:125])) + m[1][:125])
                else:
                    writer.write(ws_frame(m))
                await writer.drain()
        finally:
            self.clients.discard(q)
            rx.cancel()


# ------------------------------------------------------------- live run ----


def packet_msg(r: d8.Result, mode: str, latency_ms: float) -> dict:
    p = r.packet
    return {"type": "packet", "t": round(r.t, 5), "tx_id": list(p.tx_id), "counter": p.raw[4],
            "ch": [round(v, 1) for v in p.channels_us], "raw": p.channels, "crc_ok": p.crc_ok,
            "cfo": round(r.cfo), "mode": mode, "latency_ms": round(latency_ms, 1)}


class LiveRun:
    """Stream reader thread -> decoder -> publish callback."""

    def __init__(self, dev, center_mhz: float, gain: int | None, publish, log=print):
        self.dev, self.center, self.gain, self.publish, self.log = dev, center_mhz, gain, publish, log
        self.mhz, self.fofs = plan_tune(center_mhz * 1e6, MODE)
        self.stop = threading.Event()
        self.ld = LiveDecoder(FS)
        self.session: IqsSession | None = None
        self.error: BaseException | None = None
        self.ok_times: deque[float] = deque()     # wall time of CRC-ok packets (last 10 s)
        self.all_times: deque[tuple[float, bool]] = deque()
        self.n_ok = self.n_all = 0
        self.lat: deque[float] = deque(maxlen=50)
        self.cpu = 0.0
        self.t_start = time.monotonic()
        self.gain_index = None

    def stats(self) -> dict:
        now = time.monotonic()
        while self.all_times and now - self.all_times[0][0] > 10:
            self.all_times.popleft()
        win = min(10.0, max(now - self.t_start, 1e-3))
        ok = sum(1 for _, k in self.all_times if k)
        st = self.session.stats if self.session else None
        cpu_s = time.process_time()
        return {"type": "stats", "uptime": round(now - self.t_start, 1),
                "packets_per_s": round(ok / win, 2), "crc_rate": round(ok / len(self.all_times), 3) if self.all_times else None,
                "n_ok": self.n_ok, "n_all": self.n_all, "mode": self.ld.mode,
                "period_ms": round(self.ld.period / FS * 1e3, 2),
                "decode_frac": round(self.ld.decoded_samples / max(1, st.samples if st else 1), 3),
                "latency_ms": round(float(np.median(self.lat)), 1) if self.lat else None,
                "frames": st.frames if st else 0, "samples": st.samples if st else 0,
                "lost_samples": st.lost_samples if st else 0, "loss_frac": st.loss_fraction if st else 0,
                "bad_crc": st.bad_crc if st else 0, "short_frames": st.short_frames if st else 0,
                "center_mhz": self.center, "gain": self.gain if self.gain is not None else "hw",
                "gain_index": self.gain_index, "process_cpu_s": round(cpu_s, 2)}

    def run(self) -> None:
        """Blocking: stream until self.stop is set (then stop the stream cleanly)."""
        d = self.dev
        if self.gain is not None:
            d.command(f"GAIN MANUAL {self.gain}")
        s = self.session = IqsSession(d, DEC, BITS, self.mhz, self.fofs, seconds=0, mode=MODE)
        stopping = False
        next_stats = time.monotonic() + 1
        try:
            for iq, f in s.blocks():
                if stopping:
                    continue  # drain until IQSEND
                if self.stop.is_set():
                    d.t.write(STOP_BYTE)
                    stopping = True
                    continue
                self.gain_index = f.gain
                t_rx = time.monotonic()
                for r in self.ld.feed(f.index, iq):
                    # packet end -> publish: newer samples in this block + decode time
                    # (not the firmware/UART pipeline before the block arrived)
                    p_end = r.t * FS + d8.AIR_BITS * FS / d8.BAUD
                    lat = ((f.index + len(iq) - p_end) / FS + time.monotonic() - t_rx) * 1e3
                    if r.packet.crc_ok:
                        self.n_ok += 1
                        self.lat.append(lat)
                    self.n_all += 1
                    self.all_times.append((time.monotonic(), r.packet.crc_ok))
                    self.publish(packet_msg(r, self.ld.mode, lat))
                if time.monotonic() >= next_stats:
                    next_stats += 1
                    self.publish(self.stats())
        except BaseException as e:
            self.error = e
        finally:
            if self.gain is not None:
                try:
                    d.command("GAIN HARDWARE")
                except Exception:
                    pass


def _sigterm(*_):
    raise KeyboardInterrupt


def cmd_d8live(args, out) -> int:
    web = WebServer(args.host, args.http_port).start()
    url = f"http://{args.host}:{web.port}/"
    if not (WEB_DIR / "index.html").is_file():
        print("note: web UI not built; run: cd host/web/d8live && npm install && npm run build", file=out)
    print(f"d8live: {args.center} MHz, 1-bit dec 64 mode 2, gain {args.gain}; UI {url} (ws {url}ws)",
          file=out, flush=True)
    if args.open:
        import webbrowser
        webbrowser.open(url)
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, _sigterm)
        signal.signal(signal.SIGINT, signal.default_int_handler)  # even if started with SIGINT ignored
    gain = None if str(args.gain).lower() in ("hw", "hardware") else int(args.gain)
    with args.device_factory(args.port) as dev:
        run = LiveRun(dev, args.center, gain, web.publish)
        th = threading.Thread(target=run.run, daemon=True, name="d8live-stream")
        th.start()
        last = 0.0
        try:
            while th.is_alive():
                th.join(0.5)
                if args.status and time.monotonic() - last >= args.status:
                    last = time.monotonic()
                    s = run.stats()
                    print(f"[{s['uptime']:7.1f}s] {s['mode']:6} ok {s['n_ok']:5d}/{s['n_all']:5d} "
                          f"{s['packets_per_s']:.2f} pkt/s  decode {s['decode_frac'] * 100:.1f}% of samples  "
                          f"lost {s['lost_samples']:.0f}  cpu {s['process_cpu_s']:.1f}s", file=out, flush=True)
        except KeyboardInterrupt:
            pass
        finally:
            run.stop.set()
            th.join(10)
            web.stop()
        s = run.stats()
        st = run.session.stats if run.session else None
        print(f"\nstopped after {s['uptime']:.1f} s: {s['n_ok']} CRC-ok packets of {s['n_all']} "
              f"({s['n_ok'] / max(s['uptime'], 1e-3):.2f}/s), decoded {s['decode_frac'] * 100:.1f}% of samples, "
              f"process CPU {s['process_cpu_s']:.1f} s", file=out)
        if st:
            print(f"stream: frames {st.frames} samples {st.samples} lost {st.lost_samples:.0f} "
                  f"({st.loss_fraction * 100:.4f}%) bad_crc {st.bad_crc} short {st.short_frames}; "
                  f"IQSEND {st.end or 'missing'}", file=out)
        if th.is_alive():
            print("warning: stream thread did not finish", file=out)
        if run.error and not isinstance(run.error, KeyboardInterrupt):
            raise run.error
    return 0


def register(sub) -> None:
    p = sub.add_parser("d8live", help="live FrSky D8 channel viewer (web UI over a local WebSocket)")
    p.add_argument("--center", type=float, default=2421.032, help="channel centre MHz (default 2421.032)")
    p.add_argument("--gain", default="40", help="manual gain index, or 'hw' for hardware AGC (default 40)")
    p.add_argument("--host", default="127.0.0.1", help="web/WebSocket listen address (default 127.0.0.1)")
    p.add_argument("--http-port", type=int, default=8765, help="web/WebSocket port (default 8765)")
    p.add_argument("--open", action="store_true", help="open the UI in the default browser")
    p.add_argument("--status", type=float, default=5.0, metavar="S",
                   help="print a status line every S seconds (0 = off, default 5)")
    p.set_defaults(func=cmd_d8live)
