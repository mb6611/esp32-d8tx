# SPDX-License-Identifier: GPL-3.0-or-later
"""Continuous IQ stream (`IQS`, docs/iq-stream.md) over a Device.

`parse_iqs1` decodes one frame. `IqsSession` tunes, sends `FOFS`/`IQS`, and
yields sample blocks while accounting loss two ways that are summed:
host-detected sample-index jumps (exact, in output samples; the firmware
advances the index for every input gap and queue drop). The `IQSEND` loss
field (`ffts`, input pairs / dec) is only a cross-check.
"""
from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field

import numpy as np

from .protocol import DeviceError, TransferError, check_err
from .samples import RATES

HEADER = 24
MAX_PAYLOAD = 1024
MAGIC = b"IQS1"
END_MAGIC = b"IQSE"  # first four bytes of "IQSEND"
STOP_BYTE = b"\n"
DEFAULT_RATE_CODE = 6  # 16 MS/s ring

# Allowed (rate_code, decimation, bits): single source on the host, equal to
# the table in docs/devkitv1/iq-stream-uart.md (a test compares them).
ALLOWED: dict[tuple[int, int, int], bool] = {
    (6, dec, bits): True
    for bits, decs in ((4, (256, 512, 1024)), (8, (512, 1024)), (16, (1024,)))
    for dec in decs
}

_END_FIELDS = (
    "status detail units pairs elapsed_us late_max work_max_cycles "
    "frames drops abandoned ffts stopped_by_host"
).split()


class IqsError(Exception):
    pass


@dataclass
class Frame:
    seq: int
    index: int
    samples: int
    bits: int
    flags: int
    dec: int
    gain: int
    shift: int
    iq: np.ndarray  # complex64, standard I/Q (Q negated)


def payload_len(samples: int, bits: int) -> int:
    if bits == 4:
        return samples
    if bits in (8, 16):
        return samples * 2 * bits // 8
    raise IqsError(f"unsupported bits {bits}")


def _decode(raw: bytes, samples: int, bits: int) -> np.ndarray:
    if bits == 4:
        b = np.frombuffer(raw, dtype=np.uint8)
        i = (b & 0x0F).astype(np.int8)
        q = (b >> 4).astype(np.int8)
        i = np.where(i > 7, i - 16, i).astype(np.float32)
        nq = np.where(q > 7, q - 16, q).astype(np.float32)
    else:
        a = np.frombuffer(raw, dtype=np.int8 if bits == 8 else "<i2")
        i = a[0::2].astype(np.float32)
        nq = a[1::2].astype(np.float32)
    return (i - 1j * nq).astype(np.complex64)  # words are (I, -Q)


def parse_header(buf: bytes) -> tuple:
    """Header fields (seq, index, samples, bits, flags, dec, gain, shift)."""
    if len(buf) < HEADER or buf[:4] != MAGIC:
        raise IqsError("bad IQS1 header")
    return struct.unpack_from("<IQHBBHBB", buf, 4)


def frame_length(samples: int, bits: int) -> int:
    return HEADER + payload_len(samples, bits) + 4


def parse_iqs1(buf: bytes) -> Frame:
    """Decode one complete frame (header + payload + CRC32); raises IqsError."""
    seq, index, samples, bits, flags, dec, gain, shift = parse_header(buf)
    if bits not in (4, 8, 16) or payload_len(samples, bits) > MAX_PAYLOAD:
        raise IqsError(f"bad frame geometry: {samples} samples, {bits} bits")
    n = frame_length(samples, bits)
    if len(buf) != n:
        raise IqsError(f"frame is {len(buf)} bytes, expected {n}")
    (crc,) = struct.unpack_from("<I", buf, n - 4)
    if zlib.crc32(buf[: n - 4]) != crc:
        raise IqsError("IQS1 CRC mismatch")
    iq = _decode(buf[HEADER : n - 4], samples, bits)
    return Frame(seq, index, samples, bits, flags, dec, gain, shift, iq)


def parse_iqsend(line: str | bytes) -> dict:
    if isinstance(line, bytes):
        line = line.decode("ascii", "replace")
    parts = line.split()
    if not parts or parts[0] != "IQSEND" or len(parts) != 1 + len(_END_FIELDS):
        raise IqsError(f"bad IQSEND line: {line!r}")
    try:
        return {k: int(v) for k, v in zip(_END_FIELDS, parts[1:])}
    except ValueError as e:
        raise IqsError(f"bad IQSEND field: {line!r}") from e


