import struct
from d8tx import BetaflightMSP
from d8tx.msp import frame, MSP_RC, MSP_STATUS, MSP_ANALOG


def reply(cmd, payload):
    f = frame(cmd, payload)
    body = f[3:]
    c = 0
    for b in body[:-1]:
        c ^= b
    return b"$M>" + body


class FakeFC:
    def __init__(self):
        self.buf = b""
        stat = struct.pack("<HHHIBHH", 100, 0, 0, 1, 0, 5, 0) + bytes([0]) + bytes([26]) + struct.pack("<I", 1 << 2) + b"\0"
        self.data = {MSP_RC: struct.pack("<8H", *range(1000, 1800, 100)),
                     MSP_STATUS: stat,
                     MSP_ANALOG: struct.pack("<BHHhH", 0, 0, 77, 0, 0)}

    def write(self, b):
        self.buf += reply(b[4], self.data[b[4]])

    def read(self, n=1):
        d, self.buf = self.buf[:n], self.buf[n:]
        return d

    def close(self): pass


def test_msp():
    m = BetaflightMSP("x", serial_obj=FakeFC())
    assert m.rc() == list(range(1000, 1800, 100))
    s = m.status()
    assert s["armed"] and s["failsafe"] and s["arming_disable"] == ["RX_FAILSAFE"]
    assert m.rssi() == 77
