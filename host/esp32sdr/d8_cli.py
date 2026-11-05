# SPDX-License-Identifier: GPL-3.0-or-later
"""Decode FrSky D8 packets from a recording: python -m esp32sdr.d8_cli REC.sigmf-data [options].

Reads fs / decimation / bits from the .sigmf-meta next to the data when present."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from . import d8


def main(argv: list[str] | None = None, out=None) -> int:
    out = out or sys.stdout
    ap = argparse.ArgumentParser(prog="esp32sdr.d8_cli", description=__doc__)
    ap.add_argument("data", help="cf32_le I/Q file (.sigmf-data)")
    ap.add_argument("--fs", type=float, help="sample rate (default: from .sigmf-meta)")
    ap.add_argument("--dec", type=int, help="esp32sdr stream decimation (mlse model)")
    ap.add_argument("--bits", type=int, help="esp32sdr sample bits (mlse model)")
    ap.add_argument("--method", choices=["auto", "standard", "mlse"], default="auto")
    ap.add_argument("--cfo-range", type=float, nargs=2, metavar=("LO", "HI"),
                    help="mlse: carrier search range in Hz (default -30000 30000)")
    ap.add_argument("--shift", type=float, help="standard: translate the recording by -SHIFT Hz first")
    ap.add_argument("--dc-notch", type=int, help="standard: moving-mean DC notch length in samples (0 = off)")
    ap.add_argument("--fix1", action="store_true", help="repair a single bit error when exactly one flip fixes the CRC")
    ap.add_argument("--seconds", type=float, help="only the first N seconds")
    ap.add_argument("--all", action="store_true", help="also list bursts whose CRC fails")
    a = ap.parse_args(argv)

    data = Path(a.data)
    meta_path = data.with_suffix(".sigmf-meta")
    g = json.loads(meta_path.read_text())["global"] if meta_path.exists() else {}
    fs = a.fs or g.get("core:sample_rate")
    if not fs:
        ap.error("--fs required (no .sigmf-meta)")
    dec = a.dec or g.get("esp32sdr:decimation")
    bits = a.bits or g.get("esp32sdr:bits")
    iq = np.fromfile(data, dtype="<c8")
    if a.seconds:
        iq = iq[: int(a.seconds * fs)]
    kw = {}
    if a.cfo_range and a.method != "standard":
        kw["cfo_range"] = tuple(a.cfo_range)
    if a.shift is not None:
        kw["shift_hz"] = a.shift
    if a.dc_notch is not None:
        kw["dc_notch"] = a.dc_notch
    res = d8.decode(iq, fs, dec=dec, bits=bits, method=a.method, fix1=a.fix1, **kw)
    n_ok = sum(r.packet.crc_ok for r in res)
    print(f"{len(res)} packets found, {n_ok} CRC ok ({res[0].method if res else a.method})", file=out)
    print(f"{'time_s':>9} {'crc':>4} {'cfo_Hz':>7} {'tx_id':>8} {'b3':>3} {'b4':>3}  ch1..ch8 (raw 12-bit)", file=out)
    for r in res:
        p = r.packet
        if not (p.crc_ok or a.all):
            continue
        crc = ("ok" if r.fixed_bit is None else "ok*") if p.crc_ok else "bad"
        print(f"{r.t:9.4f} {crc:>4} {r.cfo:7.0f} {p.tx_id[0]:3d},{p.tx_id[1]:3d} {p.raw[3]:3d} {p.raw[4]:3d}  "
              + " ".join(f"{v:4d}" for v in p.channels), file=out)
    if any(r.fixed_bit is not None for r in res):
        print("ok* = one bit repaired by --fix1", file=out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
