# SPDX-License-Identifier: GPL-3.0-or-later
import json
import socket
import struct
import time
from types import SimpleNamespace

import numpy as np

from esp32sdr import d8, d8_live
from esp32sdr.hopfollow import Commander, d8_channel_hz, D8_TABLE
from esp32sdr.d8follow import HopFollower
from esp32sdr.waterfall import ROW_HDR, RowMaker, Waterfall

FS = d8_live.FS


def one_bit_tone(f_hz, n, seed=0, snr_amp=3.0):
    rng = np.random.default_rng(seed)
    k = np.arange(n)
    y = snr_amp * np.exp(2j * np.pi * f_hz * k / FS) + rng.standard_normal(n) + 1j * rng.standard_normal(n)
    return d8.quantize(y, 1)


def feed_blocks(rm, iq, index=0, sizes=(1000, 4096, 333, 2250)):
    rows, i, k = [], 0, 0
    while i < len(iq):
        n = sizes[k % len(sizes)]
        rows += rm.feed(index + i, iq[i:i + n])
        i += n
        k += 1
    return rows


def test_base_rows_rate_and_tone_bin():
    rm = RowMaker(FS, rate=25, nfft=256)
    rm.enabled["base"] = True
    iq = one_bit_tone(50e3, int(FS))  # 1 s
    rows = feed_blocks(rm, iq, index=12345)
    assert len(rows) == 25 and all(v == "base" for v, *_ in rows)
    assert [s for _, s, _, _ in rows] == list(range(25))
    for _, _, t, row in rows:
        assert row.dtype == np.uint8 and len(row) == 256 and row.min() >= 1
        assert int(np.argmax(row)) == 128 + round(50e3 / FS * 256)
    assert abs(rows[1][2] - rows[0][2] - 0.04) < 1e-9


def test_noise_is_near_zero_db():
    rm = RowMaker(FS, rate=10, nfft=256, db_min=-10, db_max=25)
    rm.enabled["base"] = True
    rng = np.random.default_rng(1)
    iq = d8.quantize(rng.standard_normal(50_000) + 1j * rng.standard_normal(50_000), 1)
    _, _, _, row = feed_blocks(rm, iq)[0]
    db = (row.astype(float) - 1) / 254 * 35 - 10
    assert abs(np.median(db)) < 1.0


def test_disabled_does_nothing_and_gap_skips_rows():
    rm = RowMaker(FS, rate=25, nfft=256)
    assert rm.feed(0, np.ones(20000, np.complex64)) == []
    rm.enabled["base"] = True
    iq = one_bit_tone(0, 20000)
    a = rm.feed(0, iq)                      # 2 rows of 10000
    b = rm.feed(100_000, iq)                # after a gap: the open row is closed, empty rows skipped
    assert len(a) == 2
    assert [round(t * FS) for _, _, t, _ in b] == [110_000, 120_000]
    assert [s for _, s, _, _ in b] == [2, 3]


def test_hop_map_from_simulated_follow():
    from test_d8follow import SimBoard
    mhz = [d8_channel_hz(n) / 1e6 for n in D8_TABLE]
    rm = RowMaker(FS, rate=25, nfft=256, slots_mhz=mhz, bins_per_ch=16, default_slot=1)
    rm.enabled["hop"] = True
    b = SimBoard(ptx_s=0.42255 / 47)
    fol = HopFollower(Commander(b), period_s=0.42255 / 47)
    rows = []
    while b.idx < 2.0 * FS:
        f = b.frame()
        fol.feed(f)
        rows += rm.feed(f.index, f.iq, f.flags, f.shift)
    assert fol.mode == "locked"
    rows = [r for v, _, _, r in rows if v == "hop"]
    assert len(rows) == 50 and all(len(r) == 47 * 16 for r in rows)
    grid = np.array(rows[-25:]).reshape(25, 47, 16)       # last second, locked
    lit = (grid > 0).all(axis=2)                           # strip fully lit = channel visited in the row
    assert lit.sum(axis=0).min() >= 1                      # every channel visited in one second
    assert 2 <= lit.sum(axis=1).mean() <= 8                # ~4.4 hops per 40 ms row
    # x order is by frequency; the packet energy sits in the middle of each strip
    mid = grid[:, :, 6:10].astype(float)[lit].mean()
    edge = grid[:, :, [0, 15]].astype(float)[lit].mean()
    assert mid > edge + 20


def test_tap_is_inert_without_subscribers():
    wf = Waterfall(FS)
    f = SimpleNamespace(index=0, iq=np.ones(100, np.complex64), flags=0, shift=0)
    wf.tap(f)
    assert len(wf.q) == 0
    wf.active = True
    wf.tap(f)
    assert len(wf.q) == 1


def test_waterfall_websocket_end_to_end(tmp_path):
    web = d8_live.WebServer("127.0.0.1", 0, tmp_path).start()
    run = SimpleNamespace(center=2421.032)
    wf = Waterfall.for_run(run, FS).attach(web).start()
    try:
        with socket.create_connection(("127.0.0.1", web.port), timeout=5) as s:
            s.sendall(b"GET /wf?view=base HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                      b"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n")
            f = s.makefile("rb")
            head = b""
            while not head.endswith(b"\r\n\r\n"):
                head += f.read(1)
            assert b"101" in head

            def frame():
                b0, b1 = f.read(2)
                n = b1
                if n == 126:
                    n = struct.unpack("!H", f.read(2))[0]
                return b0, f.read(n)

            op, meta = frame()
            meta = json.loads(meta)
            assert op == 0x81 and meta["type"] == "wf_meta" and meta["view"] == "base"
            assert meta["width"] == 256 and meta["center_mhz"] == 2421.032 and meta["views"] == ["base"]
            deadline = time.monotonic() + 2
            while not wf.active and time.monotonic() < deadline:
                time.sleep(0.01)
            iq = one_bit_tone(-30e3, 30000)
            for i in range(0, 30000, 2500):
                wf.tap(SimpleNamespace(index=i, iq=iq[i:i + 2500], flags=0, shift=0))
            while True:
                op, data = frame()
                if op == 0x82:
                    break
            kind, _, w, seq, t = ROW_HDR.unpack(data[:ROW_HDR.size])
            row = np.frombuffer(data[ROW_HDR.size:], np.uint8)
            assert kind == 0 and w == 256 and seq == 0 and len(row) == 256
            assert int(np.argmax(row)) == 128 + round(-30e3 / FS * 256)
            s.sendall(bytes([0x88, 0x80, 0, 0, 0, 0]))
        deadline = time.monotonic() + 2
        while wf.active and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not wf.active
    finally:
        wf.stop()
        web.stop()
