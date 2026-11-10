"""Independent D8 packet builder and reference vectors (no import of esp32sdr.d8).

Frame: length(0x11) + 17 payload bytes + CRC16 big endian.
Payload indices from the length byte: [1,2] tx id, [3]=0, [4]=hop counter,
[5]=1, channels 12-bit: low bytes at 6,7,8,9,12,13,14,15; high nibbles in
10 (ch0 low nibble, ch1 high), 11 (ch2,ch3), 16 (ch4,ch5), 17 (ch6,ch7).
On air: AA AA AA AA, D3 91, then the frame.
"""
PREAMBLE = bytes([0xAA] * 4)
SYNC = bytes([0xD3, 0x91])
LENGTH = 0x11
E8_ID = (0x42, 0xB2)
LOW = (6, 7, 8, 9, 12, 13, 14, 15)
HIGH = ((10, 0), (10, 4), (11, 0), (11, 4), (16, 0), (16, 4), (17, 0), (17, 4))


def crc16(data):
    c = 0xFFFF
    for b in data:
        for i in range(7, -1, -1):
            bit = (b >> i) & 1
            top = (c >> 15) & 1
            c = (c << 1) & 0xFFFF
            if top ^ bit:
                c ^= 0x8005
    return c


def build(counter, channels=(2250,) * 8, tx_id=E8_ID):
    if len(channels) != 8 or any(not 0 <= v <= 0xFFF for v in channels):
        raise ValueError("need 8 channels of 12 bits")
    p = bytearray(18)
    p[0] = LENGTH
    p[1], p[2] = tx_id
    p[3] = 0
    p[4] = counter & 0xFF
    p[5] = 1
    for v, lo, (hi, sh) in zip(channels, LOW, HIGH):
        p[lo] = v & 0xFF
        p[hi] |= (v >> 8) << sh
    c = crc16(p)
    return bytes(p) + bytes([c >> 8, c & 0xFF])


def on_air(counter, **kw):
    return PREAMBLE + SYNC + build(counter, **kw)
