import sys, time, serial
D='experiments/08-first-flight-cloned-e8/data/ab_test/'
RX='/dev/cu.usbmodem0x80000001'; ESP='/dev/cu.usbserial-0001'
def cmd(s,c,w=0.4):
    s.write((c+'\n').encode()); time.sleep(w); return s.read(2000).decode(errors='replace')
def run(tag, fofs, rxcmd, ms, espcmd=None, send_s=0, sendU=True):
    rx=serial.Serial(RX,115200,timeout=0.001); es=serial.Serial(ESP,921600,timeout=0.01)
    f=open(D+tag+'.txt','x'); g=open(D+tag+'_esp.txt','x')
    if fofs is not None: g.write('FOFS> '+cmd(es,'FOFS %d'%fofs)+'\n')
    g.write('STAT0> '+cmd(es,'STAT')+'\n')
    rx.reset_input_buffer(); es.reset_input_buffer()
    f.write('# cmd=%s\n'%rxcmd); t0=time.time(); rx.write((rxcmd+'\n').encode())
    buf=b''; sent=False; X=False; eb=b''; ts=None; nS=0
    def elog():
        nonlocal eb
        eb+=es.read(4096)
        while b'\n' in eb:
            l,eb=eb.split(b'\n',1); g.write('%.4f %s\n'%(time.time(),l.decode('latin1').rstrip()))
    while time.time()-t0<ms/1000+6 and not X:
        buf+=rx.read(4096); *ls,buf=buf.split(b'\n')
        for l in ls:
            s=l.decode('latin1').rstrip('\r'); f.write('%.4f %s\n'%(time.time(),s))
            if s.startswith('H,') and espcmd and not sent:
                sent=True; ts=time.time(); nxt=ts; g.write('%.4f >%s\n'%(ts,espcmd)); es.write((espcmd+'\n').encode())
            if s.startswith('X,'): X=True
        if sent and send_s:
            now=time.time()
            if now<ts+send_s and now>=nxt:
                es.write(b'S 1000 1500 1500 1500 1000 1000 1000 1000\n'); nS+=1; nxt+=0.008994
                if nxt<now: nxt=now+0.008994
            elif now>=ts+send_s and nS and sendU is not None:
                if sendU: es.write(b'U\n'); g.write('%.4f >U (sent %d S)\n'%(now,nS))
                else: g.write('%.4f stopped sending (sent %d S)\n'%(now,nS))
                sendU=None
        elog()
    if not X: rx.write(b'q')
    t1=time.time()
    while time.time()-t1<1.5: elog(); rx.read(4096)
    g.write('STAT> '+cmd(es,'STAT')+'\n'); g.close(); f.close(); rx.close(); es.close()
    print(tag,'done sent=',sent,'nS',nS,'rate',nS/send_s if send_s else 0)
if __name__=='__main__':
    t=sys.argv[1]
    if t=='src': run('source_off',None,'rxdiag hop 2 55 5000 2403937',5000)
    elif t in('A1','A2','B1','B2'):
        a=t[0]=='A'; run(t,0 if a else -63000,'rxdiag hop 2 55 8000 %d'%(2404000 if a else 2403937),8000,'HOP 556 127')
    elif t=='cont2': run('cont2',-63000,'rxdiag hop 2 55 12000 2403937',12000,'HOP 0 127 300',8,True)
    elif t=='timeout2': run('timeout2',-63000,'rxdiag hop 2 55 6000 2403937',6000,'HOP 0 127 300',2,False)
