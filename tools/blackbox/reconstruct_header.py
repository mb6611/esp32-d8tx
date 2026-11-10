#!/usr/bin/env python3
"""Rebuild the lost start of a Betaflight 4.2 blackbox header (Product .. Field S signed) for a capture whose first
bytes were dropped while the host re-enumerated the FC's USB VCP (see NOTES.md). The field table follows BF 4.2
blackbox.c conditions; options select the condition-dependent fields. The result is marked RECONSTRUCTED.

  reconstruct_header.py RAW OUT.bbl [--no-rssi] [--yaw-d] [--no-amperage]
"""
import argparse, sys
import bbl



def main_table(rssi=True, yaw_d=True, amperage=True):
    m = list(bbl.BF42_MAIN)
    names = [r[0] for r in m]
    if yaw_d and "axisD[2]" not in names:
        i = names.index("axisD[1]") + 1
        m.insert(i, ("axisD[2]",) + tuple(m[i - 1][1:]))
    if not rssi:
        m = [r for r in m if r[0] != "rssi"]
    if not amperage:
        m = [r for r in m if r[0] != "amperageLatest"]
    return m


def header_start(main, slow=bbl.BF42_SLOW, iint=128, pint=4):
    j = lambda col, rows: ",".join(str(r[col]) for r in rows)
    lines = [bbl.LOG_START.decode()[2:], "Data version:2", "I interval:%d" % iint, "P interval:%d" % pint,
             "P ratio:32", "Field I name:" + j(0, main), "Field I signed:" + j(1, main),
             "Field I predictor:" + j(2, main), "Field I encoding:" + j(3, main),
             "Field P predictor:" + j(4, main), "Field P encoding:" + j(5, main),
             "Field S name:" + j(0, slow), "Field S signed:" + j(1, slow)]
    return b"".join(b"H " + ln.encode() + b"\n" for ln in lines)


def rebuild(raw, main):
    k = raw.find(b"\nH Field S predictor")
    if k < 0:
        raise ValueError("capture does not contain 'H Field S predictor'; cannot splice")
    return header_start(main) + b"H Comment:RECONSTRUCTED header start (lost on USB re-enumeration)\n" + raw[k + 1:]


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("raw"); ap.add_argument("out")
    ap.add_argument("--no-rssi", action="store_true"); ap.add_argument("--no-yaw-d", action="store_true")
    ap.add_argument("--no-amperage", action="store_true")
    a = ap.parse_args()
    data = rebuild(open(a.raw, "rb").read(), main_table(not a.no_rssi, not a.no_yaw_d, not a.no_amperage))
    open(a.out, "wb").write(data)
    print("wrote", a.out, len(data))
