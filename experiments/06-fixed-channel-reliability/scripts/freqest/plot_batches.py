"""Per-packet receiver view (NOT an IQ spectrogram) of CC2500 rxdiag pkt logs: FREQEST vs receiver time.
OFFLINE ONLY: reads saved logs, writes PNGs. Needs matplotlib, e.g.:
  /private/tmp/mplvenv/bin/python experiments/06-fixed-channel-reliability/scripts/freqest/plot_batches.py \
      --batches reliability:3 reliability:6 reliability:9 --out experiments/06-fixed-channel-reliability/figures/plots_reliability
Batch spec DIR:N = results/packet/DIR/batchN_stm.txt (+ batchN_anchor.json, batchN_esp_out/esp_runner_log.jsonl,
or freqest-style files if present). E8 control: --e8 file (default: freqest/control_e8_pre.txt, else packet/control_e8_2421032.txt).
FREQEST raw int8 * 26e6/2^14 Hz = offset the receiver estimated (not a spectrum). Each packet is drawn as a ~6.7 ms bar
at that offset; logs without FREQEST (8-field P, or 'na') are drawn hatched at 0 and marked in the title."""
import sys, os, json, argparse
HERE = os.path.dirname(os.path.abspath(__file__))
PK = os.path.abspath(os.path.join(HERE, '..', '..', 'data'))
sys.path.insert(0, os.path.join(HERE, '..', '..', '..', '..', 'tools', 'd8-tx-host'))
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.collections import PatchCollection
import attempts as at, d8_vectors, batch_gate as g

HZ = 26e6 / 2 ** 14; AIR_S = 0.0067; FOC_KHZ = 135416 / 4 / 1e3   # FOC limit = BW/4 (FOCCFG=0x16: LIMIT=2)
BG, FG = '#10141c', '#d8dde6'; CMAP = 'viridis'; RMIN, RMAX = -100, -20
CAP = "Bars widened for visibility (true length ~6.7 ms). Per-packet receiver view: each bar is one received packet (CC2500 FREQEST at its receive time). Not an IQ spectrogram."

def style():
    plt.rcParams.update({'figure.facecolor': BG, 'axes.facecolor': BG, 'savefig.facecolor': BG, 'text.color': FG,
        'axes.labelcolor': FG, 'xtick.color': FG, 'ytick.color': FG, 'axes.edgecolor': '#566', 'grid.color': '#334',
        'axes.titlecolor': FG, 'legend.facecolor': '#1a2030', 'legend.edgecolor': '#566'})

def load_batch(spec):
    d, n = spec.split(':'); R = os.path.join(PK, d)
    stm = os.path.join(R, 'batch%s_stm.txt' % n)
    if not os.path.exists(stm): stm = os.path.join(R, 'stm_batch%s.txt' % n)
    recs, _ = at.parse_stm_log(stm)
    anc = json.load(open(os.path.join(R, 'batch%s_anchor.json' % n)))
    atts = at.attempts_from_runner_log(os.path.join(R, 'batch%s_esp_out' % n, 'esp_runner_log.jsonl'))
    body = d8_vectors.build(0)[:g.PKT_BODY_BYTES]
    res = at.classify_attempts(atts, recs, body, start_cmd_host=anc['start_cmd_host'], clock_rate_tol=0.003)
    return {'name': 'batch%s (%s)' % (n, d), 'recs': recs, 'res': res, 'atts': atts}

def times(recs):
    h = next((r for r in recs if r['kind'] == 'H'), None)
    if h is None: return recs[0].get('_t0'), recs[0].get('_f')   # H line unparsable by current parser: raw regex fallback
    return h['t0_us'], h['freq_req_khz']

def packets(recs, t0):
    return [dict(x=(r['t_us'] - t0) / 1e6, fe=r['freqest'], rssi=r['rssi'], seq=r['seq'], crc=r['crc_ok'], len=r['len'])
            for r in recs if r['kind'] == 'P']

WMIN = 0.0  # set per figure: min drawn bar width so 6.7 ms bars stay visible on a ~10 s axis (display only)

def bars(ax, pk, cmap, norm):
    """Bars at FREQEST offset (kHz); hatched at 0 when FREQEST is absent."""
    ok = [p for p in pk if p['fe'] is not None]; no = [p for p in pk if p['fe'] is None]
    for grp, hatch in ((ok, None), (no, '////')):
        if not grp: continue
        rc = [Rectangle((p['x'], (p['fe'] * HZ / 1e3 if hatch is None else 0) - 1.2), max(AIR_S, WMIN), 2.4) for p in grp]
        pc = PatchCollection(rc, cmap=cmap, norm=norm, edgecolor=FG if hatch else 'none', linewidth=0.4)
        pc.set_array([p['rssi'] for p in grp]); 
        if hatch: pc.set_hatch(hatch)
        ax.add_collection(pc)
    return len(ok), len(no)

