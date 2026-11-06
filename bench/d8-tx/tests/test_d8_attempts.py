import io, json, os, sys, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "host"))
import attempts as at
import batch_gate as bg
import bench_runner as r
import d8_vectors

PKT = os.path.join(HERE, "..", "results", "packet")
BODY = d8_vectors.build(0)[:18]
HEXB = BODY.hex().upper()


def P(seq, t, data, rssi=0, lqi=0, crc=0):
    return r.parse_pkt_record("P,%d,%d,%d,%s,%d,%d,%d" % (seq, t, len(data), data.hex().upper(), rssi, lqi, crc))


def E(t, seq, exp, got):
    return r.parse_pkt_record("E,%d,EPART,seq=%d;exp=%d;got=%d" % (t, seq, exp, got))


def H(t0, host):
    h = ("H,proto=4,mode=pkt,fw=x,bf=y,freq_req_khz=2412000,freq_set_hz=1,freq_word=0x5CC4EC,freq_rb=0x5CC4EC,"
         "chan=0,hop=0,cfg_rb_ok=1,bw_hz=1,sync=0xD391,cal_us=1,part=0x80,ver=0x03,spur=0,ant=1,lna=1,txen=0,"
         "quiet_us=500,duration_ms=9000,t0_us=%d" % t0)
    x = r.parse_pkt_record(h)
    x["host_t"] = host
    return x


def X(t, host):
    x = r.parse_pkt_record("X,9,%d,done" % t)
    x["host_t"] = host
    return x


def synth(n=3, t0=1_000_000, host0=100.0, spacing=0.5):
    """n attempts; record i at device time t0 + (i*spacing+0.05)s."""
    att = [{"i": i, "t_send": host0 + 0.05 + i * spacing, "ok": True} for i in range(n)]
    return att, lambda i: t0 + int((0.05 + i * spacing + 0.06) * 1e6)


class Historical(unittest.TestCase):
    """U7 batch 1 fixture (read-only evidence)."""
    @classmethod
    def setUpClass(cls):
        cls.recs, cls.bad = at.parse_stm_log(os.path.join(PKT, "batch1_2412000_stm.txt"))
        cls.att = at.attempts_from_runner_log(os.path.join(PKT, "esp_runner_log.jsonl"))
        cls.res = at.classify_attempts(cls.att, cls.recs, BODY)

    def test_ten_attempts_all_commands_ok(self):
        self.assertEqual(len(self.att), 10)
        self.assertTrue(all(a["ok"] for a in self.att))

    def test_counts_7_valid_2_provisional_1_unobserved(self):
        c = self.res["counts"]
        self.assertEqual(c, {"valid": 7, "crc_invalid": 0, "malformed": 2, "unobserved": 1})
        self.assertEqual(sum(c.values()), 10)

    def test_two_split_pairs_are_malformed_not_success(self):
        sp = [e for e in self.res["per_attempt"] if e["provisional_split"]]
        self.assertEqual(len(sp), 2)
        self.assertEqual([e["primary"] for e in sp], [0, 8])
        for e in sp:
            self.assertEqual(e["class"], "malformed")
            self.assertEqual(e["split_status"], {"rssi": 12, "lqi": 51, "crc_ok": 1, "provisional": True})
        self.assertEqual(sorted(self.res["split_tails"]), [1, 9])

    def test_p5_is_only_a_candidate(self):
        un = [e for e in self.res["per_attempt"] if e["class"] == "unobserved"]
        self.assertEqual(len(un), 1)
        self.assertEqual(un[0]["i"], 4)
        self.assertIn(5, un[0]["candidates"])
        self.assertIsNone(un[0]["primary"])

    def test_clock_uncertainty_bounded_and_no_unassigned_match(self):
        self.assertLessEqual(self.res["clock"]["uncertainty_s"], 0.25)
        self.assertEqual(self.res["unassigned"], [])
        self.assertEqual(self.res["duplicates"], [])

    def test_noise_counted_separately(self):
        self.assertGreaterEqual(len(self.res["noise"]), 10)

    def test_e8_control_and_source_off(self):
        e8, _ = at.parse_stm_log(os.path.join(PKT, "control_e8_2421032.txt"))
        so, _ = at.parse_stm_log(os.path.join(PKT, "source_off_2412000.txt"))
        ctl = bg.check_controls(so, e8, BODY)
        self.assertTrue(ctl["go"], ctl)
        self.assertGreaterEqual(ctl["e8_valid"], 30)
        self.assertEqual(ctl["source_off_valid"], 0)

    def test_pooled_keeps_batch_rows(self):
        p = bg.pool([self.res, self.res])
        self.assertEqual(p["pooled"]["valid"], 14)
        self.assertEqual(len(p["batches"]), 2)
        self.assertIn("unobserved=1", bg.format_report(self.res))


