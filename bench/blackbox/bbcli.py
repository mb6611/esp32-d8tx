#!/usr/bin/env python3
"""Betaflight CLI helper (pyserial): enter CLI, run commands, capture output, leave with 'exit' or 'save'.

  bbcli.py diff OUT.txt [--port P]                 # 'diff all' -> OUT.txt, then 'exit'
  bbcli.py apply CONFIG.txt [--save] [--log L]     # run each non-comment line; abort on '###ERROR';
                                                   # then 'save' (persist + reboot) or 'exit' (discard + reboot)
  bbcli.py run CMD [CMD ...] [--save]              # ad-hoc commands, output to stdout

Notes (Betaflight 4.2 cli.c): both 'exit' and 'save' reboot the FC (cliExit calls cliReboot), so the USB port
re-enumerates; arming is disabled while in CLI (ARMING_DISABLED_CLI). Never leave the FC in CLI mode.
"""
import argparse, sys, time

PROMPT = b"\r\n# "


def read_until_quiet(port, quiet=0.5, maxt=20.0, until=None, clock=time.time):
    out, t0, last = bytearray(), clock(), clock()
    while clock() - t0 < maxt:
        d = port.read(4096)
        if d:
            out += d
            last = clock()
            if until and out.endswith(until):
                break
        elif clock() - last > quiet:
            break
    return bytes(out)


def enter(port, tries=4):
    for _ in range(tries):
        port.write(b"#")
        r = read_until_quiet(port, 0.6, 3.0, until=PROMPT)
        if b"CLI" in r or r.endswith(PROMPT) or r.endswith(b"# "):
            return r.decode("latin1")
        if r.endswith(b"#"):
            # already in CLI (left there earlier): '#' was only echoed. Enter makes it a comment line (cli.c
            # strips '#...'), so the FC just prints the prompt.
            port.write(b"\r\n")
            r2 = read_until_quiet(port, 0.6, 3.0, until=PROMPT)
            if r2.endswith(PROMPT) or r2.endswith(b"# "):
                return (r + r2).decode("latin1")
    raise RuntimeError("no CLI prompt")


def command(port, cmd, quiet=0.5, maxt=30.0):
    """Send one command line, return its output (without the echo and trailing prompt)."""
    port.write(cmd.encode() + b"\r\n")
    r = read_until_quiet(port, quiet, maxt, until=PROMPT).decode("latin1")
    lines = r.replace("\r", "").split("\n")
    if lines and lines[0].strip() == cmd.strip():
        lines = lines[1:]
    if lines and lines[-1].strip() == "#":
        lines = lines[:-1]
    return "\n".join(lines).strip("\n")


def config_lines(text):
    """Commands from a config file: skip blanks, '#' comments, and save/exit (the tool decides how to leave)."""
    out = []
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#") or ln in ("save", "exit"):
            continue
        out.append(ln)
    return out


def leave(port, save):
    port.write(b"save\r\n" if save else b"exit\r\n")
    try:
        r = read_until_quiet(port, 0.5, 3.0).decode("latin1")
    except OSError as e:  # the FC reboots and the USB VCP disappears (SerialException is an OSError)
        r = "(port closed by FC reboot: %s)" % e
    return r


def run(port, cmds, save=False, log=None):
    """Enter CLI, run cmds; on any '###ERROR' stop and leave with 'exit' (nothing saved). Returns (ok, transcript)."""
    tr = [enter(port)]
    ok = True
    for c in cmds:
        o = command(port, c, quiet=1.0 if c.startswith(("diff", "dump")) else 0.4)
        tr.append("# " + c + "\n" + o)
        if log:
            log.write(tr[-1] + "\n")
            log.flush()
        if "###ERROR" in o:
            ok = False
            break
    tr.append(leave(port, save and ok))
    return ok, "\n".join(tr)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["diff", "apply", "run"])
    ap.add_argument("args", nargs="+")
    ap.add_argument("--port", default="/dev/cu.usbmodem0x80000001")
    ap.add_argument("--save", action="store_true")
    ap.add_argument("--log")
    a = ap.parse_args(argv)
    import serial
    port = serial.Serial(a.port, 115200, timeout=0.05)
    try:
        port.reset_input_buffer()
        if a.mode == "diff":
            tr = [enter(port)]
            d = command(port, "diff all", quiet=1.5, maxt=60)
            leave(port, False)
            with open(a.args[0], "w") as f:
                f.write(d + "\n")
            print("wrote %s (%d lines); FC rebooting" % (a.args[0], d.count("\n") + 1))
        else:
            cmds = config_lines(open(a.args[0]).read()) if a.mode == "apply" else a.args
            log = open(a.log, "w") if a.log else None
            ok, tr = run(port, cmds, a.save, log)
            print(tr)
            if not ok:
                sys.exit("###ERROR from FC: nothing saved (left with 'exit')")
    finally:
        port.close()


if __name__ == "__main__":
    main()
