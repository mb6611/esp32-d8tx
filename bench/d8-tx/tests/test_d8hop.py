import os, sys, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "host"))
import d8hop as h
import d8_vectors as v
try:
    import hopfollow, d8
except ImportError:  # no numpy: cross-checks skipped
    hopfollow = d8 = None
need = unittest.skipIf(hopfollow is None, 'd8 decoder needs numpy')


class T(unittest.TestCase):
    @need
    def test_table_matches_hopfollow(self):
        t = h.table()
        self.assertEqual(t, hopfollow.D8_TABLE)
        self.assertEqual(len(t), 47)
        self.assertEqual(len(set(t)), 47)
        self.assertEqual(t[0], 0)
        self.assertTrue(max(t) < 256)

    def test_hz(self):
        self.assertEqual(h.channel_hz(0), 2404e6)
        self.assertAlmostEqual(h.channel_hz(228), 2404e6 + 228 * 299.93e3)
        for n in h.table():
            if hopfollow: self.assertAlmostEqual(h.channel_hz(n), hopfollow.d8_channel_hz(n, 0), delta=1e-3)
            self.assertLessEqual(h.channel_hz(n), 2478e6)
        self.assertEqual(h.channel_khz(228), 2472384)

    def test_build_matches_vectors(self):
        for c in (0, 1, 46, 255, 300):
            for chs in ((2250,) * 8, (0, 1, 0xFFF, 0x123, 0x456, 0x789, 0xABC, 0xDEF)):
                self.assertEqual(h.build(c, chs), v.build(c, chs))

    @need
    def test_build_matches_d8py_layout3(self):
        chs = (1, 2, 3, 0xFFF, 0x800, 0x123, 5, 6)
        self.assertEqual(h.build(7, chs, counter_index=3),
                         d8.build_packet(counter=7, channels=chs))

    def test_roundtrip(self):
        chs = (0, 1, 0xFFF, 0x123, 0x456, 0x789, 0xABC, 0xDEF)
        for ci in (3, 4):
            r = h.parse(h.build(200, chs, counter_index=ci), ci)
            self.assertTrue(r["crc_ok"])
            self.assertEqual((r["counter"], r["channels"], r["tx_id"]), (200, list(chs), h.E8_ID))
        p = bytearray(h.build(1)); p[7] ^= 1
        self.assertFalse(h.parse(bytes(p))["crc_ok"])
        self.assertIsNone(h.parse(b"\x11" * 5))

    @need
    def test_cross_parse_d8py(self):
        chs = (1500 * 3 // 2,) * 8
        r = d8.parse_packet(h.build(9, chs, counter_index=3))
        self.assertTrue(r.crc_ok)
        self.assertEqual((r.counter, r.channels), (9, list(chs)))

    def test_us(self):
        self.assertEqual(h.us_to_raw(1500), 2250)
        self.assertEqual(h.raw_to_us(2250), 1500)

    def test_bad_input(self):
        with self.assertRaises(ValueError): h.build(0, (0x1000,) * 8)
        with self.assertRaises(ValueError): h.build(0, (0,) * 7)


if __name__ == "__main__":
    unittest.main()