class Synthetic(unittest.TestCase):
    def base(self, n=3):
        att, tdev = synth(n)
        return att, tdev, [H(1_000_000, 100.0 + 0.02), X(1_000_000 + 4_000_000, 104.1)]

    def test_valid_crc_invalid_unknown_unobserved(self):
        att, tdev, anchors = self.base(4)
        recs = anchors[:1] + [
            P(0, tdev(0), BODY, 12, 51, 1),
            P(1, tdev(1), BODY, 0, 0, 0),                      # complete, no EPART: real CRC failure
            E(tdev(2) + 600, 2, 20, 18), P(2, tdev(2), BODY),  # EPART: unknown, not CRC failure
        ] + anchors[1:]
        res = at.classify_attempts(att, recs, BODY)
        self.assertEqual([e["class"] for e in res["per_attempt"]],
                         ["valid", "crc_invalid", "malformed", "unobserved"])
        self.assertEqual(sum(res["counts"].values()), 4)

    def test_zero_fields_with_epart_never_crc_invalid(self):
        att, tdev, anchors = self.base(1)
        recs = [anchors[0], E(tdev(0), 0, 20, 18), P(0, tdev(0), BODY, 0, 0, 0), anchors[1]]
        self.assertEqual(at.classify_attempts(att, recs, BODY)["counts"]["crc_invalid"], 0)

    def test_wrong_bytes_not_a_match(self):
        att, tdev, anchors = self.base(1)
        bad = bytearray(BODY); bad[4] ^= 1
        recs = [anchors[0], P(0, tdev(0), bytes(bad), 12, 51, 1), anchors[1]]
        res = at.classify_attempts(att, recs, BODY)
        self.assertEqual(res["counts"]["valid"], 0)
        self.assertEqual(res["per_attempt"][0]["class"], "unobserved")  # unanchored partial cannot be uniquely attributed

    def test_duplicate_reported_separately(self):
        att, tdev, anchors = self.base(1)
        recs = [anchors[0], P(0, tdev(0), BODY, 12, 51, 1), P(1, tdev(0) + 5000, BODY, 12, 51, 1), anchors[1]]
        res = at.classify_attempts(att, recs, BODY)
        self.assertEqual(res["counts"]["valid"], 1)
        self.assertEqual(res["duplicates"], [1])

    def test_noise_not_counted_as_attempt(self):
        att, tdev, anchors = self.base(1)
        recs = [anchors[0], P(0, tdev(0), b"\x01\x02\x03"), anchors[1]]
        res = at.classify_attempts(att, recs, BODY)
        self.assertEqual(res["counts"]["unobserved"], 1)
        self.assertEqual(res["noise"], [0])

    def test_clock_ambiguity_leaves_unassigned(self):
        # attempts 40 ms apart: a 250 ms offset uncertainty spans two windows
        att = [{"i": 0, "t_send": 100.05, "ok": True}, {"i": 1, "t_send": 100.09, "ok": True}]
        recs = [H(1_000_000, 100.0), P(0, 1_000_000 + 80_000, BODY, 12, 51, 1)]
        res = at.classify_attempts(att, recs, BODY)
        self.assertEqual(res["counts"]["unobserved"], 2)
        self.assertEqual(len(res["unassigned"]), 1)

    def test_no_anchor_means_nothing_assigned(self):
        att, tdev, _ = self.base(1)
        res = at.classify_attempts(att, [P(0, tdev(0), BODY, 12, 51, 1)], BODY)
        self.assertEqual(res["counts"]["unobserved"], 1)
        self.assertEqual(res["unassigned"][0]["why"], "no clock anchor")

    def test_buffered_host_stamps_on_p_are_ignored(self):
        att, tdev, anchors = self.base(1)
        p = P(0, tdev(0), BODY, 12, 51, 1); p["host_t"] = 999.0
        res = at.classify_attempts(att, [anchors[0], p, anchors[1]], BODY)
        self.assertEqual(res["counts"]["valid"], 1)

    def test_tail_too_late_is_not_a_split(self):
        att, tdev, anchors = self.base(1)
        recs = [anchors[0], E(tdev(0), 0, 20, 18), P(0, tdev(0), BODY),
                E(tdev(0) + 5000, 1, 15, 2), P(1, tdev(0) + 5000, bytes.fromhex("0CB3")), anchors[1]]
        res = at.classify_attempts(att, recs, BODY)
        self.assertEqual(res["split_tails"], [])
        self.assertFalse(res["per_attempt"][0]["provisional_split"])


