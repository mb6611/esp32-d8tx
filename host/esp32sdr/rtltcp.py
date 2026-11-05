# SPDX-License-Identifier: GPL-3.0-or-later
"""rtl_tcp server: serve the IQS stream to gqrx, SDR++, GNU Radio (`esp32sdr bridge`).

Protocol: on connect a 12-byte dongle header (`RTL0`, tuner type, gain count; both
big-endian u32), then unsigned 8-bit offset-binary interleaved I/Q. Clients send 5-byte
commands (u8 id + big-endian u32). Id 0x01 (set frequency, Hz) retunes: the stream is
stopped, `FREQ` + `FOFS` are sent and `IQS` restarts (not when the frequency is already
the tuned one). The board's rate is fixed by the decimation (31250 S/s at dec 512); id
0x02 (sample rate) selects an integer interpolation factor when the requested rate is
a multiple of it (SDR++ only offers 250 kS/s and up: 250000 = 8 x 31250), otherwise the
native rate is sent. One client at a time.

Robustness: the serial stream is read without ever waiting on the client (a sender
thread with a bounded queue drops blocks when the client stops reading, e.g. gqrx with
DSP off). Frames cut short, bad CRCs and IQS runs that end or fail are resynced and
restarted with the loss counted; only repeated failures with no data end the client.
"""
from __future__ import annotations

import queue
import signal
import socket
import struct
import threading
import time

import numpy as np

from .device import FREQ_MAX_MHZ, FREQ_MIN_MHZ
from .iqs import STOP_BYTE, IqsError, IqsSession
from .protocol import DeviceError, TransferError

TUNER_R820T = 5
HEADER = b"RTL0" + struct.pack(">II", TUNER_R820T, 29)
CMD_SET_FREQ = 0x01
CMD_SET_RATE = 0x02
MAX_INTERP = 128
QUEUE_BLOCKS = 64      # ~1 s of IQS frames at dec 512
MAX_FAILURES = 5       # consecutive IQS runs that delivered nothing
STATUS_EVERY = 30.0    # seconds between status lines


def split_freq(hz: int) -> tuple[int, int]:
    """Hz -> (whole MHz, FOFS kHz in -1000..1000)."""
    mhz = round(hz / 1e6)
    fofs = round((hz - mhz * 1_000_000) / 1e3)
    return mhz, max(-1000, min(1000, fofs))


def to_u8(iq: np.ndarray, bits: int) -> bytes:
    """complex samples (signed `bits`-bit integers) -> interleaved offset-binary u8."""
    sh = 8 - bits
    inter = np.empty(iq.size * 2, np.float32)
    inter[0::2], inter[1::2] = iq.real, iq.imag
    v = np.rint(inter * (2.0 ** sh)) + 128
    return np.clip(v, 0, 255).astype(np.uint8).tobytes()


def interp_factor(requested: int, native: int) -> int:
    """Integer interpolation for a client rate request (1 = send native)."""
    if requested > 0 and requested % native == 0 and requested // native <= MAX_INTERP:
        return requested // native
    return 1


class Upsampler:
    """Streaming integer interpolator (zero-stuff + Kaiser windowed sinc, unity gain)."""

    TAPS_PER_PHASE = 16

    def __init__(self, factor: int):
        self.L = factor
        if factor == 1:
            return
        n = self.TAPS_PER_PHASE * factor
        m = np.arange(n) - (n - 1) / 2
        h = np.sinc(m / factor) * np.kaiser(n, 8.0)
        self.h = (h * factor / h.sum()).astype(np.float32)
        self.tail = np.zeros(n - 1, np.complex64)

    def __call__(self, x: np.ndarray) -> np.ndarray:
        if self.L == 1:
            return x
        z = np.zeros(x.size * self.L, np.complex64)
        z[:: self.L] = x
        zz = np.concatenate([self.tail, z])
        self.tail = zz[-(self.h.size - 1):]
        return np.convolve(zz, self.h, mode="valid").astype(np.complex64)


