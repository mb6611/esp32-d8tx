# SPDX-License-Identifier: GPL-3.0-or-later
import io
import json

import numpy as np
import pytest

from esp32sdr import d8, d8_cli


def test_phy_constants_from_registers():
    assert d8.BAUD == pytest.approx(31044, abs=1)
    assert d8.DEVIATION == pytest.approx(31738, abs=1)


def test_crc16_check_value():
    # poly 0x8005, init 0xFFFF, no reflection, no xorout (CRC-16/CMS): check value of "123456789"
    assert d8.crc16(b"123456789") == 0xAEE7


def test_packet_roundtrip_and_betaflight_packing():
    ch = [1501, 2250, 2251, 4095, 0, 1470, 3000, 17]
    raw = d8.build_packet((0x42, 0xB2), 9, ch)
    assert len(raw) == d8.PACKET_BYTES and raw[0] == 0x11
    p = d8.parse_packet(raw)
    assert p.crc_ok and p.tx_id == (66, 178) and p.counter == 9 and p.channels == ch
    # decodeChannelPair(): channels[0] = (packet[4+6] & 0xf) << 8 | packet[6], ...
    assert ((raw[10] & 0xF) << 8 | raw[6]) == ch[0]
    assert ((raw[11] & 0xF0) << 4 | raw[9]) == ch[3]
    assert ((raw[17] & 0xF0) << 4 | raw[15]) == ch[7]
    assert p.channels_us[0] == pytest.approx(1501 * 2 / 3)
    bad = bytearray(raw)
    bad[7] ^= 1
    assert not d8.parse_packet(bytes(bad)).crc_ok


def test_crc_fix1():
    raw = d8.build_packet(counter=3)
    bad = bytearray(raw)
    bad[12] ^= 0x10
    fixed, bit = d8.crc_fix1(bytes(bad))
    assert fixed == raw and bit == 12 * 8 + 3
    assert d8.crc_fix1(raw[:5]) is None


def test_find_sync_with_errors():
    bits = np.concatenate([np.zeros(40, np.uint8), d8.to_bits(d8.PREAMBLE + d8.SYNC), np.ones(8, np.uint8)])
    bits[40 + 32 + 3] ^= 1  # one sync bit wrong
    hits = d8.find_sync(bits, max_errors=2)
    assert (40 + 48, 1) in hits


def _packets(n, seed=1):
    rng = np.random.default_rng(seed)
    return [d8.build_packet(counter=i, channels=rng.integers(1400, 2300, 8)) for i in range(n)]


@pytest.mark.parametrize("dec,bits,cfo", [(128, 8, 5000), (128, 4, -8000), (64, 1, 10000)])
def test_standard_decoder_synthetic(dec, bits, cfo):
    pk = _packets(4)
    iq, fs, starts = d8.synth(pk, [0.02] * 4, cfo_hz=cfo, amp=5, noise=0.3, bits=bits, dec=dec, seed=2)
    res = d8.decode(iq, fs, method="standard")
    ok = [r for r in res if r.packet.crc_ok]
    assert len(ok) >= 3
    for r in ok:
        assert r.packet.raw in pk
        i = pk.index(r.packet.raw)
        assert r.t == pytest.approx(starts[i], abs=1 / d8.BAUD)
        assert r.cfo == pytest.approx(cfo, abs=1500)


def test_mlse_decoder_synthetic_two_samples_per_bit():
    # the recording format of the bench: dec 256 (62.5 kS/s, ~2 samples/bit), 4-bit, clipped
    pk = _packets(3, seed=4)
    iq, fs, starts = d8.synth(pk, [0.02] * 3, cfo_hz=1800, amp=12, noise=1.0, bits=4, dec=256, seed=5)
    assert fs == 62500
    res = d8.decode(iq, fs, dec=256, bits=4, cfo_range=(0, 4000))
    assert [r.method for r in res] == ["mlse"] * 3
    assert [r.packet.raw for r in res] == pk
    for r, s in zip(res, starts):
        assert r.t == pytest.approx(s, abs=0.2 / d8.BAUD)
        assert r.cfo == pytest.approx(1800, abs=150)


def test_model_matches_chain():
    """The MLSE lookup model reproduces the simulated receiver output (no noise, no quantizer)."""
    pk = d8.build_packet(counter=5)
    x = np.exp(1j * d8.gfsk_phase(d8.air_bits(pk), 1e6 / d8.BAUD, t0=300 / (1e6 / d8.BAUD), n=8000))
    cfo = 3000.0
    x = x * np.exp(2j * np.pi * cfo * np.arange(len(x)) / 1e6)
    y = d8.esp32_chain(x, 256)
    m = d8.Model(62500.0, 256)
    tau = (300 + 0.5) / 16  # bit 0 starts at input sample 300; +0.5 for the even-length FIR centre
    n, z = d8.synth_known(m.table(cfo), m.sps, d8.air_bits(pk), tau, 0, len(y), 62500.0, cfo, m.h, k_lo=4, k_hi=204)
    a = np.vdot(z, y[n]) / np.vdot(z, z)
    assert np.linalg.norm(y[n] - a * z) / np.linalg.norm(y[n]) < 0.01


def test_cli(tmp_path):
    pk = _packets(2, seed=7)
    iq, fs, _ = d8.synth(pk, [0.02] * 2, cfo_hz=2000, amp=5, noise=0.3, bits=8, dec=128, seed=8)
    data = tmp_path / "rec.sigmf-data"
    iq.astype("<c8").tofile(data)
    (tmp_path / "rec.sigmf-meta").write_text(json.dumps({"global": {"core:sample_rate": fs}}))
    out = io.StringIO()
    assert d8_cli.main([str(data)], out=out) == 0
    text = out.getvalue()
    assert "2 CRC ok (standard)" in text and " 66,178 " in text


def test_first_ok_single_packet_segments():
    """first_ok (hop-follow segments): one CRC-valid pass ends the decode, the cutoff order adapts,
    and an off-centre burst still decodes through a later (wider) cutoff."""
    pk = _packets(3, seed=11)
    dec = d8.StandardDecoder(250_000.0)
    for i, (p, cfo) in enumerate(zip(pk, (1000, -2000, 30000))):
        iq, fs, starts = d8.synth([p], [0.002], cfo_hz=cfo, amp=5, noise=0.3, bits=1, dec=64, seed=20 + i)
        full = [r for r in d8.StandardDecoder(fs).decode(iq) if r.packet.crc_ok]
        res = [r for r in dec.decode(iq, first_ok=True) if r.packet.crc_ok]
        assert [r.packet.raw for r in res] == [r.packet.raw for r in full] == [p]
        assert res[0].t == pytest.approx(starts[0], abs=1 / d8.BAUD)
        assert res[0].cfo == pytest.approx(full[0].cfo, abs=500)  # carrier as with all cutoffs
    assert sum(dec.wins.values()) == 3 and dec.wins.get(75e3) == 1  # 30 kHz off: only the wide one


def test_lerp_uniform_matches_interp():
    rng = np.random.default_rng(3)
    f = np.cumsum(rng.standard_normal(500))
    p = rng.uniform(-5, 505, (7, 40))
    assert np.allclose(d8._lerp_uniform(f, p), np.interp(p, np.arange(len(f)), f), rtol=0, atol=1e-9)
