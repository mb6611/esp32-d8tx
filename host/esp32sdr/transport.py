# SPDX-License-Identifier: GPL-3.0-or-later
"""Byte transport abstraction and the pyserial implementation."""
from __future__ import annotations

import time
from typing import Protocol

DEFAULT_PORT = "/dev/cu.usbserial-0001"
DEFAULT_BAUD = 921600


class Transport(Protocol):
    """What Device needs from a link. Timeouts raise TimeoutError."""

    def write(self, data: bytes) -> None: ...

    def read_exact(self, n: int, timeout: float) -> bytes: ...

    def readline(self, timeout: float) -> bytes: ...

    def reset_input(self) -> None: ...

    def reset(self) -> None: ...

    def close(self) -> None: ...


class SerialTransport:
    """pyserial link that reads in bulk with one fixed port timeout.

    Changing ``serial.Serial.timeout`` reconfigures the tty; doing that before
    every read drops bytes on the DevKit's CP2102 bridge (VERSION? replies
    lost, CAP16/SPC1 payloads corrupted). So the port timeout is set once, all
    reads go through an internal buffer in large chunks, and deadlines are
    enforced here instead.
    """

    POLL = 0.05  # fixed pyserial read timeout, seconds

    def __init__(self, port: str = DEFAULT_PORT, baud: int = DEFAULT_BAUD):
        import serial

        # Open with DTR/RTS deasserted so opening the port does not hold EN low.
        ser = serial.Serial(port=None, baudrate=baud, timeout=self.POLL)
        ser.dtr = False
        ser.rts = False
        ser.port = port
        ser.open()
        self._ser = ser
        self._buf = bytearray()

    def _fill(self) -> bool:
        """Read whatever is waiting (at least one byte or POLL seconds)."""
        chunk = self._ser.read(max(self._ser.in_waiting, 1))
        if chunk:
            self._buf += chunk
            return True
        return False

    def write(self, data: bytes) -> None:
        self._ser.write(data)
        self._ser.flush()

    def read_exact(self, n: int, timeout: float) -> bytes:
        deadline = time.monotonic() + timeout
        while len(self._buf) < n:
            if time.monotonic() >= deadline:
                got = len(self._buf)
                self._buf.clear()
                raise TimeoutError(f"short read {got}/{n}")
            self._fill()
        out = bytes(self._buf[:n])
        del self._buf[:n]
        return out

    def read_some(self, n: int, timeout: float) -> bytes:
        """1..n bytes as soon as any are available; TimeoutError if none arrive.
        Unlike read_exact, a timeout loses nothing."""
        deadline = time.monotonic() + timeout
        while not self._buf:
            if time.monotonic() >= deadline:
                raise TimeoutError("no data")
            self._fill()
        out = bytes(self._buf[:n])
        del self._buf[:n]
        return out

    def readline(self, timeout: float) -> bytes:
        deadline = time.monotonic() + timeout
        scanned = 0
        while True:
            i = self._buf.find(b"\n", scanned)
            if i >= 0:
                out = bytes(self._buf[: i + 1])
                del self._buf[: i + 1]
                return out
            scanned = len(self._buf)
            if time.monotonic() >= deadline:
                raise TimeoutError("readline timeout")
            self._fill()

    def reset_input(self) -> None:
        self._buf.clear()
        self._ser.reset_input_buffer()

    def reset(self) -> None:
        """Pulse RTS (wired to EN on the DevKit) to reset the board."""
        self._ser.dtr = False
        self._ser.rts = True
        time.sleep(0.1)
        self._ser.rts = False
        time.sleep(1.0)
        self.reset_input()

    def close(self) -> None:
        self._ser.close()
