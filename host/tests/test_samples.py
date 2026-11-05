# SPDX-License-Identifier: GPL-3.0-or-later
import numpy as np
import pytest

from esp32sdr.samples import RATES, decode_cap, pack_cap, payload_size


def _peak_freq(iq, fs):
    f = np.fft.fftfreq(iq.size, 1 / fs)
    return f[np.argmax(np.abs(np.fft.fft(iq)))]


@pytest.mark.parametrize("bits,amp", [(8, 100), (10, 400)])
def test_tone_positive_after_q_negation(bits, amp):
    fs, f0, n = 16e6, 1e6, 4096
    t = np.arange(n) / fs
    tone = amp * np.exp(2j * np.pi * f0 * t)
    # transmitted stream carries (I, -Q)
    tx = np.round(tone.real) + 1j * np.round(-tone.imag)
    iq = decode_cap(pack_cap(tx, bits), bits)
    assert iq.dtype == np.complex64
    assert _peak_freq(iq, fs) == pytest.approx(f0, abs=fs / n)


def test_10bit_roundtrip_all_values():
    v = np.arange(-512, 512)
    tx = v + 1j * v[::-1]
    raw = pack_cap(tx, 10)
    assert len(raw) == payload_size(tx.size, 10)
    iq = decode_cap(raw, 10)
    assert np.array_equal(iq.real, v)
    assert np.array_equal(iq.imag, -v[::-1])


def test_8bit_signed():
    iq = decode_cap(bytes([0xFF, 0x80, 1, 2]), 8)
    assert iq[0] == complex(-1, 128) and iq[1] == complex(1, -2)


def test_bad_bits_and_rates():
    with pytest.raises(ValueError):
        decode_cap(b"", 12)
    assert RATES[0] == 80_000_000 and RATES[6] == 16_000_000
