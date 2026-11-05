# SPDX-License-Identifier: GPL-3.0-or-later
import zlib

import pytest

from esp32sdr import protocol as P
from esp32sdr.device import Device
from esp32sdr.protocol import DeviceError, LinkError, LockError, TransferError
from fake_device import FakeTransport


def dev(**kw):
    t = FakeTransport(**kw)
    return Device(t, sync_timeout=0.3, reply_timeout=0.1, data_timeout=0.1), t


def test_sync_discards_garbage():
    d, t = dev(garbage=b"\x00\xffboot junk\nmore junk\n")
    d.sync()
    assert t.resets == 0
    assert d.info() == P.Info("ESP32SDR", 6, "burst", 16380)


def test_sync_retries_then_succeeds():
    d, t = dev(ignore_sync=2)
    d.sync()
    assert t.resets == 0


def test_sync_resets_once_then_ok():
    d, t = dev(no_sync_until_reset=True)
    d.sync()
    assert t.resets == 1


def test_sync_fails_raises_link_error():
    d, t = dev(ignore_sync=10**6)
    with pytest.raises(LinkError):
        d.sync()
    assert t.resets == 1


def test_queries():
    d, _ = dev()
    d.sync()
    assert d.limits()["rates"] == [0, 1, 6]
    assert d.version()["git"] == "abc123"
    assert "SPEC" in d.caps()


def test_tune_ok_and_range():
    d, t = dev()
    d.sync()
    d.tune(2437)
    assert t.freq == 2437
    n = len(t.sent)
    for bad in (1849, 2501, 2600):
        with pytest.raises(ValueError):
            d.tune(bad)
    assert len(t.sent) == n  # nothing sent


def test_tune_lock_failure():
    d, _ = dev(fail_lock=True)
    d.sync()
    with pytest.raises(LockError):
        d.tune(2437)


def test_unknown_command_is_device_error():
    d, _ = dev()
    d.sync()
    with pytest.raises(DeviceError):
        d.command("NOPE") and P.check_err("ERR x")


@pytest.mark.parametrize("bits,cmd", [(8, "CAP16"), (10, "CAP20")])
def test_cap(bits, cmd):
    d, t = dev()
    d.sync()
    raw = d.cap16(256, 1, bits)
    assert len(raw) == P.payload_bytes(256, bits)
    assert t.sent[-1].startswith(cmd)


def test_cap_crc_error_recovers():
    d, t = dev(corrupt_next_crc=True)
    d.sync()
    with pytest.raises(TransferError):
        d.cap16(256, 1, 8)
    assert len(d.cap16(256, 1, 8)) == 512


def test_cap_data_timeout_recovers():
    d, t = dev(timeout_next_data=True)
    d.sync()
    with pytest.raises(TransferError):
        d.cap16(256, 1, 8)
    assert len(d.cap16(256, 1, 8)) == 512


def test_reply_timeout_recovers():
    d, t = dev(timeout_next_reply=True)
    d.sync()
    with pytest.raises(TransferError):
        d.info()
    assert d.info().family == "ESP32SDR"


def test_protocol_parsers():
    assert P.parse_data_header("DATA 10 ff 99") == (10, 255, 99)
    with pytest.raises(DeviceError):
        P.parse_data_header("ERR capture_timeout")
    assert P.crc32_ok(b"abc", zlib.crc32(b"abc"))
    assert not P.crc32_ok(b"abd", zlib.crc32(b"abc"))
    assert P.payload_bytes(3, 10) == 8
    with pytest.raises(ValueError):
        P.cap_command(10, 1, 12)
