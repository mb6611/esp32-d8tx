"""Bounded, dry-run-default per-batch gate/report for fixed-channel D8 PKT tests.

`run` prints the plan and opens NOTHING unless `--execute` and `--approved-envelope FILE` are both
given. Hardware limits (enforced before any port is opened): channel 2412000 kHz only, <=10 PKT per
fresh envelope, power argument <=127 (and <= envelope), ~6.7 ms airtime, no retries; source-off and
E8 positive-control receiver logs must pass first. `report` classifies saved logs offline.
No hopping, no other channels, no automatic extension.
"""
import argparse
import hashlib
import json
import math
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import attempts as at
from bench_runner import Envelope, EnvelopeError, Runner, PKT_BODY_BYTES, PKT_DUR_US, PKT_OFFSET, PWR_MAX

ESP_FREQ_KHZ = 2412000
E8_FREQ_KHZ = 2421032
MAX_PKT_PER_BATCH = 10
MAX_ENVELOPE_DURATION_US = 10000
SPACING_S = 0.5
MIN_QUIET_US = 2000          # corrected receiver firmware; old quiet_us=500 logs are stale
MAX_CONTROL_AGE_CAP_S = 3600
APPROVAL_KEY = "control_approval"
# Envelope JSON must carry, besides the Envelope fields, an owner-approved block:
#   "control_approval": {"receiver_fw": "<fw id>", "receiver_bf": "<bf id>",
#                        "approved_at": <epoch s the envelope was approved>,
#                        "max_control_age_s": <=3600}
# Both controls must be recorded at/after approved_at, no older than max_control_age_s at run time.


class GateError(RuntimeError):
    pass


def check_limits(freq_khz, n_pkt, power, envelope=None):
    if freq_khz != ESP_FREQ_KHZ:
        raise GateError("frequency %r not allowed (only %d kHz)" % (freq_khz, ESP_FREQ_KHZ))
    if not isinstance(n_pkt, int) or isinstance(n_pkt, bool) or not 1 <= n_pkt <= MAX_PKT_PER_BATCH:
        raise GateError("PKT count %r outside 1..%d" % (n_pkt, MAX_PKT_PER_BATCH))
    if not isinstance(power, int) or isinstance(power, bool) or not 0 <= power <= PWR_MAX:
        raise GateError("power %r outside 0..%d" % (power, PWR_MAX))
    if envelope is not None:
        try:
            envelope.validate()
        except EnvelopeError as e:
            raise GateError(str(e))
        if (envelope.max_packets > MAX_PKT_PER_BATCH or envelope.max_commands > MAX_PKT_PER_BATCH
                or envelope.max_transitions != 0 or envelope.max_abs_offset > 1
                or envelope.max_abs_offset < PKT_OFFSET
                or envelope.max_duration_us > MAX_ENVELOPE_DURATION_US
                or envelope.max_duration_us < PKT_DUR_US):
            raise GateError("envelope exceeds per-batch limits")
        if n_pkt > envelope.max_packets or power > envelope.max_power:
            raise GateError("request exceeds approved envelope")


def _freq_of(records):
    h = next((r for r in records if r["kind"] == "H"), None)
    return None if h is None else h["freq_req_khz"]


def _valid_expected_id(records, prefix):
    eps = at.epart_seqs(records)
    return [r for r in records if r["kind"] == "P" and r["len"] == PKT_BODY_BYTES and r["crc_ok"] == 1
            and r["seq"] not in eps and r["data"][:3] == prefix]


def _contradictions(records, name, body):
    """CRC-valid P whose seq also has E,EPART is self-contradictory: fail closed."""
    eps = at.epart_seqs(records)
    bad = [r for r in records if r["kind"] == "P" and r["crc_ok"] == 1 and r["seq"] in eps]
    return ["%s control has %d CRC-valid P record(s) contradicted by EPART on the same seq" % (name, len(bad))] if bad else []


