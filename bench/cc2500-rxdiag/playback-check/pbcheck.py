#!/usr/bin/env python3
"""ESP32 stage2 playback vs Tinyhawk CC2500 `rxdiag events` (receive-only), one session.

One process owns both ports: the Tinyhawk VCP (raw fd, reader thread, every line stamped with
time.monotonic()) and the ESP32 txeng UART (stage2 dev.Dev). Conditions are interleaved in a
seeded random order; each slot is ONE stage2 `T` command (reps=1, tmo 400 us), so every keyed
burst is a single engine run of 16384 samples @80 MS/s (205 us) between key and unkey; the
firmware reports keyed_us. Slots are >= 0.35 s apart (+ random 0..0.3 s). 2412 MHz only.

Conditions (all use existing txeng commands only):
  pat    F 1 16384 200 256 (complex tone, +1.25 MHz @80 MS/s), T key|clr18  (playback under test)
  zero   F 0 16384 0 0 (all-zero samples),                      T key|clr18  (keyed control)
  unkey  pattern loaded,                                         T no key     (engine only, no RF key)
  tone   pattern loaded,                                         T key        (tone bit 18 left on: CW
                                                                              positive control of keying)
  idle   no command at all (host time slot only)
Output: <out>/rx.txt (raw detector lines with host time), <out>/slots.jsonl, <out>/esp.log, meta.json.
"""
import argparse, glob, json, os, random, select, sys, threading, time

sys.path.insert(0, "/Users/1unoe/Developer/personal/auto-drone/stage2")
from dev import Dev, Hang  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "host"))
import rxdiag_events as rx  # noqa: E402
import guard  # noqa: E402  (keyed-burst envelope: preflight + per-slot hard stop)

F_KEY, F_CLR18 = 4, 8
CTRL = 0x3FFF | 0x8000  # default 16384 samples, 80 MS/s (--count overrides)
# dc: I=200,Q=0 every word -> line at LO; pat156: +156 kHz line (period 512 samples)
FILLS = {"pat": "F 1 16384 200 256", "pat156": "F 1 16384 200 32", "zero": "F 0 16384 0 0", "dc": "F 0 16384 0xc8 0"}
COND = {  # fill, flags (None = no T command)
    "pat": ("pat", F_KEY | F_CLR18),
    "pat156": ("pat156", F_KEY | F_CLR18),
    "zero": ("zero", F_KEY | F_CLR18),
    "dc": ("dc", F_KEY | F_CLR18),
    "unkey": ("pat", 0),
    "tone": ("pat", F_KEY),
    "idle": (None, None),
}


class Reader(threading.Thread):
    def __init__(self, fd, path):
        super().__init__(daemon=True)
        self.fd, self.f, self.stop, self.got_x = fd, open(path, "w"), False, False

    def run(self):
        buf = b""
        while not self.stop:
            r, _, _ = select.select([self.fd], [], [], 0.02)
            if not r:
                continue
            try:
                d = os.read(self.fd, 65536)
            except BlockingIOError:
                continue
            except OSError as e:
                self.f.write(f"# read error {e!r}\n")
                break
            t = time.monotonic()
            buf += d
            *lines, buf = buf.split(b"\n")
            for ln in lines:
                s = ln.decode("latin1").strip()
                self.f.write(f"{t:.6f} {s}\n")
                if s.startswith("X,"):
                    self.got_x = True
            self.f.flush()


