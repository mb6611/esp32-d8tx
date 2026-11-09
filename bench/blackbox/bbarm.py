#!/usr/bin/env python3
"""Scripted arm sessions over the ESP32 D8 link, for blackbox capture tests. USB power only, NO battery, props off.

Per session: arm at throttle 1000, then roll, pitch and yaw sweeps (1500 -> 1500+amp -> 1500-amp -> 1500), a small
throttle bump (<= --max-throttle), then disarm. Every stick value sent is logged to a CSV (t, session, segment,
ch1..ch8) so rcCommand in the decoded log can be checked against it.

Runs with the d8tx venv (it imports d8tx.D8Link from python). The d8tx app (web or desktop) must not be connected to the ports.
Enter or Ctrl-C aborts: throttle 1000 + ARM low, then the link stops (Betaflight disarms ~1.25 s after packets stop).

  python/.venv/bin/python bench/blackbox/bbarm.py --dry-run
  python/.venv/bin/python bench/blackbox/bbarm.py --sessions 2 --csv OUT.csv
"""
import argparse, csv, os, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "python"))

T, A, E, R, ARM = 0, 1, 2, 3, 6  # TAER, ch7 = arm
SAFE = [1000, 1500, 1500, 1500, 1000, 1000, 1000, 1000]


def session_timeline(amp, thr_bump, sweep_s):
    """(duration_s, {channel: (start, end)}, arm, label); unspecified channels sit at SAFE."""
    def sweep(ch):
        q = sweep_s / 4
        return [(q, {ch: (1500, 1500 + amp)}, True, "ch%d up" % (ch + 1)),
                (q, {ch: (1500 + amp, 1500 + amp)}, True, "ch%d hold+" % (ch + 1)),
                (q, {ch: (1500 + amp, 1500 - amp)}, True, "ch%d down" % (ch + 1)),
                (q, {ch: (1500 - amp, 1500)}, True, "ch%d back" % (ch + 1))]
    return ([(1.5, {}, True, "arm at zero throttle")]
            + sweep(A) + [(0.5, {}, True, "centre")]
            + sweep(E) + [(0.5, {}, True, "centre")]
            + sweep(R) + [(0.5, {}, True, "centre")]
            + [(1.5, {T: (1000, thr_bump)}, True, "throttle up"),
               (1.5, {T: (thr_bump, 1000)}, True, "throttle down"),
               (1.0, {}, True, "idle armed"),
               (1.5, {}, False, "disarm")])


def lerp(a, b, f):
    return int(round(a + (b - a) * f))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", default="/dev/cu.usbserial-0001")
    ap.add_argument("--sessions", type=int, default=1)
    ap.add_argument("--amp", type=int, default=300, help="stick sweep amplitude, us")
    ap.add_argument("--sweep-s", type=float, default=3.0)
    ap.add_argument("--throttle", type=int, default=1150, help="peak of the throttle bump")
    ap.add_argument("--max-throttle", type=int, default=1200)
    ap.add_argument("--gap-s", type=float, default=4.0, help="disarmed time between sessions")
    ap.add_argument("--lead-s", type=float, default=3.0, help="link up, disarmed, before the first arm")
    ap.add_argument("--fofs", type=int, default=None)
    ap.add_argument("--csv", default=None)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.throttle > a.max_throttle:
        sys.exit("--throttle above --max-throttle")

    segs = [(a.lead_s, {}, False, "link up, disarmed")]
    for s in range(a.sessions):
        segs += [(d, c, arm, "s%d %s" % (s + 1, lbl)) for d, c, arm, lbl in session_timeline(a.amp, a.throttle, a.sweep_s)]
        if s + 1 < a.sessions:
            segs.append((a.gap_s, {}, False, "gap, disarmed"))
    t = 0.0
    for d, c, arm, lbl in segs:
        print("%6.2f-%6.2f s arm=%s %-22s %s" % (t, t + d, "ON " if arm else "off", lbl,
                                                 " ".join("ch%d %d->%d" % (k + 1, *v) for k, v in c.items())))
        t += d
    print("total %.1f s" % t)
    if a.dry_run:
        return

    from d8tx import D8Link
    abort = threading.Event()
    def watch_stdin():  # Enter aborts; EOF (stdin is /dev/null when scripted) does not
        if sys.stdin.readline():
            abort.set()
    threading.Thread(target=watch_stdin, daemon=True).start()
    out = open(a.csv, "w", newline="") if a.csv else None
    w = csv.writer(out) if out else None
    if w:
        w.writerow(["t_unix", "segment", "arm_cmd"] + ["ch%d" % i for i in range(1, 9)])
    link = D8Link(a.port)
    for i in range(10):  # opening the port may reset the ESP32 (RTS/DTR); give it time to boot
        try:
            print(link.info(), flush=True)
            break
        except TimeoutError:
            if i == 9:
                raise
            if i in (2, 6):  # a wedged ESP32 recovers with an EN reset (RTS pulse; DTR low keeps GPIO0 high)
                link._p.dtr = False
                link._p.rts = True
                time.sleep(0.2)
                link._p.rts = False
                time.sleep(1.0)
    link.start(power=127, timeout_ms=300, allow_arm=True, fofs_hz=a.fofs)
    try:
        for d, c, arm, lbl in segs:
            print("%.3f %s" % (time.time(), lbl), flush=True)
            t0 = time.monotonic()
            while (f := (time.monotonic() - t0) / d) < 1.0:
                if abort.is_set():
                    raise KeyboardInterrupt
                ch = list(SAFE)
                for k, (v0, v1) in c.items():
                    ch[k] = lerp(v0, v1, f)
                ch[T] = min(a.max_throttle, ch[T])
                ch[ARM] = 2000 if arm else 1000
                link.set_sticks(ch)
                if w:
                    w.writerow(["%.4f" % time.time(), lbl, int(arm)] + ch)
                time.sleep(0.01)
        st = link.status()
        print("link status:", st, flush=True)
    except KeyboardInterrupt:
        print("ABORT: throttle off, disarm", flush=True)
    finally:
        link.set_sticks(SAFE)
        time.sleep(0.5)
        link.stop()
        link.close()
        if out:
            out.close()
        print("link stopped", flush=True)


if __name__ == "__main__":
    main()
