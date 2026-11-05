# SPDX-License-Identifier: GPL-3.0-or-later
"""`esp32sdr` command line: info, tune, capture (SigMF) and on-chip spectrum."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

from . import sigmf
from .device import FREQ_MAX_MHZ, FREQ_MIN_MHZ, Device
from .protocol import DeviceError, LinkError, TransferError
from .samples import RATES, decode_cap
from .spec_cmd import DETECTORS, spectrum
from .spectrum import SpecError, psd
from .transport import DEFAULT_PORT

RATE_CODES = {80: 0, 40: 1, 16: 6}  # MS/s -> rate code (LIMITS? on ESP32)
BINS = (256, 512, 1024, 2048)


class CliError(Exception):
    pass


def _open(args) -> Device:
    return args.device_factory(args.port)


def _gain(dev: Device) -> tuple[str, int | None]:
    """`GAIN HARDWARE -1 0 81 0` -> ("HARDWARE", None); manual -> ("MANUAL", idx)."""
    try:
        p = dev.command("GAIN?").split()
    except TransferError:
        return "unknown", None
    if len(p) >= 3 and p[0] == "GAIN":
        idx = int(p[2]) if p[2].lstrip("-").isdigit() and int(p[2]) >= 0 else None
        return p[1], idx
    return "unknown", None


def _fw_version(dev: Device) -> str:
    try:
        v = dev.version()
    except (DeviceError, ValueError):
        return "unknown"
    return f"{v.get('revision', v.get('git', '?'))} ({v.get('profile', '?')}, {v.get('build_date', '?')})"


def cmd_info(args, out) -> int:
    with _open(args) as dev:
        info = dev.info()
        print(f"chip      {info.family} protocol {info.version} mode {info.mode}", file=out)
        print(f"max_n     {info.max_samples}", file=out)
        print(f"firmware  {_fw_version(dev)}", file=out)
        try:
            print(f"transport {dev.command('TRANSPORT?').removeprefix('TRANSPORT ')}", file=out)
        except TransferError:
            pass
        lim = dev.limits()
        rates = lim.get("rates") or []
        print("rates     " + " ".join(f"{r / 1e6:g}" for r in rates) + " MS/s", file=out)
        print("bits      " + " ".join(str(b) for b in lim.get("bits") or []), file=out)
        g = lim.get("gain")
        if g:
            print(f"gain      index {g[0]}..{g[1]} (step {g[2]}), hardware AGC default", file=out)
        print(f"tuning    {FREQ_MIN_MHZ}-{FREQ_MAX_MHZ} MHz (host limit)", file=out)
        print("caps      " + " ".join(dev.caps()), file=out)
    return 0


def cmd_tune(args, out) -> int:
    with _open(args) as dev:
        dev.tune(args.mhz)
    print(f"tuned {args.mhz} MHz", file=out)
    return 0


def _peak_report(f_hz: np.ndarray, p_db: np.ndarray, fc_hz: float, dc_guard_hz: float) -> str:
    mask = np.abs(f_hz - fc_hz) > dc_guard_hz
    i = np.flatnonzero(mask)[np.argmax(p_db[mask])]
    return (f"peak {f_hz[i] / 1e6:.3f} MHz {p_db[i]:.1f} dB, "
            f"median {np.median(p_db):.1f} dB (DC ±{dc_guard_hz / 1e6:g} MHz excluded)")


def cmd_capture(args, out) -> int:
    code = RATE_CODES[args.rate]
    fs = RATES[code]
    with _open(args) as dev:
        dev.tune(args.freq)
        fw = _fw_version(dev)
        gain_mode, gain_index = _gain(dev)
        t0 = time.monotonic()
        raw = dev.cap16(args.n, code, args.bits)
        dt = time.monotonic() - t0
    iq = decode_cap(raw, args.bits)
    data, meta = sigmf.write(
        args.output, iq, fs=fs, fc=args.freq * 1e6, bits=args.bits,
        gain_mode=gain_mode, gain_index=gain_index, fw_version=fw,
        extra={"rate_code": code, "capture": "burst"})
    print(f"captured {iq.size} samples at {fs / 1e6:g} MS/s, {args.freq} MHz, "
          f"{args.bits}-bit, CRC ok, {dt:.2f} s -> {data}", file=out)
    f, p = psd(iq, fs, 1024)
    print(_peak_report(f + args.freq * 1e6, p, args.freq * 1e6, 0.2e6), file=out)
    if args.psd:
        _save(args.psd, f + args.freq * 1e6, p,
              f"capture {args.freq} MHz, {fs / 1e6:g} MS/s, {iq.size} samples (host PSD)")
        print(f"psd -> {args.psd}", file=out)
    return 0


def cmd_spectrum(args, out) -> int:
    code = RATE_CODES[args.rate]
    with _open(args) as dev:
        dev.tune(args.freq)
        run = spectrum(dev, args.bins, code, args.ms, detector=DETECTORS[args.detector])
    f, p = run.sorted_db()
    print(f"spectrum {run.bins} bins at {run.fs / 1e6:g} MS/s, {run.mhz} MHz: "
          f"{len(run.frames)} frames, {run.ffts} FFTs, {args.detector} detector", file=out)
    print(_peak_report(f, p, run.mhz * 1e6, 2 * run.fs / run.bins), file=out)
    if args.output:
        _save(args.output, f, p, f"on-chip SPEC {run.mhz} MHz, {run.fs / 1e6:g} MS/s, "
                                 f"{run.bins} bins, {run.ffts} FFTs ({args.detector})")
        print(f"spectrum -> {args.output}", file=out)
    return 0


def _save(path: str, f_hz: np.ndarray, p_db: np.ndarray, title: str) -> None:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w") as fh:
            fh.write("freq_mhz,power_db\n")
            for a, b in zip(f_hz, p_db):
                fh.write(f"{a / 1e6:.6f},{b:.2f}\n")
        return
    if suffix == ".png":
        try:
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except ImportError as e:
            raise CliError("PNG output needs matplotlib (pip install matplotlib); "
                           "use a .csv path instead") from e
        path.parent.mkdir(parents=True, exist_ok=True)
        fig, ax = plt.subplots(figsize=(9, 4))
        ax.plot(f_hz / 1e6, p_db, lw=0.8)
        ax.set_xlabel("RF frequency (MHz)")
        ax.set_ylabel("power (dB, uncalibrated)")
        ax.set_title(title, fontsize=9)
        ax.grid(alpha=0.3)
        fig.tight_layout()
        fig.savefig(path, dpi=110)
        plt.close(fig)
        return
    raise CliError(f"output must end in .csv or .png, not {path.name!r}")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="esp32sdr", description=__doc__)
    ap.add_argument("--port", default=DEFAULT_PORT, help=f"serial port (default {DEFAULT_PORT})")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("info", help="firmware version, chip, limits, rates, bits")
    s.set_defaults(func=cmd_info)

    s = sub.add_parser("tune", help=f"tune to a whole MHz ({FREQ_MIN_MHZ}-{FREQ_MAX_MHZ})")
    s.add_argument("mhz", type=int)
    s.set_defaults(func=cmd_tune)

    s = sub.add_parser("capture", help="one burst capture written as SigMF")
    s.add_argument("--freq", type=int, required=True, help="centre frequency, whole MHz")
    s.add_argument("--rate", type=int, choices=sorted(RATE_CODES, reverse=True), default=40,
                   help="sample rate in MS/s (default 40)")
    s.add_argument("--bits", type=int, choices=(8, 10), default=8)
    s.add_argument("--n", type=int, default=16380, help="samples, 1..16380 (default 16380)")
    s.add_argument("-o", "--output", required=True, help="SigMF base path")
    s.add_argument("--psd", help="also save the host PSD (.csv or .png)")
    s.set_defaults(func=cmd_capture)

    s = sub.add_parser("spectrum", help="on-chip snapshot spectrum (SPEC)")
    s.add_argument("--freq", type=int, required=True, help="centre frequency, whole MHz")
    s.add_argument("--bins", type=int, choices=BINS, default=1024)
    s.add_argument("--rate", type=int, choices=sorted(RATE_CODES, reverse=True), default=40,
                   help="sample rate in MS/s (default 40)")
    s.add_argument("--ms", type=int, default=500, help="run length in ms (default 500)")
    s.add_argument("--detector", choices=tuple(DETECTORS), default="mean")
    s.add_argument("-o", "--output", help="save the averaged spectrum (.csv or .png)")
    s.set_defaults(func=cmd_spectrum)

    return ap


def main(argv: list[str] | None = None, *, device_factory=None, out=None) -> int:
    out = out or sys.stdout
    args = build_parser().parse_args(argv)
    args.device_factory = device_factory or Device.open
    if getattr(args, "n", 1) is not None and not 1 <= getattr(args, "n", 1) <= 16380:
        print("error: --n must be 1..16380", file=sys.stderr)
        return 2
    try:
        return args.func(args, out)
    except ValueError as e:  # includes out-of-range tuning, refused before sending
        msg = str(e)
    except (DeviceError, LinkError, TransferError, SpecError, CliError, OSError) as e:
        msg = f"{type(e).__name__}: {e}"
    except KeyboardInterrupt:
        msg = "interrupted"
    print(f"error: {msg}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