class Bridge:
    def __init__(self, dev, *, freq_hz: int, dec: int = 512, bits: int = 8,
                 host: str = "127.0.0.1", port: int = 1234, log=None,
                 offset_hz: int = 0):
        self.native_rate = IqsSession(dev, dec, bits, 2402).sample_rate  # validates dec/bits
        self.dev, self.dec, self.bits, self.freq_hz = dev, dec, bits, freq_hz
        self.offset_hz = offset_hz  # added to every client-requested frequency
        self.log = log or (lambda m: None)
        self.lock = threading.Lock()
        self.retune = threading.Event()
        self.alive = threading.Event()
        self.interp = 1
        self.dropped = 0  # blocks dropped because the client was not reading
        self.srv = socket.create_server((host, port))
        self.address = self.srv.getsockname()
        self.closed = False

    def close(self) -> None:
        self.closed = True
        self.srv.close()

    def serve_forever(self) -> None:
        while not self.closed:
            try:
                conn, peer = self.srv.accept()
            except OSError:
                return
            self.log(f"client {peer[0]}:{peer[1]}")
            try:
                self.serve_client(conn)
                self.log("client disconnected")
            except (OSError, DeviceError, TransferError, IqsError, ValueError) as e:
                self.log(f"client ended: {type(e).__name__}: {e}")
            finally:
                try:
                    conn.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                conn.close()

    # -- one client -----------------------------------------------------
    def _commands(self, conn) -> None:
        buf = b""
        try:
            while self.alive.is_set():
                d = conn.recv(256)
                if not d:
                    break
                buf += d
                while len(buf) >= 5:
                    cmd, arg = struct.unpack(">BI", buf[:5])
                    buf = buf[5:]
                    if cmd == CMD_SET_FREQ:
                        self._set_freq(arg + self.offset_hz)
                    elif cmd == CMD_SET_RATE:
                        k = interp_factor(arg, self.native_rate)
                        if k != self.interp:
                            self.interp = k
                            self.log(f"output rate {self.native_rate * k} S/s "
                                     f"(x{k} interpolation)")
                        if self.native_rate * k != arg:
                            self.log(f"client asked for {arg} S/s; sending "
                                     f"{self.native_rate * k} S/s (set the client to "
                                     f"{self.native_rate} S/s or a multiple)")
        except OSError:
            pass
        finally:
            self.alive.clear()

    def _set_freq(self, hz: int) -> None:
        mhz, _ = split_freq(hz)
        if not FREQ_MIN_MHZ <= mhz <= FREQ_MAX_MHZ:
            self.log(f"ignored out-of-range frequency {hz} Hz")
            return
        with self.lock:
            if hz == self.freq_hz:
                return  # already tuned (or pending): do not restart IQS
            self.freq_hz = hz
        self.retune.set()

    def _sender(self, conn, q: queue.Queue) -> None:
        up, k = Upsampler(1), 1
        try:
            while True:
                iq = q.get()
                if iq is None:
                    return
                if self.interp != k:
                    k = self.interp
                    up = Upsampler(k)
                conn.sendall(to_u8(up(iq), self.bits))
        except OSError:
            pass
        finally:
            self.alive.clear()

    def serve_client(self, conn) -> None:
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)  # bound the latency
        conn.sendall(HEADER)
        self.alive.set()
        self.retune.clear()
        self.interp, self.dropped = 1, 0
        q: queue.Queue = queue.Queue(maxsize=QUEUE_BLOCKS)
        rd = threading.Thread(target=self._commands, args=(conn,), daemon=True)
        tx = threading.Thread(target=self._sender, args=(conn, q), daemon=True)
        rd.start()
        tx.start()
        failures = 0
        try:
            while self.alive.is_set():
                self.retune.clear()
                with self.lock:
                    hz = self.freq_hz
                mhz, fofs = split_freq(hz)
                self.log(f"tune {mhz} MHz fofs {fofs} kHz")
                s = IqsSession(self.dev, self.dec, self.bits, mhz, fofs, seconds=0)
                try:
                    stopped = self._run(s, q, mhz)
                except (TransferError, DeviceError, IqsError, TimeoutError) as e:
                    failures = 1 if s.stats.frames else failures + 1
                    self.log(f"IQS run failed ({failures}/{MAX_FAILURES}): "
                             f"{type(e).__name__}: {e}; {self._loss(s)}; restarting")
                    if failures >= MAX_FAILURES:
                        raise
                    time.sleep(0.2)
                    continue
                failures = 0
                if stopped:
                    self.log(f"stream stopped: {self._loss(s)}")
                else:
                    self.log(f"firmware ended the stream ({s.stats.end}); {self._loss(s)}; "
                             "restarting")
        finally:
            self.alive.clear()
            try:
                q.put_nowait(None)
            except queue.Full:
                pass
            try:
                conn.shutdown(socket.SHUT_RDWR)  # wakes a sender blocked in sendall
            except OSError:
                pass
            rd.join(timeout=1)
            tx.join(timeout=1)

    def _loss(self, s: IqsSession) -> str:
        st = s.stats
        return (f"lost {st.lost_samples:.0f} samples, {st.short_frames} short frames, "
                f"{st.bad_crc} bad CRC, {self.dropped} blocks dropped for a slow client")

    def _run(self, s: IqsSession, q: queue.Queue, mhz: int) -> bool:
        """One IQS run; True if we stopped it (retune/disconnect), False if the
        firmware ended it on its own."""
        stopping = False
        next_status = time.monotonic() + STATUS_EVERY
        for iq, _f in s.blocks():
            if stopping:
                continue  # drain until IQSEND
            if not self.alive.is_set() or self.retune.is_set():
                self.dev.t.write(STOP_BYTE)
                stopping = True
                continue
            try:
                q.put_nowait(iq)
            except queue.Full:
                self.dropped += 1
            if time.monotonic() >= next_status:
                next_status += STATUS_EVERY
                self.log(f"streaming {mhz} MHz: {s.stats.samples} samples, {self._loss(s)}")
        return stopping


