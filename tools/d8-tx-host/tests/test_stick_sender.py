import csv, os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import stick_sender as ss


class FakePort:
    def __init__(self): self.out = []
    def write(self, b): self.out.append(b.decode())


class FakeClock:
    def __init__(self): self.t = 0.0
    def __call__(self): return self.t
    def sleep(self, d): self.t += d


class T(unittest.TestCase):
    def test_build_line_clamps_and_forces_ch7(self):
        line, ch = ss.build_line([0, 3000, 1500, 1500, 1500, 1500, 2000, 1500])
        self.assertEqual(line, "S 1000 2000 1500 1500 1500 1500 1000 1500\n")

    def test_pattern_square(self):
        p = ss.PatternInput(2.0, 200)
        self.assertEqual(p.read(0.1)[1], 1700)
        self.assertEqual(p.read(1.1)[1], 1300)
        self.assertEqual(p.read(0.1)[6], 1000)

    def test_run_rate_log_and_unkey(self):
        port, c = FakePort(), FakeClock()
        with tempfile.TemporaryDirectory() as d:
            lp = os.path.join(d, "l.csv")
            n = ss.run(port, ss.PatternInput(), duration=1.0, log_path=lp, clock=c, sleep=c.sleep)
            rows = list(csv.reader(open(lp)))
        self.assertTrue(110 <= n <= 112)  # one second at the ~111.2 Hz slot rate
        self.assertEqual(len(rows), n + 1)
        self.assertEqual(port.out[-1], "U\n")
        self.assertTrue(all(l.startswith("S ") for l in port.out[:-1]))

    def test_deadlines_one_write_each_and_stats(self):
        port, c = FakePort(), FakeClock()
        ss.run(port, ss.PatternInput(), duration=0.5, clock=c, sleep=c.sleep)
        st = ss.run.stats
        self.assertAlmostEqual(st["achieved_hz"], ss.RATE_HZ, delta=0.5)
        self.assertAlmostEqual(st["max_gap_ms"], ss.SLOT_S * 1000, delta=0.01)

    def test_late_clock_no_burst(self):
        port, c = FakePort(), FakeClock()
        real_read = ss.PatternInput.read
        class Slow(ss.PatternInput):
            def read(s, t):
                c.t += 0.05  # stall 50 ms
                return real_read(s, t)
        ss.run(port, Slow(), duration=0.5, clock=c, sleep=c.sleep)
        self.assertLessEqual(ss.run.stats["sent"], 11)

    def test_selftest_realtime(self):
        n = ss.run(ss.NullWriter(), ss.PatternInput(), duration=0.5)
        self.assertGreaterEqual(ss.run.stats["achieved_hz"], 108)

    def test_rate_limit(self):
        with self.assertRaises(ValueError):
            ss.run(FakePort(), ss.PatternInput(), duration=0.1, rate=112)
        port, c = FakePort(), FakeClock()
        n = ss.run(port, ss.PatternInput(), duration=1.0, rate=111, clock=c, sleep=c.sleep)
        self.assertTrue(110 <= n <= 112)

    def test_ctrl_c_sends_u(self):
        class Boom:
            def read(self, t): raise KeyboardInterrupt
        port = FakePort()
        ss.run(port, Boom())
        self.assertEqual(port.out, ["U\n"])


if __name__ == "__main__":
    unittest.main()
