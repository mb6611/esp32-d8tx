import serial,time,sys,threading,re
D='/dev/cu.usbmodem0x80000001';E='/dev/cu.usbserial-0001'
out=sys.argv[1]
def esp(e,cmd,wait=1.0):
    e.write((cmd+'\n').encode());t=time.time();r=''
    while time.time()-t<wait:
        r+=e.read(200).decode(errors='replace')
        if 'OK' in r or 'ERR' in r:break
    return r
e=serial.Serial(E,921600,timeout=0.1);d=serial.Serial(D,921600,timeout=0.1)
log=open(out,'w')
def L(s):log.write(s);log.flush()
L('# '+esp(e,'STAT')+'\n')
for f in (2412000,2404000,2441000,2478000):
  for phase,n in (('baseline',1),('keyed',3)):
    for i in range(n):
        d.reset_input_buffer()
        if phase=='keyed' and i==0: L('ESP: '+esp(e,f'RETUNE {f}')+'\n')
        d.write(f'rxdiag freq {f} 100 102 203 66 1200\n'.encode())
        L(f'## {f} {phase} {i}\n')
        t0=time.time();sent=False;buf=''
        while time.time()-t0<2.0:
            buf+=d.read(500).decode(errors='replace')
            if phase=='keyed' and not sent and time.time()-t0>0.6:
                L('ESP: '+esp(e,'TONE 0 150000 127',0.6)+'\n');sent=True
            if 'X,' in buf and ',done' in buf:break
        L(buf+'\n')
L('ESP: '+esp(e,'RETUNE 2412000')+'\nESP: '+esp(e,'STAT')+'\n')
