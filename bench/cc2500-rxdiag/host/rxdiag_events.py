#!/usr/bin/env python3
"""rxdiag events logger + summary (proto 2). Raw os.open (pyserial wedges the BF VCP on macOS).

  rxdiag_events.py run --seconds 15 --freq-khz 2402000 [--window-ms 100 --bw 812 --agc2 3 --agc1 64 --ant 1] --out f.txt
  rxdiag_events.py info
  rxdiag_events.py summary f.txt [f2.txt ...]

Receive-only: the firmware only listens. A B record is RSSI above the carrier-sense threshold; it is NOT a decoded packet.
"""
import argparse, glob, json, os, select, sys, termios, time, tty


def openp(port):
    fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    tty.setraw(fd)
    a = termios.tcgetattr(fd)
    a[2] |= termios.CLOCAL | termios.CREAD
    termios.tcsetattr(fd, termios.TCSANOW, a)
    return fd


def rd(fd, t):
    out, end = b"", time.time() + t
    while time.time() < end:
        r, _, _ = select.select([fd], [], [], 0.05)
        if r:
            try:
                out += os.read(fd, 65536)
            except BlockingIOError:
                pass
    return out


def cli(fd):
    for _ in range(3):
        os.write(fd, b"#\n")
        if b"#" in rd(fd, 0.8):
            return True
    return False


def cmd_info(a):
    fd = openp(a.port)
    cli(fd)
    for c in ("rxdiag info", "status", "get motor_pwm_protocol"):
        os.write(fd, (c + "\n").encode())
        print(rd(fd, 1.0).decode("latin1"))


def cmd_run(a):
    """Fail-closed: always sends the stop byte on exit, closes the fd, returns nonzero unless an X record arrived."""
    fd = openp(a.port)
    got_x = False
    try:
        if not cli(fd):
            sys.exit("no CLI prompt")
        rd(fd, 0.3)
        c = f"rxdiag events {a.freq_khz} {a.window_ms} {a.bw} {a.agc2} {a.agc1} {a.ant}\n"
        os.write(fd, c.encode())
        t0 = time.time()
        buf = b""
        stopped = False
        with open(a.out, "w") as f:
            f.write(f"# cmd={c.strip()} utc={time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} note={a.note}\n")
            while not got_x:
                r, _, _ = select.select([fd], [], [], 0.05)
                if r:
                    try:
                        d = os.read(fd, 65536)
                    except BlockingIOError:
                        d = b""
                    buf += d
                    *lines, buf = buf.split(b"\n")
                    for ln in lines:
                        f.write(f"{time.time()-t0:.4f} {ln.decode('latin1').strip()}\n")
                        if ln.startswith(b"X,"):
                            got_x = True
                f.flush()
                if not stopped and time.time() - t0 > a.seconds:
                    os.write(fd, b"q")
                    stopped = True
                if stopped and time.time() - t0 > a.seconds + 3:
                    f.write("# no X record\n")
                    break
    except (OSError, KeyboardInterrupt) as e:
        print(f"run aborted: {e!r}", file=sys.stderr)
    finally:
        try:
            os.write(fd, b"q")  # stop command on every path
        except OSError:
            pass
        try:
            os.close(fd)
        except OSError:
            pass
    if not got_x:
        sys.exit("no X record: run did not end cleanly")


def parse(path):
    H, B, C, E, X = None, [], [], [], None
    for ln in open(path):
        if ln.startswith("#"):
            continue
        p = ln.split(" ", 1)
        if len(p) < 2:
            continue
        rec = p[1].strip()
        if rec.startswith("H,"):
            H = dict(kv.split("=", 1) for kv in rec[2:].split(",") if "=" in kv)
        elif rec.startswith("B,"):
            try: B.append([int(x) for x in rec[2:].split(",")])
            except ValueError: pass
            else:
                if len(B[-1]) < 6: B.pop()
        elif rec.startswith("C,"):
            try: C.append([int(x) for x in rec[2:].split(",")])
            except ValueError: pass
            else:
                if len(C[-1]) < 20: C.pop()
        elif rec.startswith("E,"):
            E.append(rec)
        elif rec.startswith("X,"):
            X = rec
    return H, B, C, E, X


