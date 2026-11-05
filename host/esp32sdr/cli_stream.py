# SPDX-License-Identifier: GPL-3.0-or-later
"""`stream` subcommand: record an IQS stream to SigMF."""
from __future__ import annotations

from .iqs import IqsError, IqsSession, plan_tune
from .protocol import TransferError
from .samples import RATES
from .sigmf import StreamWriter


def add_arguments(p) -> None:
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--freq", type=int, help="LO frequency, whole MHz (with --fofs)")
    g.add_argument("--center", type=float, metavar="MHZ",
                   help="wanted centre frequency in MHz (e.g. 2421.096); sets FREQ/FOFS "
                        "so it lands at 0 Hz, LO 4 MHz below for --mode 2")
    p.add_argument("--fofs", type=int, default=0, help="PLL offset kHz (-1000..1000), with --freq")
    p.add_argument("--mode", type=int, default=0, choices=(0, 2),
                   help="0: LO at the centre; 2: LO fs/4 below, rotated by j^n on-chip "
                        "(keeps LO leakage out of band)")
    p.add_argument("--dec", type=int, default=512, help="decimation (default 512)")
    p.add_argument("--bits", type=int, default=8, choices=(1, 4, 8, 16),
                   help="bits per I/Q component; 1 = hard-limited sign only (FSK; use --dec 64)")
    p.add_argument("--seconds", type=float, default=10.0)
    p.add_argument("-o", "--output", required=True, metavar="BASE", help="SigMF base path")


def run(dev, args, out) -> int:
    if args.center is not None:
        args.freq, args.fofs = plan_tune(args.center * 1e6, args.mode)
        fc = args.center * 1e6
    else:
        fc = args.freq * 1e6 + args.fofs * 1e3 + (4e6 if args.mode == 2 else 0)
    s = IqsSession(dev, args.dec, args.bits, args.freq, args.fofs, seconds=args.seconds,
                   mode=args.mode)
    try:
        fw = dev.version().get("git", "unknown")
    except Exception:
        fw = "unknown"
    from .cli import _gain
    gain_mode = _gain(dev)[0]
    gains: list[int] = []
    with StreamWriter(args.output, fs=RATES[s.rate_code] // args.dec,
                      fc=fc,
                      bits=args.bits, gain_mode=gain_mode, gain_index=None, fw_version=fw,
                      extra={"decimation": args.dec, "fofs_khz": args.fofs,
                             "lo_mhz": args.freq, "mode": args.mode,
                             "capture": "stream"}) as w:
        prev = 0
        for iq, _f in s.blocks():
            gains.append(_f.gain)
            if s.stats.gap_samples > prev:
                w.mark_loss(s.stats.gap_samples - prev, "sample-index gap")
                prev = s.stats.gap_samples
            w.append(iq)
        if gains:  # gain byte carried in the IQS1 frame headers (docs/iq-stream.md)
            g = w._meta["global"]
            g["esp32sdr:gain_index"] = gains[0]
            g["esp32sdr:gain_index_min"] = min(gains)
            g["esp32sdr:gain_index_max"] = max(gains)
        st = s.stats
        if st.tail_samples:
            w.mark_loss(st.tail_samples, "bad-CRC final frame")
    print(f"samples {st.samples}  frames {st.frames}  bad_crc {st.bad_crc}  "
          f"seq_gaps {st.seq_gaps}", file=out)
    print(f"lost {st.lost_samples:.1f} samples ({st.loss_fraction * 100:.4f}%): "
          f"index gaps {st.gap_samples} + tail {st.tail_samples}; "
          f"firmware reports {st.fw_pairs_lost} pairs / {args.dec}", file=out)
    if st.crosscheck_warning:
        print(f"warning: {st.crosscheck_warning}", file=out)
    return 0


def cmd_stream(args, out) -> int:
    with args.device_factory(args.port) as dev:
        try:
            return run(dev, args, out)
        except IqsError as e:
            raise TransferError(str(e)) from e


def register(sub) -> None:
    p = sub.add_parser("stream", help="record a continuous IQ stream to SigMF (UART IQS)")
    add_arguments(p)
    p.set_defaults(func=cmd_stream)
