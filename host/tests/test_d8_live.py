# SPDX-License-Identifier: GPL-3.0-or-later
import json
import socket
import time

import numpy as np

from esp32sdr import d8, d8_live


def test_live_decoder_synthetic_stream_locks_and_decodes_all():
    rng = np.random.default_rng(3)
    pk = [d8.build_packet(counter=0, extra=((47 * i) & 0xFF, 1), channels=rng.integers(1400, 2300, 8))
          for i in range(6)]
    air = d8.AIR_BITS / d8.BAUD
    iq, fs, starts = d8.synth(pk, [0.1] + [d8_live.CYCLE_S - air - 1e-4] * 5, amp=5, noise=0.3,
                              bits=1, dec=64, seed=4)
    assert fs == d8_live.FS
    tail = rng.choice([-1, 1], (2, int(0.05 * fs)))  # the stream goes on past the last packet
    iq = np.concatenate([iq, (tail[0] + 1j * tail[1]).astype(np.complex64)])
    ld = d8_live.LiveDecoder(fs)
    got, modes, i = [], [], 1000  # arbitrary absolute start index
    off = i
    for n in rng.integers(300, 4096, 10_000):
        if i - off >= len(iq):
            break
        blk = iq[i - off : i - off + n]
        res = ld.feed(i, blk)
        got += res
        modes += [ld.mode] * len(res)
        i += len(blk)
    ok = [r for r in got if r.packet.crc_ok]
    assert [r.packet.raw for r in ok] == pk
    for r, s in zip(ok, starts):
        assert abs(r.t - off / fs - s) < 2 / d8.BAUD
    assert modes[-1] == "locked"
    assert ld.decoded_samples < 0.5 * len(iq)  # the gate skips most of the stream


def test_live_decoder_zero_fills_gaps():
    ld = d8_live.LiveDecoder(d8_live.FS)
    ld.feed(100, np.ones(10, np.complex64))
    ld.feed(115, np.ones(5, np.complex64))
    assert ld.base == 100 and ld.end == 120 and ld.buf[12] == 0


def test_ws_accept_rfc6455_example():
    assert d8_live.ws_accept("dGhlIHNhbXBsZSBub25jZQ==") == "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="


def test_web_server_static_and_websocket(tmp_path):
    (tmp_path / "index.html").write_text("<h1>hi</h1>")
    web = d8_live.WebServer("127.0.0.1", 0, tmp_path).start()
    try:
        with socket.create_connection(("127.0.0.1", web.port), timeout=5) as s:
            s.sendall(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")
            data = b""
            while chunk := s.recv(4096):
                data += chunk
        assert data.startswith(b"HTTP/1.1 200") and data.endswith(b"<h1>hi</h1>")

        web.publish({"type": "stats", "n": 1})  # cached and replayed to a new client
        time.sleep(0.1)
        with socket.create_connection(("127.0.0.1", web.port), timeout=5) as s:
            s.sendall(b"GET /ws HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                      b"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n")
            f = s.makefile("rb")
            head = b""
            while not head.endswith(b"\r\n\r\n"):
                head += f.read(1)
            assert b"101" in head and b"s3pPLMBiTxaQ9kYGzzhZRbK+xOo=" in head

            def frame():
                b0, b1 = f.read(2)
                assert b0 == 0x81 and b1 < 126
                return json.loads(f.read(b1))

            assert frame() == {"type": "stats", "n": 1}
            web.publish({"type": "packet", "counter": 7})
            assert frame() == {"type": "packet", "counter": 7}
            s.sendall(bytes([0x88, 0x80, 0, 0, 0, 0]))  # masked close
    finally:
        web.stop()
