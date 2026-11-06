import io, json, os, sys, tempfile, time, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "host"))
import attempts as at
import batch_gate as bg
import bench_runner as r
import d8_vectors

BODY = d8_vectors.build(0)[:r.PKT_BODY_BYTES]
NOW = 2_000_000_000.0


def H(freq, quiet=2000, fw="fwOK", bf="bfOK", host=NOW - 100):
    x = r.parse_pkt_record(
        "H,proto=4,mode=pkt,fw=%s,bf=%s,freq_req_khz=%d,freq_set_hz=1,freq_word=0x5CC4EC,freq_rb=0x5CC4EC,"
        "chan=0,hop=0,cfg_rb_ok=1,bw_hz=1,sync=0xD391,cal_us=1,part=0x80,ver=0x03,spur=0,ant=1,lna=1,txen=0,"
        "quiet_us=%d,duration_ms=9000,t0_us=1" % (fw, bf, freq, quiet))
    x["host_t"] = host
    return x


def X(host):
    x = r.parse_pkt_record("X,9,5,done")
    x["host_t"] = host
    return x


def P(host):
    x = r.parse_pkt_record("P,1,2,18,%s,50,50,1" % BODY.hex().upper())
    x["host_t"] = host
    return x


def controls(**kw):
    so = [H(2412000, host=kw.get("so_t", NOW - 100), **kw.get("so", {})), X(kw.get("so_t", NOW - 100) + 1)]
    e8 = [H(2421032, host=kw.get("e8_t", NOW - 90), **kw.get("e8", {})), P(NOW - 89), X(kw.get("e8_t", NOW - 90) + 1)]
    return so, e8


APPROVAL = {"receiver_fw": "fwOK", "receiver_bf": "bfOK", "approved_at": NOW - 200, "max_control_age_s": 600}


class FakeRunner:
    def __init__(self): self.cmds = []
    def set_phase(self, p): pass
    def command(self, c):
        self.cmds.append(c)
        class R: ok = True; error = None; records = {"keyed": 0, "on_us": 6700}
        return R
    def authorize(self, e): pass
    def _safe_unkey(self): pass


class Integrity(unittest.TestCase):
    def verify(self, so, e8, approval=APPROVAL):
        return bg.verify_controls(so, e8, BODY, approval, now=NOW)

    def test_legit_passes_and_binds(self):
        c = self.verify(*controls())
        self.assertTrue(c["go"])
        self.assertEqual(c["receiver"]["e8"]["fw"], "fwOK")
        self.assertEqual(len(c["control_sha256"]["e8"]), 64)

    def test_old_quiet_500_refused(self):
        for which in ("so", "e8"):
            with self.assertRaises(bg.GateError):
                self.verify(*controls(**{which: {"quiet": 500}}))

    def test_identity_mismatch_refused(self):
        with self.assertRaises(bg.GateError):
            self.verify(*controls(e8={"fw": "other"}))
        with self.assertRaises(bg.GateError):
            self.verify(*controls(so={"bf": "other"}))

    def test_stale_refused(self):
        with self.assertRaises(bg.GateError):          # before approval
            self.verify(*controls(so_t=NOW - 300))
        with self.assertRaises(bg.GateError):          # too old at run time
            bg.verify_controls(*controls(), BODY, dict(APPROVAL, max_control_age_s=5), now=NOW)

    def test_nan_and_future_refused(self):
        nan = float("nan")
        for ap in (dict(APPROVAL, approved_at=nan), dict(APPROVAL, max_control_age_s=nan)):
            with self.assertRaises(bg.GateError):
                self.verify(*controls(), approval=ap)
        with self.assertRaises(bg.GateError):
            bg.verify_controls(*controls(), BODY, APPROVAL, now=nan)
        so, e8 = controls(); so[1]["host_t"] = nan
        with self.assertRaises(bg.GateError):
            self.verify(so, e8)
        so, e8 = controls(); e8[1]["host_t"] = nan          # P record
        with self.assertRaises(bg.GateError):
            self.verify(so, e8)
        so, e8 = controls(); so[0]["host_t"] = NOW + 3600   # H in future
        with self.assertRaises(bg.GateError):
            self.verify(so, e8)
        so, e8 = controls(); e8[1]["host_t"] = NOW + 3600   # P in future
        with self.assertRaises(bg.GateError):
            self.verify(so, e8)

    def test_missing_approval_refused(self):
        with self.assertRaises(bg.GateError):
            self.verify(*controls(), approval=None)
        with self.assertRaises(bg.GateError):
            self.verify(*controls(), approval=dict(APPROVAL, max_control_age_s=99999))

    def test_run_batch_refuses_forged_dict(self):
        env = r.Envelope("t", 10000, 1, 127, 0, 10, 10)
        run = FakeRunner()
        for forged in ({"go": True}, bg.check_controls(*controls(), BODY)):
            with self.assertRaises(bg.GateError):
                bg.run_batch(run, env, forged, BODY, n_pkt=1, power=127, sleep=lambda s: None)
        self.assertEqual(run.cmds, [])
        with self.assertRaises(bg.GateError):
            bg.VerifiedControls({"go": True})
        att = bg.run_batch(run, env, self.verify(*controls()), BODY, n_pkt=2, power=127, sleep=lambda s: None)
        self.assertEqual(len(att), 2)

    def test_historical_offline_still_analyses(self):
        self.assertTrue(bg.check_controls(*controls(), BODY)["offline_only"])


