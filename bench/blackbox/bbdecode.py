#!/usr/bin/env python3
"""Decode a .bbl (one or more logs) to one CSV per log: <outdir>/<stem>.NN.csv.

Default engine is the official blackbox_decode (betaflight/blackbox-tools, built by build_decoder.sh);
--engine py uses the pure-Python fallback in bbl.py (same column names; vbat/amperage stay raw in both).

  bbdecode.py LOG.bbl [--outdir DIR] [--engine auto|c|py]
"""
import argparse, os, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bbl  # noqa: E402

VENDOR_BIN = os.path.join(HERE, "vendor", "blackbox-tools", "obj", "blackbox_decode")
C_ARGS = ["--unit-vbat", "raw", "--unit-amperage", "raw", "--unit-flags", "raw"]


def find_decoder():
    for p in (os.environ.get("BLACKBOX_DECODE"), VENDOR_BIN, shutil.which("blackbox_decode")):
        if p and os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


def decode(path, outdir=None, engine="auto"):
    """Return the list of CSV paths written, one per log in the file (in order)."""
    outdir = outdir or os.path.dirname(os.path.abspath(path))
    os.makedirs(outdir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(path))[0]
    data = open(path, "rb").read()
    n = len(bbl.find_logs(data))
    if n == 0:
        raise ValueError("%s: no blackbox log header found" % path)
    exe = find_decoder() if engine in ("auto", "c") else None
    if engine == "c" and not exe:
        raise FileNotFoundError("blackbox_decode not found; run build_decoder.sh or set BLACKBOX_DECODE")
    out = []
    if exe:
        for i in range(1, n + 1):
            csv = os.path.join(outdir, "%s.%02d.csv" % (stem, i))
            with open(csv, "w") as f:
                r = subprocess.run([exe, *C_ARGS, "--index", str(i), "--stdout", path], stdout=f,
                                   stderr=subprocess.PIPE, text=True)
            if r.returncode != 0:
                raise RuntimeError("blackbox_decode failed on log %d: %s" % (i, r.stderr[-500:]))
            out.append(csv)
    else:
        for i, log in enumerate(bbl.parse(data), 1):
            csv = os.path.join(outdir, "%s.%02d.csv" % (stem, i))
            bbl.to_csv(log, csv)
            out.append(csv)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("bbl")
    ap.add_argument("--outdir")
    ap.add_argument("--engine", choices=["auto", "c", "py"], default="auto")
    a = ap.parse_args(argv)
    for p in decode(a.bbl, a.outdir, a.engine):
        print(p)


if __name__ == "__main__":
    main()
