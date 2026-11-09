"""Regenerate demod/test/expected.txt from the Python reference (run from repo root with python/.venv/bin/python).
Line: file bits fs found rawhex cfo_hz(index.json expect or 0) py_cfo shift
Verify afterwards with: make -C demod test check"""
import json, pathlib, sys
sys.path.insert(0, "python")
import numpy as np
from d8tx.demod import StandardDecoder
from d8tx.link import unpack4
from d8tx.telemetry import SHIFTS, TXID, load_iq
root = pathlib.Path("protocol/captures")
idx = json.load(open(root / "index.json"))
out = []
for e in idx:
    data = (root / e["file"]).read_bytes()
    if e["bits"] == 4:
        data = unpack4(data)
    iq = load_iq(data, e["n"], 8)
    fs = e["fs"]
    x = iq - iq.mean()
    res = None
    if np.any(x):
        for s in SHIFTS:
            if abs(s) + 40e3 > fs / 2:
                continue
            for r in StandardDecoder(fs, shift_hz=float(s)).decode(x, fix1=False, first_ok=True):
                p = r.packet
                if p.crc_ok and tuple(p.tx_id) == TXID and p.raw[0] == 0x11:
                    res = (p.raw.hex(), r.cfo + s, s)
                    break
            if res:
                break
    ex = e.get("expect")
    if res:
        assert ex and abs(res[1] - ex["cfo_hz"]) < 1.0, (e["file"], res, ex)
        out.append(f'{e["file"]} {e["bits"]} {fs:.0f} 1 {res[0]} {ex["cfo_hz"]:.3f} {res[1]:.3f} {res[2]:.0f}')
    else:
        assert not ex, e["file"]
        out.append(f'{e["file"]} {e["bits"]} {fs:.0f} 0 - 0 0 0')
pathlib.Path("demod/test/expected.txt").write_text("\n".join(out) + "\n")
print("\n".join(out))
