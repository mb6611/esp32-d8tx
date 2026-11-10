"""Offline mocked tests for results/packet/reliability/batch3_driver.py (no ports, no RF)."""
import importlib.util, json, os, sys, tempfile, time, unittest
from unittest import mock
HERE = os.path.dirname(os.path.abspath(__file__))
REL = os.path.join(HERE, "..", "..", "..", "experiments", "06-fixed-channel-reliability", "data", "reliability")
sys.path.insert(0, os.path.join(HERE, "..")); sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "experiments", "05-first-packet", "scripts"))
import attempts as at
import batch_gate as g
import bench_runner as r
from test_start_anchor_clock import scenario, T0H, TOL
from test_d8_attempts import BODY

spec = importlib.util.spec_from_file_location("batch3_driver", os.path.join(HERE, "..", "..", "..", "experiments", "06-fixed-channel-reliability", "scripts", "reliability", "batch3_driver.py"))
bd = importlib.util.module_from_spec(spec); spec.loader.exec_module(bd)
REAL_E8 = os.path.join(REL, "control_e8_2421032.txt")


def e8_log(path, t0, t1):
    open(path, "w").write(
        "# cmd\n%.4f rxdiag pkt 2421032 20000\n%.4f H,proto=4,mode=pkt,fw=c5cc593b,bf=948ba63,freq_req_khz=2421032,"
        "freq_set_hz=1,freq_word=0x5D1DDB,freq_rb=0x5D1DDB,chan=0,hop=0,cfg_rb_ok=1,bw_hz=1,sync=0xD391,cal_us=1,"
        "part=0x80,ver=0x03,spur=0,ant=1,lna=1,txen=0,quiet_us=2000,duration_ms=20000,t0_us=1\n%.4f X,9,5,done\n"
        % (t0, t0, t1))


