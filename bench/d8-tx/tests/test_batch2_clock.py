"""Batch1b / batch2 offline attribution fixtures (read-only raw logs).

Finding: batch2 has 8 exact-body CRC-valid receptions whose device-time spacing fixes the attempt
*pattern* but not its absolute shift (attempts 0..9 hold the pattern at shift 0 or 1). Without an independent
host-clock anchor the shift is not provable, so the default counts stay conservative (0 valid) and the
cadence-invariant view (opt-in) credits only attempts observed under every feasible alignment.
batch1b has one feasible alignment. No receipt latency is assumed anywhere."""
import os, sys, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "host"))
import attempts as at
from test_d8_attempts import BODY, P, H, X

REL = os.path.join(HERE, "..", "results", "packet", "reliability")


def load(batch):
    recs, _ = at.parse_stm_log(os.path.join(REL, batch + "_stm.txt"))
    att = at.attempts_from_runner_log(os.path.join(REL, batch + "_esp_out", "esp_runner_log.jsonl"))
    return att, recs


class Batch1b(unittest.TestCase):
    def test_unique_alignment_and_counts(self):
        att, recs = load("batch1b")
        res = at.classify_attempts(att, recs, BODY)
        self.assertEqual(res["counts"], {"valid": 9, "crc_invalid": 0, "malformed": 0, "unobserved": 1})
        self.assertEqual(sum(res["counts"].values()), 10)
        al = res["alignment"]
        self.assertEqual(al["matching_receptions"], 9)
        self.assertTrue(al["unique"])
        self.assertEqual(al["alignments"], [[0, 1, 2, 3, 4, 5, 6, 7, 9]])
        self.assertEqual([e["i"] for e in res["per_attempt"] if e["class"] == "unobserved"], [8])


class Batch2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.att, cls.recs = load("batch2")

    def test_raw_eight_matching_receptions_reported(self):
        res = at.classify_attempts(self.att, self.recs, BODY)
        self.assertEqual(res["alignment"]["matching_receptions"], 8)
        self.assertEqual(len(res["unassigned"]), 8)

    def test_default_counts_conservative_not_invented(self):
        res = at.classify_attempts(self.att, self.recs, BODY)
        self.assertEqual(res["counts"], {"valid": 0, "crc_invalid": 0, "malformed": 0, "unobserved": 10})
        self.assertFalse(res["alignment"]["accepted_into_counts"])

    def test_two_feasible_alignments_not_unique(self):
        al = at.classify_attempts(self.att, self.recs, BODY)["alignment"]
        self.assertFalse(al["unique"])
        self.assertEqual(al["alignments"], [[0, 1, 2, 3, 4, 6, 7, 8], [1, 2, 3, 4, 5, 7, 8, 9]])
        self.assertEqual(al["invariant_attempts"], [1, 2, 3, 4, 7, 8])
        self.assertEqual(al["observed_per_alignment"], [8])
        self.assertIn("independent clock anchor", al["note"].lower())

    def test_opt_in_invariant_view_credits_only_six(self):
        res = at.classify_attempts(self.att, self.recs, BODY, accept_cadence_invariant=True)
        c = res["counts"]
        self.assertEqual(c, {"valid": 6, "crc_invalid": 0, "malformed": 0, "unobserved": 4})
        self.assertEqual(sum(c.values()), 10)
        self.assertEqual([e["i"] for e in res["per_attempt"] if e["class"] == "valid"], [1, 2, 3, 4, 7, 8])
        # the shifting attempts must stay unobserved
        self.assertEqual([e["i"] for e in res["per_attempt"] if e["class"] == "unobserved"], [0, 5, 6, 9])
        # confidence is transparent: primary seq is ambiguous between the two alignments
        e1 = res["per_attempt"][1]
        self.assertIsNone(e1["primary"])
        self.assertEqual(e1["primary_candidates"], [1, 2])


class Synthetic(unittest.TestCase):
    def test_no_false_assignment_on_missing_attempt_ambiguity(self):
        # 5 attempts, attempt 0 missing: shifts 0 and 1 both fit the cadence -> only 1..3 invariant,
        # and attempt 4 / 0 must stay unobserved (truth: 1..4 observed; 4 not provable).
        sends = [100.3 + i * 0.5 for i in range(5)]
        att = [{"i": i, "t_send": t, "ok": True} for i, t in enumerate(sends)]
        T0 = 1_000_000
        recs = [H(T0, 100.0)] + [P(i, T0 + int((0.3 + i * 0.5 + 0.06) * 1e6), BODY, 12, 51, 1) for i in range(1, 5)]
        recs.append(X(T0 + 6_000_000, 106.0))
        res = at.classify_attempts(att, recs, BODY, accept_cadence_invariant=True)
        self.assertEqual(res["alignment"]["alignments"], [[0, 1, 2, 3], [1, 2, 3, 4]])
        self.assertEqual([e["i"] for e in res["per_attempt"] if e["class"] == "valid"], [1, 2, 3])
        self.assertEqual(res["per_attempt"][0]["class"], "unobserved")
        self.assertEqual(res["per_attempt"][4]["class"], "unobserved")

    def test_rate_mismatch_beyond_tolerance_is_infeasible(self):
        sends = [100.0 + i * 0.5 for i in range(4)]
        att = [{"i": i, "t_send": t, "ok": True} for i, t in enumerate(sends)]
        recs = [P(i, 1_000_000 + int(i * 0.6 * 1e6), BODY, 12, 51, 1) for i in range(4)]  # 20 % fast clock
        res = at.classify_attempts(att, recs, BODY, accept_cadence_invariant=True)
        self.assertEqual(res["alignment"]["feasible_alignments"], 0)
        self.assertEqual(res["counts"]["valid"], 0)

    def test_duplicates_cluster_to_one_attempt(self):
        sends = [100.0 + i * 0.5 for i in range(3)]
        att = [{"i": i, "t_send": t, "ok": True} for i, t in enumerate(sends)]
        recs = [P(0, 1_000_000, BODY, 12, 51, 1), P(1, 1_005_000, BODY, 12, 51, 1),
                P(2, 1_500_000, BODY, 12, 51, 1), P(3, 2_000_000, BODY, 12, 51, 1)]
        al = at.classify_attempts(att, recs, BODY)["alignment"]
        self.assertEqual(al["clusters"], 3)
        self.assertEqual(al["alignments"], [[0, 1, 2]])


if __name__ == "__main__":
    unittest.main()
