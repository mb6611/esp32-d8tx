"""Offline per-attempt accounting for D8 fixed-channel packet tests (no hardware, no serial).

Inputs: ESP PKT attempts (host send times + command outcome), receiver records parsed by
bench_runner.parse_pkt_record (H/P/E/X; P/E carry device time t_us) and the expected 18-byte body.

Clock model. Host receipt stamps of buffered receiver lines are NOT used to place P records.
Only two anchors are used: the H line (device t0_us; receipt is never earlier than the device
start) and X (device t_us; receipt never earlier than that instant). Both give upper bounds on the
host time of device t0; the real value is at most `max_recv_latency_s` below the tighter bound
(or the receiver start command time, if supplied, whichever is later). So a record with device
time d lies at host time in [lo + (d - t0), hi + (d - t0)]. A record is assigned to an attempt
only if that interval intersects exactly one attempt window and no other; otherwise it stays
unassigned and the attempt stays unobserved (never guessed).

Classes (exactly one per attempt, four sum to attempts):
  valid        matching body, crc_ok=1, no EPART
  crc_invalid  matching body, crc_ok=0, complete read with no EPART (real CRC failure)
  malformed    matching body but EPART seq (unknown CRC, incl. status-split reads), or a unique
               in-window record with the expected 3-byte prefix but not the full body
  unobserved   nothing uniquely attributable
Duplicates, noise, split tails and receiver errors are reported separately.
"""
import re
from bench_runner import PKT_BODY_BYTES, compare_p_to_vector

CLASSES = ("valid", "crc_invalid", "malformed", "unobserved")
_EPART_RE = re.compile(r"seq=(\d+);exp=(\d+);got=(\d+)\Z")


def epart_seqs(records, times=None):
    """seq -> (exp, got) for every E,EPART record; times (optional dict) gets seq -> E device t_us."""
    out = {}
    for r in records:
        if r.get("kind") == "E" and r["code"] == "EPART":
            m = _EPART_RE.match(r["detail"])
            if m:
                out[int(m.group(1))] = (int(m.group(2)), int(m.group(3)))
                if times is not None:
                    times[int(m.group(1))] = r["t_us"]
    return out


def clock_window(records, *, start_cmd_host=None, max_recv_latency_s=None, slack_s=0.01, clock_rate_tol=None):
    """Return dict(t0, lo, hi, uncertainty_s) for host time of device t0, or None if no usable anchor.

    hi is a hard upper bound (receipts are never earlier than the device event; slack_s covers clock
    drift/stamp jitter). lo is only set by independent evidence: start_cmd_host (receiver cannot start
    before its command) or a *verified* max_recv_latency_s. Default None = unbounded below (-inf);
    classify_attempts then tightens it using send times and the matching records themselves.
    """
    h = next((r for r in records if r.get("kind") == "H" and "host_t" in r), None)
    if h is None:
        return None
    t0 = h["t0_us"]
    hi = h["host_t"]
    x = next((r for r in records if r.get("kind") == "X" and "host_t" in r), None)
    if x is not None and x["t_us"] >= t0:
        # X receipt >= host time of that device instant = T0 + d*r, r >= 1 - clock_rate_tol, so
        # T0 <= x.host - d*(1-tol). tol None keeps the legacy r == 1 assumption.
        hi = min(hi, x["host_t"] - (x["t_us"] - t0) / 1e6 * (1.0 - (clock_rate_tol or 0.0)))
    hi += slack_s
    lo = float("-inf")
    if max_recv_latency_s is not None:
        lo = hi - max_recv_latency_s
    if start_cmd_host is not None:
        lo = max(lo, start_cmd_host)
    if lo > hi:
        return None
    return {"t0": t0, "lo": lo, "hi": hi, "uncertainty_s": hi - lo}


def decode_split_status(tail):
    """Provisional decode of a 2-byte stray P: RSSI byte, then CRC_OK(bit7)|LQI. Hypothesis only."""
    return {"rssi": tail[0] - 256 if tail[0] > 127 else tail[0], "lqi": tail[1] & 0x7F,
            "crc_ok": tail[1] >> 7, "provisional": True}


