"""U3 batch driver for batches 3..10 (--batch N, default 3; N<3 or >10 rejected; N>=4 needs batch N-1 fully done,
at most 100 physical PKT total). Batch 4 only waits 1.5 s after first H before the first PKT.
E8 control is reused only while <3600 s old; if expired the driver STOPs (owner must toggle E8 on, new control, then E8 off).
U3 batch3 driver (final batch). Subcommands (nothing runs on import):
  envelope  OFFLINE: write fresh one-use batch3_envelope.json (approved_at = the owner's already-approved stage
            timestamp APPROVED_AT, max_abs_offset 1). Refuses unless the existing E8 control is unchanged-pinned,
            recorded at/after APPROVED_AT and <= 3600 s old.
  run       reuse existing E8 control (E8 stays OFF; no E8 toggle, no new control), new 5 s source-off @2412000,
            gates, ONE bounded batch_gate.main (<=10 PKT, 2412000, pwr<=127, 0.5 s spacing) triggered from the
            first verified H of the main capture. One post STAT attempt, no retries.
  classify  OFFLINE: classify saved logs (clock_rate_tol=0.003, pre-write start_cmd_host anchor) and list raw
            matching records separately.
Every failure stops with NO retry and NO new envelope; a consumed envelope stays consumed.
The final E8 recheck after the batch is handled separately by the owner/orchestrator, not here.
"""
import sys, os, time, io, threading, json, re, glob, hashlib, argparse
sys.path.insert(0,'experiments/05-first-packet/scripts'); sys.path.insert(0, 'tools/d8-tx-host')
R = 'experiments/06-fixed-channel-reliability/data/reliability/'
ENV = R + 'batch3_envelope.json'; OUT = R + 'batch3_esp_out'; STM = R + 'batch3_stm.txt'
SRC = R + 'source_off_batch3_2412000.txt'; E8 = R + 'control_e8_2421032.txt'
ANCHOR = R + 'batch3_anchor.json'; POST = R + 'post_batch3_esp.txt'; HASHES = R + 'batch3_hashes.txt'
REPORT = R + 'batch3_report.txt'; PRE = R + 'pre_batch3_esp.txt'
BATCH = 3; GATE_DELAY_S = 0.4          # batch4 only: 1.5 s after first corrected H before first PKT
MAX_BATCH = 10; MAX_PKT_TOTAL = 100
ESP_PORT = '/dev/cu.usbserial-0001'
APPROVED_AT = 1793992800; MAX_AGE = 3600; CLOCK_TOL = 0.003
FW, BF, QUIET = 'c5cc593b', '948ba63', 'quiet_us=2000'   # corrected receiver firmware identity
MAIN_MS = 11000; SRC_MS = 5000; E8_MS = 20000; COUNT = 10; POWER = 127; FREQ = 2412000; E8_FREQ = 2421032

class Stop(RuntimeError): pass

def paths_for(n):
    return {'ENV': R + 'batch%d_envelope.json' % n, 'OUT': R + 'batch%d_esp_out' % n, 'STM': R + 'batch%d_stm.txt' % n,
            'SRC': R + 'source_off_batch%d_2412000.txt' % n, 'ANCHOR': R + 'batch%d_anchor.json' % n,
            'POST': R + 'post_batch%d_esp.txt' % n, 'PRE': R + 'pre_batch%d_esp.txt' % n,
            'HASHES': R + 'batch%d_hashes.txt' % n, 'REPORT': R + 'batch%d_report.txt' % n}

def physical_pkt_total(rel=None):
    """Physical PKT attempts so far over ALL batch*_esp_out dirs (incl. aborted runs): attempts with ok true;
    a dir with a runner log but unreadable attempts.json counts COUNT (conservative)."""
    rel = rel or R; tot = 0
    for d in glob.glob(rel + 'batch*_esp_out'):
        try: tot += sum(1 for x in json.load(open(d + '/attempts.json'))['attempts'] if x.get('ok'))
        except Exception: tot += COUNT
    return tot

