import os, sys, tempfile, unittest
HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "host"))
import d8_vectors as v
import bench_runner as r

VEC = v.build(0)
HEX18 = VEC[:18].hex()
HEX20 = VEC.hex()
KOK = ("K,pkt,bits=208,pwr=32,on_us=6700,key_cycles=900,unkey_cycles=300,max_late_ns=400,late_bits=12,"
       "b8_on=00040000,b8_end=00040000,b8_off=00000000,a8_on=00000001,a8_off=00000000")


class Port:
    def __init__(self, lines=()):
        self.lines, self.out = list(lines), b""
    def write(self, b): self.out += b
    def readline(self): return (self.lines.pop(0) if self.lines else "").encode()


def env(**kw):
    d = dict(test="t", max_duration_us=10000, max_abs_offset=1, max_power=32, max_transitions=0,
             max_commands=5, max_packets=2)
    d.update(kw)
    return r.Envelope(**d)


def prec(data=VEC, n=None, rssi=-40, lqi=50, crc=1):
    n = len(data) if n is None else n
    return "P,0,1234,%d,%s,%d,%d,%d" % (n, data.hex().upper(), rssi, lqi, crc)


class Cmd(unittest.TestCase):
    def test_parse(self):
        for t in ("PKT " + HEX18 + " 32", "pkt " + HEX20.upper(), "Pkt\t" + HEX18):
            c = r.parse_esp_command(t)
            self.assertEqual(c["kind"], "PKT")
        self.assertEqual(r.parse_esp_command("PKT " + HEX18)["pwr"], 127)
        self.assertEqual(r.parse_esp_command("PKT " + HEX18 + " 5")["pwr"], 5)

    def test_bad(self):
        for t in ("PKT", "PKT 11", "PKT " + HEX18[:-2], "PKT " + HEX18 + "00" * 3, "PKT " + "zz" * 18,
                  "PKT 12" + HEX18[2:], "PKT " + HEX18 + " 128", "PKT " + HEX18 + " -1",
                  "PKT " + HEX18 + " 1 2"):
            with self.assertRaises(r.CommandError, msg=t):
                r.parse_esp_command(t)