def panel_rx(ax, pk, title, xmax, matched=None, sends=None, unobs=None, cmap=None, norm=None):
    global WMIN; WMIN = 0.006 * (xmax + 0.2)
    n_ok, n_no = bars(ax, pk, cmap, norm)
    # widen visible bars: a 6.7 ms bar is thin on a 11 s axis, so also draw a faint marker dot at bar start
    if matched is not None:
        xs = [p['x'] for p in pk if p['seq'] not in matched]
        ax.plot(xs, [0] * len(xs), '|', color='#888', ms=14, mew=1.2, label='non-matching / CRC-fail noise (grey, y=0 band if no FREQEST)')
    ax.axhline(0, color='#445', lw=0.6)
    for s in (FOC_KHZ, -FOC_KHZ): ax.axhline(s, color='#c96', lw=0.7, ls=':')
    if sends:
        for i, x in enumerate(sends):
            red = i in unobs
            ax.axvline(x, ymin=0, ymax=0.12, color='#ff4040' if red else '#e8e8e8', lw=1.8 if red else 1.0)
    ax.set_xlim(-0.2, xmax); ax.set_ylim(-45, 45); ax.grid(alpha=.3)
    ax.set_ylabel('FREQEST offset (kHz)'); ax.set_title(title + (' | no FREQEST in this log: hatched at 0' if n_ok == 0 else
        (' | %d pkts without FREQEST hatched at 0' % n_no if n_no else '')), fontsize=10)

def panel_rssi(ax, pk, xmax, matched=None, sends=None, unobs=None):
    for sel, c, lab in ((lambda p: matched is None or p['seq'] in matched, '#3ddc97', 'matched ESP' if matched is not None else 'packets'),
                        (lambda p: matched is not None and p['seq'] not in matched, '#888', 'other / noise')):
        pp = [p for p in pk if sel(p)]
        if pp: ax.scatter([p['x'] for p in pp], [p['rssi'] for p in pp], s=22, c=c, label=lab)
    if sends:
        for i, x in enumerate(sends): ax.axvline(x, color='#ff4040' if i in unobs else '#556', lw=.8, ls='--')
    ax.set_xlim(-0.2, xmax); ax.set_ylabel('RSSI (as logged)'); ax.set_xlabel('receiver time since H t0 (s)'); ax.grid(alpha=.3)
    ax.legend(fontsize=7, loc='lower right')

def batch_fig(b, e8, out, cmap, norm):
    t0, f = times(b['recs']); pk = packets(b['recs'], t0); res = b['res']; clk = res['clock']
    T0 = (clk['lo'] + clk['hi']) / 2   # host time of device t0, +/- uncertainty_s/2
    sends = [a['t_send'] - T0 for a in b['atts']]
    unobs = {i for i, e in enumerate(res['per_attempt']) if e['class'] == 'unobserved'}
    matched = set()
    for e in res['per_attempt']:
        if e['primary'] is not None: matched.add(e['primary']); matched.update(e['duplicates'])
    matched |= {p['seq'] for p in pk if p['len'] in (18, 20) and p['crc'] == 1 and p['seq'] not in res['noise']}
    xmax = max([p['x'] for p in pk] + sends) + 0.3
    et0, ef = times(e8['recs']); epk = packets(e8['recs'], et0)
    fig, ax = plt.subplots(3, 1, figsize=(12, 9.5), gridspec_kw={'height_ratios': [3, 1.6, 2.4], 'hspace': 0.35})
    panel_rx(ax[0], pk, 'ESP32 TX %s  tuned %d kHz  (offset 0 = tuned)' % (b['name'], f), xmax, matched, sends, unobs, cmap, norm)
    ax[0].plot([], [], '|', color='#e8e8e8', label='ESP send time (anchor mid; +/-%.0f ms)' % (clk['uncertainty_s'] * 500))
    ax[0].plot([], [], '|', color='#ff4040', label='send with no observed packet (%d)' % len(unobs))
    ax[0].legend(fontsize=7, loc='upper right')
    panel_rssi(ax[1], pk, xmax, matched, sends, unobs); ax[1].set_xlabel('')
    panel_rx(ax[2], epk, 'E8 control (FrSky D8 source) tuned %d kHz' % ef, max(p['x'] for p in epk) + .3, cmap=cmap, norm=norm)
    ax[2].set_xlabel('receiver time since H t0 (s) (E8 capture, own clock)')
    sm = plt.cm.ScalarMappable(norm=norm, cmap=cmap); fig.colorbar(sm, ax=list(ax), label='RSSI (as logged)', pad=0.01, fraction=.025)
    fig.suptitle('FREQEST vs receiver time, %s' % b['name'], fontsize=13)
    fig.text(0.01, 0.005, CAP + ' Send ticks mapped via H-anchor midpoint; unobserved = not attributable.', fontsize=7.5, color='#99a')
    p = os.path.join(out, 'freqest_time_%s.png' % b['name'].split()[0]); fig.savefig(p, dpi=130, bbox_inches='tight'); plt.close(fig)
    esp = [q for q in pk if q['seq'] in matched]
    return p, esp