def prior_gate(n, rel=None):
    """Batch n>=4 needs batch n-1 fully successful. Raises Stop. Also enforces group and PKT caps."""
    rel = rel or R
    if not isinstance(n, int) or n < 3 or n > MAX_BATCH: raise Stop('batch %r outside 3..%d' % (n, MAX_BATCH))
    if physical_pkt_total(rel) + COUNT > MAX_PKT_TOTAL: raise Stop('would exceed %d total physical PKT' % MAX_PKT_TOTAL)
    if n == 3: return
    q = n - 1; f = lambda x: rel + x % q
    for x in ('batch%d_envelope.json.used', 'batch%d_stm.txt', 'post_batch%d_esp.txt', 'batch%d_hashes.txt',
              'batch%d_esp_out/attempts.json', 'source_off_batch%d_2412000.txt'):
        if not os.path.exists(f(x)): raise Stop('prior batch %d control/evidence missing: %s' % (q, f(x)))
    if os.path.exists(rel + 'batch%d_envelope.json.used' % n): raise Stop('batch %d already attempted' % n)
    at_ = json.load(open(f('batch%d_esp_out/attempts.json')))['attempts']
    if len(at_) != COUNT or not all(x.get('ok') for x in at_): raise Stop('prior batch %d not 10/10 attempts ok' % q)
    if not any(l.split(' ', 1)[-1].startswith('X,') and l.rstrip().endswith(',done') for l in open(f('batch%d_stm.txt'))):
        raise Stop('prior batch %d STM lacks X done' % q)
    stats = [l for l in open(f('post_batch%d_esp.txt')) if l.startswith('STAT')]
    if not stats or 'keyed=0' not in stats[-1]: raise Stop('prior batch %d post STAT not keyed=0' % q)

def configure(n):
    """Point every path global at batch n (n=3 is the unchanged original). Applies batch4-only start delay."""
    global BATCH, GATE_DELAY_S
    if not isinstance(n, int) or n < 3 or n > MAX_BATCH: raise Stop('batch %r outside 3..%d' % (n, MAX_BATCH))
    globals().update(paths_for(n)); BATCH = n; GATE_DELAY_S = 1.5 if n == 4 else 0.4

def die(msg):
    print('STOP (no retry, no new envelope):', msg, flush=True); sys.exit(2)

def sha(p):
    return hashlib.sha256(open(p, 'rb').read()).hexdigest()

def capture(fd, r, freq, ms, out, pre=None, expect_h=None):
    """Like pk.stm_run but stamps host time IMMEDIATELY BEFORE the command write (t_cmd_pre) and after it,
    logs every received line raw. Returns (lines, t_cmd_pre, t_cmd_post). `expect_h(line)->bool` gates pre()."""
    cmd = "rxdiag pkt %d %d\n" % (freq, ms)
    f = open(out, 'x')                                   # never overwrite evidence
    f.write("# cmd=rxdiag pkt %d %d utc=%s\n" % (freq, ms, time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())))
    t_pre = time.time(); r_write = os.write(fd, cmd.encode()); t_post = time.time()
    f.write("# t_cmd_pre_write_host=%.6f t_cmd_post_write_host=%.6f\n" % (t_pre, t_post)); f.flush()
    t0 = time.time(); buf = b''; L = []; called = False
    while time.time() - t0 < ms / 1000 + 6:
        buf += r.rd(fd, 0.02); *ls, buf = buf.split(b"\n")
        for l in ls:
            s = l.decode('latin1').rstrip("\r"); f.write("%.4f %s\n" % (time.time(), s)); L.append(s)
            if s.startswith("H,") and pre and not called:
                called = True
                if expect_h is None or expect_h(s): pre()
        if any(s.startswith("X,") for s in L): break
    f.flush()
    if not any(s.startswith("X,") for s in L): os.write(fd, b"q"); r.rd(fd, .4)
    f.close(); return L, t_pre, t_post

def h_ok(s, freq, ms):
    return all(k in s for k in ('fw=' + FW, 'bf=' + BF, QUIET, 'freq_req_khz=%d' % freq, 'duration_ms=%d' % ms, 'mode=pkt'))

def esp_idle(tag, opener=None):
    import serial
    s = (opener or (lambda p: serial.Serial(p, 921600, timeout=0.3)))(ESP_PORT); s.reset_input_buffer()
    def ask(c):
        s.write((c + '\n').encode()); time.sleep(0.4); return s.read(400).decode(errors='replace')
    a = ask('PING'); b = ask('STAT'); s.close()
    open(POST if tag == 'post' else PRE, 'a').write("PING %r\nSTAT %r\n" % (a, b))
    ok = 'd8tone' in a and 'keyed=0' in b
    print('ESP', tag, repr(a), repr(b), 'idle' if ok else 'NOT IDLE', flush=True)
    return ok

