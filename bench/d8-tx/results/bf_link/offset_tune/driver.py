import sys, time, serial, threading
D='bench/d8-tx/results/bf_link/offset_tune/'
RX='/dev/cu.usbmodem0x80000001'; ESP='/dev/cu.usbserial-0001'
def esp_cmd(s,c,w=0.5):
    s.write((c+'\n').encode()); time.sleep(w); return s.read(2000).decode(errors='replace')
def run(tag, rxcmd, ms, slots=None, log=None):
    rx=serial.Serial(RX,115200,timeout=0.05); es=serial.Serial(ESP,921600,timeout=0.1)
    rx.reset_input_buffer(); es.reset_input_buffer()
    f=open(D+tag+'.txt','x'); g=open(D+tag+'_esp.txt','x')
    f.write('# cmd=%s\n'%rxcmd); t0=time.time(); rx.write((rxcmd+'\n').encode())
    buf=b''; sent=False; X=False; eb=b''
    while time.time()-t0<ms/1000+6 and not X:
        buf+=rx.read(4096); *ls,buf=buf.split(b'\n')
        for l in ls:
            s=l.decode('latin1').rstrip('\r'); f.write('%.4f %s\n'%(time.time(),s))
            if s.startswith('H,') and slots and not sent:
                sent=True; g.write('%.4f >HOP %d 127\n'%(time.time(),slots)); es.write(('HOP %d 127\n'%slots).encode())
            if s.startswith('X,'): X=True
        eb+=es.read(4096)
        while b'\n' in eb:
            l,eb=eb.split(b'\n',1); g.write('%.4f %s\n'%(time.time(),l.decode('latin1').rstrip()))
    if not X: rx.write(b'q')
    time.sleep(0.5); eb+=es.read(4096); g.write('%.4f %s\n'%(time.time(),eb.decode('latin1')))
    g.write('STAT> '+esp_cmd(es,'STAT')+'\n'); g.close(); f.close(); rx.close(); es.close()
    print(tag,'done sent=',sent)
if __name__=='__main__':
    t=sys.argv[1]
    if t=='src': run('source_off','rxdiag hop 2 55 5000 2403937',5000)
    else: run(t,'rxdiag hop 2 55 %d 2403937'%int(sys.argv[3]),int(sys.argv[3]),int(sys.argv[2]))