def pooled(esp, e8pk, out):
    fig, ax = plt.subplots(figsize=(9, 5))
    ev = [p['fe'] * HZ / 1e3 for p in esp if p['fe'] is not None]; e8v = [p['fe'] * HZ / 1e3 for p in e8pk if p['fe'] is not None and p['crc'] == 1]
    bins = [x * HZ / 1e3 - HZ / 2e3 for x in range(-30, 31)]
    if ev or e8v:
        if ev: ax.hist(ev, bins=bins, alpha=.75, color='#fde725', label='matched ESP (n=%d)' % len(ev))
        if e8v: ax.hist(e8v, bins=bins, alpha=.6, color='#35b779', label='E8 (n=%d)' % len(e8v))
        ax.legend()
    else:
        ax.text(.5, .5, 'No FREQEST field in these logs (8-field P records, pre-proto-5).\nNothing to histogram; matched ESP n=%d, E8 n=%d.' % (len(esp), len(e8pk)),
                ha='center', va='center', transform=ax.transAxes, color='#e9b')
    for s in (FOC_KHZ, -FOC_KHZ): ax.axvline(s, color='#ff8c40', ls='--', lw=1.2)
    ax.text(FOC_KHZ, .97, ' ±%.1f kHz FOC limit (BW/4)' % FOC_KHZ, transform=ax.get_xaxis_transform(), color='#ff8c40', fontsize=8, va='top')
    ax.set_xlim(-45, 45); ax.set_xlabel('FREQEST offset (kHz) = int8 * 26e6/2^14 Hz'); ax.set_ylabel('packets'); ax.grid(alpha=.3)
    ax.set_title('Pooled FREQEST: matched ESP packets vs E8 packets')
    fig.text(0.01, 0.005, CAP, fontsize=7.5, color='#99a')
    p = os.path.join(out, 'freqest_pooled_hist.png'); fig.savefig(p, dpi=130, bbox_inches='tight'); plt.close(fig); return p

def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--batches', nargs='+', default=['reliability:3', 'reliability:6', 'reliability:9'])
    ap.add_argument('--out', default=os.path.join(HERE, 'plots_reliability')); ap.add_argument('--e8')
    a = ap.parse_args(); style(); os.makedirs(a.out, exist_ok=True)
    e8p = a.e8 or next(p for p in (os.path.join(PK, 'freqest', 'control_e8_pre.txt'), os.path.join(HERE, '..', '..', '..', '05-first-packet', 'data', 'control_e8_2421032.txt')) if os.path.exists(p))
    recs, _ = at.parse_stm_log(e8p); e8 = {'recs': recs}
    if not any(r['kind'] == 'H' for r in recs):
        import re; raw = open(e8p).read()
        recs[0]['_t0'] = int(re.search(r't0_us=(\d+)', raw).group(1)); recs[0]['_f'] = int(re.search(r'freq_req_khz=(\d+)', raw).group(1))
    import matplotlib.colors as mc
    allr = [r['rssi'] for r in recs if r['kind'] == 'P']
    for sp in a.batches: allr += [r['rssi'] for r in load_batch(sp)['recs'] if r['kind'] == 'P']
    cmap, norm = plt.get_cmap(CMAP), mc.Normalize(min(allr), max(allr))
    allesp = []
    for s in a.batches:
        p, esp = batch_fig(load_batch(s), e8, a.out, cmap, norm); allesp += esp; print(p)
    et0, _ = times(recs); e8pk = [q for q in packets(recs, et0) if q['len'] in (18, 20)]
    print(pooled(allesp, e8pk, a.out), 'E8 log:', e8p)

if __name__ == '__main__':
    main()
