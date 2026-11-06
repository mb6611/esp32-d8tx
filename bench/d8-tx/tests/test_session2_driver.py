"""Offline mocked tests for results/packet/freqest/session2_driver.py (no ports, no RF)."""
import importlib.util, json, os, re, sys, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
FE = os.path.join(HERE, "..", "results", "packet", "freqest")
REL = os.path.join(HERE, "..", "results", "packet", "reliability")
sys.path.insert(0, os.path.join(HERE, "..", "host")); sys.path.insert(0, os.path.join(HERE, "..", "results", "packet"))
import attempts as at
import batch_gate as g
from test_d8_attempts import BODY

spec = importlib.util.spec_from_file_location("session2_driver", os.path.join(FE, "session2_driver.py"))
sd = importlib.util.module_from_spec(spec); spec.loader.exec_module(sd)
H5 = ("H,proto=5,mode=pkt,fw=9709091a,bf=948ba63,freq_req_khz=2412000,duration_ms=11000,quiet_us=2000")


def conv(src, dst):
    """Rewrite a real proto=4 control log into a proto=5 / fw 9709091a log with 9-field P records."""
    out = []
    for l in open(src):
        l = l.replace("proto=4", "proto=5").replace("fw=c5cc593b", "fw=9709091a")
        if re.match(r"^\S+ P,", l):
            l = l.rstrip("\n") + ",%d\n" % (len(out) % 7 - 3)
        out.append(l)
    open(dst, "w").writelines(out)


def mkprior(rel, n, keyed="keyed=0", ok=True):
    for x, c in (("batch%d_envelope.json.used", "{}"), ("batch%d_stm.txt", "1.0 X,1,2,done\n"),
                 ("batch%d_hashes.txt", ""), ("source_off_batch%d_2412000.txt", ""),
                 ("post_batch%d_esp.txt", "STAT 'x %s'\n" % keyed)):
        open(rel + x % n, "w").write(c)
    os.makedirs(rel + "batch%d_esp_out" % n)
    json.dump({"attempts": [{"i": i, "ok": ok} for i in range(10)]}, open(rel + "batch%d_esp_out/attempts.json" % n, "w"))