def _source_off_hits(records, body):
    """Any CRC-valid len 18 (3-byte ID prefix) or len 20 (first 18 bytes) match, EPART or not."""
    body = bytes(body)
    return [r for r in records if r["kind"] == "P" and r["crc_ok"] == 1
            and ((r["len"] == PKT_BODY_BYTES and r["data"][:3] == body[:3])
                 or (r["len"] == 20 and r["data"][:PKT_BODY_BYTES] == body[:PKT_BODY_BYTES]))]


def check_controls(source_off, e8, expected_body):
    """source_off/e8: parsed receiver records of each control run. Returns dict(go, reasons, ...)."""
    prefix = bytes(expected_body)[:3]
    reasons = []
    if _freq_of(source_off) != ESP_FREQ_KHZ:
        reasons.append("source-off control missing or not at %d kHz" % ESP_FREQ_KHZ)
    if not any(r["kind"] == "X" and r["reason"] == "done" for r in source_off):
        reasons.append("source-off control did not finish (no X,done)")
    so_hits = _source_off_hits(source_off, expected_body)
    reasons += _contradictions(source_off, "source-off", expected_body)
    reasons += _contradictions(e8, "E8", expected_body)
    if so_hits:
        reasons.append("source-off control has %d CRC-valid expected-ID record(s)" % len(so_hits))
    if _freq_of(e8) != E8_FREQ_KHZ:
        reasons.append("E8 control missing or not at %d kHz" % E8_FREQ_KHZ)
    if not any(r["kind"] == "X" and r["reason"] == "done" for r in e8):
        reasons.append("E8 control did not finish (no X,done)")
    e8_hits = _valid_expected_id(e8, prefix)
    if not e8_hits:
        reasons.append("E8 positive control has no CRC-valid expected-ID record")
    return {"go": not reasons, "offline_only": True, "reasons": reasons, "source_off_valid": len(so_hits),
            "e8_valid": len(e8_hits), "verdict": "GO" if not reasons else "NO-GO"}


class VerifiedControls(dict):
    """Result of verify_controls only; run_batch accepts nothing else (a plain dict go=True is refused)."""
    _minted = False

    def __init__(self, *a, _token=None, **k):
        if _token is not _TOKEN:
            raise GateError("VerifiedControls can only be created by verify_controls")
        super().__init__(*a, **k)


_TOKEN = object()


def records_sha256(records):
    blob = json.dumps(records, sort_keys=True, default=lambda b: b.hex() if isinstance(b, bytes) else repr(b))
    return hashlib.sha256(blob.encode()).hexdigest()


FUTURE_SKEW_S = 60


def _approval(approval):
    if not isinstance(approval, dict):
        raise GateError("NO-GO: envelope lacks %s block (receiver_fw, receiver_bf, approved_at, max_control_age_s)" % APPROVAL_KEY)
    fw, bf = approval.get("receiver_fw"), approval.get("receiver_bf")
    at_, age = approval.get("approved_at"), approval.get("max_control_age_s")
    if not (isinstance(fw, str) and fw and isinstance(bf, str) and bf):
        raise GateError("control_approval needs receiver_fw and receiver_bf strings")
    num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)
    if not num(at_) or not num(age) or not math.isfinite(at_) or not math.isfinite(age) \
            or not 0 < age <= MAX_CONTROL_AGE_CAP_S:
        raise GateError("control_approval needs numeric approved_at and 0<max_control_age_s<=%d" % MAX_CONTROL_AGE_CAP_S)
    return fw, bf, at_, age


