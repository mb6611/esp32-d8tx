# Run the hop follower for N s and save every tagged frame (receive only), for per-slot analysis.
# usage: host/.venv/bin/python slotrec.py OUT.npz SECONDS [GAIN]
#   OUT.npz: index (int64), flags, shift (uint8), lens, iq (complex64 concatenated)
import sys, threading, time, numpy as np
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[4] / "host"))
from esp32sdr.device import Device
from esp32sdr.d8follow import FollowRun, report

out, secs = sys.argv[1], float(sys.argv[2])
gain = int(sys.argv[3]) if len(sys.argv) > 3 else 40
frames = []
dev = Device.open("/dev/cu.usbserial-0001")
try:
    run = FollowRun(dev, gain, log=print)
    run.tap = lambda f: frames.append((f.index, f.flags, f.shift, f.iq.astype(np.complex64)))
    th = threading.Thread(target=run.run, daemon=True)
    th.start()
    time.sleep(secs)
    run.stop.set()
    th.join(10)
    report(run, sys.stdout)
finally:
    dev.close()
np.savez(out, index=np.array([f[0] for f in frames], np.int64), flags=np.array([f[1] for f in frames], np.uint8),
         shift=np.array([f[2] for f in frames], np.uint8), lens=np.array([len(f[3]) for f in frames]),
         iq=np.concatenate([f[3] for f in frames]))
print("saved", out, len(frames), "frames")