def e8_check(path=None, now=None, approved_at=None):
    """Existing E8 control must parse fully, be recorded at/after approved_at, end with X, and be <=MAX_AGE old.
    Returns (min_ts, last_X_ts). Raises Stop otherwise (final age check is re-done by batch_gate)."""
    import batch_gate as g
    path = path or E8; now = time.time() if now is None else now
    approved_at = APPROVED_AT if approved_at is None else approved_at
    recs, bad = g.parse_control_log(path)
    if bad: raise Stop('E8 log has %d unparsed lines' % len(bad))
    ts = [r.get('host_t') for r in recs]; xs = [r['host_t'] for r in recs if r['kind'] == 'X']
    if not ts or not xs: raise Stop('E8 log lacks timestamps/X')
    if min(ts) < approved_at: raise Stop('E8 log predates approved_at %s' % approved_at)
    if now - max(xs) > MAX_AGE: raise Stop('E8 log older than %ss (age %.0f)' % (MAX_AGE, now - max(xs)))
    if max(ts) > now + 60: raise Stop('E8 log timestamp in the future')
    return min(ts), max(xs)

def make_envelope():
    return {"test": "U3 batch%d 2412000 pwr127 owner-scoped" % BATCH, "max_duration_us": 6800, "max_abs_offset": 1,
            "max_power": POWER, "max_transitions": 0, "max_commands": COUNT, "max_packets": COUNT,
            "control_approval": {"receiver_fw": FW, "receiver_bf": BF, "approved_at": APPROVED_AT,
                                "max_control_age_s": MAX_AGE}}

def cmd_envelope(a):
    try: prior_gate(BATCH)
    except Stop as e: die('prior-batch gate: %s' % e)
    for p in (ENV, ENV + '.used', OUT, STM, SRC, ANCHOR):
        if os.path.exists(p): die('%s already exists; batch files are single-use' % p)
    try: e8_check()
    except Stop as e: die('E8 control not usable: %s' % e)
    env = make_envelope()
    import batch_gate as g
    g.check_limits(FREQ, COUNT, POWER, g._load_envelope_obj(env) if hasattr(g, '_load_envelope_obj')
                   else __import__('bench_runner').Envelope(**{k: v for k, v in env.items() if k != 'control_approval'}))
    with open(ENV, 'x') as f: json.dump(env, f)
    print('wrote', ENV, 'approved_at', APPROVED_AT, 'E8 sha256', sha(E8))

def _open_stm():
    import pk
    return pk, pk.stm_open()

def _verify_offline(env_path):
    """Pre-flight with batch_gate's own verification (without reserving the envelope)."""
    import batch_gate as g, d8_vectors
    body = d8_vectors.build(0)[:g.PKT_BODY_BYTES]
    env = g._load_envelope(env_path); g.check_limits(FREQ, COUNT, POWER, env)
    parsed = {}
    for n, p in (('source_off', SRC), ('e8', E8)):
        recs, bad = g.parse_control_log(p)
        if bad: raise Stop('%s log has %d unparsed lines' % (n, len(bad)))
        parsed[n] = recs
    # H gate on both controls
    for n, p, fr, ms in (('source_off', SRC, FREQ, SRC_MS), ('e8', E8, E8_FREQ, E8_MS)):
        h = next((l for l in open(p) if ' H,' in l), None)
        if not h or not h_ok(h, fr, ms): raise Stop('%s H not corrected/identity mismatch: %r' % (n, h))
    g.verify_controls(parsed['source_off'], parsed['e8'], body, g._load_approval(env_path),
                      file_hashes={'source_off': sha(SRC), 'e8': sha(E8)})