def verify_controls(source_off, e8, expected_body, approval, now=None, file_hashes=None):
    """Live-approval check. Content check (check_controls) plus: corrected receiver H (quiet_us>=2000),
    identical approved fw/bf in BOTH controls, and freshness vs the approved envelope.
    Raises GateError when not GO; returns VerifiedControls binding hashes and receiver identity."""
    now = time.time() if now is None else now
    if not isinstance(now, (int, float)) or isinstance(now, bool) or not math.isfinite(now):
        raise GateError("NO-GO: current time is not finite")
    fw, bf, approved_at, max_age = _approval(approval)
    res = check_controls(source_off, e8, expected_body)
    reasons = list(res["reasons"])
    ident = {}
    for name, recs in (("source_off", source_off), ("e8", e8)):
        h = next((r for r in recs if r["kind"] == "H"), None)
        if h is None:
            continue                      # already reported by check_controls
        q = h.get("quiet_us")
        if not isinstance(q, int) or q < MIN_QUIET_US:
            reasons.append("%s control receiver quiet_us=%r < %d (stale/uncorrected firmware)" % (name, q, MIN_QUIET_US))
        if h.get("fw") != fw or h.get("bf") != bf:
            reasons.append("%s control receiver identity fw=%r bf=%r != approved fw=%r bf=%r"
                           % (name, h.get("fw"), h.get("bf"), fw, bf))
        ident[name] = {"fw": h.get("fw"), "bf": h.get("bf"), "quiet_us": q}
        raw = [r.get("host_t") for r in recs]
        ok = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
        if not raw or not all(ok(v) for v in raw):
            reasons.append("%s control has missing/non-finite host timestamps (cannot prove freshness)" % name)
        else:
            ts = raw
            x = [r["host_t"] for r in recs if r["kind"] == "X"]
            if not x:
                reasons.append("%s control has no X timestamp (cannot prove freshness)" % name)
            else:
                if min(ts) < approved_at:
                    reasons.append("%s control predates envelope approval (stale)" % name)
                if now - max(x) > max_age:
                    reasons.append("%s control older than %ss at run time" % (name, max_age))
                if max(ts) > now + FUTURE_SKEW_S:
                    reasons.append("%s control timestamp is in the future" % name)
    if reasons:
        raise GateError("NO-GO: controls not valid for live run: " + "; ".join(reasons))
    out = dict(res)
    out.update({"go": True, "offline_only": False, "receiver": ident, "approved_fw": fw, "approved_bf": bf,
                "control_sha256": {"source_off": records_sha256(source_off), "e8": records_sha256(e8)},
                "log_file_sha256": dict(file_hashes or {}), "approved_at": approved_at,
                "max_control_age_s": max_age, "verified_at": now})
    return VerifiedControls(out, _token=_TOKEN)


def run_batch(runner, envelope, controls, body, *, n_pkt, power, freq_khz=ESP_FREQ_KHZ,
              sleep=time.sleep, clock=time.time):
    """Send up to n_pkt PKT commands through `runner`; no retry; stop (unkeyed) at the first problem.
    Returns list of attempt dicts for at.classify_attempts. Refuses unless controls passed."""
    check_limits(freq_khz, n_pkt, power, envelope)
    if not isinstance(controls, VerifiedControls) or not controls.get("go"):
        raise GateError("controls not verified by verify_controls (offline/forged control dicts refused)")
    body = bytes(body)
    if len(body) != PKT_BODY_BYTES:
        raise GateError("body must be %d bytes" % PKT_BODY_BYTES)
    runner.set_phase("esp32-test")
    stat = runner.command("STAT")
    if not stat.ok or stat.records.get("keyed") != 0:
        raise GateError("ESP not idle/unkeyed before batch")
    runner.authorize(envelope)
    out = []
    for i in range(n_pkt):
        t = clock()
        att = {"i": i, "t_send": t, "ok": False, "error": None}
        out.append(att)
        try:
            rep = runner.command("PKT %s %d" % (body.hex(), power))
        except Exception as e:           # runner already attempted unkey for keying commands
            att["error"] = repr(e)
            runner._safe_unkey()
            break
        if not rep.ok:
            att["error"] = rep.error
            break
        att["ok"] = True
        att["on_us"] = rep.records.get("on_us")
        if i + 1 < n_pkt:
            sleep(SPACING_S)
    return out


