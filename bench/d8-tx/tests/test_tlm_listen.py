"""Offline check of tlm_listen.py: a synthetic D8 telemetry frame, packed like the firmware's
EV tlm payload (int16 LE I,Q, Q not negated), is found CRC-valid with its fields."""
import os
import sys
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "host"))
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "host"))

import tlm_listen  # noqa: E402
from esp32sdr import d8  # noqa: E402


def telemetry_frame(a1=84, a2=0, rssi=0xB0, hub=b"\x5e\x24\x01\x00\x5e", tid=3) -> bytes:
    body = bytes([0x11, 66, 178, a1, a2, rssi, len(hub), tid]) + hub
    body = body + bytes(18 - len(body))
    c = d8.crc16(body)
    return body + bytes([c >> 8, c & 0xFF])


def to_wire(iq: np.ndarray) -> bytes:
    """Host convention (Q negated) back to the firmware's raw sums."""
    a = np.stack([np.round(iq.real), np.round(-iq.imag)], 1).astype("<i2")
    return a.tobytes()


class TestTlmListen(unittest.TestCase):
    def test_decode_offset_frame(self):
        fr = telemetry_frame()
        iq, fs, starts = d8.synth([fr], [0.0016], cfo_hz=-60e3, amp=300.0, noise=40.0, dec=32, bits=16, seed=1)
        self.assertEqual(fs, 500e3)
        raw = to_wire(iq)
        back = tlm_listen.load_iq(raw, len(iq))
        np.testing.assert_allclose(back, np.round(iq.real) + 1j * np.round(iq.imag))
        hits = [h for h in tlm_listen.decode_capture(back, fs) if h["telemetry"]]
        self.assertTrue(hits)
        h = hits[0]
        self.assertEqual((h["a1"], h["a2"], h["rssi_dbm"], h["hub_count"], h["telemetry_id"]), (84, 0, 0xB0 - 256, 5, 3))
        self.assertEqual(h["hub"], "5e2401005e")
        self.assertAlmostEqual(h["t_ms"], starts[0] * 1e3, delta=0.1)
        self.assertLess(abs(h["cfo_hz"] + 60e3), 8e3)

    def test_noise_only(self):
        rng = np.random.default_rng(0)
        x = 30 * (rng.standard_normal(5000) + 1j * rng.standard_normal(5000))
        self.assertEqual([h for h in tlm_listen.decode_capture(x, 500e3) if h["telemetry"]], [])
        s = tlm_listen.stats(x, 500e3)
        self.assertIn("rms", s)


if __name__ == "__main__":
    unittest.main()