class Gate(unittest.TestCase):
    def env(self, **kw):
        d = dict(test="b", max_duration_us=6800, max_abs_offset=1, max_power=127, max_transitions=0,
                 max_commands=10, max_packets=10)
        d.update(kw)
        return r.Envelope(**d)

    def test_limits(self):
        bg.check_limits(2412000, 10, 127, self.env())
        for args in ((2421032, 10, 127), (2412000, 11, 127), (2412000, 0, 127), (2412000, 10, 128)):
            with self.assertRaises(bg.GateError):
                bg.check_limits(*args)
        for kw in (dict(max_packets=11), dict(max_commands=11), dict(max_transitions=1), dict(max_duration_us=20000)):
            with self.assertRaises(bg.GateError):
                bg.check_limits(2412000, 5, 100, self.env(**kw))

    def test_dry_run_default_opens_nothing(self):
        def boom(_): raise AssertionError("port opened")
        out = io.StringIO()
        self.assertEqual(bg.main(["run"], opener=boom, out=out), 0)
        self.assertIn('"ports_opened": false', out.getvalue())
        self.assertEqual(bg.main(["run", "--count", "11"], opener=boom, out=out), 2)
        self.assertEqual(bg.main(["run", "--freq-khz", "2421032"], opener=boom, out=out), 2)

    def test_execute_requires_envelope_and_args(self):
        def boom(_): raise AssertionError("port opened")
        out = io.StringIO()
        self.assertEqual(bg.main(["run", "--execute"], opener=boom, out=out), 2)
        with tempfile.TemporaryDirectory() as d:
            ef = os.path.join(d, "e.json")
            json.dump(self.env().__dict__, open(ef, "w"))
            self.assertEqual(bg.main(["run", "--execute", "--approved-envelope", ef], opener=boom, out=out), 2)

    def test_failed_controls_nogo_no_port(self):
        def boom(_): raise AssertionError("port opened")
        with tempfile.TemporaryDirectory() as d:
            ef = os.path.join(d, "e.json")
            json.dump(self.env().__dict__, open(ef, "w"))
            out = io.StringIO()
            rc = bg.main(["run", "--execute", "--approved-envelope", ef, "--esp-port", "X",
                          "--source-off-log", os.path.join(PKT, "source_off_2412000.txt"),
                          "--e8-log", os.path.join(PKT, "source_off_2421032.txt"),
                          "--out-dir", os.path.join(d, "o")], opener=boom, out=out)
            self.assertEqual(rc, 2)
            self.assertIn("NO-GO", out.getvalue())
            self.assertFalse(os.path.exists(os.path.join(d, "o")))

    def test_controls_reject_hot_source_off_and_dead_e8(self):
        e8, _ = at.parse_stm_log(os.path.join(PKT, "control_e8_2421032.txt"))
        so, _ = at.parse_stm_log(os.path.join(PKT, "source_off_2412000.txt"))
        self.assertFalse(bg.check_controls(e8, e8, BODY)["go"])      # wrong freq + hot
        self.assertFalse(bg.check_controls(so, so, BODY)["go"])      # no positive control

    def test_run_batch_refuses_without_controls_and_stops_on_error(self):
        class Port:
            def __init__(s, replies): s.rep, s.out = list(replies), b""
            def write(s, b): s.out += b
            def readline(s): return (s.rep.pop(0) + "\n").encode() if s.rep else b""
        K = ("K,pkt,bits=208,pwr=127,on_us=6700,key_cycles=5211,unkey_cycles=4488,max_late_ns=1266,"
             "late_bits=207,b8_on=20060400,b8_end=20060400,b8_off=20000000,a8_on=00000001,a8_off=00000000")
        with tempfile.TemporaryDirectory() as d:
            run = r.Runner(Port(["S,keyed=0,b8=2003a020,a8=00000000", "OK", K, "OK", "ERR busy"]),
                           os.path.join(d, "l.jsonl"))
            with self.assertRaises(bg.GateError):
                bg.run_batch(run, self.env(), {"go": False, "reasons": ["x"]}, BODY, n_pkt=3, power=127,
                             sleep=lambda s: None)
            so, _ = at.parse_stm_log(os.path.join(PKT, "source_off_2412000.txt"))
            e8, _ = at.parse_stm_log(os.path.join(PKT, "control_e8_2421032.txt"))
            for records in (so, e8):
                for rec in records:
                    rec["host_t"] = 100.0
                    if rec["kind"] == "H":
                        rec.update(quiet_us=2000, fw="corrected", bf="approved")
            verified = bg.verify_controls(so, e8, BODY, {"receiver_fw": "corrected", "receiver_bf": "approved",
                "approved_at": 50, "max_control_age_s": 600}, now=110)
            att = bg.run_batch(run, self.env(), verified, BODY, n_pkt=3, power=127, sleep=lambda s: None)
            self.assertEqual([a["ok"] for a in att], [True, False])   # stopped at ERR, no retry
            self.assertEqual(run.port.out.count(b"PKT "), 2)


if __name__ == "__main__":
    unittest.main()
