"""U3 batch1 driver: STM capture (pk.stm_run) + bounded batch_gate.main triggered from first verified H."""
import sys, os, time, io, threading, json, re
sys.path.insert(0,'experiments/05-first-packet/scripts'); sys.path.insert(0, 'tools/d8-tx-host')
import pk, serial, batch_gate as g
R = 'experiments/06-fixed-channel-reliability/data/reliability/'
ENV = R + 'batch1b_envelope.json'; OUT = R + 'batch1b_esp_out'; STM = R + 'batch1b_stm.txt'
assert not os.path.exists(STM) and not os.path.exists(OUT) and not os.path.exists(ENV + '.used')
# ESP preflight
s = serial.Serial('/dev/cu.usbserial-0001', 921600, timeout=0.3); s.reset_input_buffer()
def ask(c):
    s.write((c + '\n').encode()); time.sleep(0.4); return s.read(400).decode(errors='replace')
a = ask('PING'); b = ask('STAT'); print('ESP', repr(a), repr(b))
assert 'd8tone' in a and 'keyed=0' in b, 'ESP not idle'
s.close()
fd = pk.stm_open()
buf = bytearray(); orig = pk.r.rd
def rd(*a, **k):
    d = orig(*a, **k); buf.extend(d); return d
pk.r.rd = rd
res = {}; gout = io.StringIO()
def gate():
    try:
        time.sleep(0.4)
        res['rc'] = g.main(['run', '--execute', '--approved-envelope', ENV, '--esp-port', '/dev/cu.usbserial-0001',
            '--source-off-log', R + 'source_off_batch1_2412000.txt', '--e8-log', R + 'control_e8_2421032.txt',
            '--out-dir', OUT, '--count', '10', '--power', '127', '--freq-khz', '2412000'], out=gout)
    except BaseException as e:
        res['exc'] = repr(e)
th = None
def pre():
    global th
    txt = bytes(buf).decode('latin1')
    m = re.search(r'^H,.*$', txt, re.M)
    ok = m and 'fw=c5cc593b' in m.group(0) and 'bf=948ba63' in m.group(0) and 'quiet_us=2000' in m.group(0) \
        and 'freq_req_khz=2412000' in m.group(0)
    print('H verified:', bool(ok), m.group(0)[:200] if m else None, flush=True)
    if not ok: return
    th = threading.Thread(target=gate); th.start()
L = pk.stm_run(fd, 2412000, 11000, STM, pre)
if th: th.join(60)
print('gate:', res, gout.getvalue())
print('H/X:', [l for l in L if l[:2] in ('H,', 'X,', 'E,')][:6], 'nP', sum(l.startswith('P,') for l in L))
