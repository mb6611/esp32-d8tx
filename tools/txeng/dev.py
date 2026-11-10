"""Serial client for the txeng firmware (line commands, replies end in OK / ERR)."""
import time

import serial

E_FIELDS = ["ctrl", "reps", "flags", "gmode", "ndone", "cyc_min", "cyc_max", "cyc_mean", "ctrl_at_done",
            "ctrl_after_clr", "per_min", "per_max", "per_mean", "tone_before", "tone_after", "keyed_us",
            "pb01", "pb11", "pb12", "pb41", "pb51", "cap_ctrl", "cap_status", "cap_cyc"]
SNAP_REGS = ["d80", "d84", "d88", "d8c", "d90", "d94", "d98", "db4", "db8", "dc0", "dd0", "dd4", "tone0"]


class Hang(Exception):
    pass


class Dev:
    def __init__(self, port="/dev/cu.usbserial-0001", baud=921600, log=None):
        self.s = serial.Serial()
        self.s.port, self.s.baudrate, self.s.timeout = port, baud, 0.2
        self.s.dtr = False
        self.s.rts = False
        self.s.open()
        self.log = log
        self.hangs = 0

    def _w(self, line):
        if self.log:
            self.log.write(line + "\n")
            self.log.flush()

    def readline(self):
        raw = self.s.readline()
        if not raw:
            return None
        line = raw.decode("ascii", "replace").strip()
        self._w("< " + line)
        return line

    def wait_ready(self, timeout=15):
        t0 = time.time()
        while time.time() - t0 < timeout:
            l = self.readline()
            if l and l.startswith("I,ready"):
                return l
        raise RuntimeError("no I,ready")

    def reset(self):
        self.s.rts = True
        time.sleep(0.1)
        self.s.rts = False
        return self.wait_ready()

    def cmd(self, line, timeout=10):
        self.s.reset_input_buffer()
        self._w("> " + line)
        self.s.write((line + "\n").encode())
        out, t0 = [], time.time()
        while time.time() - t0 < timeout:
            l = self.readline()
            if l is None:
                continue
            if l.startswith("I,boot"):
                self.hangs += 1
                self.wait_ready()
                raise Hang(line)
            if l == "OK":
                return out
            if l.startswith("ERR"):
                raise RuntimeError(f"{line}: {l}")
            out.append(l)
        raise TimeoutError(line)

    def rd(self, a):
        return int(self.cmd(f"R 0x{a:08x}")[0].split(",")[2], 16)

    def wr(self, a, v):
        return int(self.cmd(f"W 0x{a:08x} 0x{v:08x}")[0].split(",")[2], 16)

    def tx(self, ctrl, reps=1, tmo=2000, flags=0, gmode=9, pwr=-1):
        out = self.cmd(f"T 0x{ctrl:08x} {reps} {tmo} {flags} {gmode} {pwr}")
        e, snaps = None, {}
        for l in out:
            f = l.split(",")
            if f[0] == "E":
                e = dict(zip(E_FIELDS, f[1:]))
                for k in e:
                    e[k] = int(e[k], 16) if k in ("ctrl", "ctrl_at_done", "ctrl_after_clr", "tone_before",
                                                  "tone_after", "cap_ctrl", "cap_status") else int(e[k])
            elif f[0] == "S":
                snaps[f[1]] = [int(x, 16) for x in f[2:]]
        e["snaps"] = snaps
        return e

    def dump(self, off, n):
        out = self.cmd(f"D {off} {n}", timeout=30)
        words = []
        for l in out:
            f = l.split(",")
            if f[0] == "X":
                words += [int(x, 16) for x in f[2:]]
        return words
