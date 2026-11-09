#!/usr/bin/env python3
"""B3.2: ESP BIND <pwr> while the drone runs CLI bind_rx; logs both sides to bind_run.log."""
import sys, time, serial
sys.path.insert(0, "."); import bfcli
pwr = sys.argv[1] if len(sys.argv) > 1 else "30"
log = open("bind_run.log", "a")
def L(*a):
    t = f"{time.strftime('%H:%M:%S')} " + " ".join(str(x) for x in a); print(t); log.write(t + "\n"); log.flush()
esp = serial.Serial("/dev/cu.usbserial-0001", 921600, timeout=0.1); esp.dtr = False; esp.rts = False
time.sleep(0.3); esp.read(65536)
esp.write(b"STAT\n"); time.sleep(0.3); L("esp STAT", esp.read(4096).decode().strip())
esp.write(f"BIND {pwr}\n".encode()); time.sleep(0.3); L("esp BIND", esp.read(4096).decode().strip())
fc = bfcli.open_cli("/dev/cu.usbmodem0x80000001")
t0 = time.time(); L("fc bind_rx ->", bfcli.run(fc, "bind_rx", 1.0).strip())
fcbuf = ""
while time.time() - t0 < 25:
    d = fc.read(4096)
    if d: fcbuf += d.decode(errors="replace"); L("fc:", d.decode(errors="replace").strip())
    e = esp.read(4096)
    if e: L("esp:", e.decode(errors="replace").strip())
    if time.time() - t0 > 4 and int(time.time() - t0) % 4 == 0:
        o = bfcli.run(fc, "get frsky_spi", 0.5).strip(); L("fc get:", o.replace("\n", " | ")); time.sleep(1)
esp.write(b"STOP\n"); time.sleep(0.5); L("esp STOP", esp.read(4096).decode().strip())
L("fc final:", bfcli.run(fc, "get frsky_spi", 1.0).replace("\n", " | "))