def classify_attempts(attempts, records, expected_body, *, start_cmd_host=None, pre_s=0.02,
                      post_s=0.05, max_recv_latency_s=None, split_gap_us=2000, step_s=0.001,
                      accept_cadence_invariant=False, rate_tol=0.02, jitter_s=0.05,
                      clock_rate_tol=None, clock_rate_step=0.0005):
    """attempts: list of dict(i, t_send, ok=True, error=None). Returns the accounting dict.

    Result key "alignment" is always present and informational (latency-free cadence analysis, see
    cadence_alignments). clock_rate_tol (default None = device clock assumed exactly 1 host s per device s)
    is an explicit, conservative, user-calibrated bound: host seconds per device second lies in
    [1-tol, 1+tol] (e.g. 0.003); it is NOT a measured hardware frequency. start_cmd_host should be a host
    timestamp taken just BEFORE the os.write of the receiver `rxdiag pkt` command (lower bound of T0).
    Association must be identical across every feasible (T0, rate) pair. With accept_cadence_invariant=True, attempts that are observed in EVERY feasible
    cadence alignment (same class in all) are also classified; the default leaves counts untouched."""
    expected_body = bytes(expected_body)
    if len(expected_body) != PKT_BODY_BYTES:
        raise ValueError("expected_body must be 18 bytes")
    from d8_vectors import crc16
    c = crc16(expected_body)
    vector = expected_body + bytes([c >> 8, c & 0xFF])
    prefix = expected_body[:3]
    etimes = {}
    eps = epart_seqs(records, etimes)
    clk = clock_window(records, start_cmd_host=start_cmd_host, max_recv_latency_s=max_recv_latency_s,
                       clock_rate_tol=clock_rate_tol)
    ps = [r for r in records if r.get("kind") == "P"]
    errors = [r for r in records if r.get("kind") == "E" and r["code"] != "EPART"]

    # --- per-record facts
    facts = {}
    for p in ps:
        m = p["len"] in (18, 20) and compare_p_to_vector(p, vector)["bytes_equal"]
        facts[p["seq"]] = {"rec": p, "match": bool(m), "epart": p["seq"] in eps, "tail_of": None,
                           "tail": None}
    # --- provisional split pairs: EPART 18-of-20 head, then EPART 2-byte tail; gap measured between the
    # two E record device times (P t_us is stamped earlier, ~5 ms before its E)
    for a, b in zip(ps, ps[1:]):
        fa, fb = facts[a["seq"]], facts[b["seq"]]
        if (fa["match"] and fa["epart"] and a["len"] == 18 and eps[a["seq"]][1] == 18 and b["len"] == 2
                and fb["epart"] and 0 <= etimes[b["seq"]] - etimes[a["seq"]] <= split_gap_us and fb["tail_of"] is None):
            fb["tail_of"] = a["seq"]
            fa["tail"] = b["seq"]
            fa["status"] = decode_split_status(b["data"])

    def kind_of(f):
        p = f["rec"]
        if f["epart"]:
            return "malformed"
        return "valid" if p["crc_ok"] == 1 else "crc_invalid"

    # --- feasible host times of device t0. Candidates are every T0 in [lo, hi] (grid step_s) at which
    # every full-body-matching record lands in some attempt window (a transmitted body cannot be received
    # before it was sent). No receipt-latency bound is assumed; the unknown latency is constrained only by
    # hi (H/X receipts), start_cmd_host, an explicitly verified max_recv_latency_s, and this joint check.
    feas = []   # (T0 host, rate) pairs
    rates = [1.0]
    if clock_rate_tol:
        nr = max(1, int(round(2 * clock_rate_tol / clock_rate_step)))
        rates = [1.0 - clock_rate_tol + 2 * clock_rate_tol * q / nr for q in range(nr + 1)]
    if clk is not None and attempts:
        mds = [(p["t_us"] - clk["t0"]) / 1e6 for p in ps if p["len"] in (18, 20)
               and compare_p_to_vector(p, vector)["bytes_equal"]]
        sends = [a["t_send"] for a in attempts]
        for r in rates:
            floor = clk["lo"]
            if mds:
                floor = max(floor, min(sends) - max(mds) * r - post_s - PKT_AIR_S - step_s)
            else:
                floor = max(floor, clk["hi"] - 1.0)
            n = int((clk["hi"] - floor) / step_s) + 1
            for k in range(n):
                t = clk["hi"] - k * step_s
                if all(any(t + d * r <= x + PKT_AIR_S + post_s and t + d * r >= x - pre_s for x in sends)
                       for d in mds):
                    feas.append((t, r))
    clk_out = None
    if clk is not None:
        clk_out = dict(clk)
        if feas:
            ts = [t for t, _ in feas]
            clk_out["lo"], clk_out["hi"] = min(ts), max(ts)
            clk_out["clock_rate_tol"] = clock_rate_tol
            clk_out["uncertainty_s"] = clk_out["hi"] - clk_out["lo"]
            clk_out["verified_latency_bound"] = max_recv_latency_s
        else:
            clk_out["lo"] = clk_out["hi"] = None
            clk_out["uncertainty_s"] = None
            clk_out["inconsistent"] = True
    clk = clk_out

    def hit_attempts(rec):
        """Attempt indices the record maps to; [] unless identical single attempt across all feasible T0
        (ambiguity is returned as the union with >1 entries)."""
        if not feas:
            return []
        d = (rec["t_us"] - clk["t0"]) / 1e6
        sets = set()
        for t, r in feas:
            sets.add(tuple(a["i"] for a in attempts
                           if t + d * r <= a["t_send"] + PKT_AIR_S + post_s and t + d * r >= a["t_send"] - pre_s))
        u = sorted({i for st in sets for i in st})
        if len(sets) > 1 and len(u) == 1:   # some feasible T0 puts it in no window: not stable
            return u + [-1]
        return u

    per = {a["i"]: {"i": a["i"], "t_send": a["t_send"], "command_ok": a.get("ok", True),
                    "command_error": a.get("error"), "class": "unobserved", "primary": None,
                    "duplicates": [], "candidates": [], "provisional_split": False,
                    "note": ""} for a in attempts}
    unassigned, noise, tails = [], [], []
    assigned_matches = {}
    for seq, f in facts.items():
        if f["tail_of"] is not None:
            tails.append(seq)
            continue
        hits = hit_attempts(f["rec"])
        if f["match"]:
            if len(hits) == 1:
                assigned_matches.setdefault(hits[0], []).append(seq)
            else:
                unassigned.append({"seq": seq, "why": "no clock anchor" if clk is None else "clock inconsistent" if not feas else
                                   ("ambiguous: %d attempt windows" % len(hits) if hits else "outside all windows")})
        else:
            noise.append(seq)
            for i in hits:
                if i >= 0:
                    per[i]["candidates"].append(seq)
    order = {"valid": 0, "crc_invalid": 1, "malformed": 2}
    for i, seqs in assigned_matches.items():
        seqs.sort(key=lambda s: (order[kind_of(facts[s])], facts[s]["rec"]["t_us"]))
        best, rest = seqs[0], seqs[1:]
        e = per[i]
        e["class"] = kind_of(facts[best])
        e["primary"] = best
        e["duplicates"] = rest
        e["provisional_split"] = facts[best]["tail"] is not None
        if e["provisional_split"]:
            e["split_status"] = facts[best]["status"]
            e["note"] = "EPART 18/20 + 2-byte tail; status split inferred (provisional), CRC unknown"
    for i, e in per.items():
        if e["primary"] is not None:
            continue
        cands = [s for s in e["candidates"] if len(hit_attempts(facts[s]["rec"])) == 1]
        pref = [s for s in cands if facts[s]["rec"]["data"][:3] == prefix]
        if len(cands) == 1 and len(pref) == 1:
            e["class"], e["primary"] = "malformed", pref[0]
            e["note"] = "unique in-window record with expected prefix; not the full body"
        elif cands:
            e["note"] = "in-window records %s not uniquely attributable" % cands
    # --- latency-free cadence analysis (informational unless accept_cadence_invariant)
    mrecs = [f for f in facts.values() if f["match"] and f["tail_of"] is None]
    al = cadence_alignments([a["t_send"] for a in attempts], [f["rec"]["t_us"] / 1e6 for f in mrecs],
                            rate_tol=rate_tol, jitter_s=jitter_s)
    pos = {a["i"]: k for k, a in enumerate(attempts)}
    inv = {}
    if al["maps"]:
        for k_ in range(len(attempts)):
            outs = []
            for mp in al["maps"]:
                if k_ in mp:
                    cl = al["clusters"][mp.index(k_)]
                    seqs = sorted((mrecs[x] for x in cl), key=lambda f: (order[kind_of(f)], f["rec"]["t_us"]))
                    outs.append((kind_of(seqs[0]), seqs[0]["rec"]["seq"], [f["rec"]["seq"] for f in seqs[1:]]))
                else:
                    outs.append(None)
            if all(o is not None for o in outs):
                inv[k_] = outs
    alignment = {
        "matching_receptions": len(mrecs), "clusters": len(al["clusters"]),
        "feasible_alignments": len(al["maps"]), "rate_tol": rate_tol, "jitter_s": jitter_s,
        "unique": len(al["maps"]) == 1,
        "alignments": [[attempts[k]["i"] for k in mp] for mp in al["maps"]],
        "invariant_attempts": [attempts[k]["i"] for k in sorted(inv)],
        "observed_per_alignment": sorted({len(mp) for mp in al["maps"]}),
        "accepted_into_counts": False,
        "note": "cadence analysis only; no receipt latency assumed. Independent clock anchor needed to "
                "resolve alignments" if len(al["maps"]) > 1 else "",
    }
    if accept_cadence_invariant and al["maps"]:
        for k_, outs in inv.items():
            e = per[attempts[k_]["i"]]
            if e["primary"] is not None:
                continue
            classes = {o[0] for o in outs}
            if len(classes) == 1:
                e["class"] = classes.pop()
                seqs = {o[1] for o in outs}
                e["primary"] = seqs.pop() if len(seqs) == 1 else None
                e["primary_candidates"] = sorted({o[1] for o in outs})
                e["duplicates"] = sorted(outs[0][2]) if len(outs) == 1 else []
                e["note"] = "cadence-invariant over %d alignment(s)" % len(outs)
        alignment["accepted_into_counts"] = True
    counts = {k: sum(1 for e in per.values() if e["class"] == k) for k in CLASSES}
    assert sum(counts.values()) == len(attempts)
    return {"attempts": len(attempts), "counts": counts, "per_attempt": [per[a["i"]] for a in attempts],
            "duplicates": [s for e in per.values() for s in e["duplicates"]],
            "split_tails": tails, "noise": noise, "unassigned": unassigned,
            "receiver_errors": errors, "clock": clk, "alignment": alignment,
            "raw_records": len(records)}