class Freshness(unittest.TestCase):
    def test_envelope_uses_approved_stage_timestamp_and_one_use(self):
        e = bd.make_envelope()
        self.assertEqual(e["control_approval"]["approved_at"], 1793992800)
        self.assertEqual(e["max_abs_offset"], 1)
        self.assertLessEqual(e["max_packets"], 10)
        self.assertEqual(e["control_approval"]["max_control_age_s"], 3600)
        self.assertFalse(hasattr(bd, "cmd_e8"))                  # no new E8 control capture command

    def test_existing_e8_control_accepted_in_window(self):
        lo, hi = bd.e8_check(REAL_E8, now=1793993380 + 100)
        self.assertGreaterEqual(lo, bd.APPROVED_AT)

    def test_existing_e8_stale_or_predating_rejected(self):
        with self.assertRaises(bd.Stop): bd.e8_check(REAL_E8, now=1793993400 + 3700)
        with self.assertRaises(bd.Stop): bd.e8_check(REAL_E8, now=1793993400, approved_at=1793993390)

    def test_gate_agrees_with_driver_on_staleness(self):
        recs, bad = g.parse_control_log(REAL_E8)
        self.assertEqual(bad, [])
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "e"); e8_log(p, 1793993000.0, 1793993020.0)
            self.assertEqual(bd.e8_check(p, now=1793993100)[1], 1793993020.0)

    def test_envelope_cmd_refuses_when_e8_stale(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(bd, "ENV", d + "/env.json"), \
                mock.patch.object(bd, "OUT", d + "/o"), mock.patch.object(bd, "STM", d + "/s"), \
                mock.patch.object(bd, "SRC", d + "/src"), mock.patch.object(bd, "ANCHOR", d + "/a"), \
                mock.patch.object(bd, "E8", REAL_E8), mock.patch.object(time, "time", return_value=1793993380 + 9999):
            with self.assertRaises(SystemExit): bd.cmd_envelope(None)
            self.assertFalse(os.path.exists(d + "/env.json"))


class Anchor(unittest.TestCase):
    def test_pre_write_stamp_precedes_write_and_logged(self):
        order = []
        class Rd:
            def rd(self, fd, t): order.append("rd"); return b"H,x\nX,1,2,done\n"
        real = time.time
        with tempfile.TemporaryDirectory() as d, mock.patch.object(os, "write", side_effect=lambda fd, b: order.append("write") or len(b)):
            out = d + "/stm"
            L, t_pre, t_post = bd.capture(0, Rd(), 2412000, 1000, out)
            self.assertLessEqual(t_pre, t_post)
            self.assertEqual(order[0], "write")
            txt = open(out).read()
            self.assertIn("t_cmd_pre_write_host=%.6f" % t_pre, txt)
            self.assertLess(txt.index("t_cmd_pre_write_host"), txt.index("H,x"))

    def test_stamp_taken_before_write_call(self):
        stamps = iter([100.0, 100.5, 101.0, 101.0, 101.0, 101.0, 101.0, 101.0, 101.0])
        calls = []
        class Rd:
            def rd(self, fd, t): return b"X,1,2,done\n"
        def wr(fd, b): calls.append(("write", None)); return len(b)
        with tempfile.TemporaryDirectory() as d, mock.patch.object(os, "write", side_effect=wr), \
                mock.patch.object(time, "time", side_effect=lambda: next(stamps, 102.0)):
            _, t_pre, t_post = bd.capture(0, Rd(), 2412000, 1000, d + "/s")
        self.assertEqual((t_pre, t_post), (100.0, 100.5))


class GateFailure(unittest.TestCase):
    def _run(self, gate_rc, idle=True, h_ok=True):
        """Drive cmd_run with everything mocked; returns (calls dict, exit code)."""
        c = {"gate": 0, "idle_post": 0, "capture": 0}
        def cap(fd, rd, freq, ms, out, pre=None, expect_h=None):
            c["capture"] += 1
            if pre and h_ok: pre()
            return ["H,x", "X,1,2,done"], 1.0, 1.1
        def idle_f(tag, opener=None):
            if tag == "post": c["idle_post"] += 1
            if tag == "post" and isinstance(idle, Exception): raise idle
            return idle if tag == "post" else True
        def gmain(argv, out=None):
            c["gate"] += 1; return gate_rc
        with tempfile.TemporaryDirectory() as d:
            ps = {k: d + "/" + k for k in ("ENV", "OUT", "STM", "SRC", "E8", "ANCHOR", "POST", "HASHES")}
            open(ps["ENV"], "w").write("{}"); open(ps["E8"], "w").write("x")
            fake_pk = mock.Mock(); fake_pk.stm_open.return_value = 3
            with mock.patch.multiple(bd, **ps), mock.patch.object(bd, "capture", cap), \
                    mock.patch.object(bd, "esp_idle", idle_f), mock.patch.object(bd, "e8_check", return_value=(0, 0)), \
                    mock.patch.object(bd, "prior_gate"), mock.patch.object(bd, "_verify_offline"), mock.patch.object(bd, "_open_stm", return_value=(fake_pk, 3)), \
                    mock.patch.object(g, "main", gmain), mock.patch.object(time, "sleep"):
                try: bd.cmd_run(None); rc = 0
                except SystemExit as e: rc = e.code
        return c, rc

    def test_gate_failure_stops_once_no_retry(self):
        c, rc = self._run(2)
        self.assertEqual(rc, 2); self.assertEqual(c["gate"], 1); self.assertEqual(c["capture"], 2)

    def test_gate_never_started_without_h(self):
        c, rc = self._run(0, h_ok=False)
        self.assertEqual(rc, 2); self.assertEqual(c["gate"], 0)

    def test_post_stat_single_attempt(self):
        c, rc = self._run(0, idle=RuntimeError("port"))
        self.assertEqual(rc, 2); self.assertEqual(c["idle_post"], 1); self.assertEqual(c["gate"], 1)
        c, rc = self._run(0, idle=False)
        self.assertEqual(rc, 2); self.assertEqual(c["idle_post"], 1)

    def test_success(self):
        c, rc = self._run(0)
        self.assertEqual(rc, 0); self.assertEqual(c["gate"], 1)


class Classify(unittest.TestCase):
    def test_classify_passes_tol_and_anchor_with_drift(self):
        att, recs = scenario(10, missing={0})
        seen = {}
        orig = at.classify_attempts
        def spy(a, rc, b, **kw): seen.update(kw); return orig(a, rc, b, **kw)
        with tempfile.TemporaryDirectory() as d, mock.patch.object(at, "parse_stm_log", return_value=(recs, [])), \
                mock.patch.object(at, "attempts_from_runner_log", return_value=att), \
                mock.patch.object(at, "classify_attempts", spy):
            ap = d + "/anchor.json"; json.dump({"start_cmd_host": T0H - 0.02}, open(ap, "w"))
            res = bd.classify(ap, "stm", "runner")
        self.assertEqual(seen["clock_rate_tol"], 0.003); self.assertEqual(seen["start_cmd_host"], T0H - 0.02)
        self.assertEqual([e["i"] for e in res["per_attempt"] if e["class"] == "valid"], list(range(1, 10)))
        self.assertEqual(len(res["raw_matches"]), 9)             # raw matches reported separately
        self.assertEqual(res["unparsed_lines"], 0)


if __name__ == "__main__":
    unittest.main()
