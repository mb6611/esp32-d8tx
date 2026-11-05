# SPDX-License-Identifier: GPL-3.0-or-later
"""High-level device control over a Transport."""
from __future__ import annotations

import math
import time

from . import protocol as P
from .protocol import DeviceError, LinkError, LockError, TransferError  # noqa: F401
from .transport import DEFAULT_BAUD, DEFAULT_PORT, SerialTransport, Transport

FREQ_MIN_MHZ = 1850
FREQ_MAX_MHZ = 2500


class Device:
    def __init__(self, transport: Transport, *, sync_timeout: float = 10.0,
                 reply_timeout: float = 5.0, data_timeout: float = 5.0):
        self.t = transport
        self.sync_timeout = sync_timeout
        self.reply_timeout = reply_timeout
        self.data_timeout = data_timeout

    @classmethod
    def open(cls, port: str = DEFAULT_PORT, baud: int = DEFAULT_BAUD, **kw) -> "Device":
        try:
            dev = cls(SerialTransport(port, baud), **kw)
        except Exception as e:  # serial.SerialException etc.
            raise LinkError(f"cannot open {port}: {e}") from e
        try:
            dev.sync()
        except Exception:
            dev.close()
            raise
        return dev

    def close(self) -> None:
        try:
            self.t.write(b"RELEASE\n")
        except Exception:
            pass
        self.t.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- link -------------------------------------------------------
    def _sync_once(self) -> bool:
        deadline = time.monotonic() + self.sync_timeout
        while time.monotonic() < deadline:
            self.t.reset_input()
            marker = f"SYNC {time.monotonic_ns()}"
            self.t.write(f"\nRELEASE\n{marker}\n".encode())
            end = min(deadline, time.monotonic() + 1.0)
            while time.monotonic() < end:
                try:
                    line = self.t.readline(max(end - time.monotonic(), 0.01))
                except TimeoutError:
                    break
                if line.strip() == marker.encode():
                    return True
        return False

    def sync(self) -> None:
        if self._sync_once():
            return
        self.t.reset()
        if self._sync_once():
            return
        raise LinkError("no SYNC echo from board (even after reset)")

    def _resync_after(self, msg: str) -> TransferError:
        try:
            self.sync()
        except LinkError as e:
            return TransferError(f"{msg}; resync failed: {e}")
        return TransferError(msg)

    def command(self, text: str) -> str:
        self.t.write((text + "\n").encode())
        try:
            return self.t.readline(self.reply_timeout).decode(errors="replace").strip()
        except TimeoutError as e:
            raise self._resync_after(f"timeout waiting for reply to {text!r}") from e

    # -- queries ----------------------------------------------------
    def info(self) -> P.Info:
        return P.parse_info(self.command("INFO"))

    def caps(self) -> list[str]:
        return P.parse_caps(self.command("CAPS"))

    def limits(self) -> dict:
        return P.parse_limits(self.command("LIMITS?"))

    def version(self) -> dict:
        return P.parse_version(self.command("VERSION?"))

    # -- control ----------------------------------------------------
    def tune(self, mhz: int) -> None:
        if not isinstance(mhz, int) or isinstance(mhz, bool):
            f = float(mhz)
            if not math.isfinite(f) or f != int(f):
                raise ValueError("frequency must be a whole MHz")
            mhz = int(mhz)
        if not FREQ_MIN_MHZ <= mhz <= FREQ_MAX_MHZ:
            raise ValueError(
                f"{mhz} MHz outside supported range {FREQ_MIN_MHZ}-{FREQ_MAX_MHZ} MHz")
        reply = self.command(f"FREQ {mhz}")
        if reply == "OK":
            return
        if reply.startswith("ERR"):
            if "lock" in reply.lower():
                raise LockError(reply)
            raise DeviceError(reply)
        if "lock" in reply.lower() or "fail" in reply.lower():
            raise LockError(reply)
        raise DeviceError(f"unexpected FREQ reply: {reply!r}")

    def cap16(self, n: int, rate_code: int, bits: int = 8) -> bytes:
        """Capture n samples; returns the raw verified payload bytes."""
        cmd = P.cap_command(n, rate_code, bits)
        reply = self.command(cmd)
        try:
            got, crc, _us = P.parse_data_header(reply)
        except ValueError as e:
            raise self._resync_after(f"bad capture header: {e}") from e
        if got != n:
            raise self._resync_after(f"asked for {n} samples, header says {got}")
        try:
            raw = self.t.read_exact(P.payload_bytes(got, bits), self.data_timeout)
        except TimeoutError as e:
            raise self._resync_after("timeout reading capture data") from e
        if not P.crc32_ok(raw, crc):
            raise self._resync_after("capture CRC mismatch")
        return raw
