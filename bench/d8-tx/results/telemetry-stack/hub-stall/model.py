"""Offline model of the fc_10min_b hub stall (2026-11-08 12:06-12:16).

Re-implements Betaflight 4.2.11 cc2500_frsky_d.c appendFrSkyHubData (L76-107) and the patched frsky_hub.c
processFrSkyHubTelemetry cycle (L512-618 + patch 0001), drives the real d8tx Tracker with the replies, and
compares the decoded hub ids per reply with the recorded WS log.

Drone state at the start of session 2 (end of nofc_arm, ~11:06:01): an odd (gyro) cycle of 33 bytes was in
progress, bytes 0..19 sent, only 0..9 acked (the last reply's ack never came: the link stopped).
The server restarted, so our tid starts at 0 while the drone expects 27.

usage: python model.py [fc_10min_b.jsonl.gz]
"""
import gzip
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../../d8tx/python"))
from d8tx.telemetry import Tracker  # noqa: E402

U32 = 1 << 32


def cmp_time_us(a, b):  # common/time.h L46: (int32_t)(a - b), timeUs_t is uint32 on F411 (no USE_64BIT_TIME)
    d = (a - b) % U32
    return d - U32 if d >= 1 << 31 else d


def frame(i, v):
    out = [0x5E, i]
    for b in (v & 0xFF, (v >> 8) & 0xFF):
        out += [0x5D, b ^ 0x60] if b in (0x5D, 0x5E) else [b]
    return out


def odd_cycle():  # patched: status, arming flags, gyro (odd cycle), ACC, tail
    return bytes(frame(0x46, 2) + frame(0x47, 0) + frame(0x40, 0) + frame(0x41, -1 & 0xFFFF) + frame(0x42, -1 & 0xFFFF)
                 + frame(0x24, -28 & 0xFFFF) + frame(0x25, -45 & 0xFFFF) + frame(0x26, 1005) + [0x5E])


class Drone:
    def __init__(self, t_last_us, expected, buf, sent, acked):
        self.last = t_last_us
        self.expected, self.sent, self.acked = expected, sent, acked
        self.buf = bytearray(64)
        self.buf[:len(buf)] = buf
        self.generated = len(buf)

    def process(self, now_us):
        if cmp_time_us(now_us, self.last) < 125000:
            return  # the stall: a negative int32 delta looks "too early" until the uint32 difference wraps
        self.last = now_us
        cyc = odd_cycle()[:64]
        self.buf[:len(cyc)] = cyc
        self.generated = len(cyc)

    def reply(self, tid, now_us):
        if tid == self.expected:
            self.acked = self.sent
            self.expected = (tid + 1) & 0x1F
            if not self.generated:
                self.sent = 0
                self.process(now_us)
        else:
            self.sent = self.acked
        out = bytearray()
        for _ in range(10):
            if self.sent == self.generated:
                self.generated = 0
                break
            out.append(self.buf[self.sent])
            self.sent = (self.sent + 1) & 63
        return bytes(out)


def run(gap_s, n=60):
    """gap_s: seconds between the drone's last hub cycle and the first trigger of the new link."""
    t = [0.0]
    trk = Tracker(lambda: t[0])
    trk.reset(enabled=True)
    d = Drone(0, expected=27, buf=odd_cycle(), sent=20, acked=10)
    tid, rows = 0, []
    for k in range(n):
        t[0] = 0.433 * k
        now_us = int((gap_s + t[0]) * 1e6) % U32
        hub = d.reply(tid, now_us)
        before = dict(trk.hub.t_id)
        trk.note_reply({"a1": 0, "a2": 0, "rssi": 85, "hub_count": len(hub), "tid": tid, "hub": hub, "cfo_hz": 0.0})
        rows.append(sorted(i for i, tt in trk.hub.t_id.items() if before.get(i) != tt))
        tid = (tid + 1) & 0x1F  # every trigger answered (catch 1.0 in the first minute)
    return rows


def from_log(path, n=60):
    """Hub ids whose raw value appeared/changed or whose age reset, per reply (replies counter), from the WS log."""
    rows, prev_rep, prev = {}, 0, {}
    with gzip.open(path, "rt") as f:
        for line in f:
            m = json.loads(line)
            r = m.get("radio") or {}
            rep = r.get("replies") or 0
            if rep != prev_rep and rep <= n:
                age = r["hub"]["age_ms"]
                fresh = age is not None and age < 100
                raw = r["hub"]["raw"]
                rows[rep] = (fresh, sorted(k for k in raw if prev.get(k) != raw[k]))
                prev, prev_rep = dict(raw), rep
    return rows


if __name__ == "__main__":
    gap_last = 3643.0  # 11:06:01 (end of nofc_arm) -> 12:06:44 (reply 30), 60.7 min
    stall = run(gap_last)
    ok = run(600.0)
    print("model, gap 60.7 min (in [35.8, 71.6] min):")
    for k, ids in enumerate(stall[:34]):
        print(f"  reply {k + 1:2d}: {' '.join('%02X' % i for i in ids) or '-'}")
    print("replies with hub frames, 60 replies: stall model %d, 10-min gap model %d"
          % (sum(1 for r in stall if r), sum(1 for r in ok if r)))
    assert all(stall[k] == [0x41, 0x42] for k in range(27))
    assert stall[27] == [0x24, 0x25] and stall[28] == [0x26] and not any(stall[29:])
    assert sum(1 for r in ok[29:] if r) > 20
    if len(sys.argv) > 1:
        log = from_log(sys.argv[1])
        print("log (reply: fresh hub frame, new raw ids):")
        for k in sorted(log)[:34]:
            print(f"  reply {k:2d}: {log[k]}")
        assert all(log[k][0] for k in range(1, 30)) and not any(log[k][0] for k in range(30, 61))
        assert log[28][1] == ["0x24", "0x25"] and log[29][1] == ["0x26"]
        print("log matches the model: frames on replies 1-29 (41/42 x27, then 24/25, 26), none from reply 30")
