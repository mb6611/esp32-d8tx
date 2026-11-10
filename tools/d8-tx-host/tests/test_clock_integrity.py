"""Clock-correlation integrity: unverified receipt latency must never yield a (possibly wrong) unique match."""
import os, sys, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import attempts as at
import d8_vectors
from test_d8_attempts import P, H, X, BODY

PKT = os.path.join(HERE, "..", "..", "..", "experiments", "05-first-packet", "data")
T0 = 1_000_000
HOST0 = 100.0           # true host time of device t0
SP = 0.5


def scenario(n, missing, latency):
    """True T0 = HOST0; H receipt delayed by `latency`; attempt i sent at HOST0+0.3+i*SP, received 60ms later
    unless i in `missing`. X is delayed by the same latency (worst case: not independently timely)."""
    att = [{"i": i, "t_send": HOST0 + 0.3 + i * SP, "ok": True} for i in range(n)]
    recs = [H(T0, HOST0 + latency)]
    for i in range(n):
        if i in missing:
            continue
        recs.append(P(i, T0 + int((0.3 + i * SP + 0.06) * 1e6), BODY, 12, 51, 1))
    recs.append(X(T0 + 6_000_000, HOST0 + 6 + latency))
    return att, recs


class DelayedH(unittest.TestCase):
    def test_no_false_unique_assignment(self):
        for lat in (0.0, 0.5, 0.6, 0.7):
            for missing in ((), (0,), (1,), (3,), (0, 1)):
                att, recs = scenario(5, set(missing), lat)
                res = at.classify_attempts(att, recs, BODY)
                for e in res["per_attempt"]:
                    if e["class"] == "valid":
                        # truth: attempt i observed iff not missing; a claimed valid must be a real one
                        self.assertNotIn(e["i"], missing, (lat, missing, e))
                        self.assertEqual(e["primary"], e["i"], (lat, missing, e))   # P seq == true attempt

    def test_missing_first_with_delay_is_ambiguous_not_shifted(self):
        for lat in (0.5, 0.6, 0.7):
            att, recs = scenario(5, {0}, lat)
            res = at.classify_attempts(att, recs, BODY)
            self.assertEqual(res["counts"]["valid"] + res["counts"]["malformed"], 0, lat)
            self.assertEqual(res["counts"]["unobserved"], 5)
            self.assertTrue(res["unassigned"])

    def test_first_record_anchors_when_nothing_missing_before_it(self):
        att, recs = scenario(5, {3}, 0.7)
        res = at.classify_attempts(att, recs, BODY)
        self.assertEqual([e["class"] for e in res["per_attempt"]],
                         ["valid", "valid", "valid", "unobserved", "valid"])

    def test_no_default_latency_assumption(self):
        att, recs = scenario(5, {0}, 0.6)
        res = at.classify_attempts(att, recs, BODY)
        self.assertIsNone(res["clock"]["verified_latency_bound"])
        # an explicitly verified bound may resolve it
        res2 = at.classify_attempts(att, recs, BODY, max_recv_latency_s=0.25)
        self.assertIsNotNone(res2["clock"])

    def test_start_command_anchor_resolves(self):
        att, recs = scenario(5, {0}, 0.6)
        res = at.classify_attempts(att, recs, BODY, start_cmd_host=HOST0 - 0.01)
        self.assertEqual([e["class"] for e in res["per_attempt"]],
                         ["unobserved", "valid", "valid", "valid", "valid"])

    def test_inconsistent_clock_is_not_guessed(self):
        att, recs = scenario(3, set(), 0.0)
        for a in att:
            a["t_send"] += 30.0
        res = at.classify_attempts(att, recs, BODY)
        self.assertEqual(res["counts"]["unobserved"], 3)
        self.assertTrue(res["clock"].get("inconsistent"))


class Historical(unittest.TestCase):
    def test_u7_batch1_unique_without_latency_assumption(self):
        recs, _ = at.parse_stm_log(os.path.join(PKT, "batch1_2412000_stm.txt"))
        att = at.attempts_from_runner_log(os.path.join(PKT, "esp_runner_log.jsonl"))
        res = at.classify_attempts(att, recs, BODY)
        self.assertEqual(res["counts"], {"valid": 7, "crc_invalid": 0, "malformed": 2, "unobserved": 1})
        self.assertIsNone(res["clock"]["verified_latency_bound"])
        self.assertLess(res["clock"]["uncertainty_s"], 0.25)


if __name__ == "__main__":
    unittest.main()
