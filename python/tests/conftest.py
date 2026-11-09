import threading
import time

import pytest


class FakePort:
    """Fake ESP32 speaking protocol v1."""
    def __init__(self):
        self.lines = []
        self.out_waiting = 0
        self._rx = bytearray()
        self._lk = threading.Lock()
        self.linked = False
        self.armok = False
        self.closed = False
        self.t_sticks = []

    def _emit(self, s):
        with self._lk:
            self._rx += (s + "\n").encode()

    def read(self, n=1):
        with self._lk:
            d = bytes(self._rx[:n]); del self._rx[:n]
        if not d:
            time.sleep(0.002)
        return d

    def write(self, b):
        for ln in b.decode().splitlines():
            self.lines.append(ln)
            self._cmd(ln)
        return len(b)

    def _cmd(self, ln):
        w = ln.split()
        c = w[0]
        if c == "S":
            if not self.linked:
                self._emit("OK")
            else:
                self.t_sticks.append(time.perf_counter())
        elif self.linked and c not in ("STOP", "STAT"):
            self.linked = False
            self._emit("EV link_end why=err slots=1 late_max_us=0 retune_max_us=0")
            self._emit("ERR busy linked")
        elif c == "INFO":
            self._emit("OK proto=1 fw=test slot_us=8994 channels=47 pwr_max=127 fofs_max_hz=200000 timeout_max_ms=1000")
        elif c == "STAT":
            self._emit(f"OK keyed={int(self.linked)} link={int(self.linked)} fofs=0 armok={int(self.armok)}")
        elif c == "FOFS":
            self._emit("OK" if abs(int(w[1])) <= 200000 else "ERR range fofs")
        elif c == "ARMOK":
            self.armok = True; self._emit("OK")
        elif c == "LINK":
            self.linked = True; self._emit("OK")
        elif c in ("STOP", "U"):
            if self.linked:
                self._emit("EV link_end why=stop slots=5 late_max_us=7 retune_max_us=3")
            self.linked = False; self.armok = False; self._emit("OK")
        else:
            self._emit("ERR unknown cmd")

    def close(self):
        self.closed = True


@pytest.fixture
def port():
    return FakePort()
