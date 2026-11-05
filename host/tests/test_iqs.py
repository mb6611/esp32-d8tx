# SPDX-License-Identifier: GPL-3.0-or-later
import json
import re
import struct
import zlib
from pathlib import Path

import numpy as np
import pytest

from esp32sdr import cli, iqs
from esp32sdr.device import Device
from esp32sdr.protocol import TransferError
from fake_device import FakeTransport

DOC = Path(__file__).resolve().parents[2] / "docs" / "devkitv1" / "iq-stream-uart.md"
DEC, BITS, N = 512, 8, 100


def frame(seq, index, vals, bits=BITS, dec=DEC, flags=0, bad_crc=False, gain=0):
    """vals: (n, 2) ints of (I, -Q) words."""
    vals = np.asarray(vals)
    if bits == 8:
        pay = vals.astype(np.int8).tobytes()
    elif bits == 16:
        pay = vals.astype("<i2").tobytes()
    else:
        pay = (((vals[:, 1] & 15) << 4) | (vals[:, 0] & 15)).astype(np.uint8).tobytes()
    h = b"IQS1" + struct.pack("<IQHBBHBB", seq, index, len(vals), bits, flags, dec, gain, 7)
    crc = zlib.crc32(h + pay) ^ (1 if bad_crc else 0)
    return h + pay + struct.pack("<I", crc)


def vals(k, n=N):
    r = np.random.default_rng(k)
    return r.integers(-7, 8, size=(n, 2))


def iqsend(ffts=0, status=0):
    return f"IQSEND {status} 0 0 0 1000 0 0 0 0 0 {ffts} 0\n".encode()


class StreamTransport(FakeTransport):
    def __init__(self, stream: bytes):
        super().__init__()
        self.stream = stream

    def _handle(self, line):
        w = line.split()
        if w[0] == "IQS":
            self.sent.append(line)
            self._say(f"IQS 31250 {w[2]} {w[3]} 7 0 2402")
            self.out += self.stream
        elif w[0] == "FOFS":
            self.sent.append(line)
            self._say("OK")
        else:
            super()._handle(line)


def run(stream, **kw):
    t = StreamTransport(stream)
    d = Device(t, sync_timeout=0.3, reply_timeout=0.1, data_timeout=0.1)
    s = iqs.IqsSession(d, DEC, BITS, 2402, 0, **kw)
    blocks = [b for b, _ in s.blocks()]
    return s, blocks, t


def test_parse_roundtrip_and_conjugate():
    v = vals(1)
    f = iqs.parse_iqs1(frame(3, 1000, v))
    assert (f.seq, f.index, f.samples, f.bits, f.dec, f.shift) == (3, 1000, N, 8, DEC, 7)
    np.testing.assert_array_equal(f.iq, (v[:, 0] - 1j * v[:, 1]).astype(np.complex64))


@pytest.mark.parametrize("bits", [4, 8, 16])
def test_bit_widths(bits):
    v = vals(2)
    f = iqs.parse_iqs1(frame(0, 0, v, bits=bits))
    np.testing.assert_array_equal(f.iq, (v[:, 0] - 1j * v[:, 1]).astype(np.complex64))


def test_bad_crc_rejected():
    with pytest.raises(iqs.IqsError):
        iqs.parse_iqs1(frame(0, 0, vals(1), bad_crc=True))


def test_clean_stream_no_loss():
    data = b"".join(frame(i, i * N, vals(i)) for i in range(5)) + iqsend()
    s, blocks, t = run(data)
    assert len(blocks) == 5 and s.stats.samples == 5 * N
    assert s.stats.lost_samples == 0 and s.stats.loss_fraction == 0
    assert any(x.startswith("IQS 1000 512 8 6") for x in t.sent)


def test_dropped_frame_counted_exactly():
    fr = [frame(i, i * N, vals(i), flags=0) for i in range(6)]
    data = b"".join(fr[:2] + fr[3:]) + iqsend()  # frame 2 dropped
    s, blocks, _ = run(data)
    assert s.stats.gap_samples == N and s.stats.gap_events == 1
    assert s.stats.seq_gaps == 1
    assert s.stats.lost_samples == N
    assert s.stats.loss_fraction == pytest.approx(N / (6 * N))


def test_bad_crc_frame_counted_via_gap():
    fr = [frame(i, i * N, vals(i), bad_crc=(i == 2)) for i in range(5)]
    s, blocks, _ = run(b"".join(fr) + iqsend())
    assert s.stats.bad_crc == 1 and len(blocks) == 4
    assert s.stats.lost_samples == N


def test_bad_crc_last_frame_counted_as_tail():
    fr = [frame(i, i * N, vals(i), bad_crc=(i == 3)) for i in range(4)]
    s, _, _ = run(b"".join(fr) + iqsend())
    assert s.stats.tail_samples == N and s.stats.lost_samples == N


def test_index_jump_with_contiguous_seq():
    a = frame(0, 0, vals(0))
    b = frame(1, N + 37, vals(1))
    s, _, _ = run(a + b + iqsend())
    assert s.stats.gap_samples == 37 and s.stats.seq_gaps == 0


def test_firmware_loss_is_crosscheck_only():
    # index gap of 10 plus matching firmware report: counted once
    data = frame(0, 0, vals(0)) + frame(1, N + 10, vals(1)) + iqsend(ffts=10 * DEC)
    s, _, _ = run(data)
    assert s.stats.lost_samples == 10 and s.stats.crosscheck_warning is None
    # firmware says much more than the index shows: warn, loss unchanged
    data = frame(0, 0, vals(0)) + frame(1, N + 10, vals(1)) + iqsend(ffts=50 * DEC)
    s, _, _ = run(data)
    assert s.stats.lost_samples == 10 and s.stats.crosscheck_warning


