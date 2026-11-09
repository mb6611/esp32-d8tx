"""Scripted short hop: take off ~2 ft, drift ~2 ft forward, land, disarm. OPEN LOOP.

The drone has no altitude sensor and the ESP32 gets no telemetry, so every number here is a
guess you tune by watching. Betaflight flies in Angle mode (AUX1 low): pitch = tilt angle,
centred sticks = level. Throttle values are in microseconds (1000 = off, 2000 = full).

Safety: props on means it really flies. Clear the area. Press Ctrl-C (or Enter) at any moment:
the script immediately sends throttle 1000 + ARM low, then stops the link; Betaflight also
disarms by itself ~1.25 s after packets stop.

The d8tx app (web or desktop) must NOT be connected: this script opens the ESP32 port directly.

Usage (from python):
  .venv/bin/python examples/up_forward_land.py --dry-run          # print the timeline only
  .venv/bin/python examples/up_forward_land.py --hover 1450        # fly
"""
import argparse
import sys
import threading
import time

from d8tx import D8Link

T, A, E, R = 0, 1, 2, 3  # TAER channel indices


def timeline(a):
    """(duration_s, throttle_us, pitch_us, arm) segments; values ramp linearly within a segment."""
    up = a.hover + a.climb
    fwd = 1500 + a.pitch
    return [
        # dur   throttle start->end     pitch start->end   arm
        (3.0, (1000, 1000), (1500, 1500), False, "link up, wait for Betaflight"),
        (1.0, (1000, 1000), (1500, 1500), True, "arm at zero throttle"),
        (0.5, (1000, a.hover - 100), (1500, 1500), True, "spool up"),
        (a.climb_s, (up, up), (1500, 1500), True, "climb (~2 ft)"),
        (0.3, (up, a.hover), (1500, 1500), True, "settle to hover"),
        (a.fwd_s, (a.hover + 20, a.hover + 20), (fwd, fwd), True, "tilt forward (~2 ft)"),
        (0.6, (a.hover, a.hover), (1500 - a.pitch // 2, 1500), True, "brake and level"),
        (a.land_s, (a.hover - 30, a.hover - 150), (1500, 1500), True, "descend"),
        (1.0, (1100, 1000), (1500, 1500), True, "touch down"),
        (0.5, (1000, 1000), (1500, 1500), False, "disarm"),
    ]


def lerp(a, b, f):
    return int(round(a + (b - a) * f))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", default="/dev/cu.usbserial-0001")
    ap.add_argument("--hover", type=int, default=1450, help="throttle that roughly holds altitude (guess, tune it)")
    ap.add_argument("--climb", type=int, default=120, help="throttle above hover while climbing")
    ap.add_argument("--climb-s", type=float, default=0.8)
    ap.add_argument("--pitch", type=int, default=120, help="forward pitch deflection, us (Angle mode: tilt)")
    ap.add_argument("--fwd-s", type=float, default=0.9)
    ap.add_argument("--land-s", type=float, default=2.0)
    ap.add_argument("--max-throttle", type=int, default=1750, help="hard cap")
    ap.add_argument("--fofs", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    segs = timeline(a)
    t = 0.0
    for d, thr, pit, arm, what in segs:
        print(f"{t:5.1f}-{t + d:4.1f} s  thr {thr[0]}->{thr[1]}  pitch {pit[0]}->{pit[1]}  arm={'ON ' if arm else 'off'}  {what}")
        t += d
    if a.dry_run:
        return
    if max(max(s[1]) for s in segs) > a.max_throttle:
        sys.exit("timeline exceeds --max-throttle")

    abort = threading.Event()
    threading.Thread(target=lambda: (sys.stdin.readline(), abort.set()), daemon=True).start()
    link = D8Link(a.port)
    print(link.info())
    link.start(power=127, timeout_ms=300, allow_arm=True, fofs_hz=a.fofs)
    safe = [1000, 1500, 1500, 1500, 1000, 1000, 1000, 1000]
    try:
        for d, thr, pit, arm, what in segs:
            print(what, flush=True)
            t0 = time.monotonic()
            while (f := (time.monotonic() - t0) / d) < 1.0:
                if abort.is_set():
                    raise KeyboardInterrupt
                ch = list(safe)
                ch[T] = min(a.max_throttle, lerp(*thr, f))
                ch[E] = lerp(*pit, f)
                ch[6] = 2000 if arm else 1000
                link.set_sticks(ch)
                time.sleep(0.01)
    except KeyboardInterrupt:
        print("ABORT: throttle off, disarm", flush=True)
    finally:
        link.set_sticks(safe)
        time.sleep(0.3)
        link.stop()
        link.close()
        print("link stopped")


if __name__ == "__main__":
    main()