def cmd_run(a):
    try: prior_gate(BATCH)
    except Stop as e: die('prior-batch gate: %s' % e)
    for p in (STM, OUT, SRC, ANCHOR, POST, ENV + '.used'):
        if os.path.exists(p): die('%s exists; batch already attempted' % p)
    for p in (ENV, E8):
        if not os.path.exists(p): die('missing %s (run envelope first; E8 control must already exist)' % p)
    try: e8_check()
    except Stop as e: die('E8 control not usable: %s' % e)
    e8_sha_before = sha(E8)
    if not esp_idle('pre'): die('ESP not idle')
    pk, fd = _open_stm(); r = pk.r
    # 1) fresh 5 s source-off (E8 must be OFF)
    L, _, _ = capture(fd, r, FREQ, SRC_MS, SRC)
    print('source-off P', sum(l.startswith('P,') for l in L), 'X', [l for l in L if l.startswith('X,')])
    try: _verify_offline(ENV)
    except Exception as e: die('controls not valid: %r' % (e,))
    print('controls verified (offline pre-check)', flush=True)
    # 2) main capture + gate thread from first corrected H
    import batch_gate as g
    buf = bytearray(); orig = r.rd
    def rd(*x, **k):
        d = orig(*x, **k); buf.extend(d); return d
    r.rd = rd
    res = {}; gout = io.StringIO(); th = []
    def gate():
        try:
            time.sleep(GATE_DELAY_S)
            res['rc'] = g.main(['run', '--execute', '--approved-envelope', ENV, '--esp-port', ESP_PORT,
                '--source-off-log', SRC, '--e8-log', E8, '--out-dir', OUT, '--count', str(COUNT),
                '--power', str(POWER), '--freq-khz', str(FREQ)], out=gout)
        except BaseException as e:
            res['exc'] = repr(e)
    def pre():
        t = threading.Thread(target=gate); th.append(t); t.start()
    L, t_pre, t_post = capture(fd, r, FREQ, MAIN_MS, STM, pre, lambda s: h_ok(s, FREQ, MAIN_MS))
    r.rd = orig
    if th: th[0].join(60)
    json.dump({"start_cmd_host": t_pre, "t_cmd_post_write_host": t_post, "stm_log": STM}, open(ANCHOR, 'x'))
    print('gate:', res, gout.getvalue())
    print('H/X:', [l for l in L if l[:2] in ('H,', 'X,', 'E,')][:6], 'nP', sum(l.startswith('P,') for l in L))
    ok = bool(th) and res.get('rc') == 0
    # 3) post ESP idle, hashes
    time.sleep(1.0); idle = False
    try: idle = esp_idle('post')            # ONE attempt only; no retry
    except Exception as e: print('post STAT failed (no retry):', repr(e))
    with open(HASHES, 'x') as f:
        for p in (E8, SRC, STM, ENV, ENV + '.used', ANCHOR, POST, OUT + '/esp_runner_log.jsonl', OUT + '/attempts.json'):
            if os.path.exists(p): f.write('%s  %s\n' % (sha(p), p))
    if not th: die('main H not corrected; gate never started (no ESP command sent)')
    if not ok: die('gate rc=%r' % res.get('rc'))
    if sha(E8) != e8_sha_before: die('E8 control file changed during run')
    if not idle: die('post ESP STAT not verified idle; STOP, owner must check hardware')
    print('batch%d done; run: batch3_driver.py --batch %d classify' % (BATCH, BATCH))

def raw_matches(recs, body):
    """Raw P records whose bytes equal the expected 18-byte body+CRC vector (listed regardless of attribution)."""
    import attempts as at
    from d8_vectors import crc16
    c = crc16(body); vec = body + bytes([c >> 8, c & 0xFF])
    return [{"seq": p["seq"], "t_us": p["t_us"], "len": p["len"], "crc_ok": p["crc_ok"]}
            for p in recs if p.get("kind") == "P" and p["len"] in (18, 20) and at.compare_p_to_vector(p, vec)["bytes_equal"]]

def classify(anchor_path=None, stm=None, runner_log=None):
    anchor_path = anchor_path or ANCHOR; stm = stm or STM; runner_log = runner_log or OUT + '/esp_runner_log.jsonl'
    import attempts as at, batch_gate as g, d8_vectors
    anc = json.load(open(anchor_path)); recs, bad = at.parse_stm_log(stm)
    body = d8_vectors.build(0)[:g.PKT_BODY_BYTES]
    atts = at.attempts_from_runner_log(runner_log)
    res = at.classify_attempts(atts, recs, body, start_cmd_host=anc['start_cmd_host'], clock_rate_tol=CLOCK_TOL)
    res['unparsed_lines'] = len(bad); res['raw_matches'] = raw_matches(recs, body)
    return res

def cmd_classify(a):
    import batch_gate as g
    res = classify()
    txt = g.format_report(res) + '\nclock=%r\nunparsed_lines=%d\nraw_matching_records(n=%d)=%r\n' % (
        res.get('clock'), res['unparsed_lines'], len(res['raw_matches']), res['raw_matches'])
    open(REPORT, 'x').write(txt); print(txt)

if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('cmd', choices=['envelope', 'run', 'classify'])
    ap.add_argument('--batch', type=int, default=3)
    a = ap.parse_args()
    try: configure(a.batch)
    except Stop as e: die(str(e))
    {'envelope': cmd_envelope, 'run': cmd_run, 'classify': cmd_classify}[a.cmd](a)
