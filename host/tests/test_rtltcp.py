# SPDX-License-Identifier: GPL-3.0-or-later
import socket
import struct
import threading
import time

import numpy as np
import pytest

from esp32sdr import cli, rtltcp
from esp32sdr.device import Device
from fake_device import FakeTransport
from test_iqs import BITS, DEC, N, frame, iqsend, vals


class LiveStream(FakeTransport):
    """Endless IQS stream generated on demand; a newline (STOP) ends it with IQSEND."""

    def __init__(self):
        super().__init__()
        self.streaming = False
        self.seq = 0
        self.iqs_cmds: list[str] = []
        self.lock = threading.Lock()

    def _handle(self, line):
        w = line.split()
        if w[0] == "IQS":
            self.sent.append(line)
            self.iqs_cmds.append(f"{self.freq} {self.fofs} {line}")
            self._say(f"IQS 31250 {w[2]} {w[3]} 7 0 2402")
            self.seq = 0
            self.streaming = True
        elif w[0] == "FOFS":
            self.sent.append(line)
            self.fofs = int(w[1])
            self._say("OK")
        else:
            super()._handle(line)

    fofs = 0

    def write(self, data):
        with self.lock:
            if data == b"\n" and self.streaming:
                self.streaming = False
                self.out += iqsend()
                return
            super().write(data)

    def _fill(self, n):
        deadline = time.time() + 2
        while len(self.out) < n:
            with self.lock:
                if self.streaming:
                    # sample value encodes the block number: I = seq % 100, Q = 0
                    v = np.stack([np.full(N, self.seq % 100), np.zeros(N, int)], 1)
                    self.out += frame(self.seq, self.seq * N, v)
                    self.seq += 1
                elif len(self.out) < n and time.time() > deadline:
                    raise TimeoutError("short read")
            time.sleep(0.001)

    def read_exact(self, n, timeout):
        self._fill(n)
        b = bytes(self.out[:n])
        del self.out[:n]
        return b

    def readline(self, timeout):
        deadline = time.time() + 2
        while b"\n" not in self.out:
            self._fill(len(self.out) + 1)
            if time.time() > deadline:
                raise TimeoutError
        i = self.out.index(b"\n")
        b = bytes(self.out[: i + 1])
        del self.out[: i + 1]
        return b


def recv_n(c, n):
    buf = b""
    while len(buf) < n:
        d = c.recv(n - len(buf))
        assert d, "connection closed"
        buf += d
    return buf


@pytest.fixture
def bridge():
    t = LiveStream()
    dev = Device(t, sync_timeout=0.3, reply_timeout=0.1, data_timeout=0.5)
    b = rtltcp.Bridge(dev, freq_hz=2402_000_000, dec=DEC, bits=BITS, port=0)
    th = threading.Thread(target=b.serve_forever, daemon=True)
    th.start()
    yield b, t
    b.close()
    th.join(timeout=3)


def connect(b):
    c = socket.create_connection(b.address, timeout=3)
    assert recv_n(c, 12) == b"RTL0" + struct.pack(">II", 5, 29)
    return c


def test_split_freq():
    assert rtltcp.split_freq(2402_000_000) == (2402, 0)
    assert rtltcp.split_freq(2402_300_000) == (2402, 300)
    assert rtltcp.split_freq(2402_700_000) == (2403, -300)


def test_to_u8_offset_binary():
    iq = np.array([0 + 0j, 127 - 128j, -3 + 5j], np.complex64)
    assert list(rtltcp.to_u8(iq, 8)) == [128, 128, 255, 0, 125, 133]
    assert list(rtltcp.to_u8(np.array([7 - 8j], np.complex64), 4)) == [240, 0]


def test_header_and_u8_stream(bridge):
    b, t = bridge
    c = connect(b)
    d = recv_n(c, 2 * N * 3)
    c.close()
    first = np.frombuffer(d, np.uint8).reshape(-1, 2)
    # frame k carries I=k, Q=0 -> offset binary 128+k, 128 (conjugation leaves Q=0)
    assert first[0].tolist() == [128, 128] and first[N].tolist() == [129, 128]
    assert first[2 * N].tolist() == [130, 128]
    assert t.iqs_cmds[0].startswith("2402 0 IQS 0 512 8 6")


def test_set_freq_retunes_and_restarts(bridge):
    b, t = bridge
    c = connect(b)
    recv_n(c, 2 * N)
    c.sendall(struct.pack(">BI", 0x02, 250000))  # sample rate: ignored
    c.sendall(struct.pack(">BI", 0x01, 2483_250_000))
    deadline = time.time() + 3
    while len(t.iqs_cmds) < 2 and time.time() < deadline:
        time.sleep(0.01)
    assert len(t.iqs_cmds) == 2
    assert t.iqs_cmds[1].startswith("2483 250 IQS 0 512 8 6")
    recv_n(c, 2 * N * 2)  # data flows again after the restart
    c.close()


