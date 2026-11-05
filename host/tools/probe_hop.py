#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Host side of the HOP_PROBE fast-retune probe (docs/devkitv1/fast-hop.md).

Library + CLI. Needs a build with -DHOP_PROBE=ON. Usage (from host/):
    .venv/bin/python tools/probe_hop.py timing      # HOPT per-phase timing
    .venv/bin/python tools/probe_hop.py settle      # mid-burst retune, settle curves
    .venv/bin/python tools/probe_hop.py sweep       # 47 D8 channels, fast vs full tune
Replies are read in bulk with a fixed timeout (see probe_ring.collect).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import zlib
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from esp32sdr.device import Device  # noqa: E402
from esp32sdr.samples import decode_cap  # noqa: E402
from probe_ring import collect, raw_reply  # noqa: E402

D8_N = [0, 57, 112, 167, 222, 21, 76, 131, 186, 241, 40, 95, 150, 205, 4, 59, 114, 169, 224, 23,
        78, 133, 188, 243, 42, 97, 152, 207, 6, 61, 116, 171, 226, 25, 80, 135, 190, 245, 44, 99,
        154, 209, 8, 63, 118, 173, 228]
D8_KHZ = [round(2404000 + n * 299.93) for n in D8_N]
RATE_HZ = {0: 80e6, 1: 40e6, 6: 16e6}


def ask(dev: Device, cmd: str, quiet=0.3, total=10.0) -> str:
    return "\n".join(collect(dev, cmd, quiet, total))


def hopcap(dev: Device, khz: int, mode: int, rate: int, n: int, at_us: int, fmt: int = 20):
    """Returns (t0_us, t1_us, stale, complex samples)."""
    buf = raw_reply(dev, f"HOPCAP {khz} {mode} {rate} {n} {at_us} {fmt}", quiet=0.25, total=10)
    l1, _, rest = buf.partition(b"\n")
    l2, _, payload = rest.partition(b"\n")
    h = l1.decode(errors="replace").split()
    d = l2.decode(errors="replace").split()
    if not h or h[0] != "HOPCAP" or not d or d[0] != "DATA":
        raise RuntimeError(f"bad reply {buf[:120]!r}")
    kv = dict(x.split("=") for x in h[1:])
    bits = 8 if fmt == 16 else 10
    nbytes = 2 * n if bits == 8 else (n * 20 + 7) // 8
    payload = payload[:nbytes]
    if len(payload) != nbytes or f"{zlib.crc32(payload):08x}" != d[2].lower():
        raise RuntimeError("payload/crc")
    return int(kv["t0"]) / 100, int(kv["t1"]) / 100, int(kv["stale"]), decode_cap(payload, bits)


def metrics(x: np.ndarray, full_scale: float) -> dict:
    p = np.mean(np.abs(x) ** 2)
    dc = np.mean(x)
    clip = np.mean((np.abs(x.real) >= full_scale - 1) | (np.abs(x.imag) >= full_scale - 1))
    return {"dc_i": float(dc.real), "dc_q": float(dc.imag),
            "dc_db": float(10 * np.log10(np.abs(dc) ** 2 / p + 1e-12)),
            "rms": float(np.sqrt(p)), "clip": float(clip)}


def open_dev(port: str) -> Device:
    dev = Device.open(port)
    dev.sync()
    return dev


