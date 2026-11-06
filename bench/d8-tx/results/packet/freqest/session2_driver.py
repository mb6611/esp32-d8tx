"""Session-2 (freqest) bench driver: <=5 batches x <=10 PKT @2412000 kHz, power<=127, 0.5 s spacing,
receive-only rxdiag fw=9709091a bf=948ba63 quiet_us=2000 proto=5 (P records carry freqest).
Reuses reliability/batch3_driver.py (not modified) with all paths redirected to results/packet/freqest/.
Subcommands: e8 [--post] | envelope --batch N | run --batch N | classify --batch N | summary
Requires freqest/approval.json (owner-created, parent-written) with integer approved_at. No retry, no replacement
envelope; post STAT once. Session cap 5 batches / 50 physical PKT counted from freqest/ only."""
import sys, os, json, glob, time, argparse, importlib.util, statistics
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..', '..'))
FE = 'bench/d8-tx/results/packet/freqest/'
_spec = importlib.util.spec_from_file_location('batch3_driver', os.path.join(HERE, '..', 'reliability', 'batch3_driver.py'))
base = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(base)
Stop = base.Stop
MAX_BATCH = 5; MAX_PKT_TOTAL = 50; COUNT = 10; PROTO = 'proto=5'
FW = '9709091a'; BF = '948ba63'
E8_PRE = FE + 'control_e8_pre.txt'; E8_POST = FE + 'control_e8_post.txt'; APPROVAL = FE + 'approval.json'
_orig_h_ok = base.h_ok

def load_approved_at(path=None):
    path = path or APPROVAL
    try: v = json.load(open(path))['approved_at']
    except Exception as e: raise Stop('approval file missing/unreadable %s: %r' % (path, e))
    if not isinstance(v, int) or isinstance(v, bool) or v <= 0: raise Stop('approved_at must be a positive int')
    return v

def h_ok(s, freq, ms):
    return _orig_h_ok(s, freq, ms) and PROTO in s.split('H,', 1)[-1].split(',')

def paths_for(n):
    f = lambda x: FE + x % n
    return {'ENV': f('batch%d_envelope.json'), 'OUT': f('batch%d_esp_out'), 'STM': f('batch%d_stm.txt'),
            'SRC': f('source_off_batch%d_2412000.txt'), 'ANCHOR': f('batch%d_anchor.json'),
            'POST': f('post_batch%d_esp.txt'), 'PRE': f('pre_batch%d_esp.txt'),
            'HASHES': f('batch%d_hashes.txt'), 'REPORT': f('batch%d_report.txt')}

def physical_pkt_total(rel=None):
    rel = rel or FE; tot = 0
    for d in glob.glob(rel + 'batch*_esp_out'):
        try: tot += sum(1 for x in json.load(open(d + '/attempts.json'))['attempts'] if x.get('ok'))
        except Exception: tot += COUNT
    return tot

def prior_gate(n, rel=None):
    rel = rel or FE
    if not isinstance(n, int) or n < 1 or n > MAX_BATCH: raise Stop('batch %r outside 1..%d' % (n, MAX_BATCH))
    if physical_pkt_total(rel) + COUNT > MAX_PKT_TOTAL: raise Stop('would exceed %d total physical PKT' % MAX_PKT_TOTAL)
    if os.path.exists(rel + 'batch%d_envelope.json.used' % n): raise Stop('batch %d already attempted' % n)
    if n == 1: return
    q = n - 1; f = lambda x: rel + x % q
    for x in ('batch%d_envelope.json.used', 'batch%d_stm.txt', 'post_batch%d_esp.txt', 'batch%d_hashes.txt',
              'batch%d_esp_out/attempts.json', 'source_off_batch%d_2412000.txt'):
        if not os.path.exists(f(x)): raise Stop('prior batch %d evidence missing: %s' % (q, f(x)))
    at_ = json.load(open(f('batch%d_esp_out/attempts.json')))['attempts']
    if len(at_) != COUNT or not all(x.get('ok') for x in at_): raise Stop('prior batch %d not 10/10 attempts ok' % q)
    if not any(l.split(' ', 1)[-1].startswith('X,') and l.rstrip().endswith(',done') for l in open(f('batch%d_stm.txt'))):
        raise Stop('prior batch %d STM lacks X done' % q)
    stats = [l for l in open(f('post_batch%d_esp.txt')) if l.startswith('STAT')]
    if not stats or 'keyed=0' not in stats[-1]: raise Stop('prior batch %d post STAT not keyed=0' % q)

def configure(n, approval=None):
    if not isinstance(n, int) or n < 1 or n > MAX_BATCH: raise Stop('batch %r outside 1..%d' % (n, MAX_BATCH))
    ap = load_approved_at(approval)
    p = paths_for(n)
    base.R = FE; base.FW = FW; base.BF = BF; base.APPROVED_AT = ap; base.E8 = E8_PRE
    base.MAX_BATCH = MAX_BATCH; base.MAX_PKT_TOTAL = MAX_PKT_TOTAL
    base.prior_gate = prior_gate; base.h_ok = h_ok; base.physical_pkt_total = physical_pkt_total
    base.paths_for = paths_for
    base.__dict__.update(p); base.BATCH = n; base.GATE_DELAY_S = 0.4
    for k, v in p.items(): globals()[k] = v
    return p