def test_garbage_between_frames_resyncs():
    data = frame(0, 0, vals(0)) + b"\x01junkIQ" + frame(1, N, vals(1)) + iqsend()
    s, blocks, _ = run(data)
    assert len(blocks) == 2 and s.stats.lost_samples == 0 and s.stats.resync_bytes > 0


def test_truncated_stream_raises():
    with pytest.raises(TransferError):
        run(frame(0, 0, vals(0))[:-10])


def test_refused_combinations():
    d = Device(FakeTransport())
    for dec, bits in ((64, 8), (256, 8), (512, 16), (128, 4)):
        with pytest.raises(ValueError, match="link budget"):
            iqs.IqsSession(d, dec, bits, 2402)
    with pytest.raises(ValueError):
        iqs.IqsSession(d, 512, 8, 2402, rate_code=1)


def test_allowed_matches_doc():
    spec = {}
    for m in re.finditer(r"^ALLOWED rate=(\d+) bits=(\d+) dec=([\d,]+)$", DOC.read_text(), re.M):
        for dec in m.group(3).split(","):
            spec[(int(m.group(1)), int(dec), int(m.group(2)))] = True
    assert spec and spec == iqs.ALLOWED


def test_cli_stream_writes_sigmf(tmp_path, capsys):
    data = b"".join(frame(i, i * N + (20 if i >= 2 else 0), vals(i)) for i in range(4)) + iqsend()
    t = StreamTransport(data)
    base = tmp_path / "cap"
    rc = cli.main(["stream", "--freq", "2402", "--dec", "512", "--bits", "8", "--seconds", "1",
                   "-o", str(base)], device_factory=lambda port: Device(
                       t, sync_timeout=0.3, reply_timeout=0.1, data_timeout=0.1))
    assert rc == 0
    out = capsys.readouterr().out
    assert "lost 20.0 samples" in out
    meta = json.loads((tmp_path / "cap.sigmf-meta").read_text())
    assert meta["global"]["core:sample_count"] == 4 * N
    assert meta["global"]["core:sample_rate"] == 31250
    assert (tmp_path / "cap.sigmf-data").stat().st_size == 4 * N * 8
    assert any(a["esp32sdr:lost_samples"] == 20 for a in meta["annotations"])


def test_cli_records_frame_gain(tmp_path):
    data = b"".join(frame(i, i * N, vals(i), gain=40 + i) for i in range(3)) + iqsend()
    t = StreamTransport(data)
    cli.main(["stream", "--freq", "2402", "--seconds", "1", "-o", str(tmp_path / "g")],
             device_factory=lambda port: Device(
                 t, sync_timeout=0.3, reply_timeout=0.1, data_timeout=0.1))
    g = json.loads((tmp_path / "g.sigmf-meta").read_text())["global"]
    assert g["esp32sdr:gain_index"] == 40 and g["esp32sdr:gain_index_max"] == 42


def test_fofs_cleared_after_stream():
    data = b"".join(frame(i, i * N, vals(i)) for i in range(2)) + iqsend()
    t = StreamTransport(data)
    d = Device(t, sync_timeout=0.3, reply_timeout=0.1, data_timeout=0.1)
    s = iqs.IqsSession(d, DEC, BITS, 2402, 100)
    list(s.blocks())
    fofs = [x for x in t.sent if x.split()[0] == "FOFS"]
    assert [x.split()[1] for x in fofs] == ["100", "0"]


def test_no_fofs_reset_when_zero():
    s, _, t = run(b"".join(frame(i, i * N, vals(i)) for i in range(2)) + iqsend())
    assert [x for x in t.sent if x.split()[0] == "FOFS"] == [t.sent[[x.split()[0] for x in t.sent].index("FOFS")]]


def test_cli_refuses_bad_combo(capsys):
    rc = cli.main(["stream", "--freq", "2402", "--dec", "64", "--bits", "8", "-o", "/tmp/x"],
                  device_factory=lambda p: Device(FakeTransport()))
    assert rc == 1 and "link budget" in capsys.readouterr().err


class SomeTransport(StreamTransport):
    """Also offers read_some (like SerialTransport): a timeout loses nothing."""

    def read_some(self, n, timeout):
        if not self.out:
            raise TimeoutError("no data")
        b = bytes(self.out[:n])
        del self.out[:n]
        return b


def run_some(stream):
    t = SomeTransport(stream)
    d = Device(t, sync_timeout=0.3, reply_timeout=0.1, data_timeout=0.1)
    s = iqs.IqsSession(d, DEC, BITS, 2402, 0)
    return s, [b for b, _ in s.blocks()]


def test_frame_cut_short_by_iqsend_resyncs():
    # the 2026-11-05 bridge failure: a frame cut short (USB overflow / firmware
    # ending mid-frame) swallowed the IQSEND line and the read timed out
    cut = frame(1, N, vals(1))[:60]
    s, blocks = run_some(frame(0, 0, vals(0)) + cut + iqsend())
    assert len(blocks) == 1 and s.stats.short_frames == 1
    assert s.stats.end["status"] == 0


def test_frame_cut_short_mid_stream_continues():
    cut = frame(1, N, vals(1))[:150]
    data = frame(0, 0, vals(0)) + cut + frame(2, 2 * N, vals(2)) + iqsend()
    s, blocks = run_some(data)
    # the cut frame's header claims more bytes than arrived; frame 2 is inside
    # them, so the bad CRC + rescan path recovers it
    assert len(blocks) == 2 and s.stats.gap_samples == N