def test_offset_added_to_requested_freq():
    t = LiveStream()
    dev = Device(t, sync_timeout=0.3, reply_timeout=0.1, data_timeout=0.5)
    b = rtltcp.Bridge(dev, freq_hz=2402_000_000, dec=DEC, bits=BITS, port=0,
                      offset_hz=2000_000_000)
    th = threading.Thread(target=b.serve_forever, daemon=True)
    th.start()
    try:
        c = connect(b)
        recv_n(c, 2 * N)
        c.sendall(struct.pack(">BI", 0x01, 480_000_000))  # gqrx hw freq for 2480 MHz
        deadline = time.time() + 3
        while len(t.iqs_cmds) < 2 and time.time() < deadline:
            time.sleep(0.01)
        assert t.iqs_cmds[1].startswith("2480 0 IQS")
        c.close()
    finally:
        b.close()
        th.join(timeout=3)


def test_out_of_range_freq_ignored(bridge):
    b, t = bridge
    c = connect(b)
    recv_n(c, 2 * N)
    c.sendall(struct.pack(">BI", 0x01, 100_000_000))
    time.sleep(0.2)
    recv_n(c, 2 * N)
    assert len(t.iqs_cmds) == 1
    c.close()


def test_reconnect_after_disconnect(bridge):
    b, t = bridge
    c = connect(b)
    recv_n(c, 2 * N)
    c.close()
    deadline = time.time() + 3
    while t.streaming and time.time() < deadline:
        time.sleep(0.01)
    assert not t.streaming  # stream was stopped
    c2 = connect(b)
    recv_n(c2, 2 * N)
    assert len(t.iqs_cmds) == 2
    c2.close()


def test_cli_bridge_registered_and_refuses_bad_combo(capsys):
    rc = cli.main(["bridge", "--listen", ":0", "--dec", "64"],
                  device_factory=lambda p: Device(FakeTransport()))
    assert rc == 1 and "link budget" in capsys.readouterr().err
    assert rtltcp.parse_listen(":1234") == ("127.0.0.1", 1234)
    assert rtltcp.parse_listen("0.0.0.0:99") == ("0.0.0.0", 99)


def wait_for(cond, timeout=3):
    deadline = time.time() + timeout
    while not cond() and time.time() < deadline:
        time.sleep(0.01)
    return cond()


def test_same_freq_does_not_restart(bridge):
    b, t = bridge
    c = connect(b)
    recv_n(c, 2 * N)
    c.sendall(struct.pack(">BI", 0x01, 2402_000_000))  # already tuned
    time.sleep(0.2)
    recv_n(c, 2 * N)
    assert len(t.iqs_cmds) == 1
    c.close()


def test_firmware_ending_mid_frame_restarts_stream(bridge):
    b, t = bridge
    c = connect(b)
    recv_n(c, 2 * N)
    with t.lock:  # firmware stops on its own, cutting the current frame short
        t.streaming = False
        v = np.stack([np.full(N, 1), np.zeros(N, int)], 1)
        t.out += frame(t.seq, t.seq * N, v)[:50] + iqsend(status=2)
    assert wait_for(lambda: len(t.iqs_cmds) >= 2)
    recv_n(c, 2 * N * 2)  # the client is still served
    c.close()


def test_rate_request_selects_interpolation(bridge):
    b, t = bridge
    c = connect(b)
    c.sendall(struct.pack(">BI", 0x02, 250000))  # SDR++'s lowest rate = 8 x 31250
    assert wait_for(lambda: b.interp == 8)
    recv_n(c, 2 * N * 8 * 3)
    c.close()
    assert rtltcp.interp_factor(31250, 31250) == 1
    assert rtltcp.interp_factor(2_400_000, 31250) == 1  # not a multiple
    assert rtltcp.interp_factor(250000, 31250) == 8


def test_upsampler_preserves_tone_and_continuity():
    fs, k, f0 = 31250, 8, 3000.0
    n = np.arange(4096)
    x = np.exp(2j * np.pi * f0 / fs * n).astype(np.complex64)
    up = rtltcp.Upsampler(k)
    y = np.concatenate([up(x[i:i + 512]) for i in range(0, x.size, 512)])
    assert y.size == x.size * k
    spec = np.abs(np.fft.fft(y[2048:2048 + 16384]))
    peak = np.fft.fftfreq(16384, 1 / (fs * k))[np.argmax(spec)]
    assert abs(peak - f0) < fs * k / 16384 * 1.5
    assert abs(np.abs(y[4000:30000]).mean() - 1) < 0.02  # unity gain, no block seams