def format_report(result):
    c = result["counts"]
    lines = ["attempts=%d  valid=%d crc_invalid=%d malformed=%d unobserved=%d  (sum=%d)"
             % (result["attempts"], c["valid"], c["crc_invalid"], c["malformed"], c["unobserved"],
                sum(c.values())),
             "separate: duplicates=%d split_tails=%d noise=%d unassigned=%d receiver_errors=%d"
             % (len(result["duplicates"]), len(result["split_tails"]), len(result["noise"]),
                len(result["unassigned"]), len(result["receiver_errors"]))]
    for e in result["per_attempt"]:
        lines.append("  #%d %s%s primary=%s dup=%s %s" % (
            e["i"], e["class"], " (provisional split)" if e["provisional_split"] else "",
            e["primary"], e["duplicates"], e["note"]))
    return "\n".join(lines)


def pool(results):
    """Pool per-batch counts without merging away the per-batch rows."""
    tot = {k: sum(r["counts"][k] for r in results) for k in at.CLASSES}
    return {"batches": [r["counts"] for r in results], "pooled": tot,
            "attempts": sum(r["attempts"] for r in results)}


def _load_envelope(path):
    with open(path) as f:
        d = json.load(f)
    d.pop(APPROVAL_KEY, None)
    try:
        return Envelope(**d)
    except TypeError as e:
        raise GateError("bad envelope file: %s" % e)


def _load_approval(path):
    with open(path) as f:
        return json.load(f).get(APPROVAL_KEY)


def _sha_file(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def reserve_authorization(envelope_path, controls, out_dir):
    """Single-use consent: atomically create <envelope>.used BEFORE any port opens. Consumed even if the
    run later fails; a new approved envelope (new file) is required to retry. This stops accidental reuse
    only; a local file is not cryptographic consent."""
    marker = envelope_path + ".used"
    rec = {"envelope_sha256": _sha_file(envelope_path), "out_dir": os.path.abspath(out_dir),
           "control_log_sha256": controls["log_file_sha256"], "reserved_at": time.time()}
    try:
        fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o444)
    except FileExistsError:
        raise GateError("NO-GO: envelope already consumed (%s exists); new approved envelope required" % marker)
    except OSError as e:
        raise GateError("NO-GO: cannot reserve single-use authorization: %r" % e)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(rec, sort_keys=True))
            f.flush()
            os.fsync(f.fileno())
    except OSError as e:
        raise GateError("NO-GO: cannot record single-use authorization: %r" % e)


_ECHO_RE = re.compile(r"^(\S+) rxdiag pkt (\d+) (\d+)$")
_EMPTY_RE = re.compile(r"^(\S+) $")


def _finite_ts(tok):
    try:
        v = float(tok)
    except ValueError:
        return False
    return math.isfinite(v)


def parse_control_log(path):
    """at.parse_stm_log, but tolerate ONLY the benign pk.py wrappers: the timestamped command echo
    'rxdiag pkt FREQ MS' (must match H freq/duration) and a trailing timestamped empty line, both
    with finite timestamps and only when an X,done record exists. Anything else stays unparsed."""
    recs, bad = at.parse_stm_log(path)
    h = next((r for r in recs if r["kind"] == "H"), None)
    done = any(r["kind"] == "X" and r.get("reason") == "done" for r in recs)
    rest = []
    for line in bad:
        m = _ECHO_RE.match(line)
        if m and h and done and _finite_ts(m.group(1)) and int(m.group(2)) == h["freq_req_khz"] \
                and int(m.group(3)) == h["duration_ms"]:
            continue
        m = _EMPTY_RE.match(line)
        if m and h and done and _finite_ts(m.group(1)):
            continue
        rest.append(line)
    return recs, rest


