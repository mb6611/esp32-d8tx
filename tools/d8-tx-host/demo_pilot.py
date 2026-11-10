"""Scripted 'human-looking' stick demo for the Betaflight Configurator Receiver-tab preview.

Starts continuous ESP32 hopping (FOFS -63000, HOP 0) and streams `S` updates at the D8 slot rate
via stick_sender.run(). The sticks follow a sequence of eased manoeuvres (hover, banked turns,
pitch forward/back, yaw pirouette, a fast roll and a flip) with small hand jitter.
ch7 (ARM/AUX3) and all AUX stay at 1000: this cannot arm. Battery must be out.

Usage (repo root): /private/tmp/val-venv/bin/python tools/d8-tx-host/demo_pilot.py [--seconds 60]
"""
import argparse
import math
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stick_sender as ss  # noqa: E402

# (duration s, throttle, roll, pitch, yaw) targets in -1..1 (throttle 0..1)
MANOEUVRES = [
    (2.0, 0.00, 0, 0, 0),        # idle
    (2.0, 0.45, 0, 0, 0),        # spool up / hover
    (2.5, 0.50, 0.35, 0.25, 0.15),   # gentle forward right bank
    (2.5, 0.50, -0.35, 0.25, -0.15),  # forward left bank
    (2.0, 0.48, 0, -0.30, 0),    # pull back
    (3.0, 0.50, 0, 0, 0.8),      # yaw pirouette
    (1.5, 0.55, 0, 0.45, 0),     # punch forward
    (0.6, 0.30, 1.0, 0, 0),      # fast roll right
    (1.5, 0.50, 0, 0, 0),        # level
    (0.6, 0.30, 0, -1.0, 0),     # back flip
    (2.0, 0.50, 0, 0, 0),        # level
    (3.0, 0.52, 0.5, 0.2, 0.4),  # coordinated turn
    (3.0, 0.52, -0.5, 0.2, -0.4),
    (2.0, 0.40, 0, 0, 0),        # settle
    (2.0, 0.00, 0, 0, 0),        # land
]
TAU = 0.18  # s, stick follow time constant (thumbs are not instant)


class Pilot:
    def __init__(self, seed=1):
        self.rng = random.Random(seed)
        self.cur = [0.0, 0.0, 0.0, 0.0]
        self.last = None
        self.total = sum(m[0] for m in MANOEUVRES)

    def target(self, t):
        t %= self.total
        for d, *v in MANOEUVRES:
            if t < d:
                return v
            t -= d
        return MANOEUVRES[-1][1:]

    def read(self, t):
        dt = 0.009 if self.last is None else max(0.0, t - self.last)
        self.last = t
        a = 1 - math.exp(-dt / TAU)
        tgt = self.target(t)
        for i in range(4):
            jitter = 0.0 if i == 0 else 0.015 * math.sin(2 * math.pi * (1.3 + i) * t) + self.rng.gauss(0, 0.006)
            self.cur[i] += a * (tgt[i] - self.cur[i]) + jitter * a
        thr, roll, pitch, yaw = self.cur
        us = lambda x: int(1500 + 500 * max(-1.0, min(1.0, x)))
        return [int(1000 + 1000 * max(0.0, min(1.0, thr))), us(roll), us(pitch), us(yaw), 1000, 1000, 1000, 1000]


def main():
    import serial
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", default="/dev/cu.usbserial-0001")
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--fofs", type=int, default=-63000)
    ap.add_argument("--log", default=None)
    a = ap.parse_args()
    p = serial.Serial(a.port, 921600, timeout=0.2, write_timeout=0)
    p.reset_input_buffer()

    def cmd(c):
        p.write((c + "\n").encode()); time.sleep(0.3)
        r = p.read(400).decode(errors="replace").strip()
        print(c, "->", r.replace("\r\n", " | ")); return r

    if "keyed=0" not in cmd("STAT"):
        sys.exit("ESP32 not idle")
    cmd("FOFS %d" % a.fofs)
    p.write(b"HOP 0 127 300\n")
    try:
        n = ss.run(p, Pilot(), duration=a.seconds, log_path=a.log)
        print("sent", n)
    finally:
        p.write(b"U\n"); time.sleep(0.5)
        print("tail:", p.read(3000).decode(errors="replace").strip().splitlines()[-2:])
        cmd("STAT")


if __name__ == "__main__":
    main()
