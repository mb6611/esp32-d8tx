"""Offline checks of tlm_misses.py on synthetic captures: a full reply is 'hit' with a high template
correlation and zero soft-bit sign errors, noise only is 'a', a reply cut by the window end is 'c',
and wideband noise bursts are 'b' without a template hit."""
import os
import sys
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "host"))

import tlm_listen  # noqa: E402
import tlm_misses as tm  # noqa: E402
import d8  # noqa: E402

FS = 500e3
N = 4500  # 9 ms, as cap_us 9000 at dec 32


def capture(gap_s, *, tid=5, noise=25.0, seed=1):
    fr = tm.reply_template(tid, rssi=0x46)
    iq, fs, _ = d8.synth([fr], [gap_s], cfo_hz=-35e3, amp=2000.0, noise=noise, dec=32, bits=16, seed=seed)
    assert fs == FS
    x = np.zeros(N, complex)
    rng = np.random.default_rng(seed + 100)
    x += noise * (rng.standard_normal(N) + 1j * rng.standard_normal(N))
    m = min(N, len(iq))
    x[:m] = iq[:m]
    return x, fr


def run_one(iq, tid=5):
    bl, _, _ = tm.bursts(iq, FS, floor=2 * 25.0 ** 2)
    tel = [h for h in tlm_listen.decode_capture(iq, FS) if h["telemetry"]]
    return tm.classify(bl, len(iq) / FS, bool(tel)), tel, tm.template_corr(iq, FS, tid)[0]


class TestTlmMisses(unittest.TestCase):
    def test_hit(self):
        iq, fr = capture(0.0014)
        cls, tel, corr = run_one(iq)
        self.assertEqual(cls, "hit")
        self.assertGreater(corr, 0.7)
        m = tm.soft_margin(iq, FS, tel[0]["shift_hz"], tel[0]["t_ms"] / 1e3, tm._with_crc(tel[0]["hex"]))
        self.assertEqual(m["sign_errors"], 0)
        self.assertGreater(m["eye_min"], 0.3)
        self.assertEqual(tm._with_crc(tel[0]["hex"]), fr)

    def test_noise_only(self):
        rng = np.random.default_rng(3)
        iq = 25.0 * (rng.standard_normal(N) + 1j * rng.standard_normal(N))
        cls, _, corr = run_one(iq)
        self.assertEqual(cls, "a")
        self.assertLess(corr, tm.CORR_PRESENT)

    def test_cut_by_window_end(self):
        iq, _ = capture(0.0060)  # starts ~6 ms in: only ~3 ms of 6.7 ms fit
        cls, tel, _ = run_one(iq)
        self.assertEqual(cls, "c")
        self.assertFalse(tel)

    def test_wideband_burst(self):
        rng = np.random.default_rng(4)
        iq = 25.0 * (rng.standard_normal(N) + 1j * rng.standard_normal(N))
        iq[1300:1950] += 1200.0 * (rng.standard_normal(650) + 1j * rng.standard_normal(650))
        cls, _, corr = run_one(iq)
        self.assertEqual(cls, "b")
        self.assertLess(corr, tm.CORR_PRESENT)
        self.assertLess(tm.band_fraction(iq[1300:1950], FS), 0.5)


if __name__ == "__main__":
    unittest.main()