def cmd_e8(a):
    if not os.path.exists(APPROVAL): base.die('missing %s' % APPROVAL)
    try: load_approved_at()
    except Stop as e: base.die(str(e))
    base.FW = FW; base.BF = BF   # identity check must use the session-2 image, not batch3_driver's default
    out = E8_POST if a.post else E8_PRE
    if os.path.exists(out): base.die('%s exists' % out)
    pk, fd = base._open_stm()
    L, _, _ = capture_e8(pk, fd, out)
    print('e8 control', out, 'P', sum(l.startswith('P,') for l in L), [l for l in L if l[:2] in ('H,', 'X,', 'E,')][:4])
    if not any(l.startswith('H,') and h_ok(l, base.E8_FREQ, base.E8_MS) for l in L): base.die('E8 H identity mismatch')
    if not any(l.startswith('X,') and l.rstrip().endswith(',done') for l in L): base.die('E8 lacks X done')

def capture_e8(pk, fd, out):
    return base.capture(fd, pk.r, base.E8_FREQ, base.E8_MS, out)

def _cfg(a):
    try: configure(a.batch)
    except Stop as e: base.die(str(e))

def cmd_envelope(a): _cfg(a); base.cmd_envelope(a)
def cmd_run(a): _cfg(a); base.cmd_run(a)

def cmd_classify(a):
    _cfg(a); base.cmd_classify(a)

# ---------------- summary
def _stats(xs):
    if not xs: return None
    return {'n': len(xs), 'mean': round(statistics.mean(xs), 3), 'min': min(xs), 'max': max(xs),
            'stdev': round(statistics.pstdev(xs), 3)}

def batch_facts(n):
    """classify batch n offline; return counts, matched ESP (freqest, rssi) and per-miss neighbour offsets."""
    configure(n)
    import attempts as at
    res = base.classify()
    recs, _ = at.parse_stm_log(base.STM); bys = {r['seq']: r for r in recs if r.get('kind') == 'P'}
    per = res['per_attempt']; matched = {}
    for e in per:
        if e['class'] != 'unobserved' and e['primary'] in bys: matched[e['i']] = bys[e['primary']]
    misses = []
    for e in per:
        if e['class'] != 'unobserved': continue
        nb = {}
        for d in (-1, 1):
            k = e['i']
            while 0 <= k + d < len(per) and (k + d) not in matched and abs(k + d - e['i']) < len(per): k += d
            j = k + d
            nb['prev' if d < 0 else 'next'] = ({'offset': j - e['i'], 'freqest': matched[j]['freqest'], 'rssi': matched[j]['rssi']}
                                             if j in matched else None)
        misses.append({'i': e['i'], 'neighbours': nb})
    return {'counts': res['counts'], 'attempts': res['attempts'], 'matched': [matched[i] for i in sorted(matched)],
            'misses': misses}

def e8_packets(paths):
    import attempts as at
    out = []
    for p in paths:
        if not os.path.exists(p): continue
        recs, _ = at.parse_stm_log(p)
        out += [r for r in recs if r.get('kind') == 'P' and r.get('whole') and r.get('crc_ok') == 1]
    return out

def summarize(facts, e8):
    pooled = {k: sum(f['counts'][k] for f in facts.values()) for k in ('valid', 'crc_invalid', 'malformed', 'unobserved')}
    m = [p for f in facts.values() for p in f['matched']]
    fe = lambda ps: [p['freqest'] for p in ps if p.get('freqest') is not None]
    return {'per_batch': {n: f['counts'] for n, f in facts.items()}, 'pooled': pooled,
            'attempts': sum(f['attempts'] for f in facts.values()),
            'esp_matched': {'n': len(m), 'freqest': _stats(fe(m)), 'rssi': _stats([p['rssi'] for p in m])},
            'e8': {'n': len(e8), 'freqest': _stats(fe(e8)), 'rssi': _stats([p['rssi'] for p in e8])},
            'misses': {n: f['misses'] for n, f in facts.items() if f['misses']}}

def cmd_summary(a):
    facts = {}
    for n in range(1, MAX_BATCH + 1):
        if os.path.exists(paths_for(n)['ANCHOR']) and os.path.exists(paths_for(n)['STM']): facts[n] = batch_facts(n)
    print(json.dumps(summarize(facts, e8_packets([E8_PRE, E8_POST])), indent=1))

if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('cmd', choices=['e8', 'envelope', 'run', 'classify', 'summary'])
    ap.add_argument('--batch', type=int); ap.add_argument('--post', action='store_true')
    a = ap.parse_args()
    if a.cmd in ('envelope', 'run', 'classify') and a.batch is None: base.die('--batch required')
    {'e8': cmd_e8, 'envelope': cmd_envelope, 'run': cmd_run, 'classify': cmd_classify, 'summary': cmd_summary}[a.cmd](a)