PKT_AIR_S = 0.0067


def cadence_alignments(sends, recv_times, *, rate_tol=0.02, jitter_s=0.05, dup_gap_s=None, rate_step=0.0002):
    """Latency-free alignment of matching receptions to attempts using only device-time spacing.

    sends: host send times of attempts (ascending). recv_times: device times (s) of receptions whose body
    equals the expected one. Receptions closer than dup_gap_s (default 0.3 x smallest send spacing) are one
    cluster (one attempt, duplicates). A map (cluster j -> attempt a_j, strictly increasing) is feasible iff
    some relative clock rate r in [1-rate_tol, 1+rate_tol] gives |(m_j-m_0)*r - (s_aj - s_a0)| <= jitter_s
    for every j. No receipt latency is used or assumed; the only assumptions are those two stated numbers.
    Returns dict(clusters=[[recv idx]], maps=[tuple of attempt positions], rate_tol, jitter_s)."""
    n = len(sends)
    order = sorted(range(len(recv_times)), key=lambda k: recv_times[k])
    if dup_gap_s is None:
        gaps = [b - a for a, b in zip(sends, sends[1:]) if b > a]
        dup_gap_s = 0.3 * min(gaps) if gaps else 0.0
    clusters = []
    for k in order:
        if clusters and recv_times[k] - recv_times[clusters[-1][-1]] < dup_gap_s:
            clusters[-1].append(k)
        else:
            clusters.append([k])
    if not clusters or n == 0:
        return {"clusters": clusters, "maps": [], "rate_tol": rate_tol, "jitter_s": jitter_s}
    m = [recv_times[c[0]] for c in clusters]
    maps = set()
    steps = int(round(2 * rate_tol / rate_step))
    for a0 in range(n):
        for q in range(steps + 1):
            r = 1 - rate_tol + q * rate_step
            cur, ok = [a0], True
            for j in range(1, len(m)):
                want = (m[j] - m[0]) * r
                cands = [a for a in range(cur[-1] + 1, n) if abs(want - (sends[a] - sends[a0])) <= jitter_s]
                if len(cands) != 1:   # none: infeasible; several: this r is not discriminating, skip
                    ok = False
                    break
                cur.append(cands[0])
            if ok:
                maps.add(tuple(cur))
    return {"clusters": clusters, "maps": sorted(maps), "rate_tol": rate_tol, "jitter_s": jitter_s}