def pct(v, q):
    v = sorted(v)
    return v[min(len(v) - 1, int(q * len(v)))] if v else None


def summary(path):
    H, B, C, E, X = parse(path)
    if not C:
        return {"file": path, "error": "no C records", "E": E, "X": X}
    last = C[-1]
    # C: seq,t,span,edges,lost,bseq,bfail,orphan,att,acc,rej,min,max,maxlow,minhigh,nhigh,gapmax,open,marc,flags
    t_span = sum(c[2] for c in C) / 1e6
    seqs = [c[0] for c in C]
    durs = [b[2] for b in B]
    att = sum(c[8] for c in C)
    acc = sum(c[9] for c in C)
    peaks = [b[3] for b in B if b[4] > 0]
    return {
        "file": os.path.basename(path), "freq_khz": H and H.get("freq_req_khz"), "agc2": H and H.get("agcctrl2"),
        "agc1": H and H.get("agcctrl1"), "ant": H and H.get("ant"), "gdo_ok": H and H.get("gdo_ok"),
        "freq_word": H and H.get("freq_word"), "freq_rb": H and H.get("freq_rb"), "fscal1": H and H.get("fscal1"),
        "seconds": round(t_span, 3), "C": len(C), "C_seq_gaps": sum(1 for a, b in zip(seqs, seqs[1:]) if b != a + 1),
        "edges": last[3], "ring_lost": last[4], "bursts": last[5], "B_tx_fail": last[6], "orphan_falls": last[7],
        "B_records": len(B), "bursts_per_s": round(last[5] / t_span, 2) if t_span else None,
        "dur_us_p10_50_90_max": [pct(durs, .1), pct(durs, .5), pct(durs, .9), max(durs) if durs else None],
        "bursts_lt_100us": sum(1 for d in durs if d < 100), "bursts_100_1000us": sum(1 for d in durs if 100 <= d < 1000),
        "bursts_ge_1ms": sum(1 for d in durs if d >= 1000),
        "unsampled_bursts": sum(1 for b in B if b[4] == 0), "peak_p50": pct(peaks, .5),
        "rssi_att": att, "rssi_acc": acc, "rssi_rej_frac": round(1 - acc / att, 4) if att else None,
        "sample_us": round(t_span * 1e6 / att, 1) if att else None, "gapmax_us": max(c[16] for c in C),
        "rssi_max_low": max(c[13] for c in C), "rssi_min_high": min(c[14] for c in C),
        "radio_reentries": sum(1 for c in C if c[19] & 1), "dropped_flag_windows": sum(1 for c in C if c[19] & 4),
        "E": E, "X": X,
    }


def cmd_summary(a):
    for p in a.files:
        print(json.dumps(summary(p)))


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    port = (glob.glob("/dev/cu.usbmodem*") or ["/dev/cu.usbmodem0x80000001"])[0]
    i = sp.add_parser("info"); i.add_argument("--port", default=port)
    r = sp.add_parser("run"); r.add_argument("--port", default=port)
    r.add_argument("--freq-khz", type=int, required=True); r.add_argument("--window-ms", type=int, default=100)
    r.add_argument("--bw", type=int, default=812); r.add_argument("--agc2", type=int, default=3)
    r.add_argument("--agc1", type=int, default=64); r.add_argument("--ant", type=int, default=1)
    r.add_argument("--seconds", type=float, default=10); r.add_argument("--out", required=True)
    r.add_argument("--note", default="")
    s = sp.add_parser("summary"); s.add_argument("files", nargs="+")
    a = ap.parse_args()
    {"info": cmd_info, "run": cmd_run, "summary": cmd_summary}[a.cmd](a)


if __name__ == "__main__":
    main()
