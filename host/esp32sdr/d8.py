# SPDX-License-Identifier: GPL-3.0-or-later
"""Offline FrSky D8 (CC2500) packet decoder for esp32sdr stream recordings.

PHY, from Betaflight cc2500_frsky_shared.c (cc2500FrskyBaseConfig +
cc2500FrskyDConfig) and the CC2500 datasheet (SWRS040C):

- MDMCFG4 0xAA / MDMCFG3 0x39: DRATE_E 10, DRATE_M 57 ->
  R = (256 + 57) * 2^10 / 2^28 * 26 MHz = 31.044 kbaud; CHANBW_E 2, CHANBW_M 2
  -> RX filter 135 kHz.
- MDMCFG2 0x11: MOD_FORMAT 1 = GFSK (Gaussian BT = 1, datasheet 16.1),
  no Manchester, SYNC_MODE 1 = 15/16 sync word bits.
- MDMCFG1 0x23: NUM_PREAMBLE 2 = 4 preamble bytes (0xAA), no FEC.
- DEVIATN 0x42: E 4, M 2 -> 26 MHz / 2^17 * (8 + 2) * 2^4 = 31.738 kHz,
  so h = 2 * 31.738 / 31.044 = 2.045.
- SYNC1/SYNC0 not written -> reset defaults 0xD3 0x91.
- PKTCTRL0 0x05: no whitening, normal packet mode, CRC on, variable length.
- On air: preamble AA AA AA AA, sync D3 91, length 0x11, 17 bytes, CRC-16
  (x^16 + x^15 + x^2 + 1, init 0xFFFF, over length + payload, sent MSB
  first). Bits go out MSB first; '1' is the positive deviation.

Payload (cc2500_frsky_d.c, indices from the length byte): [1..2] TX id
(bindTxId), [3] counter, [6..17] eight 12-bit channels: low bytes at 6, 7,
8, 9, 12, 13, 14, 15, high nibbles in 10, 11, 16, 17. Betaflight scales a
raw value by 2/3 to microseconds.

Receiver chain (main/targets/esp32/iq_stream.c): 16 MS/s -> 16-pair boxcar
-> 1 MS/s -> Kaiser windowed-sinc FIR (L = min(12 * dec / 16, 256) taps,
beta 5.65, cutoff at the output Nyquist) decimating by dec / 16 -> rounded,
saturated n-bit I/Q (Q negated by the host, so 4-bit I is -8..7, Q -7..8).

Observed from the bench E8 transmitter (ch_on recording, Nov 2026): byte [3] is
always 0x00 and byte [4] is the packet counter (+47 per hop cycle), byte [5]
0x01; Betaflight's own field names say [3] is the counter.

Two decoders. StandardDecoder is the usual chain (channel filter -> FM
discriminator -> M&M clock recovery -> slicer -> sync correlation -> CRC),
for any fs with >= ~4 samples per bit and the full signal in band (e.g.
4/8-bit at dec 128, or 1-bit at dec 64; simulation shows 1-bit at 125 kS/s
fails: the -3rd harmonic of one tone aliases onto the other). MlseDecoder is
for the 62.5 kS/s (dec 256) recordings. It is model based: it builds the noiseless receiver output
for every 9-bit window of GFSK bits (that chain, with the burst's carrier
offset inside the filter) and runs a Viterbi search with per-survivor
carrier phase over the clipped samples. This works even at ~2 samples per
bit with both tones at the filter edge, where a plain FM discriminator
cannot tell the tones apart (63.5 kHz apart at 62.5 kS/s: they alias onto
each other).
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
CHANNEL_SCALING = 2.0 / 3.0  # Betaflight FRSKY_D_CHANNEL_SCALING (raw -> us)

# ---------------------------------------------------------------- packet ----


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
_CH = [(6, 10, 0), (7, 10, 4), (8, 11, 0), (9, 11, 4), (12, 16, 0), (13, 16, 4), (14, 17, 0), (15, 17, 4)]


def build_packet(tx_id=(0x42, 0xB2), counter=0, channels=(2250,) * 8, extra=(0x01, 0x00)) -> bytes:
    """Length byte + 17-byte payload + CRC (big endian). channels are raw 12-bit."""
    p = bytearray(1 + LENGTH)
    p[0] = LENGTH
    p[1], p[2] = tx_id
    p[3] = counter & 0xFF
    p[4], p[5] = extra
    for (lo, hi, sh), v in zip(_CH, channels):
        v = int(v) & 0xFFF
        p[lo] = v & 0xFF
        p[hi] |= (v >> 8) << sh
    c = crc16(bytes(p))
    return bytes(p) + bytes([c >> 8, c & 0xFF])


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


def air_bits(packet: bytes) -> np.ndarray:
    return to_bits(PREAMBLE + SYNC + packet)


# ------------------------------------------------------------ PHY model ----


def esp32_taps(dec: int) -> np.ndarray:
    """Stage-2 FIR of iq_stream.c make_taps (float, unity DC gain), at 1 MS/s."""
    d2 = dec // 16
    L = min(12 * d2, 256)
    fc = 0.5 / d2
    m = np.arange(L) - 0.5 * (L - 1)
    r = 2 * m / (L - 1)
    h = np.sinc(2 * fc * m) * np.i0(5.65 * np.sqrt(np.maximum(0.0, 1 - r * r)))
    return h / h.sum()


def _erf(x: np.ndarray) -> np.ndarray:
    """erf, Abramowitz & Stegun 7.1.26 (|error| < 1.5e-7); numpy only."""
    x = np.asarray(x, float)
    t = 1.0 / (1.0 + 0.3275911 * np.abs(x))
    y = 1 - t * (0.254829592 + t * (-0.284496736 + t * (1.421413741 + t * (-1.453152027 + t * 1.061405429)))) * np.exp(
        -x * x
    )
    return np.sign(x) * y


def _q(x: np.ndarray, bt: float = BT) -> np.ndarray:
    """Phase pulse in bits: integral of the Gaussian-filtered unit rect on [0, 1), rising 0 -> 1."""
    s = np.sqrt(np.log(2)) / (2 * np.pi * bt)

    def G(v):  # integral of 0.5 * (1 + erf(v / (s sqrt 2)))
        a = v / (s * np.sqrt(2))
        return 0.5 * (v + v * _erf(a) + s * np.sqrt(2 / np.pi) * np.exp(-a * a))

    x = np.asarray(x, float)
    return G(x) - G(x - 1)


def gfsk_phase(bits, sps: float, h: float = 2 * DEVIATION / BAUD, bt: float = BT, t0: float = 0.0, n: int | None = None):
    """Phase (rad) at sample times k / sps - t0 (in bits) for bit i starting at time i."""
    s = 2 * np.asarray(bits, float) - 1
    if n is None:
        n = int(np.ceil((len(s) + 2 + t0) * sps))
    t = np.arange(n) / sps - t0
    ph = np.zeros(n)
    for i, si in enumerate(s):
        x = t - i
        m = x > -1.5
        qq = np.ones(n)
        qq[m & (x < 2.5)] = _q(x[m & (x < 2.5)], bt)
        qq[~m] = 0.0
        ph += np.pi * h * si * qq
    return ph


def esp32_chain(x_1m: np.ndarray, dec: int, phase: int = 0) -> np.ndarray:
    """1 MS/s complex baseband -> FIR -> decimate by dec/16 (float, unquantized)."""
    taps = esp32_taps(dec)
    y = np.convolve(x_1m, taps, mode="full")[(len(taps) - 1) // 2 :][: len(x_1m)]  # centred: y(t) ~ x(t)
    return y[phase :: dec // 16]


def quantize(y: np.ndarray, bits: int = 4) -> np.ndarray:
    """Round + saturate like the firmware, in host convention (Q negated). bits=1: hard-limited signs (+-1)."""
    if bits == 1:
        return (np.where(y.real >= 0, 1.0, -1.0) + 1j * np.where(y.imag >= 0, 1.0, -1.0)).astype(np.complex64)
    hi = 2 ** (bits - 1) - 1
    i = np.clip(np.round(y.real), -hi - 1, hi)
    nq = np.clip(np.round(-y.imag), -hi - 1, hi)
    return (i - 1j * nq).astype(np.complex64)


def synth(packets, gaps_s, *, cfo_hz=0.0, amp=12.0, noise=1.0, dec=256, bits=4, h=None, seed=0, lead_s=0.0001,
          dc=0j):
    """Synthetic recording: each packet's air bits as GFSK at 1 MS/s through the ESP32 chain.

    packets: list of length+payload+CRC bytes; gaps_s: idle time before each. Returns
    (iq, fs, start_times_s)."""
    rng = np.random.default_rng(seed)
    h = 2 * DEVIATION / BAUD if h is None else h
    sps = 1e6 / BAUD
    chunks, starts, t = [], [], 0.0
    for pkt, gap in zip(packets, gaps_s):
        idle = int(gap * 1e6)
        chunks.append(np.zeros(idle, complex))
        t += idle / 1e6
        frac = rng.uniform(0, 1)
        bitsv = air_bits(pkt)
        lead = int(lead_s * 1e6)
        ph = gfsk_phase(bitsv, sps, h, t0=(lead + frac) / sps, n=lead + int((len(bitsv) + 1) * sps))
        ph += rng.uniform(0, 2 * np.pi)
        starts.append(t + (lead + frac + 0.5) / 1e6)  # +0.5: even-length FIR centre
        chunks.append(np.exp(1j * ph))
        t += len(ph) / 1e6
    chunks.append(np.zeros(5000, complex))
    x = np.concatenate(chunks)
    x = x * np.exp(2j * np.pi * cfo_hz * np.arange(len(x)) / 1e6)
    y = esp32_chain(amp * x, dec)
    y = y + noise * (rng.standard_normal(len(y)) + 1j * rng.standard_normal(len(y))) / np.sqrt(2) + dc
    return quantize(y, bits), 1e6 / (dec // 16), starts


# ------------------------------------------------------------ demodulator ----

W = 4  # window half width in bits: sample in bit k depends on bits k-W .. k+W
NU = 64  # sub-bit timing grid of the model tables


class Model:
    """Noiseless receiver output tables g[pattern, u] for one (h, cfo).

    pattern = bits k-W..k+W (MSB = oldest), u = position inside bit k on a
    NU grid; the output for a sample is A * exp(j(theta + 2 pi c t + Phi)) *
    g, Phi = pi h * sum of +-1 over bits before k-W."""

    _qcache: dict = {}

    def __init__(self, fs: float, dec: int, h: float = 2 * DEVIATION / BAUD, bt: float = BT):
        self.fs, self.dec, self.h, self.bt = fs, dec, h, bt
        self.sps = fs / BAUD  # output samples per bit
        taps = esp32_taps(dec)
        L = len(taps)
        self.taps = taps
        self.d_s = (np.arange(L) - 0.5 * (L - 1)) * 1e-6  # tap time offsets (s), 1 MS/s
        key = (dec, bt)
        if key not in Model._qcache:
            u = np.arange(NU) / NU
            tb = u[:, None] + self.d_s[None, :] * BAUD  # (NU, L) time in bits from start of bit k
            j = np.arange(-W, W + 1)
            Model._qcache[key] = _q(tb[:, :, None] - j[None, None, :], bt)  # (NU, L, 2W+1)
        Q = Model._qcache[key]
        P = 1 << (2 * W + 1)
        pats = ((np.arange(P)[:, None] >> np.arange(2 * W, -1, -1)[None, :]) & 1) * 2 - 1  # (P, 2W+1), col 0 oldest
        self.pat_s = pats
        psi = np.pi * h * np.einsum("ulj,pj->pul", Q, pats.astype(float))
        self.E = np.exp(1j * psi).astype(np.complex64)  # (P, NU, L)

    def table(self, cfo: float | np.ndarray) -> np.ndarray:
        """g for one cfo -> (P, NU), or for an array of cfos -> (Nc, P, NU)."""
        c = np.atleast_1d(np.asarray(cfo, float))
        tc = (self.taps[:, None] * np.exp(2j * np.pi * self.d_s[:, None] * c[None, :])).astype(np.complex64)
        g = np.tensordot(self.E, tc, axes=([2], [0]))  # (P, NU, Nc)
        g = np.moveaxis(g, 2, 0)
        return g[0] if np.ndim(cfo) == 0 else g


def _lookup(g: np.ndarray, pat, u: np.ndarray) -> np.ndarray:
    """g[pat, u] with u in [0, 1) linearly interpolated on the NU grid (the last cell wraps to u = 1
    using the same pattern, a small error at the bit edge)."""
    x = u * NU
    i0 = np.minimum(np.floor(x).astype(int), NU - 1)
    f = x - i0
    i1 = np.minimum(i0 + 1, NU - 1)
    return g[pat, i0] * (1 - f) + g[pat, i1] * f


def _clip(z: np.ndarray, bits: int) -> np.ndarray:
    hi = 2 ** (bits - 1) - 1
    return np.clip(z.real, -hi - 1, hi) + 1j * np.clip(z.imag, -hi, hi + 1)


def _pattern_index(bits: np.ndarray, k: np.ndarray) -> np.ndarray:
    """Pattern (bits k-W..k+W) per bit index k; out-of-range bits count as 0."""
    b = np.concatenate([np.zeros(W, int), np.asarray(bits, int), np.zeros(W + 1, int)])
    idx = np.zeros(len(k), int)
    for j in range(2 * W + 1):
        idx = (idx << 1) | b[k + j]
    return idx


@dataclass
class Fit:
    tau: float  # sample index (float, burst-local) of the start of bit 0
    cfo: float
    theta: float
    amp: complex
    dc: complex
    score: float = 0.0


def synth_known(g: np.ndarray, sps: float, bits, tau: float, n0: int, n1: int, fs: float, cfo: float, h: float,
                k_lo: int = 0, k_hi: int | None = None):
    """Unit-amplitude, zero-phase model for samples n0..n1-1 given all bits; returns (n, z) for samples whose
    bit index lies in [k_lo, k_hi)."""
    bits = np.asarray(bits, int)
    k_hi = len(bits) if k_hi is None else k_hi
    n = np.arange(n0, n1)
    tb = (n - tau) / sps
    k = np.floor(tb).astype(int)
    m = (k >= k_lo) & (k < k_hi)
    n, tb, k = n[m], tb[m], k[m]
    s = 2 * bits - 1
    cum = np.concatenate([[0], np.cumsum(s)])
    phi = np.pi * h * cum[np.clip(k - W, 0, len(bits))]
    z = _lookup(g, _pattern_index(bits, k), tb - k) * np.exp(1j * (phi + 2 * np.pi * cfo * (n - tau) / fs))
    return n, z


def viterbi(y: np.ndarray, g: np.ndarray, sps: float, fs: float, fit: Fit, h: float, nbits: int, bits_q: int,
            known: dict | None = None, track: float = 0.3):
    """MLSE over nbits air bits. known = {bit index: value} forced decisions.

    track: per-survivor carrier phase loop gain (0 = fixed phase). Returns the decided bits."""
    known = known or {}
    S = 1 << (2 * W)
    INF = 1e18
    metric = np.full(S, INF)
    metric[0] = 0.0  # bits before 0 taken as 0 (they only shape the edge samples, which are not scored)
    phase = np.zeros(S)  # pi*h*sum(s) before the window, per survivor
    theta = np.zeros(S)  # per-survivor carrier phase correction
    hist = np.zeros((nbits + W, S), np.int32)  # predecessor state
    n_all = np.arange(len(y))
    tb_all = (n_all - fit.tau) / sps
    for step in range(nbits + W):  # adding bit index b = step; scoring bit k = step - W
        b_idx = step
        k = step - W
        cand_bits = [known[b_idx]] if b_idx in known else [0, 1]
        if b_idx >= nbits:
            cand_bits = [0]
        new_metric = np.full(S, INF)
        new_prev = np.zeros(S, np.int32)
        new_phase = np.zeros(S)
        new_theta = np.zeros(S)
        if k >= 0:
            sel = np.where((tb_all >= k) & (tb_all < k + 1))[0]
            u = tb_all[sel] - k
            rot = fit.amp * np.exp(1j * (fit.theta + 2 * np.pi * fit.cfo * (sel - fit.tau) / fs))
        for b in cand_bits:
            pat = ((np.arange(S) << 1) | b)  # (S,) patterns over bits k-W..k+W
            ns = pat & (S - 1)
            msb = (pat >> (2 * W)) & 1
            ph_next = phase + np.pi * h * (2 * msb - 1) if step >= 2 * W else phase  # padding bits: no phase
            if k >= 0 and len(sel):
                z = _lookup(g, pat[:, None], u[None, :]) * rot[None, :] * np.exp(1j * (phase + theta))[:, None]
                zc = _clip(z + fit.dc, bits_q)
                e = y[sel][None, :] - zc
                bm = np.sum(np.abs(e) ** 2, axis=1)
                if track:
                    err = np.angle(np.sum(y[sel][None, :] * np.conj(z), axis=1) + 1e-12)
                    th_next = theta + track * err
                else:
                    th_next = theta
            else:
                bm = np.zeros(S)
                th_next = theta
            cand = metric + bm
            # add-compare-select: the two predecessors of a state differ in their oldest bit
            for half in (0, 1):
                m = ((np.arange(S) >> (2 * W - 1)) & 1) == half
                idx = np.where(m)[0]
                upd = cand[idx] < new_metric[ns[idx]]
                tgt = ns[idx][upd]
                src = idx[upd]
                new_metric[tgt] = cand[src]
                new_prev[tgt] = src
                new_phase[tgt] = ph_next[src]
                new_theta[tgt] = th_next[src]
        hist[step] = new_prev
        metric = new_metric - np.min(new_metric)
        phase = np.mod(new_phase, 2 * np.pi)
        theta = new_theta
    # traceback
    s = int(np.argmin(metric))
    out = np.zeros(nbits + W, int)
    for step in range(nbits + W - 1, -1, -1):
        out[step] = s & 1
        s = hist[step][s]
    return out[:nbits]


# --------------------------------------------------------------- pipeline ----

PRE_SYNC_BITS = 8 * (len(PREAMBLE) + len(SYNC))  # 48
AIR_BITS = PRE_SYNC_BITS + 8 * PACKET_BYTES  # 208


def find_bursts(iq: np.ndarray, fs: float, *, min_ms=5.0, max_ms=12.0, thresh_db=8.0, smooth=32):
    """(start, stop) sample pairs where smoothed power exceeds the noise floor by thresh_db."""
    x = iq - np.median(iq.real) - 1j * np.median(iq.imag)
    e = np.convolve(np.abs(x) ** 2, np.ones(smooth) / smooth, "same")
    on = e > np.median(e) * 10 ** (thresh_db / 10)  # floor: idle time is most of the recording
    d = np.diff(on.astype(np.int8))
    st = list(np.where(d == 1)[0] + 1)
    en = list(np.where(d == -1)[0] + 1)
    if on[0]:
        st.insert(0, 0)
    if on[-1]:
        en.append(len(on))
    return [(a, b) for a, b in zip(st, en) if min_ms * 1e-3 * fs <= b - a <= max_ms * 1e-3 * fs]


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


class MlseDecoder:
    """Model-based (MLSE) decoder for 2-sample/bit esp32sdr recordings (dec 256, 62.5 kS/s)."""

    def __init__(self, fs: float, dec: int, bits: int, h: float = 2 * DEVIATION / BAUD, cfo_range=(-40e3, 40e3),
                 cfo_step=2e3, bt: float = BT, track: float = 0.3, min_score: float = 0.45):
        self.fs, self.dec, self.qbits, self.h, self.track = fs, dec, bits, h, track
        self.min_score = min_score  # prefix correlation needed to decode a burst (real D8 bursts: 0.75-0.86)
        self.model = Model(fs, dec, h, bt)
        self.sps = self.model.sps
        self.cfo_grid = np.arange(cfo_range[0], cfo_range[1] + 1, cfo_step)
        self.tables = self.model.table(self.cfo_grid)
        self.prefix = to_bits(PREAMBLE + SYNC + bytes([LENGTH]))  # 56 known bits
        self._tcache: dict = {}

    def table(self, cfo: float) -> np.ndarray:
        key = round(cfo, 1)
        if key not in self._tcache:
            if len(self._tcache) > 64:
                self._tcache.clear()
            self._tcache[key] = self.model.table(cfo)
        return self._tcache[key]

    def _template(self, g, frac: float, nsamp: int):
        """Prefix template (unit amp, zero cfo phase) with bit 0 starting at sample frac."""
        n, z = synth_known(g, self.sps, self.prefix, frac, 0, nsamp, self.fs, 0.0, self.h, k_lo=W,
                           k_hi=len(self.prefix) - W)
        return n, z

    def acquire(self, y: np.ndarray, n_lo: int, n_hi: int, nfft: int = 1024, nfrac: int = 8):
        """Coarse search of start (integer + fraction) and cfo over the prefix. y has DC removed."""
        best = (-1.0, None)
        nsamp = int((len(self.prefix) + 1) * self.sps) + 2
        starts = np.arange(max(n_lo, 0), min(n_hi, len(y) - nsamp))
        if len(starts) == 0:
            return None
        for ci, c0 in enumerate(self.cfo_grid):
            g = self.tables[ci]
            for fi in range(nfrac):
                frac = fi / nfrac
                n, z = self._template(g, frac, nsamp)
                zn = z / np.linalg.norm(z)
                # y[start + n] * conj(z) * exp(-j 2 pi c0 (start+n)/fs) -> FFT over n for residual cfo
                Y = y[starts[:, None] + n[None, :]] * np.conj(zn)[None, :]
                Y = Y * np.exp(-2j * np.pi * c0 * n / self.fs)[None, :]
                F = np.abs(np.fft.fft(Y, nfft, axis=1))
                fr = np.fft.fftfreq(nfft, 1 / self.fs)
                step = self.cfo_grid[1] - self.cfo_grid[0] if len(self.cfo_grid) > 1 else self.fs
                F[:, np.abs(fr) > 0.6 * step] = 0  # residual cfo within the grid cell
                F /= np.linalg.norm(y[starts[:, None] + n[None, :]], axis=1)[:, None] + 1e-12
                i, j = np.unravel_index(np.argmax(F), F.shape)
                if F[i, j] > best[0]:
                    best = (F[i, j], (starts[i] + frac, c0 + fr[j], F[i, j]))
        return best[1]

    def refine(self, y: np.ndarray, tau: float, cfo: float, bits=None, k_lo=W, span=(0.25, 300.0), steps=(11, 11)):
        """Grid refine (tau, cfo) maximising |<y, model>| over known/decided bits; returns tau, cfo, a, corr."""
        bits = self.prefix if bits is None else bits
        k_hi = len(bits) - W
        best = (-1, tau, cfo, 0j)
        for c in cfo + np.linspace(-span[1], span[1], steps[1]):
            g = self.table(c)
            for t in tau + np.linspace(-span[0], span[0], steps[0]):
                n, z = synth_known(g, self.sps, bits, t, 0, len(y), self.fs, c, self.h, k_lo=k_lo, k_hi=k_hi)
                if len(n) == 0:
                    continue
                v = np.vdot(z, y[n])
                r = abs(v) / (np.linalg.norm(z) * np.linalg.norm(y[n]) + 1e-12)
                if r > best[0]:
                    best = (r, t, c, v / np.vdot(z, z))
        r, t, c, a = best
        return t, c, a, r

    def fit_amp(self, y, fit: Fit, bits, k_lo=W):
        """Pick |amp| minimising the clipped-model error (clipping biases the linear estimate low)."""
        g = self.table(fit.cfo)
        n, z = synth_known(g, self.sps, bits, fit.tau, 0, len(y), self.fs, fit.cfo, self.h, k_lo=k_lo,
                           k_hi=len(bits) - W)
        a0 = fit.amp
        best = (np.inf, a0)
        for m in np.exp(np.linspace(np.log(0.5), np.log(6), 40)):
            e = np.sum(np.abs(y[n] - _clip(m * a0 * z + fit.dc, self.qbits)) ** 2)
            if e < best[0]:
                best = (e, m * a0)
        fit.amp = best[1]
        return fit

    def decode_burst(self, y: np.ndarray, dc: complex, n_lo: int, n_hi: int, iters: int = 2):
        yc = y - dc
        acq = self.acquire(yc, n_lo, n_hi)
        if acq is None:
            return None
        tau, cfo, _ = acq
        tau, cfo, a, r = self.refine(yc, tau, cfo, span=(0.5, 400.0))
        tau, cfo, a, r = self.refine(yc, tau, cfo, span=(0.1, 60.0))
        if r < self.min_score:  # no D8 preamble/sync/length here
            return None
        fit = Fit(tau, cfo, 0.0, a, dc, r)
        self.fit_amp(y, fit, self.prefix)
        known = {i: int(b) for i, b in enumerate(self.prefix[:PRE_SYNC_BITS])}
        bits = None
        for it in range(iters + 1):
            bits = viterbi(y, self.table(fit.cfo), self.sps, self.fs, fit, self.h, AIR_BITS, self.qbits, known=known,
                           track=self.track)
            if it == iters:
                break
            # data-aided refinement over the whole decoded packet
            t, c, a, r = self.refine(yc, fit.tau, fit.cfo, bits=bits, span=(0.1, 40.0), steps=(5, 9))
            fit = Fit(t, c, 0.0, a, dc, r)
            self.fit_amp(y, fit, bits)
        pkt = parse_packet(from_bits(bits[PRE_SYNC_BITS:]))
        return fit, bits, pkt

    def decode(self, iq: np.ndarray, *, guard_ms=1.0, bursts=None, fix1=False):
        """Decode every burst; returns a list of Result (one per burst)."""
        out = []
        g = int(guard_ms * 1e-3 * self.fs)
        nair = int(AIR_BITS * self.sps)
        for a, b in find_bursts(iq, self.fs) if bursts is None else bursts:
            pre = iq[max(0, a - 300) : max(0, a - 20)]
            dc = complex(np.median(pre.real) + 1j * np.median(pre.imag)) if len(pre) > 50 else 0j
            lo = max(0, a - g)
            hi = min(len(iq), b + g)
            y = iq[lo:hi].astype(complex)
            # the packet starts anywhere from just before the power rise up to a packet length before its end
            r = self.decode_burst(y, dc, a - lo - 40, max(a - lo + 40, b - lo - nair + 40))
            if r is None:
                continue
            fit, bits, pkt = r
            fit.tau += lo
            sync_err = int(np.sum(bits[32:48] != to_bits(SYNC)))  # forced: always 0 here
            out.append(_finish(Result(fit.tau / self.fs, fit.cfo, pkt, sync_err, fit.score, bits, method="mlse"), fix1))
        return out


# ----------------------------------------------------- standard receiver ----


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
    omega = omega0 = sps
    i = 0.0 + mu
    last_s, last_dec = 0.0, 0.0
    out, pos = [], []
    n = len(d)
    while i < n - 2:
        k = int(i)
        f = i - k
        s = d[k] * (1 - f) + d[k + 1] * f
        dec = 1.0 if s >= 0 else -1.0
        err = last_dec * s - dec * last_s
        err = max(-1.0, min(1.0, err))
        last_s, last_dec = s, dec
        out.append(s)
        pos.append(i)
        omega += gain_omega * err
        omega = min(max(omega, omega0 * (1 - omega_limit)), omega0 * (1 + omega_limit))
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

    def _taps(self, cutoff: float) -> np.ndarray:
        return lowpass(self.fs, cutoff) if cutoff < 0.5 * self.fs else np.array([1.0])

    def decode(self, iq: np.ndarray, *, fix1=False, track_bits: int = 32):
        """Runs the chain once per cutoff and merges per burst (results within 2 ms): a CRC-valid
        result beats a failed one, and among CRC-valid ones the widest filter wins (a narrow filter
        biases the carrier estimate of an off-centre burst). Sorted by time."""
        merged: list[tuple[Result, float]] = []
        for c in self.cutoffs:
            self.cutoff, self.taps = c, self._taps(c)
            for r in self._decode_once(iq, fix1=fix1, track_bits=track_bits):
                same = [i for i, (m, _) in enumerate(merged) if abs(m.t - r.t) < 2e-3]
                if not same:
                    merged.append((r, c))
                    continue
                m, mc = merged[same[0]]
                if r.packet.crc_ok and (not m.packet.crc_ok or c > mc):
                    merged[same[0]] = (r, c)
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


def _std_refine(self, d: np.ndarray, p0: float, span: float = 1.0, steps: int = 33):
    """Best start time (samples) near p0, carrier (preamble mean) and sliced air bits."""
    known = 2.0 * to_bits(PREAMBLE + SYNC) - 1
    n = np.arange(AIR_BITS)
    idx = np.arange(len(d))
    best = None
    cs = np.concatenate([[0.0], np.cumsum(d)])  # integrate-and-dump over the middle of each bit
    cidx = np.arange(len(cs)) - 0.5
    lo_f, hi_f = (0.5 - 0.5 * self.dump, 0.5 + 0.5 * self.dump)
    for t0 in p0 + np.linspace(-span, span, steps) * self.sps:
        if self.dump > 0 and self.sps >= 3:
            a = np.interp(t0 + (n + lo_f) * self.sps, cidx, cs)
            b = np.interp(t0 + (n + hi_f) * self.sps, cidx, cs)
            v = (b - a) / (self.dump * self.sps)
        else:
            v = np.interp(t0 + (n + 0.5) * self.sps, idx, d)
        c = float(np.mean(v[:32]))
        m = float(np.mean((v[:PRE_SYNC_BITS] - c) * known))
        if best is None or m > best[0]:
            best = (m, t0, c, ((v - c) > 0).astype(np.uint8))
    return best[1], best[2], best[3]


StandardDecoder._refine = _std_refine


def decode(iq: np.ndarray, fs: float, *, dec: int | None = None, bits: int | None = None, method: str = "auto",
           fix1: bool = False, **kw) -> list[Result]:
    """Decode D8 packets from complex I/Q at any fs. method 'standard', 'mlse' (esp32sdr chain model;
    needs dec and bits) or 'auto' (standard at >= 3 samples/bit, else mlse when dec/bits are known)."""
    if method == "auto":
        method = "standard" if fs / BAUD >= 3 or dec is None or bits is None else "mlse"
    if method == "standard":
        return StandardDecoder(fs, **kw).decode(iq, fix1=fix1)
    if method == "mlse":
        return MlseDecoder(fs, dec, bits, **kw).decode(iq, fix1=fix1)
    raise ValueError(f"unknown method {method}")
