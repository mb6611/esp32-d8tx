# SPDX-License-Identifier: GPL-3.0-or-later
"""Serve the d8live UI from a recording or a simulated hop-follow tx (no board).

  .venv/bin/python tools/wf_demo.py --sigmf /tmp/d8/centred_m2      # plain mode replay
  .venv/bin/python tools/wf_demo.py --follow                         # simulated 47-channel hopping
  open http://127.0.0.1:8765/#waterfall

Frames are paced at the real stream rate (250 kS/s) and go through the same
decoder + Waterfall.tap path as `esp32sdr d8live`. `--bench S` instead runs S
stream seconds as fast as possible with both views subscribed and prints the
waterfall CPU per stream second.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE.parent / "tests")]

from esp32sdr import d8, d8_live  # noqa: E402
from esp32sdr.waterfall import RowMaker, Waterfall  # noqa: E402

FS = d8_live.FS


def sigmf_frames(base: str, loop: bool, n=2048):
    meta = json.loads(Path(base + ".sigmf-meta").read_text())
    iq = np.fromfile(base + ".sigmf-data", np.complex64)
    fc = meta["captures"][0]["core:frequency"] / 1e6
    def gen():
        idx = 0
        while True:
            for i in range(0, len(iq) - n, n):
                yield SimpleNamespace(index=idx, iq=iq[i:i + n], flags=0, shift=0, gain=40)
                idx += n
            if not loop:
                return
    return fc, gen()


def follow_frames():
    from test_d8follow import SimBoard
    from esp32sdr.d8follow import HopFollower
    from esp32sdr.hopfollow import Commander
    # slot 33 never carries a packet (like 2411.435 MHz on the bench), and hops 2000-2099
    # are lost (a ~0.9 s fade: lock loss and re-acquire)
    dead = {m for m in range(400_000) if m % 47 == 33} | set(range(2000, 2100))
    b = SimBoard(ptx_s=0.42255 / 47, amp=3.0, dead=dead)
    fol = HopFollower(Commander(b), period_s=0.42255 / 47)
    def gen():
        while True:
            f = b.frame()
            f.res = fol.feed(f)
            f.mode = fol.mode
            yield f
    return gen()


def bench(seconds: float, follow: bool, sigmf: str | None):
    from esp32sdr.d8follow import channel_table_khz
    if follow:
        frames = follow_frames()
        slots = [(k * 1e3 + 4e6) / 1e6 for k in channel_table_khz()]
    else:
        _, frames = sigmf_frames(sigmf, True)
        slots = None
    buf = []
    while sum(len(f.iq) for f in buf) < seconds * FS:
        buf.append(next(frames))
    rm = RowMaker(FS, slots_mhz=slots, default_slot=1)
    rm.enabled["base"] = True
    rm.enabled["hop"] = bool(slots)
    t = time.process_time()
    rows = sum(len(rm.feed(f.index, f.iq, f.flags, f.shift)) for f in buf)
    cpu = time.process_time() - t
    wf = Waterfall(FS)
    t = time.perf_counter()
    for f in buf:
        wf.tap(f)
    idle = (time.perf_counter() - t) / len(buf)
    print(f"{'follow' if follow else 'plain'}: {seconds} stream s, {len(buf)} frames, {rows} rows; "
          f"RowMaker CPU {cpu:.3f} s = {100 * cpu / seconds:.2f}% of one core; "
          f"tap() with no subscriber {idle * 1e9:.0f} ns/frame")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sigmf", default="/tmp/d8/centred_m2", help="recording base path (plain mode)")
    ap.add_argument("--follow", action="store_true", help="simulated hopping tx + HopFollower")
    ap.add_argument("--http-port", type=int, default=8765)
    ap.add_argument("--seconds", type=float, default=0, help="stop after N stream seconds (0 = forever)")
    ap.add_argument("--bench", type=float, default=0, metavar="S")
    a = ap.parse_args()
    if a.bench:
        return bench(a.bench, a.follow, a.sigmf)
    web = d8_live.WebServer("127.0.0.1", a.http_port).start()
    if a.follow:
        from esp32sdr.d8follow import channel_table_khz
        run = SimpleNamespace(khz=channel_table_khz(), acq_slot=1)
        frames = follow_frames()
        ld = None
    else:
        fc, frames = sigmf_frames(a.sigmf, True)
        run = SimpleNamespace(center=round(fc, 4))
        ld = d8_live.LiveDecoder(FS)
    wf = Waterfall.for_run(run, FS).attach(web).start()
    print(f"http://127.0.0.1:{web.port}/#waterfall", flush=True)
    t0, n = time.monotonic(), 0
    try:
        for f in frames:
            wf.tap(f)
            res = ld.feed(f.index, f.iq) if ld else f.res
            mode = ld.mode if ld else f.mode
            for r in res:
                web.publish(d8_live.packet_msg(r, mode, 0.0))
            n += len(f.iq)
            ahead = n / FS - (time.monotonic() - t0)
            if ahead > 0:
                time.sleep(ahead)
            if a.seconds and n >= a.seconds * FS:
                break
    except KeyboardInterrupt:
        pass
    finally:
        print(f"waterfall worker CPU {wf.cpu_s:.2f} s over {n / FS:.1f} stream s, dropped {wf.dropped}")
        wf.stop()
        web.stop()


if __name__ == "__main__":
    main()
