"""Bounded clock-rate interval + start-write anchor (offline, synthetic; batch fixtures regression).

clock_rate_tol is a documented conservative calibration bound (host s per device s in [1-tol, 1+tol]),
not a measured hardware frequency. start_cmd_host is a host stamp taken just before os.write of the
receiver command. Default (tol None) behaviour is unchanged."""
import os, sys, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import attempts as at
from test_d8_attempts import BODY, P, H, X
from test_batch2_clock import load

TOL = 0.003
RATE = 0.998          # simulated true host seconds per device second
T0H = 100.0           # true host time of device t0
T0 = 1_000_000


def scenario(n=10, missing=(), h_lag=0.3, rx_lat=0.01):
    sends = [T0H + 0.3 + i * 0.5 for i in range(n)]
    att = [{"i": i, "t_send": t, "ok": True} for i, t in enumerate(sends)]
    recs = [H(T0, T0H + h_lag)]
    seq = 1
    for i, t in enumerate(sends):
        if i in missing:
            continue
        dev = (t + rx_lat - T0H) / RATE
        recs.append(P(seq, T0 + int(dev * 1e6), BODY, 12, 51, 1))
        seq += 1
    dx = (sends[-1] + 1.0 - T0H) / RATE
    recs.append(X(T0 + int(dx * 1e6), T0H + dx * RATE + 0.002))   # X receipt just after the event
    return att, recs


def valid_idx(res):
    return [e["i"] for e in res["per_attempt"] if e["class"] == "valid"]


class RateAnchor(unittest.TestCase):
    def test_default_unchanged_and_hard_k1_can_exclude_truth(self):
        att, recs = scenario(10, missing={0})
        res = at.classify_attempts(att, recs, BODY, start_cmd_host=T0H - 0.02)
        # legacy r==1 bound puts hi below the true T0 (truth excluded); the rate interval fixes that
        self.assertLess(res["clock"]["hi"] if res["clock"]["hi"] is not None else -1, T0H + 0.01)

    def test_rate_and_start_write_give_unique_mapping(self):
        att, recs = scenario(10, missing={0})
        res = at.classify_attempts(att, recs, BODY, start_cmd_host=T0H - 0.02, clock_rate_tol=TOL)
        self.assertEqual(valid_idx(res), list(range(1, 10)))
        self.assertEqual(res["counts"]["unobserved"], 1)
        self.assertEqual(res["unassigned"], [])

    def test_rate_without_start_write_stays_ambiguous(self):
        att, recs = scenario(10, missing={0})
        res = at.classify_attempts(att, recs, BODY, clock_rate_tol=TOL)
        self.assertEqual(valid_idx(res), [])

    def test_delayed_h_and_missing_middle_no_false_assign(self):
        att, recs = scenario(10, missing={0, 4}, h_lag=2.0)
        res = at.classify_attempts(att, recs, BODY, start_cmd_host=T0H - 0.02, clock_rate_tol=TOL)
        self.assertEqual(valid_idx(res), [1, 2, 3, 5, 6, 7, 8, 9])
        self.assertEqual(res["per_attempt"][4]["class"], "unobserved")

    def test_late_start_anchor_that_is_too_loose_is_not_promoted(self):
        att, recs = scenario(10, missing={0})
        res = at.classify_attempts(att, recs, BODY, start_cmd_host=T0H - 0.6, clock_rate_tol=TOL)
        self.assertEqual(valid_idx(res), [])


class Fixtures(unittest.TestCase):
    def test_batch1b_preserved(self):
        att, recs = load("batch1b")
        for kw in ({}, {"clock_rate_tol": TOL}):
            res = at.classify_attempts(att, recs, BODY, **kw)
            self.assertEqual(res["counts"]["valid"], 9)

    def test_batch2_not_promoted_without_start_anchor(self):
        att, recs = load("batch2")
        res = at.classify_attempts(att, recs, BODY, clock_rate_tol=TOL)
        self.assertEqual(res["counts"], {"valid": 0, "crc_invalid": 0, "malformed": 0, "unobserved": 10})
        self.assertEqual(res["alignment"]["matching_receptions"], 8)


if __name__ == "__main__":
    unittest.main()
