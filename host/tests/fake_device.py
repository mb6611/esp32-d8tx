# SPDX-License-Identifier: GPL-3.0-or-later
"""In-memory Transport that answers the burst protocol commands."""
from __future__ import annotations

import json
import zlib

from esp32sdr.protocol import payload_bytes


class FakeTransport:
    def __init__(self, *, garbage: bytes = b"", ignore_sync: int = 0,
                 no_sync_until_reset: bool = False, fail_lock: bool = False,
                 corrupt_next_crc: bool = False, timeout_next_data: bool = False,
                 timeout_next_reply: bool = False):
        self.out = bytearray(garbage)
        self.inbuf = bytearray()
        self.ignore_sync = ignore_sync          # swallow this many SYNC commands
        self.dead = no_sync_until_reset         # unresponsive until reset()
        self.fail_lock = fail_lock
        self.corrupt_next_crc = corrupt_next_crc
        self.timeout_next_data = timeout_next_data
        self.timeout_next_reply = timeout_next_reply
        self.resets = 0
        self.freq = None
        self.sent: list[str] = []
        self.closed = False

    # -- Transport ---------------------------------------------------
    def write(self, data: bytes) -> None:
        self.inbuf += data
        while b"\n" in self.inbuf:
            i = self.inbuf.index(b"\n")
            line = bytes(self.inbuf[:i]).decode(errors="replace").strip()
            del self.inbuf[:i + 1]
            if line:
                self._handle(line)

    def read_exact(self, n: int, timeout: float) -> bytes:
        if len(self.out) < n:
            self.out.clear()
            raise TimeoutError("short read")
        b = bytes(self.out[:n])
        del self.out[:n]
        return b

    def readline(self, timeout: float) -> bytes:
        if b"\n" not in self.out:
            raise TimeoutError("readline timeout")
        i = self.out.index(b"\n")
        b = bytes(self.out[:i + 1])
        del self.out[:i + 1]
        return b

    def reset_input(self) -> None:
        self.out.clear()

    def reset(self) -> None:
        self.resets += 1
        self.dead = False
        self.out.clear()

    def close(self) -> None:
        self.closed = True

    # -- firmware ----------------------------------------------------
    def _say(self, text: str) -> None:
        self.out += (text + "\n").encode()

    def _handle(self, line: str) -> None:
        self.sent.append(line)
        if self.dead:
            return
        w = line.split()
        c = w[0]
        if c == "SYNC":
            if self.ignore_sync > 0:
                self.ignore_sync -= 1
                return
            self._say(line)
            return
        if self.timeout_next_reply and c != "RELEASE":
            self.timeout_next_reply = False
            return
        if c == "RELEASE":
            self._say("OK")
        elif c == "INFO":
            self._say("ESP32SDR 6 burst 16380")
        elif c == "CAPS":
            self._say("CAPS VERSION SPEC IQ8")
        elif c == "LIMITS?":
            self._say('LIMITS {"gain":[0,10,1],"bandwidth":null,"rates":[0,1,6],"bits":[8,10]}')
        elif c == "VERSION?":
            self._say("VERSION " + json.dumps({"git": "abc123", "built": "now"}))
        elif c == "FREQ":
            if self.fail_lock:
                self._say("ERR pll_lock")
            else:
                self.freq = int(w[1])
                self._say("OK")
        elif c in ("CAP16", "CAP20"):
            n = int(w[1])
            bits = 8 if c == "CAP16" else 10
            raw = bytes((i * 7 + 3) & 0xFF for i in range(payload_bytes(n, bits)))
            crc = zlib.crc32(raw)
            if self.corrupt_next_crc:
                self.corrupt_next_crc = False
                crc ^= 1
            self._say(f"DATA {n} {crc:08x} 1234")
            if self.timeout_next_data:
                self.timeout_next_data = False
                self.out += raw[: len(raw) // 2]
            else:
                self.out += raw
        else:
            self._say("ERR command")
