"""Offline tests for batch3_driver.py batches 3..10 (no ports, no RF, no files outside tmp)."""
import importlib.util, json, os, subprocess, sys, tempfile, unittest
from unittest import mock
HERE = os.path.dirname(os.path.abspath(__file__))
REL = os.path.join(HERE, "..", "..", "..", "experiments", "06-fixed-channel-reliability", "data", "reliability")
DRV = os.path.join(HERE, "..", "..", "..", "experiments", "06-fixed-channel-reliability", "scripts", "reliability", "batch3_driver.py")
sys.path.insert(0, os.path.join(HERE, "..")); sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "experiments", "05-first-packet", "scripts"))
spec = importlib.util.spec_from_file_location("bd_session", DRV)
bd = importlib.util.module_from_spec(spec); spec.loader.exec_module(bd)
DEFAULTS = {k: getattr(bd, k) for k in ("ENV", "OUT", "STM", "SRC", "ANCHOR", "POST", "PRE", "HASHES", "REPORT", "BATCH", "GATE_DELAY_S")}


def fake_batch(rel, n, ok=10, done=True, keyed="keyed=0"):
    os.makedirs(rel + "batch%d_esp_out" % n, exist_ok=True)
    open(rel + "batch%d_envelope.json.used" % n, "w").write("{}")
    json.dump({"attempts": [{"i": i, "ok": True} for i in range(ok)]}, open(rel + "batch%d_esp_out/attempts.json" % n, "w"))
    open(rel + "batch%d_stm.txt" % n, "w").write("1.0 H,x\n2.0 X,1,2,%s\n" % ("done" if done else "abort"))
    open(rel + "post_batch%d_esp.txt" % n, "w").write("PING 'P'\nSTAT 'S,%s,b8=0'\n" % keyed)
    open(rel + "batch%d_hashes.txt" % n, "w").write("x\n")
    open(rel + "source_off_batch%d_2412000.txt" % n, "w").write("x\n")


class Base(unittest.TestCase):
    def tearDown(self):
        for k, v in DEFAULTS.items(): setattr(bd, k, v)


class Paths(Base):
    def test_default_is_batch3(self):
        self.assertEqual(bd.ENV, bd.R + "batch3_envelope.json"); self.assertEqual(bd.GATE_DELAY_S, 0.4)

    def test_isolation_and_delay(self):
        seen = {}
        for n in range(3, 11):
            bd.configure(n)
            seen[n] = {k: getattr(bd, k) for k in ("ENV", "OUT", "STM", "SRC", "ANCHOR", "POST", "PRE", "HASHES", "REPORT")}
            self.assertEqual(bd.GATE_DELAY_S, 1.5 if n == 4 else 0.4)
            for v in seen[n].values(): self.assertIn("%d" % n, os.path.basename(v))
        allp = [p for d in seen.values() for p in d.values()]
        self.assertEqual(len(allp), len(set(allp)))
        self.assertEqual(bd.make_envelope()["test"], "U3 batch10 2412000 pwr127 owner-scoped")
        self.assertEqual(bd.make_envelope()["max_packets"], 10)

    def test_range(self):
        for n in (2, 11, 0, -1):
            with self.assertRaises(bd.Stop): bd.configure(n)
            with self.assertRaises(bd.Stop): bd.prior_gate(n)


class Cli(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, DRV, *args], capture_output=True, text=True,
                              cwd=os.path.abspath(os.path.join(HERE, "..", "..", "..")), timeout=60)

    def test_rejects_out_of_range(self):
        for n in ("11", "2", "-1"):
            r = self.run_cli("--batch", n, "run")
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr); self.assertIn("STOP", r.stdout)

    def test_batch3_already_attempted_refused(self):
        r = self.run_cli("run"); self.assertEqual(r.returncode, 2); self.assertIn("STOP", r.stdout)

    def test_batch4_envelope_refused_when_no_e8_or_taken_never_writes_env(self):
        before = os.path.exists(bd.R + "batch4_envelope.json")
        self.run_cli("--batch", "10", "envelope")                  # batch9 missing -> STOP
        self.assertFalse(os.path.exists(bd.R + "batch10_envelope.json")) if not before else None


class Gate(Base):
    def test_prior_ok(self):
        with tempfile.TemporaryDirectory() as d:
            rel = d + "/"; fake_batch(rel, 3); bd.prior_gate(4, rel)

    def test_prior_failures(self):
        for kw in ({"ok": 9}, {"done": False}, {"keyed": "keyed=1"}):
            with tempfile.TemporaryDirectory() as d:
                rel = d + "/"; fake_batch(rel, 3, **kw)
                with self.assertRaises(bd.Stop): bd.prior_gate(4, rel)

    def test_prior_missing_and_missing_file(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(bd.Stop): bd.prior_gate(5, d + "/")
            rel = d + "/"; fake_batch(rel, 3); os.remove(rel + "post_batch3_esp.txt")
            with self.assertRaises(bd.Stop): bd.prior_gate(4, rel)

    def test_already_attempted(self):
        with tempfile.TemporaryDirectory() as d:
            rel = d + "/"; fake_batch(rel, 3); fake_batch(rel, 4)
            with self.assertRaises(bd.Stop): bd.prior_gate(4, rel)

    def test_pkt_cap_no_eleventh_group(self):
        with tempfile.TemporaryDirectory() as d:
            rel = d + "/"
            for n in range(1, 10): fake_batch(rel, n)               # 90 physical PKT
            self.assertEqual(bd.physical_pkt_total(rel), 90); bd.prior_gate(10, rel)
            fake_batch(rel, 10)                                     # 100 -> nothing more
            with self.assertRaises(bd.Stop): bd.prior_gate(10, rel)
            with self.assertRaises(bd.Stop): bd.prior_gate(11, rel)

    def test_aborted_run_counts(self):
        with tempfile.TemporaryDirectory() as d:
            rel = d + "/"; fake_batch(rel, 3, ok=4)
            self.assertEqual(bd.physical_pkt_total(rel), 4)
            os.makedirs(rel + "batch9_esp_out")                      # unreadable attempts -> counts 10
            self.assertEqual(bd.physical_pkt_total(rel), 14)

    def test_real_evidence_capped_refuses_further_attempts(self):
        # live evidence is fully completed (10 groups / 100 PKT): no further group or attempt may pass the gate
        self.assertGreaterEqual(bd.physical_pkt_total(), bd.MAX_PKT_TOTAL)
        with self.assertRaises(bd.Stop): bd.prior_gate(4)
        with self.assertRaises(bd.Stop): bd.prior_gate(10)
        with self.assertRaises(bd.Stop): bd.prior_gate(11)

    def test_cmd_run_stops_without_hardware_on_gate_fail(self):
        bd.configure(7)                                             # batch6 evidence absent
        with mock.patch.object(bd, "esp_idle") as idle, mock.patch.object(bd, "_open_stm") as o:
            with self.assertRaises(SystemExit): bd.cmd_run(None)
            idle.assert_not_called(); o.assert_not_called()

    def test_stale_e8_stops_before_hardware(self):
        bd.configure(4)
        with mock.patch.object(bd, "esp_idle") as idle, mock.patch.object(bd, "_open_stm") as o, \
                mock.patch.object(bd.time, "time", return_value=1793993400 + 4000), \
                mock.patch.object(bd, "prior_gate"):
            with self.assertRaises(SystemExit): bd.cmd_run(None)
            idle.assert_not_called(); o.assert_not_called()

    def test_gate_delay_used_by_run_thread(self):
        self.assertIn("time.sleep(GATE_DELAY_S)", open(DRV).read())


if __name__ == "__main__":
    unittest.main()