def quiet_stats(x: np.ndarray, win: int = 256, frac: float = 0.25) -> dict:
    """DC and noise over the quietest `frac` of windows (robust to bursty ambient)."""
    w = x[: len(x) // win * win].reshape(-1, win)
    p = np.mean(np.abs(w - w.mean(axis=1, keepdims=True)) ** 2, axis=1)
    k = max(1, int(len(p) * frac))
    idx = np.argsort(p)[:k]
    dc = w[idx].mean()
    return {"dc": complex(dc), "dc_abs": float(abs(dc)), "noise_rms": float(np.sqrt(p[idx].mean())),
            "clip": float(np.mean((np.abs(x.real) >= 511) | (np.abs(x.imag) >= 511)))}


RULERS_KHZ = (2400000, 2440000, 2480000)  # 40 MHz crystal harmonics, seen on this board


def ruler_snr(caps: list[np.ndarray], lo_khz: int, fs: float = 40e6, nfft: int = 16380):
    """Median PSD; for each crystal-harmonic line within 0.45*fs (not at DC), return
    (offset_khz, measured_peak_offset_khz, peak_over_local_median_db)."""
    ps = []
    win = np.hanning(nfft)
    for x in caps:
        x = x[:nfft] - x[:nfft].mean()
        if len(x) < nfft:
            x = np.pad(x, (0, nfft - len(x)))
        ps.append(np.abs(np.fft.fftshift(np.fft.fft(x * win))) ** 2)
    p = 10 * np.log10(np.median(ps, axis=0) + 1e-9)
    fr = (np.arange(nfft) - nfft // 2) * fs / nfft / 1e3
    out = []
    for h in RULERS_KHZ:
        off = h - lo_khz
        if 50 < abs(off) < 0.45 * fs / 1e3:
            i = int(np.argmin(np.abs(fr - off)))
            seg = p[i - 4:i + 5]
            j = i - 4 + int(np.argmax(seg))
            local = np.median(np.r_[p[i - 200:i - 20], p[i + 20:i + 200]])
            out.append((off, float(fr[j]), float(p[j] - local)))
    return out


def collect_sweep(dev: Device, ref_khz: int, chans: list[int], caps: int, mode: int, out: str,
                  gain: str = "GAIN MANUAL 50", n: int = 16380, rate: int = 1,
                  bandwidth: str = "LPF AUTO"):
    """For each channel: fast retune (no recalibration, calibrated once at ref_khz) then caps
    captures; then a full recalibrated tune and caps captures. Saves npz.
    Rate 0 with "BANDWIDTH 67" puts a crystal-harmonic ruler in view for every D8 channel."""
    ask(dev, gain)
    ask(dev, bandwidth)
    fs = RATE_HZ[rate]
    data = {}
    for k, khz in enumerate(chans):
        ask(dev, f"HOPFULL {ref_khz}")  # back to the single reference calibration
        # Prior channel state as in real hopping: retune from the previous channel.
        if k:
            hopcap(dev, chans[k - 1], mode, rate, 256, 0)
        fast = []
        for j in range(caps):
            t0, t1, st, x = hopcap(dev, khz if j == 0 else 0, mode, rate, n, 0)
            fast.append(x)
        ask(dev, f"HOPFULL {khz}")
        full = [hopcap(dev, 0, 0, rate, n, 0)[3] for _ in range(caps)]
        data[f"fast_{khz}"] = np.array(fast)
        data[f"full_{khz}"] = np.array(full)
        qf = [quiet_stats(x) for x in fast]
        qr = [quiet_stats(x) for x in full]
        rf, rr = ruler_snr(fast, khz, fs), ruler_snr(full, khz, fs)
        print(f"{khz} fast |dc|={np.median([q['dc_abs'] for q in qf]):6.1f} noise="
              f"{np.median([q['noise_rms'] for q in qf]):6.1f} clip={np.mean([q['clip'] for q in qf]):.4f} "
              f"ruler={[(round(a), round(b, 1), round(c, 1)) for a, b, c in rf]} | full |dc|="
              f"{np.median([q['dc_abs'] for q in qr]):6.1f} noise={np.median([q['noise_rms'] for q in qr]):6.1f} "
              f"clip={np.mean([q['clip'] for q in qr]):.4f} ruler={[(round(b, 1), round(c, 1)) for a, b, c in rr]}",
              flush=True)
    ask(dev, "LPF AUTO")
    np.savez_compressed(out, ref=ref_khz, rate=rate, mode=mode, **data)


def collect_settle(dev: Device, a_khz: int, b_khz: int, reps: int, mode: int, out: str,
                   at_us: int = 100, gain: str = "GAIN MANUAL 50", ref_khz: int = 2440000,
                   rate: int = 1):
    """Mid-burst retunes a->b and b->a (reps each) at at_us into a 16380-sample capture
    (rate code 1: 40 MS/s, 410 us; 6: 16 MS/s, 1024 us).
    Saves the captures and the retune start/end times (us from capture start)."""
    ask(dev, gain)
    ask(dev, f"HOPFULL {ref_khz}")
    caps, times, dirs = [], [], []
    hopcap(dev, a_khz, mode, 1, 256, 0)
    for r in range(2 * reps):
        dst = b_khz if r % 2 == 0 else a_khz
        t0, t1, st, x = hopcap(dev, dst, mode, rate, 16380, at_us)
        caps.append(x)
        times.append((t0, t1))
        dirs.append(r % 2)
    np.savez_compressed(out, caps=np.array(caps), times=np.array(times), dirs=np.array(dirs),
                        a=a_khz, b=b_khz, mode=mode, fs=RATE_HZ[rate])


def settle_profile(x: np.ndarray, line_khz: float, fs: float = 40e6, win: int = 256, step: int = 64):
    """Line power (dB) at line_khz vs time, using a short sliding DFT; and per-window DC."""
    t = np.arange(len(x))
    ph = np.exp(-2j * np.pi * line_khz * 1e3 * t / fs)
    y = x * ph
    k = np.hanning(win)
    starts = np.arange(0, len(x) - win, step)
    line = np.array([abs(np.sum(y[s:s + win] * k)) ** 2 for s in starts])
    dc = np.array([np.mean(x[s:s + win]) for s in starts])
    pw = np.array([np.mean(abs(x[s:s + win]) ** 2) for s in starts])
    centre_us = (starts + win / 2) / fs * 1e6
    return centre_us, line, dc, pw


def ruler_for(khz: int) -> int:
    """Offset (kHz) of the crystal-harmonic line nearest to the LO, below or above 2440."""
    return (2400000 - khz) if khz < 2440000 else (2480000 - khz)


def settle_summary(fn: str, win: int = 128, step: int = 16) -> list[str]:
    """Per direction: when the source line drops 10 dB and when the destination line is
    (and stays) within 3 dB of its final level, vs the retune start/end (t0/t1)."""
    d = np.load(fn)
    caps, tm, dirs, fs = d["caps"], d["times"], d["dirs"], float(d["fs"])
    a, b = int(d["a"]), int(d["b"])
    lines = []
    for dr in (0, 1):
        src, dst = (a, b) if dr == 0 else (b, a)
        l1, l2 = [], []
        for x in caps[dirs == dr]:
            c, p1, _, _ = settle_profile(x, ruler_for(src), fs, win, step)
            l2.append(settle_profile(x, ruler_for(dst), fs, win, step)[1])
            l1.append(p1)
        l1 = 10 * np.log10(np.median(l1, 0))
        l2 = 10 * np.log10(np.median(l2, 0))
        t0, t1 = np.median(tm[dirs == dr, 0]), np.median(tm[dirs == dr, 1])
        fin, ini = np.median(l2[c > c[-1] - 150]), np.median(l1[c < t0 - 10])
        bad = np.where(np.abs(l2 - fin) > 3)[0]
        arrive = c[bad[-1] + 1] if len(bad) else c[0]
        gone = c[np.argmax((c > t0) & (l1 < ini - 10))]
        lines.append(f"{src}->{dst} mode={int(d['mode'])} t0={t0:.1f} t1={t1:.1f} src_gone={gone:.0f} "
                     f"dst_within_3dB={arrive:.0f} ({arrive - t1:+.0f} vs t1) us")
    return lines


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", choices=["timing", "settle", "sweep"])
    ap.add_argument("--port", default="/dev/cu.usbserial-0001")
    ap.add_argument("--out", default="/tmp/hop")
    a = ap.parse_args()
    dev = Device.open(a.port)
    if a.what == "timing":
        print(ask(dev, "HOPFULL 2440000"))
        for cmd in ["HOPT 2404000 2477000 200 0", "HOPT 2404000 2477000 200 1", "HOPT 2404000 2477000 200 2",
                    "HOPT 2404000 2404300 200 1", "HOPT 2440000 2440300 200 1"]:
            print(cmd, "->", ask(dev, cmd))
    elif a.what == "settle":
        for m in (0, 1, 2):
            fn = f"{a.out}_settle_big_m{m}.npz"
            collect_settle(dev, 2404000, 2477000, 20, m, fn, rate=6)
            print("\n".join(settle_summary(fn)))
        fn = f"{a.out}_settle_small_m1.npz"
        collect_settle(dev, 2404000, 2410000, 20, 1, fn, rate=6)
        print("\n".join(settle_summary(fn)))
    else:
        collect_sweep(dev, 2404000, D8_KHZ, 4, 1, f"{a.out}_sweep.npz", rate=0, bandwidth="BANDWIDTH 67")
    ask(dev, "GAIN HARDWARE")


if __name__ == "__main__":
    main()
