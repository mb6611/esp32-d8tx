# SPDX-License-Identifier: GPL-3.0-or-later
"""Decode raw CAP16/CAP20 capture payloads into complex64 samples."""
from __future__ import annotations

import numpy as np

# Rate code -> sample rate in Hz (docs/protocol.md).
RATES = {
    0: 80_000_000,
    1: 40_000_000,
    2: 20_000_000,
    3: 10_000_000,
    4: 8_000_000,
    5: 4_000_000,
    6: 16_000_000,
    7: 32_000_000,
    8: 10_666_667,
    9: 6_400_000,
}


def payload_size(samples: int, bits: int) -> int:
    """Bytes in a capture payload of ``samples`` I/Q pairs (bits per component)."""
    return -(-samples * bits * 2 // 8)


def decode_cap(raw: bytes, bits: int) -> np.ndarray:
    """Decode a capture payload (I, -Q pairs) to standard complex64 (I, Q).

    bits=8: CAP16, int8 I then int8 -Q. bits=10: CAP20, 10-bit signed I in
    bits 0-9 and -Q in bits 10-19, packed LSB first with no padding.
    Q is negated so RF above the LO appears at positive frequency.
    """
    if bits == 8:
        a = np.frombuffer(raw, dtype=np.int8)
        if a.size % 2:
            raise ValueError("8-bit payload has odd byte count")
        i = a[0::2].astype(np.float32)
        nq = a[1::2].astype(np.float32)
    elif bits == 10:
        n = len(raw) * 8 // 20
        if len(raw) != payload_size(n, 10):
            raise ValueError("10-bit payload length is not a whole number of samples")
        b = np.unpackbits(np.frombuffer(raw, dtype=np.uint8), bitorder="little")
        b = b[: n * 20].reshape(n * 2, 10).astype(np.int32)
        v = (b << np.arange(10)).sum(axis=1)
        v = np.where(v >= 512, v - 1024, v).astype(np.float32)
        i, nq = v[0::2], v[1::2]
    else:
        raise ValueError(f"unsupported bits: {bits}")
    return (i - 1j * nq).astype(np.complex64)


def pack_cap(iq_ints: np.ndarray, bits: int) -> bytes:
    """Inverse helper (for tests): complex ints (I, -Q as transmitted) -> payload."""
    i = iq_ints.real.astype(np.int32)
    q = iq_ints.imag.astype(np.int32)
    inter = np.empty(i.size * 2, dtype=np.int32)
    inter[0::2], inter[1::2] = i, q
    if bits == 8:
        return inter.astype(np.int8).tobytes()
    if bits == 10:
        v = (inter & 0x3FF).astype(np.uint16)
        bits_arr = ((v[:, None] >> np.arange(10)) & 1).astype(np.uint8).reshape(-1)
        return np.packbits(bits_arr, bitorder="little").tobytes()
    raise ValueError(f"unsupported bits: {bits}")
