"""D8 hop table, channel frequencies and data-packet build/parse (pure host, no I/O).

Layout matches the measured E8 stream (see d8_vectors.py): byte 3 = 0, byte 4 = packet counter,
byte 5 = 1. NOTE esp32sdr.d8.build_packet and Betaflight read the counter at byte 3 (BF telemetry
slot test packet[3]%4) -- pass counter_index=3 for that layout; default 4 is the E8's.
"""
LENGTH = 0x11
PACKET_BYTES = 20
N_CHANNELS = 47
BASE_HZ = 2404.000e6
STEP_HZ = 299.93e3
E8_ID = (0x42, 0xB2)
_LOW = (6, 7, 8, 9, 12, 13, 14, 15)
_HIGH = ((10, 0), (10, 4), (11, 0), (11, 4), (16, 0), (16, 4), (17, 0), (17, 4))


def table(start=2, step=55, n=N_CHANNELS):
    """Entry 0 is channel 0; entry k>=1 is (start + step*k) & 0xFF (E8: start 2, step 55)."""
    return [0] + [(start + step * k) & 0xFF for k in range(1, n)]


def channel_hz(n):
    return BASE_HZ + n * STEP_HZ


def channel_khz(n):
    return int(round(channel_hz(n) / 1e3))


def crc16(data):
    c = 0xFFFF
    for b in data:
        c ^= b << 8
        for _ in range(8):
            c = ((c << 1) ^ 0x8005) & 0xFFFF if c & 0x8000 else (c << 1) & 0xFFFF
    return c


def us_to_raw(us):
    return (us * 3 + 1) // 2  # round half up, same as firmware d8_us_to_raw


def raw_to_us(raw):
    return raw / 1.5


def build(counter, channels=(2250,) * 8, tx_id=E8_ID, counter_index=4):
    """20 bytes: length + 17 payload + CRC16 big endian. channels = raw 12-bit values."""
    if len(channels) != 8 or any(not 0 <= v <= 0xFFF for v in channels):
        raise ValueError("need 8 raw 12-bit channels")
    p = bytearray(18)
    p[0] = LENGTH
    p[1], p[2] = tx_id
    if counter_index == 4:
        p[3], p[4], p[5] = 0, counter & 0xFF, 1
    elif counter_index == 3:
        p[3], p[4], p[5] = counter & 0xFF, 1, 0
    else:
        raise ValueError("counter_index 3 or 4")
    for v, lo, (hi, sh) in zip(channels, _LOW, _HIGH):
        p[lo] = v & 0xFF
        p[hi] |= (v >> 8) << sh
    c = crc16(p)
    return bytes(p) + bytes([c >> 8, c & 0xFF])


def parse(raw, counter_index=4):
    """dict(crc_ok, tx_id, counter, channels) or None if too short / wrong length byte."""
    raw = bytes(raw)
    if len(raw) < PACKET_BYTES or raw[0] != LENGTH:
        return None
    ok = crc16(raw[:18]) == (raw[18] << 8 | raw[19])
    ch = [((raw[hi] >> sh) & 0xF) << 8 | raw[lo] for lo, (hi, sh) in zip(_LOW, _HIGH)]
    return dict(crc_ok=ok, tx_id=(raw[1], raw[2]), counter=raw[counter_index], channels=ch)