class Paths(unittest.TestCase):
    def test_paths_unique_under_freqest(self):
        a, b = sd.paths_for(1), sd.paths_for(2)
        for k in a:
            self.assertTrue(a[k].startswith("bench/d8-tx/results/packet/freqest/"))
            self.assertNotEqual(a[k], b[k])
        self.assertEqual(len(set(a.values())), len(a))

    def test_approval_required(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(sd.Stop): sd.load_approved_at(d + "/none.json")
            p = d + "/a.json"; json.dump({"approved_at": 123}, open(p, "w"))
            self.assertEqual(sd.load_approved_at(p), 123)
            json.dump({"approved_at": "x"}, open(p, "w"))
            with self.assertRaises(sd.Stop): sd.load_approved_at(p)
            sd.configure(2, p) if False else None
            json.dump({"approved_at": 1793996715}, open(p, "w"))
            sd.configure(3, p)
            e = sd.base.make_envelope()
            self.assertEqual(e["control_approval"]["approved_at"], 1793996715)
            self.assertEqual(e["control_approval"]["receiver_fw"], "9709091a")
            self.assertEqual(e["max_packets"], 10); self.assertLessEqual(e["max_power"], 127)
            self.assertEqual(sd.base.ENV, sd.paths_for(3)["ENV"])
            with self.assertRaises(sd.Stop): sd.configure(6, p)
            with self.assertRaises(sd.Stop): sd.configure(0, p)


class Identity(unittest.TestCase):
    def test_h_ok(self):
        sd.base.FW, sd.base.BF = sd.FW, sd.BF
        self.assertTrue(sd.h_ok(H5, 2412000, 11000))
        self.assertFalse(sd.h_ok(H5.replace("proto=5", "proto=4"), 2412000, 11000))
        self.assertFalse(sd.h_ok(H5.replace("9709091a", "c5cc593b"), 2412000, 11000))
        self.assertFalse(sd.h_ok(H5.replace("948ba63", "x"), 2412000, 11000))
        self.assertFalse(sd.h_ok(H5.replace("quiet_us=2000", "quiet_us=0"), 2412000, 11000))

    def test_host_gate_accepts_proto5_and_9_field_p(self):
        with tempfile.TemporaryDirectory() as d:
            s, e = d + "/s", d + "/e"
            conv(os.path.join(REL, "source_off_batch3_2412000.txt"), s)
            conv(os.path.join(REL, "control_e8_2421032.txt"), e)
            self.assertIn(",", open(e).read())
            so, bs = g.parse_control_log(s); e8, be = g.parse_control_log(e)
            self.assertEqual((bs, be), ([], []))
            self.assertTrue(any(r.get("freqest") is not None for r in e8 if r["kind"] == "P"))
            ap = {"receiver_fw": "9709091a", "receiver_bf": "948ba63", "approved_at": 1793990000, "max_control_age_s": 3600}
            now = max(r["host_t"] for r in so + e8 if r["kind"] == "X") + 100
            self.assertTrue(g.verify_controls(so, e8, BODY, ap, now=now)["go"])
            ap["receiver_fw"] = "c5cc593b"
            with self.assertRaises(g.GateError): g.verify_controls(so, e8, BODY, ap, now=now)


class Ordering(unittest.TestCase):
    def test_gate_order_and_caps(self):
        with tempfile.TemporaryDirectory() as d:
            rel = d + "/"
            sd.prior_gate(1, rel)
            with self.assertRaises(sd.Stop): sd.prior_gate(2, rel)          # batch 1 missing
            with self.assertRaises(sd.Stop): sd.prior_gate(6, rel)
            mkprior(rel, 1); sd.prior_gate(2, rel)
            with self.assertRaises(sd.Stop): sd.prior_gate(1, rel)          # already attempted
            for n in (2, 3, 4): mkprior(rel, n)
            sd.prior_gate(5, rel)
            mkprior(rel, 5)
            self.assertEqual(sd.physical_pkt_total(rel), 50)
            with self.assertRaises(sd.Stop): sd.prior_gate(5, rel)          # cap/used

    def test_keyed_or_failed_prior_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            rel = d + "/"; mkprior(rel, 1, keyed="keyed=1")
            with self.assertRaises(sd.Stop): sd.prior_gate(2, rel)
        with tempfile.TemporaryDirectory() as d:
            rel = d + "/"; mkprior(rel, 1, ok=False)
            with self.assertRaises(sd.Stop): sd.prior_gate(2, rel)

    def test_e8_freshness_via_base(self):
        with tempfile.TemporaryDirectory() as d:
            p = d + "/e"; conv(os.path.join(REL, "control_e8_2421032.txt"), p)
            recs, _ = g.parse_control_log(p); x = max(r["host_t"] for r in recs if r["kind"] == "X")
            lo = min(r["host_t"] for r in recs)
            sd.base.e8_check(p, now=x + 100, approved_at=int(lo) - 1)
            with self.assertRaises(sd.Stop): sd.base.e8_check(p, now=x + 3700, approved_at=int(lo) - 1)
            with self.assertRaises(sd.Stop): sd.base.e8_check(p, now=x + 100, approved_at=int(lo) + 1)


class Summary(unittest.TestCase):
    def test_math(self):
        P = lambda f, r: {"freqest": f, "rssi": r}
        f1 = {"counts": {"valid": 8, "crc_invalid": 0, "malformed": 1, "unobserved": 1}, "attempts": 10,
              "matched": [P(2, -60), P(4, -62)], "misses": [{"i": 3, "neighbours": {"prev": None, "next": None}}]}
        f2 = {"counts": {"valid": 10, "crc_invalid": 0, "malformed": 0, "unobserved": 0}, "attempts": 10,
              "matched": [P(None, -70)], "misses": []}
        s = sd.summarize({1: f1, 2: f2}, [P(-3, -50), P(-1, -52)])
        self.assertEqual(s["pooled"], {"valid": 18, "crc_invalid": 0, "malformed": 1, "unobserved": 1})
        self.assertEqual(s["attempts"], 20)
        self.assertEqual(s["esp_matched"]["freqest"]["mean"], 3.0)
        self.assertEqual(s["esp_matched"]["freqest"]["n"], 2)
        self.assertAlmostEqual(s["esp_matched"]["rssi"]["mean"], -64.0)
        self.assertEqual(s["e8"]["freqest"]["min"], -3); self.assertEqual(s["e8"]["rssi"]["max"], -50)
        self.assertEqual(list(s["misses"]), [1])


if __name__ == "__main__":
    unittest.main()