def check_allowed(rate_code: int, dec: int, bits: int) -> None:
    if (rate_code, dec, bits) not in ALLOWED:
        ok = ", ".join(f"dec {d}/{b}-bit" for (c, d, b) in sorted(ALLOWED) if c == rate_code)
        raise ValueError(
            f"rate_code {rate_code}, decimation {dec}, {bits}-bit exceeds the UART "
            f"link budget (docs/devkitv1/iq-stream-uart.md); allowed: {ok or 'none'}")


@dataclass
class Stats:
    frames: int = 0
    samples: int = 0
    bad_crc: int = 0
    resync_bytes: int = 0
    seq_gaps: int = 0          # frames missing by sequence number
    gap_samples: int = 0       # host-detected output samples lost (index jumps)
    gap_events: int = 0
    backward: int = 0          # index went backwards (not counted as loss)
    tail_samples: int = 0      # samples of a bad-CRC frame at the very end
    short_frames: int = 0      # frames cut short (bytes stopped mid-frame); resynced
    fw_pairs_lost: int = 0     # IQSEND loss field (input pairs)
    end: dict = field(default_factory=dict)
    dec: int = 1

    @property
    def fw_lost_samples(self) -> float:
        return self.fw_pairs_lost / self.dec

    @property
    def lost_samples(self) -> float:
        return self.gap_samples + self.tail_samples

    @property
    def crosscheck_warning(self) -> str | None:
        """IQSEND ffts/dec is a cross-check only (index jumps already include it)."""
        if abs(self.fw_lost_samples - self.gap_samples) > max(self.gap_events, 1):
            return (f"firmware reports {self.fw_lost_samples:.1f} lost samples "
                    f"({self.fw_pairs_lost} pairs / {self.dec}) but index gaps show "
                    f"{self.gap_samples} in {self.gap_events} events")
        return None

    @property
    def loss_fraction(self) -> float:
        tot = self.samples + self.lost_samples
        return self.lost_samples / tot if tot else 0.0


class _Short(Exception):
    """Bytes stopped arriving part-way through a read; they stay in the buffer."""


class _Reader:
    """Buffered reads with two deadlines: `timeout` for the first byte of a
    read (the stream may be idle) and `gap` once a read has started (a frame
    takes ~11 ms on the wire, so a longer pause means it was cut short, e.g.
    by a dropped USB chunk or the firmware ending the run mid-frame)."""

    GAP = 0.5

    def __init__(self, t, timeout):
        self.t, self.timeout, self.buf = t, timeout, bytearray()
        self.some = getattr(t, "read_some", None)

    def read(self, n):
        if len(self.buf) < n:
            if self.some is None:
                self.buf += self.t.read_exact(n - len(self.buf), self.timeout)
            else:
                while len(self.buf) < n:
                    first = not self.buf
                    try:
                        self.buf += self.some(n - len(self.buf),
                                              self.timeout if first else self.GAP)
                    except TimeoutError:
                        if first:
                            raise
                        raise _Short(f"short read {len(self.buf)}/{n}") from None
        b = bytes(self.buf[:n])
        del self.buf[:n]
        return b

    def push_back(self, b: bytes):
        self.buf[:0] = b

    def readline(self):
        if b"\n" in self.buf:
            i = self.buf.index(b"\n")
            b = bytes(self.buf[: i + 1])
            del self.buf[: i + 1]
            return b
        head = bytes(self.buf)
        self.buf.clear()
        return head + self.t.readline(self.timeout)


