# SPDX-License-Identifier: GPL-3.0-or-later
"""Each CLI subcommand against the in-memory fake device (no board)."""
from __future__ import annotations

import io
import json
import struct
import zlib

import numpy as np
import pytest

from esp32sdr import cli
from esp32sdr.device import Device
from esp32sdr.spec_cmd import spectrum
from esp32sdr.protocol import TransferError

from fake_device import FakeTransport


def spc1(seq: int, log2: int, codes: np.ndarray, ffts: int = 4, flags: int = 0) -> bytes:
    n = 1 << log2
    hdr = struct.pack("<4sIQIHBBHBB", b"SPC1", seq, seq * 1000, n * ffts, ffts, flags, 0, 0, log2, 2)
    body = hdr + codes.astype(np.uint8).tobytes()
    assert len(body) == 28 + n
    return body + struct.pack("<I", zlib.crc32(body))


class SpecFake(FakeTransport):
    """FakeTransport plus GAIN?, TRANSPORT? and a SPEC run of `frames` frames."""

    def __init__(self, frames: int = 3, corrupt_frame: int | None = None,
                 sps1: bool = False, **kw):
        super().__init__(**kw)
        self.frames = frames
        self.corrupt_frame = corrupt_frame
        self.sps1 = sps1
        self.stop_bytes = 0
        self.in_spec = False

    def write(self, data: bytes) -> None:
        if self.in_spec and data == b"\n":
            self.stop_bytes += 1
            return
        super().write(data)

    def _handle(self, line: str) -> None:
        w = line.split()
        if w[0] == "GAIN?":
            self.sent.append(line)
            self._say("GAIN HARDWARE -1 0 81 0")
            return
        if w[0] == "TRANSPORT?":
            self.sent.append(line)
            self._say("TRANSPORT UART 921600")
            return
        if w[0] == "SPEC":
            self.sent.append(line)
            ms, stride, units, det, rate, n = map(int, w[1:7])
            fs = {0: 80_000_000, 1: 40_000_000, 6: 16_000_000}[rate]
            self._say(f"SPEC {n} {fs} {n} {self.freq or 0}")
            log2 = n.bit_length() - 1
            # natural FFT order: put a strong bin at +n/8 (baseband)
            codes = np.full(n, 40, dtype=np.uint8)
            codes[n // 8] = 200
            for k in range(self.frames):
                if self.sps1 and k == 1:
                    body = b"SPS1" + bytes(32)
                    self.out += body + struct.pack("<I", zlib.crc32(body))
                fr = bytearray(spc1(k, log2, codes, flags=det))
                if k == self.corrupt_frame:
                    fr[40] ^= 0xFF
                self.out += fr
            self._say(f"SPECEND 0 0 {self.frames * 4} {self.frames * 4 * n} 300000 0 0 "
                      f"{self.frames} 0 0 {self.frames * 4} 0")
            self.in_spec = True
            return
        self.in_spec = False
        super()._handle(line)


def factory(fake):
    def make(port):
        dev = Device(fake, sync_timeout=0.5, reply_timeout=0.1, data_timeout=0.1)
        dev.sync()
        return dev
    return make


def run(argv, fake):
    out = io.StringIO()
    rc = cli.main(argv, device_factory=factory(fake), out=out)
    return rc, out.getvalue()


def test_info():
    fake = SpecFake()
    rc, text = run(["info"], fake)
    assert rc == 0
    assert "ESP32SDR" in text and "16380" in text
    assert "UART 921600" in text
    assert "rates" in text and "bits      8 10" in text
    assert fake.closed


def test_tune_ok_and_refused(capsys):
    fake = SpecFake()
    rc, text = run(["tune", "2437"], fake)
    assert rc == 0 and fake.freq == 2437 and "2437" in text
    fake = SpecFake()
    rc, _ = run(["tune", "2600"], fake)
    err = capsys.readouterr().err
    assert rc == 1 and "2600" in err and err.count("\n") == 1
    assert not any(s.startswith("FREQ") for s in fake.sent)


def test_tune_lock_failure(capsys):
    rc, _ = run(["tune", "2437"], SpecFake(fail_lock=True))
    assert rc == 1 and "LockError" in capsys.readouterr().err


@pytest.mark.parametrize("bits", [8, 10])
def test_capture_writes_sigmf(tmp_path, bits):
    fake = SpecFake()
    base = tmp_path / "ch6"
    rc, text = run(["capture", "--freq", "2437", "--rate", "40", "--bits", str(bits),
                    "--n", "1000", "-o", str(base), "--psd", str(tmp_path / "p.csv")], fake)
    assert rc == 0, text
    assert any(s == ("CAP16 1000 1" if bits == 8 else "CAP20 1000 1") for s in fake.sent)
    meta = json.loads((tmp_path / "ch6.sigmf-meta").read_text())
    g = meta["global"]
    assert g["core:sample_rate"] == 40e6 and g["core:sample_count"] == 1000
    assert g["esp32sdr:bits"] == bits and g["esp32sdr:gain_mode"] == "HARDWARE"
    assert meta["captures"][0]["core:frequency"] == 2437e6
    assert (tmp_path / "ch6.sigmf-data").stat().st_size == 1000 * 8
    assert (tmp_path / "p.csv").read_text().startswith("freq_mhz,power_db\n")


def test_capture_crc_error_exits_nonzero(tmp_path, capsys):
    fake = SpecFake(corrupt_next_crc=True)
    rc, _ = run(["capture", "--freq", "2437", "--n", "100", "-o", str(tmp_path / "x")], fake)
    err = capsys.readouterr().err
    assert rc == 1 and "CRC" in err
    assert not (tmp_path / "x.sigmf-data").exists()


def test_capture_bad_n(tmp_path):
    rc, _ = run(["capture", "--freq", "2437", "--n", "20000", "-o", str(tmp_path / "x")], SpecFake())
    assert rc == 2


def test_spectrum_csv_and_orientation(tmp_path):
    fake = SpecFake(frames=3, sps1=True)
    path = tmp_path / "s.csv"
    rc, text = run(["spectrum", "--freq", "2437", "--bins", "256", "--rate", "40",
                    "-o", str(path)], fake)
    assert rc == 0, text
    assert any(s == "SPEC 500 1 1 0 1 256" for s in fake.sent)
    assert "3 frames, 12 FFTs" in text
    rows = path.read_text().splitlines()
    assert rows[0] == "freq_mhz,power_db" and len(rows) == 257
    f = np.array([float(r.split(",")[0]) for r in rows[1:]])
    p = np.array([float(r.split(",")[1]) for r in rows[1:]])
    assert np.all(np.diff(f) > 0)
    # baseband bin +n/8 = +5 MHz of raw (I,-Q) data is RF LO - 5 MHz
    assert f[np.argmax(p)] == pytest.approx(2432.0)
    assert "peak 2432.000 MHz" in text


def test_spectrum_bad_bins():
    with pytest.raises(SystemExit):
        cli.main(["spectrum", "--freq", "2437", "--bins", "300"])


def test_spectrum_bad_extension(tmp_path, capsys):
    rc, _ = run(["spectrum", "--freq", "2437", "--bins", "256", "-o", str(tmp_path / "s.txt")],
                SpecFake())
    assert rc == 1 and ".csv or .png" in capsys.readouterr().err


def test_spectrum_crc_failure_resyncs():
    fake = SpecFake(frames=3, corrupt_frame=1)
    dev = factory(fake)("x")
    dev.tune(2437)
    with pytest.raises(TransferError):
        spectrum(dev, 256, 1, 300)
    # link usable afterwards
    assert dev.info().family == "ESP32SDR"


def test_spectrum_stop_byte_after_max_frames():
    fake = SpecFake(frames=5)
    dev = factory(fake)("x")
    run_ = spectrum(dev, 512, 6, 0, max_frames=2)
    assert fake.stop_bytes == 1
    assert len(run_.frames) == 5 and run_.end["frames"] == 5
    assert run_.fs == 16_000_000


def test_spectrum_requires_bound():
    dev = factory(SpecFake())("x")
    with pytest.raises(ValueError):
        spectrum(dev, 512, 1, 0)
