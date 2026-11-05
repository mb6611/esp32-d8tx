# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure command builders and reply parsers for the burst serial protocol."""
from __future__ import annotations

import json
import zlib
from dataclasses import dataclass


class DeviceError(Exception):
    """The firmware answered `ERR ...`."""


class LinkError(Exception):
    """Could not establish or keep a link to the board."""


class TransferError(Exception):
    """A capture failed (CRC, timeout, short data); the link was resynced."""


class LockError(DeviceError):
    """The firmware reported that tuning failed."""


@dataclass(frozen=True)
class Info:
    family: str
    version: int
    mode: str
    max_samples: int


def check_err(line: str) -> str:
    line = line.strip()
    if line.startswith("ERR"):
        raise DeviceError(line)
    return line


def parse_info(line: str) -> Info:
    p = check_err(line).split()
    if len(p) != 4:
        raise ValueError(f"bad INFO reply: {line!r}")
    return Info(p[0], int(p[1]), p[2], int(p[3]))


def parse_limits(line: str) -> dict:
    line = check_err(line)
    if not line.startswith("LIMITS "):
        raise ValueError(f"bad LIMITS reply: {line!r}")
    return json.loads(line[7:])


def parse_version(line: str) -> dict:
    line = check_err(line)
    if not line.startswith("VERSION "):
        raise ValueError(f"bad VERSION reply: {line!r}")
    return json.loads(line[8:])


def parse_caps(line: str) -> list[str]:
    p = check_err(line).split()
    if not p or p[0] != "CAPS":
        raise ValueError(f"bad CAPS reply: {line!r}")
    return p[1:]


def parse_data_header(line: str) -> tuple[int, int, int]:
    """`DATA n crchex us` -> (samples, crc, capture_us)."""
    p = check_err(line).split()
    if len(p) != 4 or p[0] != "DATA":
        raise ValueError(f"bad DATA header: {line!r}")
    return int(p[1]), int(p[2], 16), int(p[3])


def crc32_ok(payload: bytes, crc: int) -> bool:
    return zlib.crc32(payload) & 0xFFFFFFFF == crc


def payload_bytes(samples: int, bits: int) -> int:
    """Bytes following a DATA header: ceil(samples * bits * 2 / 8)."""
    return (samples * bits * 2 + 7) // 8


def cap_command(samples: int, rate_code: int, bits: int) -> str:
    if bits == 8:
        return f"CAP16 {samples} {rate_code}"
    if bits == 10:
        return f"CAP20 {samples} {rate_code}"
    raise ValueError(f"bits must be 8 or 10, not {bits}")