def parse_listen(text: str) -> tuple[str, int]:
    host, _, port = text.rpartition(":")
    return host or "127.0.0.1", int(port)


def _sigterm(*_):
    raise KeyboardInterrupt


def cmd_bridge(args, out) -> int:
    """The one bridge code path (`esp32sdr bridge`; `esp32sdr sdrpp` calls it too).
    `args.on_ready(bridge)`, if set, runs once the server is listening."""
    host, port = parse_listen(args.listen)
    with args.device_factory(args.port) as dev:
        b = Bridge(dev, freq_hz=int(round(args.freq * 1e6)), dec=args.dec, bits=args.bits,
                   host=host, port=port,
                   offset_hz=int(round(args.offset_mhz * 1e6)), log=lambda m: print(m, file=out, flush=True))
        print(f"rtl_tcp on {b.address[0]}:{b.address[1]}, sample rate "
              f"{b.native_rate} S/s", file=out, flush=True)
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGTERM, _sigterm)  # `kill` releases the board cleanly
        on_ready = getattr(args, "on_ready", None)
        if on_ready:
            on_ready(b)
        try:
            b.serve_forever()
        finally:
            b.close()
    return 0


def add_bridge_args(p, *, freq: float = 2402.0) -> None:
    """Bridge options, shared by `bridge` and the `sdrpp` launcher."""
    p.add_argument("--listen", default="127.0.0.1:1234", metavar="[HOST]:PORT",
                   help="listen address (default 127.0.0.1:1234; ':1234' = 127.0.0.1)")
    p.add_argument("--freq", type=float, default=freq, help=f"initial centre MHz (default {freq:g})")
    p.add_argument("--offset-mhz", type=float, default=0.0,
                   help="MHz added to every frequency the client requests; the R820T header "
                        "makes gqrx clamp to 24-1766 MHz, so use 2000 with gqrx 'LNB LO' = 2000 MHz")
    p.add_argument("--dec", type=int, default=512)
    p.add_argument("--bits", type=int, default=8, choices=(4, 8, 16))


def register(sub) -> None:
    p = sub.add_parser("bridge", help="rtl_tcp server for gqrx / SDR++ (UART IQS)")
    add_bridge_args(p)
    p.set_defaults(func=cmd_bridge)
