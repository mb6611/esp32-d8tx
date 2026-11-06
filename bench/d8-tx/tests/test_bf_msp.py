import os, sys, io, struct, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "host"))
import bf_msp as m


def reply(cmd, payload):
    body = bytes([len(payload), cmd]) + payload
    c = 0
    for b in body:
        c ^= b
    return b"$M>" + body + bytes([c])


class Fake:
    def __init__(self, replies):
        self.buf, self.out, self.replies = b"", b"", replies
    def write(self, b):
        self.out += b
        self.buf += self.replies[b[4]]
    def read(self, n):
        r, self.buf = self.buf[:n], self.buf[n:]
        return r


STATUS = struct.pack("<HHHIBHH", 125, 0, 1, 0, 0, 5, 0) + b"\x00" + b"\x1a" + struct.pack("<I", 1 << 2) + b"\x00"
REPL = {105: reply(105, struct.pack("<4H", 1200, 1400, 1600, 1800)),
        110: reply(110, struct.pack("<BHHhH", 0, 0, 77, 0, 0)),
        101: reply(101, STATUS)}


class T(unittest.TestCase):
    def test_frame(self):
        self.assertEqual(m.frame(105), b"$M<\x00\x69\x69")
    def test_sample(self):
        s = m.sample(Fake(REPL))
        self.assertEqual(s["rc"], [1200, 1400, 1600, 1800])
        self.assertEqual(s["analog"]["rssi"], 77)
        self.assertTrue(s["status"]["rx_failsafe"])
        self.assertIn("RX_FAILSAFE", m.row(s))
    def test_bad_checksum(self):
        bad = bytearray(REPL[105]); bad[-1] ^= 1
        with self.assertRaises(ValueError):
            m.request(Fake({105: bytes(bad)}), 105)
    def test_timeout(self):
        with self.assertRaises(TimeoutError):
            m.read_frame(Fake({}), 0.05)
    def test_watch(self):
        o = io.StringIO()
        m.watch(Fake(REPL), o, 0.05, 0.01)
        self.assertIn("rc=1200,1400,1600,1800", o.getvalue())

    def test_fast(self):
        o = io.StringIO()
        m.fast(Fake(REPL), o, 0.1, 100)
        L = o.getvalue().splitlines()
        self.assertEqual(L[0], "t_send,t_recv,rtt_ms,rc")
        self.assertGreaterEqual(len(L), 8)
        self.assertTrue(L[1].endswith(",1200,1400,1600,1800"))
    def test_fast_err(self):
        o = io.StringIO()
        m.fast(Fake({105: b""}), o, 0.02, 50)
        self.assertIn("ERR", o.getvalue())

if __name__ == "__main__":
    unittest.main()