def main(argv=None, opener=None, out=sys.stdout):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--freq-khz", type=int, default=ESP_FREQ_KHZ)
    r.add_argument("--count", type=int, default=MAX_PKT_PER_BATCH)
    r.add_argument("--power", type=int, default=PWR_MAX)
    r.add_argument("--execute", action="store_true", help="open hardware (needs --approved-envelope)")
    r.add_argument("--approved-envelope", help="JSON Envelope file approved by the owner for this batch")
    r.add_argument("--esp-port")
    r.add_argument("--source-off-log")
    r.add_argument("--e8-log")
    r.add_argument("--out-dir", help="new directory for the raw runner log + attempts.json")
    p = sub.add_parser("report")
    p.add_argument("--stm-log", required=True)
    p.add_argument("--runner-log", required=True)
    p.add_argument("--body-hex", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "report":
        recs, bad = at.parse_stm_log(a.stm_log)
        res = at.classify_attempts(at.attempts_from_runner_log(a.runner_log), recs, bytes.fromhex(a.body_hex))
        res["unparsed_lines"] = len(bad)
        print(format_report(res), file=out)
        return 0
    import d8_vectors
    body = d8_vectors.build(0)[:PKT_BODY_BYTES]
    try:
        env = _load_envelope(a.approved_envelope) if a.approved_envelope else None
        check_limits(a.freq_khz, a.count, a.power, env)
        if not a.execute:
            print(json.dumps({"mode": "dry-run", "ports_opened": False, "freq_khz": a.freq_khz,
                              "count": a.count, "power": a.power, "body": body.hex(),
                              "airtime_ms": 6.7, "retries": 0, "spacing_s": SPACING_S,
                              "requires": ["source-off + E8 control logs", "approved envelope",
                                           "--execute"]}), file=out)
            return 0
        if env is None or not (a.esp_port and a.source_off_log and a.e8_log and a.out_dir):
            raise GateError("--execute needs --approved-envelope --esp-port --source-off-log --e8-log --out-dir")
        parsed = {}
        for name, path in (("source_off", a.source_off_log), ("e8", a.e8_log)):
            try:
                recs, bad = parse_control_log(path)
            except (ValueError, OSError) as e:
                raise GateError("NO-GO: %s control log unreadable/unparseable: %r" % (name, e))
            if bad:
                raise GateError("NO-GO: %s control log has %d unparsed line(s); controls must fully parse"
                                % (name, len(bad)))
            parsed[name] = recs
        so, e8 = parsed["source_off"], parsed["e8"]
        controls = verify_controls(so, e8, body, _load_approval(a.approved_envelope),
                                   file_hashes={"source_off": _sha_file(a.source_off_log),
                                                "e8": _sha_file(a.e8_log)})
        reserve_authorization(a.approved_envelope, controls, a.out_dir)
        os.makedirs(a.out_dir)           # fails if it exists: never overwrite evidence
        if opener is None:
            def opener(port):
                import serial
                return serial.Serial(port, 921600, timeout=0.05)
        port = opener(a.esp_port)
        runner = Runner(port, os.path.join(a.out_dir, "esp_runner_log.jsonl"))
        try:
            att = run_batch(runner, env, controls, body, n_pkt=a.count, power=a.power, freq_khz=a.freq_khz)
        finally:
            runner._safe_unkey()
        with open(os.path.join(a.out_dir, "attempts.json"), "w") as f:
            json.dump({"attempts": att, "controls": dict(controls), "receiver": controls["receiver"],
                       "control_sha256": controls["control_sha256"],
                       "log_file_sha256": controls["log_file_sha256"]}, f, indent=1)
        print(json.dumps({"sent": len(att), "ok": sum(1 for x in att if x["ok"])}), file=out)
        return 0 if all(x["ok"] for x in att) else 3
    except GateError as e:
        print("REFUSED: %s" % e, file=out)
        return 2


if __name__ == "__main__":
    sys.exit(main())