class IqsSession:
    """Run one IQS stream. Iterate `blocks()` for complex64 sample arrays;
    `stats` holds the loss accounting (final after iteration ends)."""

    def __init__(self, device, dec: int, bits: int, mhz: int, fofs_khz: int = 0, *,
                 rate_code: int = DEFAULT_RATE_CODE, seconds: float = 1.0, mode: int = 0,
                 shift: int | None = None):
        check_allowed(rate_code, dec, bits)
        if not -1000 <= fofs_khz <= 1000:
            raise ValueError("fofs must be within -1000..1000 kHz")
        if seconds < 0:
            raise ValueError("seconds must be >= 0")
        self.dev, self.dec, self.bits, self.mhz = device, dec, bits, mhz
        self.fofs_khz, self.rate_code, self.seconds, self.mode = fofs_khz, rate_code, seconds, mode
        self.shift = shift  # None = firmware default (15 - bits)
        self.stats = Stats(dec=dec)
        self.sample_rate = RATES[rate_code] // dec
        self.start_reply: list[str] = []

    def blocks(self, max_blocks: int | None = None):
        d = self.dev
        try:
            yield from self._blocks(max_blocks)
        finally:
            if self.fofs_khz:  # FOFS is sticky in firmware; do not leak it
                try:
                    d.command("FOFS 0")
                except Exception:
                    pass

    def _blocks(self, max_blocks):
        d, st = self.dev, self.stats
        d.tune(self.mhz)
        check_err(d.command(f"FOFS {self.fofs_khz}"))
        ms = int(round(self.seconds * 1000))
        cmd = f"IQS {ms} {self.dec} {self.bits} {self.rate_code}"
        if self.mode or self.shift is not None:
            sh = self.shift if self.shift is not None else (15 - self.bits if self.bits < 16 else 0)
            cmd += f" {sh} {self.mode}"
        reply = d.command(cmd)
        check_err(reply)
        p = reply.split()
        if len(p) != 7 or p[0] != "IQS" or int(p[2]) != self.dec or int(p[3]) != self.bits:
            raise d._resync_after(f"unexpected IQS start: {reply!r}")
        self.start_reply = p
        self.sample_rate = int(p[1])
        rd = _Reader(d.t, d.data_timeout + 1.0)
        expect_idx = expect_seq = None
        last_bad = 0
        stopped = False
        try:
            while True:
                try:
                    magic = rd.read(4)
                except _Short:
                    # 1-3 stray bytes and then silence: drop one, rescan
                    st.resync_bytes += 1
                    del rd.buf[:1]
                    continue
                if magic == END_MAGIC:
                    st.end = parse_iqsend(b"IQSE" + rd.readline())
                    break
                if magic != MAGIC:
                    # slip one byte and rescan
                    st.resync_bytes += 1
                    rd.push_back(magic[1:])
                    continue
                try:
                    head = rd.read(HEADER - 4)
                except _Short:
                    st.short_frames += 1
                    rd.push_back(magic[1:])
                    continue
                try:
                    _, _, samples, bits, *_ = parse_header(magic + head)
                    if bits != self.bits or payload_len(samples, bits) > MAX_PAYLOAD:
                        raise IqsError("bad geometry")
                except IqsError:
                    st.resync_bytes += 1
                    rd.push_back((magic + head)[1:])
                    continue
                try:
                    rest = rd.read(payload_len(samples, bits) + 4)
                except _Short:
                    # cut-short frame: the IQSEND line or the next frame may be
                    # inside what did arrive, so rescan it from the next byte
                    st.short_frames += 1
                    last_bad = samples
                    rd.push_back((magic + head)[1:])
                    continue
                raw = magic + head + rest
                try:
                    f = parse_iqs1(raw)
                except IqsError:
                    st.bad_crc += 1
                    last_bad = samples
                    rd.push_back(raw[4:])  # the real next frame may start inside
                    continue
                last_bad = 0
                if expect_idx is not None:
                    if f.index > expect_idx:
                        st.gap_samples += f.index - expect_idx
                        st.gap_events += 1
                    elif f.index < expect_idx:
                        st.backward += 1
                    if f.seq > expect_seq:
                        st.seq_gaps += f.seq - expect_seq
                expect_idx, expect_seq = f.index + f.samples, f.seq + 1
                st.frames += 1
                st.samples += f.samples
                yield f.iq, f
                if max_blocks and st.frames >= max_blocks and not stopped:
                    d.t.write(STOP_BYTE)
                    stopped = True
        except (TimeoutError, IqsError) as e:
            raise d._resync_after(f"IQS stream failed: {e}") from e
        st.tail_samples = last_bad
        st.fw_pairs_lost = st.end.get("ffts", 0)
        if st.end.get("status", 0) != 0:
            raise DeviceError(f"IQSEND status {st.end['status']}")
