import os
import random
import sys
import unittest

HOST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, HOST)
import hop_capture as hc  # noqa: E402
import d8hop  # noqa: E402

TABLE = hc.default_table()
STICKS = (2250, 1500, 3000, 2250, 100, 4095, 2250, 2250)


def synth(nslots, drop=(), corrupt=(), counter0=0, prefix=""):
    lines = []
    for s in range(nslots):
        if s in drop:
            continue
        raw = bytearray(d8hop.build(counter0 + s, STICKS)[:18])
        if s in corrupt:
            raw[5] ^= 0x10
        lines.append(f"{prefix}P,{s},{s * 9000},{len(raw)},{raw.hex().upper()},{200 + s % 5},60,{0 if s in corrupt else 1},{'na' if s % 2 else -s},{TABLE[s % 47]},{s}")
    return lines


class T(unittest.TestCase):
    def test_clean(self):
        recs = hc.parse_log(["H,proto=6,mode=hop"] + synth(94, prefix="1.5 "))
        self.assertEqual(len(recs), 94)
        self.assertEqual(recs[3].counter, 3)
        self.assertEqual(recs[0].sticks, list(STICKS))
        st = hc.analyze(recs, TABLE)
        self.assertEqual((st["slots"], st["received"], st["longest_loss_run"]), (94, 94, 0))
        self.assertEqual(st["counter_discontinuities"], 0)
        self.assertEqual(st["chan_mismatch"], 0)
        self.assertEqual(st["tx_ids"], ["42B2"])
        self.assertTrue(all(v["rate"] == 1 and v["expected"] == 2 for v in st["per_channel"].values()))

    def test_loss_and_counter(self):
        drop = {10, 11, 12, 50}
        st = hc.analyze(hc.parse_log(synth(94, drop=drop, corrupt={20})), TABLE)
        self.assertEqual(st["received"], 94 - 5)
        self.assertEqual(st["longest_loss_run"], 3)
        self.assertEqual(st["longest_loss_start_slot"], 10)
        self.assertEqual(st["counter_discontinuities"], 0)  # counter tracks slots
        self.assertEqual(st["invalid_records"], 1)
        self.assertEqual(st["per_channel"][TABLE[10]]["received"], 1)

    def test_counter_break_and_wrap(self):
        lines = synth(300, counter0=200)  # wraps through 255
        self.assertEqual(hc.analyze(hc.parse_log(lines), TABLE)["counter_discontinuities"], 0)
        recs = hc.parse_log(synth(20))
        recs[10].counter += 5
        self.assertEqual(hc.analyze(recs, TABLE)["counter_discontinuities"], 2)

    def test_trailing_loss_with_total_slots(self):
        st = hc.analyze(hc.parse_log(synth(40)), TABLE, total_slots=47)
        self.assertEqual((st["slots"], st["longest_loss_run"]), (47, 7))

    def test_real_format(self):
        raw = d8hop.build(7, STICKS)[:18].hex().upper()
        lines = ["E,LOCK,1", "E,RESYNC,2", f"3.1 P,1,100,18,{raw},200,60,1,-12,{TABLE[0]},0",
                 f"P,2,200,18,{raw},200,60,1,na,{TABLE[1]},1", f"P,3,300,18,{raw},200,60,1,{TABLE[2]},2",
                 f"P,4,400,18,{raw},200,60,0,5,{TABLE[3]},3"]
        recs = hc.parse_log(lines)
        self.assertEqual([r.freqest for r in recs], [-12, None, None, 5])
        self.assertEqual([r.valid for r in recs], [True, True, True, False])
        self.assertEqual((recs[0].counter, recs[0].sticks), (7, list(STICKS)))

    def test_bad_lines_ignored_and_rssi(self):
        self.assertEqual(hc.parse_log(["E,1,2,3", "P,garbage", ""]), [])
        self.assertEqual(hc.rssi_dbm(0xF0), -8 - 72.0)
        self.assertEqual(hc.rssi_dbm(100), -22.0)

    def test_plot(self):
        try:
            import matplotlib  # noqa: F401
        except ImportError:
            self.skipTest("no matplotlib")
        import tempfile
        import hop_plot
        random.seed(1)
        recs = hc.parse_log(synth(200, drop=set(random.sample(range(200), 15))))
        out = os.path.join(tempfile.mkdtemp(), "m.png")
        hop_plot.plot(recs, TABLE, out)
        self.assertGreater(os.path.getsize(out), 5000)


if __name__ == "__main__":
    unittest.main()