def resetup(d, a, meta):
    time.sleep(0.5)
    d.s.reset_input_buffer()
    q = []
    for _ in range(3):
        try:
            q = d.cmd("Q")
        except Hang:
            continue
        if q and q[0].startswith("V,freq"):
            break
    k = d.cmd(f"K {a.km}")
    meta.setdefault("resetup", []).append([q, k])
    if "2412" not in q[0]:
        raise SystemExit("ESP32 not on 2412 after reboot")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--conds", default="pat,zero,unkey,tone")
    ap.add_argument("--n", type=int, default=10, help="slots per condition")
    ap.add_argument("--km", type=int, default=0, help="txeng K mode (0 txcal, 1 xpd_tx_on)")
    ap.add_argument("--pwr", type=int, default=127, help="T pwr (PBUS (5,1) code; 127 or 0 only)")
    ap.add_argument("--gmode", type=int, default=3)
    ap.add_argument("--agc2", type=int, default=251)
    ap.add_argument("--agc1", type=int, default=64)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--count", type=lambda x: int(x, 0), default=guard.COUNT_DEFAULT,
                    help="engine count (N = count+1 samples @80 MS/s); 6143 = 76.8 us")
    ap.add_argument("--tmo", type=int, default=guard.TMO_DEFAULT, help="firmware poll cap per keyed T, us")
    ap.add_argument("--rx-khz", type=int, default=2412000, help="detector centre (TX stays 2412 MHz)")
    ap.add_argument("--rx-bw", type=int, default=812, help="detector bandwidth kHz")
    a = ap.parse_args()
    assert a.pwr in (0, 127) and a.km in (0, 1)
    try:
        worst = guard.preflight(a.count, a.tmo, a.km, a.pwr)
    except guard.Abort as e:
        sys.exit(f"REFUSED: {e}")
    print(f"preflight: worst-case keyed {worst} us (observed overhead {guard.OVERHEAD_WORST_US} + tmo {a.tmo}), "
          f"abort above {guard.ABORT_US} us", file=sys.stderr)
    os.makedirs(a.out, exist_ok=True)
    conds = a.conds.split(",")
    rng = random.Random(a.seed)
    order = [c for c in conds for _ in range(a.n)]
    rng.shuffle(order)

    esplog = open(os.path.join(a.out, "esp.log"), "w")
    d = Dev(log=esplog)
    meta = {"args": vars(a), "order": order, "ready": d.reset(), "abort": None}
    meta["Q"] = d.cmd("Q")
    if "2412" not in meta["Q"][0]:
        sys.exit("ESP32 not on 2412")
    meta["K"] = d.cmd(f"K {a.km}")
    meta["pb51_before"] = d.cmd("B 5 1")

    fd = rx.openp((glob.glob("/dev/cu.usbmodem*") or ["/dev/cu.usbmodem0x80000001"])[0])
    if not rx.cli(fd):
        sys.exit("no CLI prompt")
    rx.rd(fd, 0.3)
    rd = Reader(fd, os.path.join(a.out, "rx.txt"))
    rd.start()
    c = f"rxdiag events {a.rx_khz} 100 {a.rx_bw} {a.agc2} {a.agc1} 1\n"
    meta["rx_cmd"] = c.strip()
    meta["t_rx_cmd"] = time.monotonic()
    os.write(fd, c.encode())
    slots = open(os.path.join(a.out, "slots.jsonl"), "w")
    cur_fill, last = None, time.monotonic()
    try:
        time.sleep(1.5)
        try:  # ESP alive and still on 2412 after the detector started (one unexplained reboot was seen here)
            meta["Q_after_rx_start"] = d.cmd("Q")
        except Hang:
            meta.setdefault("hangs_at", []).append({"slot": -1, "cmd": "Q", "t": time.monotonic()})
            resetup(d, a, meta)
        for i, cond in enumerate(order):
            fill, flags = COND[cond]
            if fill and fill != cur_fill:
                try:
                    d.cmd(FILLS[fill], timeout=20)
                    cur_fill = fill
                except Hang:  # unexpected I,boot (seen once during F): re-setup, then refill
                    meta.setdefault("hangs_at", []).append({"slot": i, "cmd": FILLS[fill], "t": time.monotonic()})
                    resetup(d, a, meta)
                    d.cmd(FILLS[fill], timeout=20)
                    cur_fill = fill
            gap = 0.35 + rng.uniform(0, 0.3)
            while time.monotonic() - last < gap:
                time.sleep(0.005)
            rec = {"i": i, "cond": cond, "fill": fill, "flags": flags}
            t0 = time.monotonic()
            if flags is not None:
                try:
                    e = d.tx(a.count | 0x8000, reps=1, tmo=a.tmo, flags=flags, gmode=a.gmode, pwr=a.pwr if flags & F_KEY else -1)
                    e.pop("snaps", None)
                    rec.update(e)
                except Hang:
                    rec["hang"] = True
                    meta.setdefault("hangs_at", []).append({"slot": i, "cmd": "T", "t": time.monotonic()})
                    if not flags & F_KEY:
                        resetup(d, a, meta)
                        cur_fill = None
            t1 = time.monotonic()
            rec.update(t_send=t0, t_reply=t1)
            last = t0
            slots.write(json.dumps(rec) + "\n")
            slots.flush()
            if flags is not None and flags & F_KEY:
                guard.check_keyed(rec)  # raises Abort: no further keying this session
        time.sleep(1.0)
    except guard.Abort as e:
        meta["abort"] = str(e)
        print(f"ABORT: {e}", file=sys.stderr)
    finally:
        os.write(fd, b"q")
        t = time.monotonic()
        while not rd.got_x and time.monotonic() - t < 4:
            time.sleep(0.05)
        rd.stop = True
        rd.join(1)
        os.close(fd)
        for k, c in (("pb51_after", "B 5 1"), ("Q_after", "Q")):
            try:
                meta[k] = d.cmd(c)
            except Hang:
                meta[k] = "hang"
        meta["got_x"] = rd.got_x
        meta["hangs"] = d.hangs
        d.s.close()
        json.dump(meta, open(os.path.join(a.out, "meta.json"), "w"), indent=1)
    print(json.dumps({k: meta[k] for k in ("Q", "K", "pb51_before", "pb51_after", "got_x", "hangs", "abort")}))


if __name__ == "__main__":
    main()