class MainFlow(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.env = os.path.join(self.d, "env.json")

    def raw_logs(self, quiet, fw="fwOK", t=None):
        t = t or time.time()
        hdr = ("H,proto=4,mode=pkt,fw=%s,bf=bfOK,freq_req_khz=%d,freq_set_hz=1,freq_word=0x5CC4EC,freq_rb=0x5CC4EC,"
               "chan=0,hop=0,cfg_rb_ok=1,bw_hz=1,sync=0xD391,cal_us=1,part=0x80,ver=0x03,spur=0,ant=1,lna=1,txen=0,"
               "quiet_us=%d,duration_ms=9000,t0_us=1")
        so = os.path.join(self.d, "so.txt"); e8 = os.path.join(self.d, "e8.txt")
        open(so, "w").write("%.4f %s\n%.4f X,9,5,done\n" % (t, hdr % (fw, 2412000, quiet), t + 1))
        open(e8, "w").write("%.4f %s\n%.4f P,1,2,18,%s,50,50,1\n%.4f X,9,5,done\n"
                            % (t, hdr % (fw, 2421032, quiet), t + 1, BODY.hex().upper(), t + 2))
        return so, e8

    def run_main(self, so, e8, approval):
        env = {"test": "t", "max_duration_us": 10000, "max_abs_offset": 1, "max_power": 127,
               "max_transitions": 0, "max_commands": 10, "max_packets": 10}
        if approval is not None:
            env["control_approval"] = approval
        json.dump(env, open(self.env, "w"))
        opened = []
        out = io.StringIO()
        rc = bg.main(["run", "--execute", "--approved-envelope", self.env, "--esp-port", "X",
                      "--source-off-log", so, "--e8-log", e8, "--out-dir", os.path.join(self.d, "o")],
                     opener=lambda p: opened.append(p) or (_ for _ in ()).throw(RuntimeError("no port")), out=out)
        return rc, opened, out.getvalue()

    def appr(self):
        return {"receiver_fw": "fwOK", "receiver_bf": "bfOK", "approved_at": time.time() - 60, "max_control_age_s": 600}

    REAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "results", "packet", "reliability")

    def real(self):
        return (os.path.join(self.REAL, "source_off_batch1_2412000.txt"),
                os.path.join(self.REAL, "control_e8_2421032.txt"))

    def _mut(self, src, fn):
        dst = os.path.join(self.d, os.path.basename(src))
        open(dst, "w").write(fn(open(src).read()))
        return dst

    def test_real_logs_pass_parse_and_reach_port_opener(self):
        so, e8 = self.real()
        for p in (so, e8):
            recs, bad = bg.parse_control_log(p)
            self.assertEqual(bad, [])
        ap = {"receiver_fw": "c5cc593b", "receiver_bf": "948ba63", "approved_at": 1793993300,
              "max_control_age_s": 3600}
        real_time = time.time
        try:
            time.time = lambda: 1793993600.0
            with self.assertRaisesRegex(RuntimeError, "no port"):   # stub opener reached = gate accepted
                self.run_main(so, e8, ap)
        finally:
            time.time = real_time

    def test_wrapper_tampering_still_refused(self):
        so, e8 = self.real()
        muts = [lambda s: s.replace("rxdiag pkt 2412000 5000", "rxdiag pkt 2412001 5000"),
                lambda s: s.replace("rxdiag pkt 2412000 5000", "rxdiag pkt 2412000 5000 x"),
                lambda s: s.replace("1793993498.1930 rxdiag", "nan rxdiag"),
                lambda s: s.rstrip("\n").rsplit("\n", 1)[0] + "\nnan \n",
                lambda s: s.replace("\n1793993503.1873 X,", "\n1793993503.1873 junk\n1793993503.1873 X,"),
                lambda s: s.replace("1142B200", "1142B20", 1) if "P," in s else s + "P,0,1,18,ZZ\n"]
        for i, m in enumerate(muts):
            bad = self._mut(so, m)
            recs, rest = bg.parse_control_log(bad)
            self.assertTrue(rest or any(r["kind"] == "P" for r in recs), i)
        # corrupted P in source-off must still refuse
        bad = self._mut(so, lambda s: s.rstrip("\n").rsplit("\n", 1)[0] + "\n1793993503.0000 P,0,1,18,ZZ,1,1,1\n"
                        + s.rstrip("\n").rsplit("\n", 1)[1] + "\n")
        _, rest = bg.parse_control_log(bad)
        self.assertEqual(len(rest), 1 + 0)
        rc, opened, out = self.run_main(bad, e8, {"receiver_fw": "c5cc593b", "receiver_bf": "948ba63",
                                                  "approved_at": time.time(), "max_control_age_s": 10})
        self.assertEqual((rc, opened), (2, []))

    def test_stale_and_mismatch_refuse_before_port(self):
        for kw, ap in ((dict(quiet=500), self.appr()), (dict(quiet=2000, fw="bad"), self.appr()),
                       (dict(quiet=2000, t=time.time() - 3000), self.appr()), (dict(quiet=2000), None)):
            so, e8 = self.raw_logs(**kw)
            rc, opened, out = self.run_main(so, e8, ap)
            self.assertEqual(rc, 2, out)
            self.assertEqual(opened, [])
            self.assertIn("REFUSED", out)
            self.assertFalse(os.path.exists(os.path.join(self.d, "o")))

    def test_nan_and_future_refuse_before_port(self):
        for mode in ("nan_ts", "future_h", "nan_approval"):
            so, e8 = self.raw_logs(quiet=2000)
            ap = self.appr()
            if mode == "nan_approval":
                ap["approved_at"] = float("nan")
            else:
                t = "nan" if mode == "nan_ts" else "%.4f" % (time.time() + 3600)
                lines = open(e8).read().split("\n")
                lines[0] = t + " " + lines[0].split(" ", 1)[1]
                open(e8, "w").write("\n".join(lines))
            rc, opened, out = self.run_main(so, e8, ap)
            self.assertEqual(rc, 2, (mode, out))
            self.assertEqual(opened, [])
            self.assertFalse(os.path.exists(os.path.join(self.d, "o")))

    def test_unparsed_or_malformed_control_refuses_before_port(self):
        for mode in ("bad_p", "bad_ts"):
            so, e8 = self.raw_logs(quiet=2000)
            if mode == "bad_p":      # corrupted source-off P record must not be silently dropped
                open(so, "a").write("%.4f P,1,2,18,ZZ,50,50,1\n" % time.time())
            else:
                lines = open(so).read().split("\n")
                lines[0] = "notatime " + lines[0].split(" ", 1)[1]
                open(so, "w").write("\n".join(lines))
            rc, opened, out = self.run_main(so, e8, self.appr())
            self.assertEqual(rc, 2, (mode, out))
            self.assertIn("NO-GO", out)
            self.assertEqual(opened, [])
            self.assertFalse(os.path.exists(os.path.join(self.d, "o")))

    def test_legit_reaches_port_open(self):
        so, e8 = self.raw_logs(quiet=2000)
        with self.assertRaises(RuntimeError):      # opener reached => gate passed
            self.run_main(so, e8, self.appr())

    def test_offset_below_pkt_offset_refused_before_marker_and_opener(self):
        so, e8 = self.raw_logs(quiet=2000)
        env = {"test": "t", "max_duration_us": 10000, "max_abs_offset": 0, "max_power": 127,
               "max_transitions": 0, "max_commands": 10, "max_packets": 10, "control_approval": self.appr()}
        json.dump(env, open(self.env, "w"))
        opened = []; out = io.StringIO()
        rc = bg.main(["run", "--execute", "--approved-envelope", self.env, "--esp-port", "X",
                      "--source-off-log", so, "--e8-log", e8, "--out-dir", os.path.join(self.d, "o")],
                     opener=lambda p: opened.append(p), out=out)
        self.assertEqual(rc, 2)
        self.assertEqual(opened, [])
        self.assertFalse(os.path.exists(self.env + ".used"))
        self.assertFalse(os.path.exists(os.path.join(self.d, "o")))

    def test_second_call_same_envelope_refuses_before_opener(self):
        so, e8 = self.raw_logs(quiet=2000)
        with self.assertRaises(RuntimeError):
            self.run_main(so, e8, self.appr())
        self.assertTrue(os.path.exists(self.env + ".used"))
        out = io.StringIO(); opened = []
        rc = bg.main(["run", "--execute", "--approved-envelope", self.env, "--esp-port", "X",
                      "--source-off-log", so, "--e8-log", e8, "--out-dir", os.path.join(self.d, "o2")],
                     opener=lambda p: opened.append(p), out=out)
        self.assertEqual(rc, 2)
        self.assertEqual(opened, [])
        self.assertIn("consumed", out.getvalue())

    def test_ledger_error_refuses(self):
        so, e8 = self.raw_logs(quiet=2000)
        os.mkdir(self.env + ".used")          # unusable marker path
        rc, opened, out = self.run_main(so, e8, self.appr())
        self.assertEqual((rc, opened), (2, []))
        os.rmdir(self.env + ".used")
        os.chmod(self.d, 0o555)           # read-only dir: marker cannot be created
        try:
            if not os.access(self.d, os.W_OK):
                rc, opened, out = self.run_main(so, e8, self.appr())
                self.assertEqual((rc, opened), (2, []))
        finally:
            os.chmod(self.d, 0o755)

    def test_contradictory_and_len20_controls(self):
        def rec(line, t=NOW - 89):
            x = r.parse_pkt_record(line); x["host_t"] = t; return x
        so, e8 = controls()
        e8_ep = e8[:1] + [P(NOW - 89), r.parse_pkt_record("E,1,EPART,seq=1;exp=20;got=18")] + e8[2:]
        e8_ep[2]["host_t"] = NOW - 89
        res = bg.check_controls(so, e8_ep, BODY)
        self.assertFalse(res["go"], res)
        so_ep = so[:1] + [P(NOW - 99), r.parse_pkt_record("E,1,EPART,seq=1;exp=20;got=18")] + so[1:]
        self.assertFalse(bg.check_controls(so_ep, e8, BODY)["go"])
        p20 = r.parse_pkt_record("P,7,8,20,%s0000,50,50,1" % BODY.hex().upper())
        p20["host_t"] = NOW - 99
        so20 = so[:1] + [p20] + so[1:]
        res = bg.check_controls(so20, e8, BODY)
        self.assertFalse(res["go"], res)
        self.assertTrue(bg.check_controls(*controls(), BODY)["go"])


if __name__ == "__main__":
    unittest.main()
