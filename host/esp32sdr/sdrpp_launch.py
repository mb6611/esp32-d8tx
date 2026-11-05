# SPDX-License-Identifier: GPL-3.0-or-later
"""`esp32sdr sdrpp`: one-command live view in SDR++ (docs/devkitv1/live-view.md).

A thin wrapper around `esp32sdr bridge`: it stops an old bridge and SDR++, backs up
and writes SDR++'s config (RTL-TCP source on the bridge, frequency, decimation and
FFT for the ~31 kHz span, rigctl server on), launches SDR++, starts playback through
the rigctl server (`\\start`), and runs the unchanged bridge code path
(`rtltcp.cmd_bridge`) in the foreground. Ctrl-C stops the bridge; SDR++ stays open.

SDR++'s RTL-TCP source sends the frequency as a u32 in Hz (no clamp, so no
`--offset-mhz`), but only offers 250 kS/s and up. It asks for 250 kS/s; the bridge
interpolates by 8 (31250 x 8) and SDR++'s own decimation 8 brings the span back to
31.25 kHz with a correct frequency axis.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import threading
import time
from pathlib import Path

from . import rtltcp
from .iqs import ALLOWED, DEFAULT_RATE_CODE
from .samples import RATES

APP = Path("/Applications/SDR++.app")
ROOT = Path.home() / "Library" / "Application Support" / "sdrpp"
SDRPP_RATES = (250e3, 1.024e6, 1.536e6, 1.792e6, 1.92e6, 2.048e6, 2.16e6, 2.4e6,
               2.56e6, 2.88e6, 3.2e6)  # rtl_tcp_source's list
SDRPP_DECIMATIONS = (1, 2, 4, 8, 16, 32, 64)
RIGCTL_PORT = 4532


def client_rate(native: int) -> tuple[int, int]:
    """(SDR++ rtl_tcp rate, interpolation = SDR++ decimation) for a bridge rate."""
    for r in SDRPP_RATES:
        k = int(r) // native
        if int(r) % native == 0 and k in SDRPP_DECIMATIONS:
            return int(r), k
    raise ValueError(f"no SDR++ RTL-TCP rate is a power-of-two multiple of {native} S/s")


def _pids(*lsof_args: str) -> list[int]:
    r = subprocess.run(["lsof", "-t", *lsof_args], capture_output=True, text=True)
    return [int(p) for p in r.stdout.split()]


def _cmdline(pid: int) -> str:
    r = subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True)
    return r.stdout.strip()


def _wait_gone(pids: list[int], timeout: float = 5.0) -> list[int]:
    deadline = time.monotonic() + timeout
    while pids and time.monotonic() < deadline:
        pids = [p for p in pids if _alive(p)]
        if pids:
            time.sleep(0.1)
    return pids


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def stop_old_bridge(port: int, serial_port: str, log) -> None:
    """Terminate esp32sdr processes holding the TCP port or the serial port."""
    me = os.getpid()
    pids = set(_pids(f"-iTCP:{port}", "-sTCP:LISTEN"))
    if os.path.exists(serial_port):
        pids |= set(_pids(serial_port))
    pids.discard(me)
    victims = []
    for pid in sorted(pids):
        cmd = _cmdline(pid)
        if "esp32sdr" not in cmd:
            raise RuntimeError(f"port {port} or {serial_port} is held by pid {pid} ({cmd!r}); "
                               "stop it first")
        log(f"stopping old bridge pid {pid}")
        os.kill(pid, signal.SIGTERM)  # SIGINT is ignored by `cmd &` jobs
        victims.append(pid)
    for pid in _wait_gone(victims):
        os.kill(pid, signal.SIGKILL)
    _wait_gone(victims, 2.0)


def quit_sdrpp(log) -> None:
    """SDR++ saves its config on exit, so it must be gone before we write it."""
    pids = [int(p) for p in subprocess.run(["pgrep", "-x", "sdrpp"], capture_output=True,
                                           text=True).stdout.split()]
    if not pids:
        return
    log("quitting SDR++")
    for p in pids:
        os.kill(p, signal.SIGTERM)
    for p in _wait_gone(pids, 8.0):
        os.kill(p, signal.SIGKILL)
    _wait_gone(pids, 2.0)


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def write_config(root: Path, *, freq_hz: int, host: str, port: int, rate: int, decim: int,
                 log, stamp: str | None = None) -> Path | None:
    """Back up and update SDR++'s config. Returns the backup dir (None if nothing existed)."""
    root.mkdir(parents=True, exist_ok=True)
    names = ("config.json", "rtl_tcp_config.json", "rigctl_server_config.json",
             "radio_config.json")
    backup = None
    if any((root / n).exists() for n in names):
        backup = root / f"esp32sdr-backup-{stamp or time.strftime('%Y%m%d-%H%M%S')}"
        backup.mkdir(exist_ok=True)
        for n in names:
            if (root / n).exists():
                shutil.copy2(root / n, backup / n)
        log(f"backed up SDR++ config to {backup}")

    c = _load(root / "config.json")  # SDR++ fills in every key we leave out
    c.update({
        "source": "RTL-TCP",
        "frequency": float(freq_hz),
        "decimation": decim,          # 250 kS/s / decim = the bridge rate
        "centerTuning": True,         # typing a frequency retunes the board
        "fftSize": 1024,              # 30 Hz bins at 31.25 kS/s
        "fftRate": 25,                # 25 x 1024 < 31250 samples/s, no overlap needed
        "fftWindow": 2,
        "fftSmoothing": False,
        "fullWaterfallUpdate": True,
        "min": -110.0,
        "max": -40.0,
        "showWaterfall": True,
        "selectedOffset": "None",
        "manualOffset": 0.0,
        "invertIQ": False,
        "iqCorrection": False,
    })
    c.setdefault("streams", {}).setdefault("Radio", {}).update({"muted": True})
    mods = c.setdefault("moduleInstances", {})
    for name, module in (("RTL-TCP Source", "rtl_tcp_source"), ("Rigctl Server", "rigctl_server")):
        inst = mods.get(name)
        if isinstance(inst, dict):
            inst["enabled"] = True
        elif inst is None or isinstance(inst, str):
            mods[name] = {"module": module, "enabled": True}
    (root / "config.json").write_text(json.dumps(c, indent=4))

    r = _load(root / "rtl_tcp_config.json")
    r.update({"host": host, "port": port, "sampleRate": float(rate), "directSamplingMode": 0,
              "ppm": 0, "gainIndex": 0, "biasTee": False, "offsetTuning": False,
              "rtlAGC": False, "tunerAGC": False})
    (root / "rtl_tcp_config.json").write_text(json.dumps(r, indent=4))

    g = _load(root / "rigctl_server_config.json")
    g["Rigctl Server"] = {**g.get("Rigctl Server", {}), "host": "localhost",
                          "port": RIGCTL_PORT, "tuning": True, "recording": False,
                          "autoStart": True, "vfo": "Radio", "recorder": ""}
    (root / "rigctl_server_config.json").write_text(json.dumps(g, indent=4))

    # The default WFM VFO (150 kHz wide, 100 kHz snap) does not fit a 31 kHz span and
    # pulls the centre off the requested frequency; use NFM, 12.5 kHz, 1 kHz snap.
    a = _load(root / "radio_config.json")
    radio = a.setdefault("Radio", {})
    radio["selectedDemodId"] = 0  # NFM
    radio.setdefault("NFM", {}).update({"bandwidth": 12500.0, "snapInterval": 1000.0})
    (root / "radio_config.json").write_text(json.dumps(a, indent=4))
    return backup


