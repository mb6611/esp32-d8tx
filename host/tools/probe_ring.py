#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Run the RING_PROBE diagnostics (plan U4) against a probe build and log raw replies.

Usage (from host/):
    .venv/bin/python tools/probe_ring.py [--port P] [--freq 2412] [--log FILE] \
        [--check] [CMD ...]

Default commands: RINGPROBE 0, RINGPROBE 1, RINGPROBE 6. Each command's reply
lines are collected until the line stream is quiet for --quiet seconds.
--check additionally runs a CAP16 capture at each rate (CRC checked) and a
short SPEC sweep afterwards, to confirm the normal receive paths still work.
Replies are read in bulk with a fixed serial timeout; see collect().

Probe commands (ESP32 probe build): RINGPROBE r; RINGSPLIT r mode count;
RINGPP r halves margin [stride]; RINGPP8 r halves; RINGREARM r n reps;
DSPPROBE r. Keep interrupt-masked runs under ~250 ms (interrupt WDT).
A bootloader banner ("rst:", "ets ") in a reply is reported as RESET.
"""
from __future__ import annotations

import argparse
import sys
import time
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from esp32sdr.device import Device  # noqa: E402

DEFAULT_CMDS = ["RINGPROBE 0", "RINGPROBE 1", "RINGPROBE 6"]


def collect(dev: Device, cmd: str, quiet: float, total: float) -> list[str]:
    """Send cmd; return reply lines until `quiet` s of silence or `total` s.

    Reads in bulk with a fixed serial timeout: changing the pyserial timeout per
    byte (as SerialTransport.readline does) loses bytes on this CP2102 link."""
    ser = dev.t._ser
    ser.timeout = 0.1
    ser.reset_input_buffer()
    ser.write((cmd + "\n").encode())
    buf = bytearray()
    start = last = time.monotonic()
    while time.monotonic() - start < total and time.monotonic() - last < quiet:
        chunk = ser.read(4096)
        if chunk:
            buf += chunk
            last = time.monotonic()
    return [ln.rstrip("\r") for ln in buf.decode(errors="replace").split("\n") if ln.strip()]


def ask(dev: Device, cmd: str) -> str:
    return "\n".join(collect(dev, cmd, 0.5, 5.0))


def raw_reply(dev: Device, cmd: str, quiet: float = 1.0, total: float = 15.0) -> bytes:
    ser = dev.t._ser
    ser.timeout = 0.1
    ser.reset_input_buffer()
    ser.write((cmd + "\n").encode())
    buf = bytearray()
    start = last = time.monotonic()
    while time.monotonic() - start < total and time.monotonic() - last < quiet:
        chunk = ser.read(65536)
        if chunk:
            buf += chunk
            last = time.monotonic()
    return bytes(buf)


def cap_check(dev: Device, rate: int, n: int = 16380) -> str:
    buf = raw_reply(dev, f"CAP16 {n} {rate}")
    head, _, payload = buf.partition(b"\n")
    f = head.decode(errors="replace").split()
    if len(f) < 3 or f[0] != "DATA":
        return f"FAILED header {head[:60]!r}"
    ok = len(payload) == 2 * int(f[1]) and f"{zlib.crc32(payload):08x}" == f[2].lower()
    return f"{head.decode()} payload={len(payload)} crc={'good' if ok else 'BAD'}"


def spec_check(dev: Device) -> str:
    buf = raw_reply(dev, "SPEC 300 1 1 0 1 1024", quiet=1.5)
    i = buf.find(b"SPECEND")
    if i < 0:
        return "SPEC FAILED (no SPECEND)"
    head = buf[: buf.find(b"\n")].decode(errors="replace")
    return f"{head} | {buf[i:].decode(errors='replace').strip()}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmds", nargs="*", default=DEFAULT_CMDS)
    ap.add_argument("--port", default="/dev/cu.usbserial-0001")
    ap.add_argument("--freq", type=int, default=2412)
    ap.add_argument("--quiet", type=float, default=3.0, help="seconds of silence that ends a reply")
    ap.add_argument("--total", type=float, default=30.0, help="max seconds per command")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--check", action="store_true", help="run CAP16 + SPEC after the commands")
    ap.add_argument("--reset", action="store_true", help="RTS-reset the board before syncing")
    ap.add_argument("--log", type=Path, help="append raw output to this file")
    a = ap.parse_args()

    out: list[str] = []

    def emit(s: str) -> None:
        print(s, flush=True)
        out.append(s)

    dev = Device.open(a.port)
    try:
        if a.reset:
            dev.t.reset()
            time.sleep(3.0)
            dev.sync()
        emit(f"# {time.strftime('%Y-%m-%d %H:%M:%S')} port={a.port}")
        emit(f"> INFO\n{ask(dev, 'INFO')}")
        emit(f"> VERSION?\n{ask(dev, 'VERSION?')}")
        emit(f"> FREQ {a.freq}\n{ask(dev, f'FREQ {a.freq}')}")
        for _ in range(a.repeat):
            for cmd in a.cmds:
                lines = collect(dev, cmd, a.quiet, a.total)
                emit(f"> {cmd}")
                for ln in lines:
                    emit(ln)
                if any(("rst:" in ln or ln.startswith("ets ")) for ln in lines):
                    emit("# RESET detected during command")
                    time.sleep(3.0)
                    dev.sync()
        if a.check:
            for rate in (0, 1, 6):
                emit(f"> CAP16 16380 {rate}\n{cap_check(dev, rate)}")
            emit(f"> SPEC 300 1 1 0 1 1024\n{spec_check(dev)}")
            dev.sync()
            emit(f"> INFO\n{ask(dev, 'INFO')}")
    finally:
        dev.close()
    if a.log:
        with a.log.open("a") as f:
            f.write("\n".join(out) + "\n\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
