# Record ONE D8 channel (no hopping) and count CRC-valid packets. Receive only.
# usage: host/.venv/bin/python onechan.py OUT CHAN_MHZ LO_OFS_KHZ MODE GAIN|hw SECONDS
#   LO_OFS_KHZ moves the stream centre to CHAN+ofs; the decoder shifts the signal back.
# Prints: packets with sync, CRC-ok, CRC-ok %, median CFO; saves OUT.npy (complex64 @ 250 kS/s).
import sys, numpy as np
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[4] / "host"))
from esp32sdr.device import Device
from esp32sdr.iqs import IqsSession, plan_tune
from esp32sdr import d8

out, chan, ofs, mode, gain, secs = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), int(sys.argv[4]), sys.argv[5], float(sys.argv[6])
FS = 250e3
centre = chan * 1e6 + ofs * 1e3
mhz, fofs = plan_tune(centre, mode)
dev = Device.open("/dev/cu.usbserial-0001")
dev.command("GAIN HARDWARE" if gain == "hw" else f"GAIN MANUAL {gain}")
s = IqsSession(dev, 64, 1, mhz, fofs, seconds=secs, mode=mode)
x = np.concatenate([iq for iq, fr in s.blocks()]).astype(np.complex64)
g = dev.command("GAIN?")
dev.command("GAIN HARDWARE")
dev.close()
np.save(out + ".npy", x)
dec = d8.StandardDecoder(FS, shift_hz=-ofs * 1e3)
res = [r for r in dec.decode(x) if r.packet.tx_id is not None]

ok = [r for r in res if r.packet.crc_ok]
cfo = np.median([r.cfo for r in ok]) if ok else float("nan")
print(f"{out}: chan {chan} ofs {ofs:+.0f} kHz mode {mode} gain {gain} ({g.strip()}) LO {mhz} MHz {fofs:+d} kHz: "
      f"sync {len(res)} crc_ok {len(ok)} ({100 * len(ok) / max(len(res), 1):.0f}%) cfo_med {cfo:.0f} Hz "
      f"gap {s.stats.gap_samples}")
