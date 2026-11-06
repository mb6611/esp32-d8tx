import serial,sys,time
s=serial.Serial('/dev/cu.usbserial-0001',921600,timeout=0.1)
s.write(('FOFS %s\n'%sys.argv[1]).encode());time.sleep(0.5);print(s.read(500).decode())
s.write(b'STAT\n');time.sleep(0.5);print(s.read(500).decode())
