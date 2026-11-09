"""FrSky D8 (CC2500) packet demodulator for the telemetry reply captures.

Vendored subset of host/esp32sdr/d8.py (standard decoder only: FM discriminator, M&M clock recovery,
sync search, CRC) so the d8tx package is self-contained. PHY constants from Betaflight
cc2500_frsky_shared.c (cc2500FrskyBaseConfig + cc2500FrskyDConfig): 31.044 kbaud GFSK, 4x 0xAA preamble,
sync D3 91, length 0x11, CRC-16 0x8005 init 0xFFFF.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

XTAL = 26e6
BAUD = XTAL * (256 + 0x39) * 2**0x0A / 2**28  # 31044.0 baud
DEVIATION = XTAL / 2**17 * (8 + (0x42 & 7)) * 2 ** ((0x42 >> 4) & 7)  # 31738 Hz
BT = 1.0
PREAMBLE = bytes([0xAA] * 4)
SYNC = bytes([0xD3, 0x91])
LENGTH = 0x11
PACKET_BYTES = 1 + LENGTH + 2  # length + payload + CRC

def crc16(data: bytes) -> int:
    """CC2500 CRC-16: poly 0x8005, init 0xFFFF, MSB first, no reflection."""
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x8005) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


# (low byte index, high-nibble byte index, nibble shift) per channel, packet
# indices counted from the length byte, as decodeChannelPair() reads them.

# (low byte index, high-nibble byte index, nibble shift) per channel, as decodeChannelPair() reads them.
_CH = [(6, 10, 0), (7, 10, 4), (8, 11, 0), (9, 11, 4), (12, 16, 0), (13, 16, 4), (14, 17, 0), (15, 17, 4)]
CHANNEL_SCALING = 2.0 / 3.0  # Betaflight FRSKY_D_CHANNEL_SCALING (raw -> us)


@dataclass
class Packet:
    raw: bytes
    crc_ok: bool
    tx_id: tuple[int, int]
    counter: int
    channels: list[int]  # raw 12-bit values

    @property
    def channels_us(self) -> list[float]:
        return [v * CHANNEL_SCALING for v in self.channels]


def parse_packet(raw: bytes) -> Packet:
    """raw = length byte + payload + 2 CRC bytes (PACKET_BYTES)."""
    raw = bytes(raw)
    body = raw[: 1 + LENGTH]
    crc_ok = len(raw) >= PACKET_BYTES and crc16(body) == (raw[1 + LENGTH] << 8 | raw[2 + LENGTH])
    ch = [((body[hi] >> sh) & 0xF) << 8 | body[lo] for lo, hi, sh in _CH]
    return Packet(raw, crc_ok, (body[1], body[2]), body[3], ch)


def to_bits(data: bytes) -> np.ndarray:
    return np.unpackbits(np.frombuffer(bytes(data), np.uint8))  # MSB first


def from_bits(bits) -> bytes:
    return np.packbits(np.asarray(bits, np.uint8)).tobytes()



# --------------------------------------------------------------- pipeline ----

PRE_SYNC_BITS = 8 * (len(PREAMBLE) + len(SYNC))  # 48
AIR_BITS = PRE_SYNC_BITS + 8 * PACKET_BYTES  # 208

@dataclass
class Result:
    t: float  # seconds, start of the preamble (first air bit)
    cfo: float  # Hz, burst carrier offset from the recording centre
    packet: Packet
    sync_errors: int  # bit errors in the 16-bit sync word as received
    score: float  # MLSE: prefix correlation (0..1); standard: preamble/sync match fraction
    bits: np.ndarray = field(repr=False, default=None)
    fixed_bit: int | None = None  # bit index flipped by crc_fix1, if any
    method: str = ""


def crc_fix1(raw: bytes) -> tuple[bytes, int] | None:
    """If exactly one single-bit flip of raw (PACKET_BYTES) makes the CRC valid, return (fixed, bit)."""
    raw = bytes(raw[:PACKET_BYTES])
    if len(raw) < PACKET_BYTES:
        return None
    hits = []
    for i in range(8 * PACKET_BYTES):
        b = bytearray(raw)
        b[i // 8] ^= 0x80 >> (i % 8)
        if crc16(bytes(b[: 1 + LENGTH])) == (b[1 + LENGTH] << 8 | b[2 + LENGTH]):
            hits.append((bytes(b), i))
    return hits[0] if len(hits) == 1 else None


def _finish(res: Result, fix1: bool) -> Result:
    if fix1 and not res.packet.crc_ok:
        f = crc_fix1(res.packet.raw)
        if f is not None:
            res.packet = parse_packet(f[0])
            res.fixed_bit = f[1]
    return res


def lowpass(fs: float, cutoff: float, ntaps: int = 63) -> np.ndarray:
    m = np.arange(ntaps) - (ntaps - 1) / 2
    h = np.sinc(2 * cutoff / fs * m) * np.hamming(ntaps)
    return h / h.sum()


def fm_demod(x: np.ndarray, fs: float) -> np.ndarray:
    """Quadrature discriminator: instantaneous frequency in Hz (same length as x)."""
    d = np.angle(x[1:] * np.conj(x[:-1])) * fs / (2 * np.pi)
    return np.concatenate([d[:1], d])


def mm_clock_recovery(d: np.ndarray, sps: float, *, mu: float = 0.5, gain_mu: float = 0.175,
                      omega_limit: float = 0.005) -> tuple[np.ndarray, np.ndarray]:
    """Mueller & Mueller symbol timing (as GNU Radio clock_recovery_mm_ff) on a +-1-ish real signal.

    Returns (symbol values, fractional sample positions)."""
    gain_omega = 0.25 * gain_mu * gain_mu
    omega = omega0 = float(sps)
    om_lo, om_hi = omega0 * (1 - omega_limit), omega0 * (1 + omega_limit)
    i = 0.0 + mu
    last_s, last_dec = 0.0, 0.0
    out, pos = [], []
    dl = np.asarray(d, float).tolist()  # plain floats: ~5x faster than numpy scalar indexing
    n = len(dl)
    while i < n - 2:
        k = int(i)
        f = i - k
        s = dl[k] * (1 - f) + dl[k + 1] * f
        dec = 1.0 if s >= 0 else -1.0
        err = last_dec * s - dec * last_s
        if err > 1.0:
            err = 1.0
        elif err < -1.0:
            err = -1.0
        last_s, last_dec = s, dec
        out.append(s)
        pos.append(i)
        omega += gain_omega * err
        if omega < om_lo:
            omega = om_lo
        elif omega > om_hi:
            omega = om_hi
        i += omega + gain_mu * err
    return np.array(out), np.array(pos)


def find_sync(bits: np.ndarray, max_errors: int = 2) -> list[tuple[int, int]]:
    """(index of the first bit after the sync word, sync bit errors), best match per region."""
    sync = to_bits(SYNC).astype(int)
    b = np.asarray(bits, int)
    if len(b) < 16:
        return []
    win = np.lib.stride_tricks.sliding_window_view(b, 16)
    err = np.sum(win != sync[None, :], axis=1)
    hits = []
    for i in np.where(err <= max_errors)[0]:
        if hits and i - hits[-1][0] + 16 < 8 * PACKET_BYTES:  # keep the best within one packet span
            if err[i] < hits[-1][1]:
                hits[-1] = (int(i) + 16, int(err[i]))
            continue
        hits.append((int(i) + 16, int(err[i])))
    return hits


class StandardDecoder:
    """Channel filter -> FM discriminator -> per-burst CFO (preamble mean) -> M&M clock recovery ->
    slicer -> sync correlation (<= max_sync_errors) -> length/CRC. Needs ~>= 4 samples per bit and the
    whole +-32 kHz deviation inside the passband (e.g. 125 kS/s hard-limited I/Q); at 62.5 kS/s the two
    tones alias onto each other and the discriminator output carries almost no information.

    The channel filter matters with hard-limited (1-bit) samples: the limiter spreads noise and
    harmonics over the whole band, so a filter just wider than the signal (~+-40 kHz for a centred
    burst) decodes far more packets than a wide one (bench, 1-bit dec 64 centred: 45 of 47 CRC-valid
    at 35-40 kHz, 30 at 75 kHz). A narrow filter cuts an off-centre signal, so by default the chain
    runs with several cutoffs (CUTOFFS, the last one the wide 0.45 fs / 75 kHz) and keeps, per burst,
    the first CRC-valid result. Pass ``cutoff`` (a number or a sequence) to override."""

    CUTOFFS = (40e3, 50e3, 35e3, 45e3)  # Hz, tried in this order before the wide default

    def __init__(self, fs: float, *, cutoff=None, max_sync_errors: int = 2, dump: float = 0.6,
                 dc_notch: int | None = None, shift_hz: float = 0.0):
        self.fs = fs
        self.shift_hz = shift_hz  # move the signal by -shift_hz first (e.g. fs/2 when it sits at the band edge)
        self.dump = dump  # fraction of each bit averaged by the slicer (0: one sample at the centre)
        # LO leakage removal: subtract a moving mean of this many samples (0/None = off; ~fs/4 kHz is a
        # ~4 kHz wide notch). It helps find bursts next to strong leakage but biases the carrier estimate.
        self.dc_notch = dc_notch or 0
        self.sps = fs / BAUD
        wide = min(0.45 * fs, 75e3)
        if cutoff is None:
            cuts = [c for c in self.CUTOFFS if c < wide] + [wide]
        else:
            cuts = list(np.atleast_1d(cutoff).astype(float))
        self.cutoffs = cuts
        self.cutoff = cuts[0]
        self.taps = self._taps(self.cutoff)
        self.max_sync_errors = max_sync_errors
        self.wins: dict[float, int] = {}  # first_ok: CRC-valid stops per cutoff

    def _taps(self, cutoff: float) -> np.ndarray:
        return lowpass(self.fs, cutoff) if cutoff < 0.5 * self.fs else np.array([1.0])

    def decode(self, iq: np.ndarray, *, fix1=False, track_bits: int = 32, first_ok: bool = False):
        """Runs the chain once per cutoff and merges per burst (results within 2 ms): a CRC-valid
        result beats a failed one, and among CRC-valid ones the widest filter wins (a narrow filter
        biases the carrier estimate of an off-centre burst). Sorted by time.

        first_ok: for input that holds at most one packet (a hop-follow channel segment): try the
        cutoffs in order of past success on this decoder and stop at the first pass that gives a
        CRC-valid result. Same decode rate on centred channels at ~1/4 of the CPU."""
        merged: list[tuple[Result, float]] = []
        cuts = self.cutoffs
        if first_ok:
            wins = self.wins
            cuts = sorted(cuts, key=lambda c: -wins.get(c, 0))  # stable: default order on ties
        for c in cuts:
            self.cutoff, self.taps = c, self._taps(c)
            for r in self._decode_once(iq, fix1=fix1, track_bits=track_bits):
                same = [i for i, (m, _) in enumerate(merged) if abs(m.t - r.t) < 2e-3]
                if not same:
                    merged.append((r, c))
                    continue
                m, mc = merged[same[0]]
                if r.packet.crc_ok and (not m.packet.crc_ok or c > mc):
                    merged[same[0]] = (r, c)
            if first_ok and any(r.packet.crc_ok for r, _ in merged):
                wins[c] = wins.get(c, 0) + 1
                break
        self.cutoff, self.taps = self.cutoffs[0], self._taps(self.cutoffs[0])
        wide = max(self.cutoffs)
        if any(c < wide and r.packet.crc_ok for r, c in merged):
            # carrier from the widest filter: mean discriminator output over the (balanced) preamble
            d = fm_demod(np.convolve(self._prep(iq), self._taps(wide), "same"), self.fs)
            n = int(len(PREAMBLE) * 8 * self.sps)
            for r, c in merged:
                if c < wide and r.packet.crc_ok:
                    i = int(round(r.t * self.fs))
                    if 0 <= i and i + n <= len(d):
                        r.cfo = float(np.mean(d[i : i + n]))
        return sorted((r for r, _ in merged), key=lambda r: r.t)

    def _prep(self, iq: np.ndarray) -> np.ndarray:
        x = np.asarray(iq, complex)
        x = x - x.mean()  # not the median: it is +-1 for hard-limited samples
        if self.shift_hz:
            x = x * np.exp(-2j * np.pi * self.shift_hz * np.arange(len(x)) / self.fs)
        if self.dc_notch and self.dc_notch > 1:
            x = x - np.convolve(x, np.ones(self.dc_notch) / self.dc_notch, "same")
        return x

    def _decode_once(self, iq: np.ndarray, *, fix1=False, track_bits: int = 32):
        """One pass with the current channel filter (no power gate: hard-limited I/Q has constant power)."""
        x = self._prep(iq)
        y = np.convolve(x, self.taps, "same")
        d = fm_demod(y, self.fs)
        # carrier offset: moving mean over track_bits (the preamble and the payload are near balanced)
        w = max(3, int(track_bits * self.sps))
        cfo = np.convolve(d, np.ones(w) / w, "same")
        sym, pos = mm_clock_recovery((d - cfo) / DEVIATION, self.sps)
        bits = (sym > 0).astype(np.uint8)
        pre = to_bits(PREAMBLE)
        out = []
        for start, err in find_sync(bits, self.max_sync_errors):
            body = bits[start : start + 8 * PACKET_BYTES]
            if len(body) < 8 * PACKET_BYTES or start < PRE_SYNC_BITS:
                continue
            i0 = start - PRE_SYNC_BITS
            pre_match = float(np.mean(bits[i0 : start - 16] == pre))
            if pre_match < 0.75:  # sync-like pattern in noise or payload
                continue
            # refine: fixed-rate bit grid fitted to the known preamble + sync (M&M jitters at ~4 samples/bit)
            t0, c, air = self._refine(d, pos[i0])
            pkt = parse_packet(from_bits(air[PRE_SYNC_BITS:]))
            if not pkt.crc_ok:
                alt = parse_packet(from_bits(body))
                pkt = alt if alt.crc_ok else pkt
            out.append(_finish(Result(t0 / self.fs, c, pkt, err, pre_match, air, method="standard"), fix1))
        return out


def _lerp_uniform(f: np.ndarray, p: np.ndarray) -> np.ndarray:
    """np.interp(p, arange(len(f)), f) (clamped at the ends), without the per-point search."""
    p = np.clip(p, 0.0, len(f) - 1.0)
    k = np.minimum(p.astype(np.intp), len(f) - 2)
    return f[k] + (p - k) * (f[k + 1] - f[k])


def _std_refine(self, d: np.ndarray, p0: float, span: float = 1.0, steps: int = 33):
    """Best start time (samples) near p0, carrier (preamble mean) and sliced air bits.
    All candidate start times are evaluated in one vectorized pass (rows of t0)."""
    known = 2.0 * to_bits(PREAMBLE + SYNC) - 1
    n = np.arange(AIR_BITS)
    t0s = p0 + np.linspace(-span, span, steps) * self.sps
    if self.dump > 0 and self.sps >= 3:
        cs = np.concatenate([[0.0], np.cumsum(d)])  # integrate-and-dump over the middle of each bit
        lo_f, hi_f = (0.5 - 0.5 * self.dump, 0.5 + 0.5 * self.dump)
        # cs[j] sits at sample time j - 0.5: linear interpolation on that uniform grid
        a = _lerp_uniform(cs, t0s[:, None] + (n + lo_f) * self.sps + 0.5)
        b = _lerp_uniform(cs, t0s[:, None] + (n + hi_f) * self.sps + 0.5)
        v = (b - a) / (self.dump * self.sps)
    else:
        v = np.interp(t0s[:, None] + (n + 0.5) * self.sps, np.arange(len(d)), d)
    c = np.mean(v[:, :32], axis=1)
    m = np.mean((v[:, :PRE_SYNC_BITS] - c[:, None]) * known, axis=1)
    k = int(np.argmax(m))  # first best, as the sequential search
    return t0s[k], float(c[k]), ((v[k] - c[k]) > 0).astype(np.uint8)


StandardDecoder._refine = _std_refine