class Run(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.p = Port()
        self.run_ = r.Runner(self.p, os.path.join(self.d, "l.jsonl"))

    def cmd(self, pwr=32):
        return "PKT %s %d" % (HEX18, pwr)

    def test_needs_phase_and_envelope(self):
        with self.assertRaises(r.EnvelopeError):
            self.run_.command(self.cmd())
        self.run_.set_phase("esp32-test")
        with self.assertRaises(r.EnvelopeError):
            self.run_.command(self.cmd())
        self.run_.authorize(env(max_packets=0))
        with self.assertRaises(r.EnvelopeError):
            self.run_.command(self.cmd())
        self.assertEqual(self.p.out, b"")

    def test_power_cap_and_default_power(self):
        self.run_.set_phase("esp32-test")
        self.run_.authorize(env())
        with self.assertRaises(r.EnvelopeError):
            self.run_.command(self.cmd(33))
        with self.assertRaises(r.EnvelopeError):
            self.run_.command("PKT " + HEX18)  # omitted = 127
        self.assertEqual(self.p.out, b"")

    def test_budget_exhaustion(self):
        self.run_.set_phase("esp32-test")
        self.run_.authorize(env())
        for _ in range(2):
            self.p.lines = [KOK + "\n", "OK\n"]
            rep = self.run_.command(self.cmd())
            self.assertTrue(rep.ok)
            self.assertEqual(rep.records["on_us"], 6700)
        out = self.p.out
        with self.assertRaises(r.EnvelopeError):
            self.run_.command(self.cmd().lower())
        self.assertEqual(self.p.out, out)

    def test_validate_envelope(self):
        with self.assertRaises(r.EnvelopeError):
            env(max_duration_us=6000).validate()
        with self.assertRaises(r.EnvelopeError):
            env(max_packets=-1).validate()
        env(max_duration_us=6000, max_packets=0).validate()

    def test_err_reply(self):
        self.run_.set_phase("esp32-test")
        self.run_.authorize(env())
        self.p.lines = ["ERR packet\n"]
        rep = self.run_.command(self.cmd())
        self.assertFalse(rep.ok)

    def bad(self, kline, exc):
        self.run_.set_phase("esp32-test")
        self.run_.authorize(env())
        self.p.lines = [kline + "\n", "OK\n"] if kline else ["OK\n"]
        with self.assertRaises(exc):
            self.run_.command(self.cmd())
        self.assertTrue(self.p.out.endswith(b"U\n"), self.p.out)

    def test_bad_k_replies_autounkey(self):
        self.bad(KOK.replace("b8_off=00000000", "b8_off=00040000"), r.UnkeyError)
        self.setUp(); self.bad(KOK.replace("on_us=6700", "on_us=6699"), r.DurationError)
        self.setUp(); self.bad(KOK.replace("on_us=6700", "on_us=6801"), r.DurationError)
        self.setUp(); self.bad(KOK.replace("max_late_ns=400", "max_late_ns=99999"), r.DurationError)
        self.setUp(); self.bad(KOK.replace("key_cycles=900", "key_cycles=999999"), r.DurationError)
        self.setUp(); self.bad(KOK.replace("pwr=32", "pwr=31"), r.ResponseError)
        self.setUp(); self.bad(KOK.replace("bits=208", "bits=200"), r.ResponseError)
        self.setUp(); self.bad(KOK.replace("late_bits=12", "late_bits=209"), r.ResponseError)
        self.setUp(); self.bad(KOK[:-9], r.ResponseError)  # truncated
        self.setUp(); self.bad(KOK + ",x=1", r.ResponseError)
        self.setUp(); self.bad(KOK.replace("K,pkt", "K,tone"), r.ResponseError)
        self.setUp(); self.bad("", r.ResponseError)

    def test_extra_line(self):
        self.run_.set_phase("esp32-test")
        self.run_.authorize(env())
        self.p.lines = [KOK + "\n", "T,0,1,2,00000000\n", "OK\n"]
        with self.assertRaises(r.ResponseError):
            self.run_.command(self.cmd())


class Stm(unittest.TestCase):
    H = ("H,proto=4,mode=pkt,fw=rxdiag-1,bf=MATEKF411RXDIAG,freq_req_khz=2412000,freq_set_hz=2412000000,"
         "freq_word=0x5CEC4E,freq_rb=0x5CEC4E,chan=0,hop=0,cfg_rb_ok=1,bw_hz=135416,sync=0xD391,"
         "mdmcfg4=0xAA,fscal3=0xA9,cal_us=800,part=0x80,ver=0x03,spur=0,ant=1,lna=1,txen=0,"
         "spi_hz=1000000,quiet_us=500,duration_ms=5000,t0_us=100")

    def test_p_good(self):
        p = r.parse_pkt_record(prec() + "\n")
        self.assertEqual((p["seq"], p["t_us"], p["len"], p["rssi"], p["lqi"], p["crc_ok"]),
                         (0, 1234, 20, -40, 50, 1))
        self.assertTrue(p["whole"])
        self.assertEqual(p["data"], VEC)
        self.assertEqual(r.parse_pkt_record(prec(rssi=0, lqi=0, crc=0))["crc_ok"], 0)
        self.assertEqual(r.parse_pkt_record(prec(VEC[:7], rssi=0, lqi=0, crc=0).replace("1234", "9"))["whole"], False)

    def test_p_bad(self):
        good = prec()
        parts = good.split(",")
        def mod(i, val):
            q = list(parts); q[i] = val; return ",".join(q)
        bads = [good[:-2], good + ",1", "P," + ",".join(parts[1:6]),
                mod(3, "19"), mod(3, "21"), mod(3, "0"), mod(4, parts[4].lower()), mod(4, parts[4][:-1]),
                mod(4, "ZZ" * 20), mod(5, "128"), mod(5, "-129"), mod(5, "abc"), mod(5, ""),
                mod(6, "128"), mod(7, "2"), mod(7, "-1"), mod(1, "-1"), mod(1, "01"), mod(2, "x"),
                prec(VEC[:7], rssi=-3, lqi=0, crc=0), prec(VEC[:7], rssi=0, lqi=0, crc=1), "", "p," + good[2:], "Q,1"]
        for b in bads:
            with self.assertRaises(r.ReportError, msg=b):
                r.parse_pkt_record(b)

    def test_e_x(self):
        e = r.parse_pkt_record("E,500,EPART,seq=0;exp=20;got=7")
        self.assertEqual((e["code"], e["t_us"]), ("EPART", 500))
        for b in ("E,5,EBOGUS,x", "E,5,EOVF", "E,x,EOVF,-", "E,5,epart,-", "E,5,EOVF,", "E,5,EOVF,a,b"):
            with self.assertRaises(r.ReportError, msg=b):
                r.parse_pkt_record(b)
        x = r.parse_pkt_record("X,3,9000,done")
        self.assertEqual((x["seq"], x["reason"]), (3, "done"))
        for b in ("X,3,9000", "X,3,9000,Done", "X,3,9000,bye", "X,3,9000,done,1", "X,a,1,done"):
            with self.assertRaises(r.ReportError, msg=b):
                r.parse_pkt_record(b)

    def test_h(self):
        h = r.parse_pkt_record(self.H)
        self.assertEqual((h["freq_req_khz"], h["freq_word"], h["part"]), (2412000, 0x5CEC4E, 0x80))
        self.assertEqual(h["bf"], "MATEKF411RXDIAG")
        for b in (self.H.replace("proto=4", "proto=3"), self.H.replace("mode=pkt", "mode=freq"),
                  self.H.replace("txen=0", "txen=1"), self.H.replace(",t0_us=100", ""),
                  self.H[:-6], self.H + ",t0_us=1", self.H.replace("sync=0xD391", "sync=0x0000"),
                  self.H.replace("spur=0", "spur=x"), "H"):
            with self.assertRaises(r.ReportError, msg=b):
                r.parse_pkt_record(b)

    def test_non_ascii_and_bytes(self):
        self.assertEqual(r.parse_pkt_record(prec().encode() + b"\r\n")["seq"], 0)
        with self.assertRaises(r.ReportError):
            r.parse_pkt_record(b"P,\xff")


class Compare(unittest.TestCase):
    def test_pass(self):
        p = r.parse_pkt_record(prec())
        for vec in (VEC, VEC[:18]):
            c = r.compare_p_to_vector(p, vec)
            self.assertTrue(c["ok"], c)
            self.assertEqual(c["diffs"], [])

    def test_real_18_byte(self):
        line = "P,2,170120487,18,1142B2000001CACACACA8888CACACACA8888,12,51,1"
        p = r.parse_pkt_record(line)
        body = bytes.fromhex("1142B2000001CACACACA8888CACACACA8888")
        self.assertEqual(len(body), 18)
        for vec in (body, body + bytes([v.crc16(body) >> 8, v.crc16(body) & 255])):
            c = r.compare_p_to_vector(p, vec)
            self.assertTrue(c["ok"], c)
        c = r.compare_p_to_vector(r.parse_pkt_record(line[:-1] + "0"), body)
        self.assertEqual(c["diffs"], ["crc_ok: got 0 want 1"])
        other = bytearray(body); other[4] ^= 1
        c = r.compare_p_to_vector(p, bytes(other))
        self.assertIn("byte 4 (hop_counter): got 00 want 01", c["diffs"])
        # 20-byte vector with wrong CRC is rejected
        c = r.compare_p_to_vector(p, body + b"\x00\x00")
        self.assertFalse(c["ok"])
        self.assertIn("vector crc mismatch", c["diffs"][0])

    def test_diffs(self):
        bad = bytearray(VEC); bad[4] ^= 0xFF; bad[19] ^= 1
        p = r.parse_pkt_record(prec(bytes(bad), crc=0))
        c = r.compare_p_to_vector(p, VEC)
        self.assertFalse(c["ok"])
        self.assertFalse(c["bytes_equal"])
        txt = "\n".join(c["diffs"])
        self.assertIn("byte 4 (hop_counter)", txt)
        self.assertIn("byte 19 (crc_lo)", txt)
        self.assertIn("crc_ok: got 0 want 1", txt)

    def test_crc_flag_only(self):
        c = r.compare_p_to_vector(r.parse_pkt_record(prec(crc=0)), VEC)
        self.assertEqual(c["diffs"], ["crc_ok: got 0 want 1"])
        self.assertTrue(c["bytes_equal"])

    def test_partial(self):
        p = r.parse_pkt_record(prec(VEC[:7], rssi=0, lqi=0, crc=0))
        c = r.compare_p_to_vector(p, VEC)
        self.assertFalse(c["ok"])
        self.assertIn("len: got 7 want 18", c["diffs"])
        self.assertIn("byte 7 (payload[7]): got missing want %02X" % VEC[7], c["diffs"])

    def test_bad_inputs(self):
        with self.assertRaises(ValueError):
            r.compare_p_to_vector(r.parse_pkt_record(prec()), VEC[:5])
        with self.assertRaises(ValueError):
            r.compare_p_to_vector({"kind": "E"}, VEC)


if __name__ == "__main__":
    unittest.main()