# ------------------------------------------------------------------ log readers

def parse_stm_log(path):
    """Read a pk.py-style receiver log ('<host_ts> <record>' lines). Returns (records, unparsed)."""
    from bench_runner import parse_pkt_record, ReportError
    recs, bad = [], []
    for line in open(path):
        line = line.rstrip("\n")
        if not line.strip() or line.startswith("#"):
            continue
        ts, _, body = line.partition(" ")
        if not body or body[0] not in "HPEX" or body[1:2] != ",":
            bad.append(line)
            continue
        try:
            r = parse_pkt_record(body, strict_partial=False)
        except ReportError:
            bad.append(line)
            continue
        r["host_t"] = float(ts)
        recs.append(r)
    return recs, bad


def attempts_from_runner_log(path):
    """PKT attempts from a Runner JSONL log: send time = the 'cmd' event time; ok iff OK seen."""
    import json
    out, cur = [], None
    for line in open(path):
        j = json.loads(line)
        ev = j.get("event")
        if ev == "cmd" and j["text"].startswith("PKT "):
            cur = {"i": len(out), "t_send": j["t"], "ok": False, "error": "no terminal reply"}
            out.append(cur)
        elif ev == "cmd":
            cur = None
        elif cur is not None and ev == "reply_line":
            if j["text"] == "OK":
                cur["ok"], cur["error"] = True, None
            elif j["text"].startswith("ERR"):
                cur["error"] = j["text"]
        elif cur is not None and ev in ("timeout", "bad_reply"):
            cur["error"] = ev
    return out
