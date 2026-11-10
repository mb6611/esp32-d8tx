#!/usr/bin/env python3
"""Parse rxdiag proto-6 hop logs, decode D8 packets, and report hop statistics.

P record (proto 6) = proto-5 fields + chan,slot:
    P,seq,t_us,len,<hex>,rssi,lqi,crc_ok,freqest,chan,slot
(freqest = signed int or 'na'; the older 10-field form without it is accepted.)
The CC2500 strips the CRC: a D8 packet is 18 bytes (0x11 + 17), integrity = hw crc_ok.
Lines may carry a leading host timestamp ("12.345 P,...").  `slot` counts hop
slots from the capture start (monotonic); the expected channel of slot s is
table[s % len(table)].

    python hop_capture.py LOG [--table-start 2 --table-step 55] [--json]
"""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass

_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import d8hop  # noqa: E402

RE_P = re.compile(r"(?:^|\s)P,(\d+),(\d+),(\d+),([0-9A-Fa-f]*),(-?\d+),(\d+),(\d),(?:(-?\d+|na),)?(-?\d+),(-?\d+)\s*$")


def default_table(start: int = 2, step: int = 55) -> list[int]:
    """47-entry table: d8hop.table (U1) if present, else the E8 table from hopfollow."""
    try:
        import d8hop
        return list(d8hop.table(start=start, step=step))
    except ImportError:
        from hopfollow import D8_TABLE
        return list(D8_TABLE)


def rssi_dbm(raw: int) -> float:
    """CC2500 RSSI byte (signed, 0.5 dB steps, offset 72 dB)."""
    if raw >= 128:
        raw -= 256
    return raw / 2.0 - 72.0


@dataclass
class Rec:
    seq: int
    t_us: int
    length: int
    raw: bytes
    rssi: int
    lqi: int
    crc_hw: bool
    chan: int
    slot: int
    freqest: int | None = None
    valid: bool = False      # hardware CRC ok AND full length (18, or 20 with sw CRC)
    counter: int | None = None
    tx_id: tuple | None = None
    sticks: list | None = None  # raw 12-bit


def parse_log(lines) -> list[Rec]:
    out = []
    for line in lines:
        m = RE_P.search(line.rstrip("\r\n"))
        if not m:
            continue
        raw = bytes.fromhex(m[4]) if len(m[4]) % 2 == 0 else b""
        r = Rec(int(m[1]), int(m[2]), int(m[3]), raw, int(m[5]), int(m[6]), m[7] == "1", int(m[9]), int(m[10]),
                None if m[8] in (None, "na") else int(m[8]))
        if r.crc_hw and raw[:1] == bytes([d8hop.LENGTH]) and len(raw) in (18, 20):
            full = raw + bytes([d8hop.crc16(raw) >> 8, d8hop.crc16(raw) & 0xFF]) if len(raw) == 18 else raw
            p = d8hop.parse(full)
            if p and p["crc_ok"]:
                r.valid, r.counter, r.tx_id, r.sticks = True, p["counter"], p["tx_id"], p["channels"]
        out.append(r)
    return out


def analyze(recs: list[Rec], table: list[int] | None = None, total_slots: int | None = None) -> dict:
    """Per-channel CRC-valid rate, loss runs, counter continuity.

    Slots span first..last record slot unless total_slots (slots 0..n-1) is given.
    A slot counts as received when at least one valid record has that slot.
    """
    table = table or default_table()
    n = len(table)
    valid = {}
    for r in recs:
        if r.valid:
            valid.setdefault(r.slot, r)
    if total_slots is not None:
        lo, hi = 0, total_slots - 1
    elif recs:
        lo, hi = min(r.slot for r in recs), max(r.slot for r in recs)
    else:
        lo, hi = 0, -1
    per = {c: [0, 0] for c in table}  # expected, received
    longest = cur = 0
    run_start = best_start = None
    for s in range(lo, hi + 1):
        c = table[s % n]
        per[c][0] += 1
        if s in valid:
            per[c][1] += 1
            cur = 0
        else:
            if cur == 0:
                run_start = s
            cur += 1
            if cur > longest:
                longest, best_start = cur, run_start
    ss = sorted(valid)
    cont = gaps = lost_by_counter = 0
    for a, b in zip(ss, ss[1:]):
        dc = (valid[b].counter - valid[a].counter) & 0xFF
        if dc == (b - a) & 0xFF:
            cont += 1
        else:
            gaps += 1
            lost_by_counter += dc
    wrong_chan = sum(1 for r in valid.values() if r.chan != table[r.slot % n])
    ids = sorted({r.tx_id for r in valid.values()})
    sticks = sorted({tuple(r.sticks) for r in valid.values()})
    nslots = max(0, hi - lo + 1)
    rate = {c: (v[1] / v[0] if v[0] else None) for c, v in per.items()}
    return dict(
        slots=nslots, received=len(valid), rate=len(valid) / nslots if nslots else None,
        records=len(recs), invalid_records=sum(1 for r in recs if not r.valid),
        per_channel={c: dict(expected=v[0], received=v[1], rate=rate[c]) for c, v in per.items()},
        longest_loss_run=longest, longest_loss_start_slot=best_start,
        counter_continuous_pairs=cont, counter_discontinuities=gaps, counter_lost=lost_by_counter,
        chan_mismatch=wrong_chan, tx_ids=[f"{a:02X}{b:02X}" for a, b in ids], distinct_stick_frames=len(sticks),
    )


def channels_comparable(stats: dict, reference_rate: float, tol: float = 0.15) -> int:
    """Channels whose rate is within tol of the reference (e.g. E8 control) rate or better."""
    return sum(1 for v in stats["per_channel"].values() if v["rate"] is not None and v["rate"] >= reference_rate - tol)


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("log")
    ap.add_argument("--table-start", type=int, default=2)
    ap.add_argument("--table-step", type=int, default=55)
    ap.add_argument("--slots", type=int, default=None, help="total slots in the run (default: span of records)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    st = analyze(parse_log(open(a.log)), default_table(a.table_start, a.table_step), a.slots)
    if a.json:
        print(json.dumps(st, indent=1))
    else:
        print(f"slots={st['slots']} valid={st['received']} rate={st['rate']}")
        print(f"longest loss run={st['longest_loss_run']} (slot {st['longest_loss_start_slot']})")
        print(f"counter: continuous={st['counter_continuous_pairs']} discontinuities={st['counter_discontinuities']}")
        print(f"ids={st['tx_ids']} stick frames={st['distinct_stick_frames']} chan mismatches={st['chan_mismatch']}")
        for c, v in st["per_channel"].items():
            print(f"  ch{c:3d} {v['received']:3d}/{v['expected']:3d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
