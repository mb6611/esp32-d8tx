# SPDX-License-Identifier: GPL-3.0-or-later
import struct
import zlib

import numpy as np
import pytest

from esp32sdr.spectrum import SpecError, parse_spc1, parse_specend, psd


def make_frame(lg=8, codes=None, corrupt=False):
    n = 1 << lg
    codes = bytes(range(n)) if codes is None else codes
    hdr = struct.pack("<4sIQIHBBHBB", b"SPC1", 7, 1234567890123, 5000, 12, 1, 3, 9, lg, 2)
    body = hdr + codes
    crc = zlib.crc32(body) & 0xFFFFFFFF
    if corrupt:
        crc ^= 1
    return body + struct.pack("<I", crc)


def test_good_frame():
    f = parse_spc1(make_frame())
    assert (f.seq, f.first_sample, f.span, f.ffts, f.gain, f.drops) == (7, 1234567890123, 5000, 12, 3, 9)
    assert f.max_detector and not f.skipped and f.bins == 256
    assert f.codes[10] == 10 and f.db()[10] == 5.0


def test_bad_crc_and_magic_and_len():
    with pytest.raises(SpecError):
        parse_spc1(make_frame(corrupt=True))
    with pytest.raises(SpecError):
        parse_spc1(b"XXXX" + make_frame()[4:])
    with pytest.raises(SpecError):
        parse_spc1(make_frame()[:-1])


def test_specend():
    r = parse_specend("SPECEND 0 0 1 2 3 4 5 6 7 8 9 1")
    assert r["status"] == 0 and r["ffts"] == 9 and r["stopped_by_host"] == 1
    with pytest.raises(SpecError):
        parse_specend("SPECEND 0 1")


def test_psd_peak():
    fs, f0 = 1e6, 100e3
    t = np.arange(8192) / fs
    fr, p = psd(np.exp(2j * np.pi * f0 * t), fs, 1024)
    assert fr[np.argmax(p)] == pytest.approx(f0, abs=fs / 1024)
