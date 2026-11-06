#!/usr/bin/env python3
"""100 Hz stick sender: writes `S c1..c8` lines to the ESP32 during `HOP 0`.
Channel order TAER1234. ch7 (ARM/AUX3) is always 1000. Ctrl-C sends `U`.
Inputs: keyboard (default), gamepad (pygame), pattern (scripted square wave)."""
import argparse, csv, sys, time

LO, MID, HI = 1000, 1500, 2000
ARM_CH = 6  # index of ch7
SLOT_S = 0.008994  # D8 hop slot
RATE_HZ = 1.0 / SLOT_S  # ~111.2 Hz: one S per slot, so every packet carries fresh sticks
MAX_HZ = RATE_HZ  # FIFO 128 B holds ~3 S lines (~42 B), so host jitter of one extra line per slot is safe


def clamp(v):
    return max(LO, min(HI, int(round(v))))


def build_line(ch, allow_arm=False):
    ch = [clamp(v) for v in ch]
    if len(ch) != 8:
        raise ValueError("need 8 channels")
    if not allow_arm:  # ARM (ch7) stays low unless the caller explicitly allows it (props-off motor tests)
        ch[ARM_CH] = 1000
    return "S " + " ".join(str(v) for v in ch) + "\n", ch


class PatternInput:
    """Roll (ch2) square wave between 1500-amp and 1500+amp; throttle low."""
    def __init__(self, period_s=2.0, amp=200):
        self.period, self.amp = period_s, amp

    def read(self, t):
        hi = (t % self.period) < self.period / 2
        ch = [LO, MID, MID, MID, MID, MID, LO, MID]
        ch[1] = MID + (self.amp if hi else -self.amp)
        return ch


class KeyboardInput:
    """w/s throttle, a/d roll? Keys: w/s throttle, j/l roll, i/k pitch, q/e yaw, space centre."""
    STEP = 50

    def __init__(self):
        import termios, tty, select
        self._t, self._s = termios, select
        self.fd = sys.stdin.fileno()
        self.old = termios.tcgetattr(self.fd)
        tty.setcbreak(self.fd)
        self.ch = [LO, MID, MID, MID, MID, MID, LO, MID]

    def read(self, t):
        while self._s.select([sys.stdin], [], [], 0)[0]:
            k = sys.stdin.read(1)
            idx = {"w": (0, 1), "s": (0, -1), "l": (1, 1), "j": (1, -1),
                   "i": (2, 1), "k": (2, -1), "e": (3, 1), "q": (3, -1)}.get(k)
            if idx:
                self.ch[idx[0]] = clamp(self.ch[idx[0]] + idx[1] * self.STEP)
            elif k == " ":
                self.ch = [LO, MID, MID, MID, MID, MID, LO, MID]
        return list(self.ch)

    def close(self):
        self._termios_restore()

    def _termios_restore(self):
        self._t.tcsetattr(self.fd, self._t.TCSADRAIN, self.old)


class GamepadInput:
    def __init__(self):
        import pygame
        pygame.init(); pygame.joystick.init()
        self.pg, self.js = pygame, pygame.joystick.Joystick(0)
        self.js.init()

    def read(self, t):
        self.pg.event.pump()
        a = lambda i: self.js.get_axis(i) if i < self.js.get_numaxes() else 0.0
        us = lambda x: MID + 500 * x
        return [LO + 500 * (1 - a(1)), us(a(2)), us(-a(3)), us(a(0)),
                MID, MID, LO, MID]

    def close(self):
        self.pg.quit()


class NullWriter:
    def write(self, b): return len(b)


SPIN_S = 0.001  # sleep until this long before the deadline, then spin


def run(port, source, duration=None, log_path=None, rate=RATE_HZ, clock=time.perf_counter, sleep=time.sleep, spin=None, allow_arm=False):
    """Send at `rate` against absolute deadlines until duration (s) or Ctrl-C; always send U at end.
    One S per deadline max; a late deadline never causes a burst (resync to now after >1 period late).
    Stats (achieved_hz, max_gap_ms, sent, skipped) are left in run.stats."""
    if not 0 < rate <= MAX_HZ:
        raise ValueError(f"rate must be in (0, {MAX_HZ}] Hz")
    if spin is None:
        spin = clock is time.perf_counter
    period = 1.0 / rate
    logf = open(log_path, "w", newline="") if log_path else None
    w = csv.writer(logf) if logf else None
    if w:
        w.writerow(["host_time_s"] + [f"ch{i}" for i in range(1, 9)] + ["send_t_s", "gap_ms"])
    t0 = clock()
    nxt = t0
    sent = skipped = 0
    last = None
    max_gap = 0.0
    try:
        while True:
            # wait for deadline: coarse sleep, then spin
            while True:
                d = nxt - clock()
                if d <= 0:
                    break
                if spin:
                    if d > SPIN_S:
                        sleep(d - SPIN_S)
                else:
                    sleep(d)
            now = clock()
            if duration is not None and now - t0 >= duration:
                break
            if getattr(port, "out_waiting", 0) > 64:  # don't block on a backed-up serial buffer
                skipped += 1
            else:
                line, ch = build_line(source.read(now - t0), allow_arm)
                port.write(line.encode())
                gap = 0.0 if last is None else (now - last) * 1000
                max_gap = max(max_gap, gap)
                last = now
                if w:
                    w.writerow([f"{time.time():.4f}"] + ch + [f"{now - t0:.6f}", f"{gap:.3f}"])
                sent += 1
            nxt += period
            if clock() - nxt > period:
                nxt = clock()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            port.write(b"U\n")
        except Exception:
            pass
        if logf:
            logf.close()
        if hasattr(source, "close"):
            source.close()
    el = (last - t0) if last is not None else 0
    hz = (sent - 1) / el if sent > 1 and el > 0 else 0.0
    run.stats = {"sent": sent, "skipped": skipped, "achieved_hz": hz, "max_gap_ms": max_gap}
    return sent


run.stats = {}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port")
    ap.add_argument("--selftest", action="store_true", help="no port: 2 s null-writer pacing test")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--input", choices=["keyboard", "gamepad", "pattern"], default="keyboard")
    ap.add_argument("--hz", type=float, default=RATE_HZ, help="send rate, default and max = D8 slot rate (~111.2 Hz)")
    ap.add_argument("--duration", type=float)
    ap.add_argument("--log")
    ap.add_argument("--period", type=float, default=2.0)
    ap.add_argument("--amp", type=int, default=200)
    a = ap.parse_args()
    if a.selftest:
        n = run(NullWriter(), PatternInput(), duration=2.0)
        st = run.stats
        print(f"selftest sent {n} achieved {st['achieved_hz']:.2f} Hz max gap {st['max_gap_ms']:.2f} ms")
        return 0 if st["achieved_hz"] >= 110 else 1
    if not a.port:
        ap.error("--port required")
    import serial
    src = {"keyboard": KeyboardInput, "gamepad": GamepadInput,
           "pattern": lambda: PatternInput(a.period, a.amp)}[a.input]()
    with serial.Serial(a.port, a.baud, timeout=0, write_timeout=0) as p:
        n = run(p, src, a.duration, a.log, rate=a.hz)
    st = run.stats
    print(f"sent {n} lines, achieved {st['achieved_hz']:.2f} Hz, max gap {st['max_gap_ms']:.2f} ms, skipped {st['skipped']}")


if __name__ == "__main__":
    sys.exit(main())