def rigctl(cmd: str, timeout: float = 2.0) -> str:
    with socket.create_connection(("127.0.0.1", RIGCTL_PORT), timeout=timeout) as s:
        s.sendall((cmd + "\n").encode())
        if cmd.startswith("\\st"):  # \start / \stop send no reply
            return ""
        return s.recv(256).decode(errors="replace").strip()


def start_playback(bridge, log, timeout: float = 30.0) -> bool:
    """Wait for SDR++'s rigctl server, send \\start until the bridge has a client."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if bridge.alive.is_set():
            return True
        try:
            rigctl("\\start")
        except OSError:
            time.sleep(0.5)
            continue
        t = time.monotonic() + 3.0
        while time.monotonic() < t and not bridge.alive.is_set():
            time.sleep(0.1)
    if not bridge.alive.is_set():
        log("could not start SDR++ playback automatically: press the play button "
            "(top-left triangle) in SDR++")
        return False
    return True


def cmd_sdrpp(args, out) -> int:
    def log(m):
        print(m, file=out, flush=True)

    if (6, args.dec, args.bits) not in ALLOWED:
        raise ValueError(f"decimation {args.dec}/{args.bits}-bit exceeds the UART link budget")
    native = RATES[DEFAULT_RATE_CODE] // args.dec
    rate, decim = client_rate(native)
    host, port = rtltcp.parse_listen(args.listen)
    app = Path(args.app)
    if not app.exists():
        raise ValueError(f"SDR++ not found at {app} (install it, or pass --app)")

    try:
        stop_old_bridge(port, args.port, log)
    except RuntimeError as e:
        raise ValueError(str(e)) from e
    quit_sdrpp(log)
    write_config(Path(args.root), freq_hz=int(round(args.freq * 1e6)),
                 host=host if host not in ("0.0.0.0", "") else "127.0.0.1", port=port,
                 rate=rate, decim=decim, log=log)

    def on_ready(bridge):
        log(f"launching SDR++ ({rate} S/s from the bridge, SDR++ decimation {decim} "
            f"-> {native} S/s span)")
        subprocess.run(["open", "-a", str(app)], check=False)
        threading.Thread(target=start_playback, args=(bridge, log), daemon=True).start()

    args.on_ready = on_ready
    log("bridge running; Ctrl-C stops it")
    return rtltcp.cmd_bridge(args, out)


def register(sub) -> None:
    p = sub.add_parser("sdrpp", help="live view: configure + launch SDR++ and run the bridge")
    rtltcp.add_bridge_args(p, freq=2480.0)
    p.add_argument("--app", default=str(APP), help=f"SDR++ app bundle (default {APP})")
    p.add_argument("--root", default=str(ROOT), help=f"SDR++ config dir (default {ROOT})")
    p.set_defaults(func=cmd_sdrpp)
