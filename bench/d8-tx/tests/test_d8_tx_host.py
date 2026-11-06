import json, os, sys, tempfile, unittest
HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "host"))
import d8_vectors as v
import bench_runner as r

# Captured-E8 identity, counter 0 and 0x2F, all channels 2250 (0x8CA).
VEC0 = bytes.fromhex("11" "42b2" "00" "00" "01" "ca" "ca" "ca" "ca" "88" "88" "ca" "ca" "ca" "ca" "88" "88")


H = ("H,proto=3,mode=freq,fw=rxdiag-1,bf=MATEKF411RXDIAG,freq_req_khz=2421000,freq_set_hz=2421000000,"
     "freq_word=0x5D1745,freq_rb=0x5D1745,bw_hz=812000,agc2=251,agc1=64,foccfg=1D,fsctrl0=0,fsctrl1=0A,"
     "fscal3=0x0A,fscal2=0x0D,fscal1=0x20,fscal0=0x1F,cal_us=800,hz_per_lsb=1587,part=0x80,ver=0x03,"
     "spur=0,ant=1,lna=1,txen=0,spi_hz=1000000,window_us=100000,duration_ms=5000,t0_us=12345")


def slurp(d):
    with open(os.path.join(d, "log.jsonl")) as f:
        return f.read()


class Port:
    def __init__(self, lines=()):
        self.lines, self.out = list(lines), b""
    def write(self, b): self.out += b
    def readline(self): return (self.lines.pop(0) if self.lines else "").encode()


class T(unittest.TestCase):
    def test_vector_bytes(self):
        p = v.build(0)
        self.assertEqual(p[:18], VEC0)
        self.assertEqual(p[3:6], b"\x00\x00\x01")
        self.assertEqual(p[-2:], v.crc16(p[:18]).to_bytes(2, "big"))
        self.assertEqual(v.build(0x2F)[4], 0x2F)
        self.assertEqual(v.on_air(1)[:6], bytes.fromhex("aaaaaaaad391"))

    def test_matches_reference_decoder_if_available(self):
        sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "host"))
        try:
            from esp32sdr import d8
        except Exception:
            self.skipTest("esp32sdr unavailable")
        for c in (0, 1, 47, 255):
            ch = (2250, 0, 4095, 1, 0x123, 0xABC, 7, 2250)
            ref = d8.build_packet(counter=0, channels=ch, extra=(c, 1))
            self.assertEqual(v.build(c, ch), ref)

    def test_channel_roundtrip(self):
        ch = (0, 4095, 0x123, 0xABC, 1, 2, 3, 0x800)
        p = v.build(5, ch)
        got = [((p[h] >> s) & 0xF) << 8 | p[l] for l, (h, s) in zip(v.LOW, v.HIGH)]
        self.assertEqual(got, list(ch))
        with self.assertRaises(ValueError):
            v.build(0, (4096,) * 8)

    def test_reports(self):
        F = "F,3,100200,50,1,49,-3,-9,4,-2,-1587,-60,64,90,13,0"
        f = r.parse_report(F + "\r\n")
        self.assertTrue(f["carrier"]); self.assertEqual(f["fe_mean_hz"], -1587)
        nc = r.parse_report("F,0,5000,20,0,0,0,0,0,0,0,-90,0,0,1,16")
        self.assertFalse(nc["carrier"])
        x = r.parse_report("X,4,500000,done\n")
        self.assertEqual((x["seq"], x["reason"]), (4, "done"))
        self.assertEqual(r.parse_report(H)["freq_set_hz"], 2421000000)
        bad = ["", "\n", "PKT,freq_hz=1,len=1,data=00,crc=ok", "FREQ,freq_hz=1,offset_hz=2", "JUNK,a=1",
               F[:-2],                                   # truncated: last field missing
               F + ",1", "F,3,1,50,1,49,-3,-9,4,-2,-1587,-60,64,90,13",
               "F,0,5000,20,0,0,0,0,0,0,0,-90,0,0,1,8",    # ncs=0 but no-carrier flag clear
               "F,0,5000,20,0,3,0,0,0,0,0,-90,0,0,1,16",   # carrier but no-carrier flag set
               "F,0,5000,20,0,0,5,0,0,0,0,-90,0,0,1,16",   # no-carrier with nonzero estimate
               "F,0,5000,20,0,25,0,0,0,0,0,-90,0,0,1,0",    # ncs>n
               "F,0,5000,20,0,3,-3,-9,4,9,1,-60,64,90,13,0",  # mean outside min..max
               "F,0,5000,20,0,3,0,0,0,0,0,-90,0,0,1,32",   # flags out of range
               "F,0,5000,20,0,3,0,0,200,0,0,-90,0,0,1,0",   # int8 overflow
               "X,4,5", "X,4,5,bogus", "X,a,5,done", "X,4,5,done,extra",
               H[:-7], H.replace("proto=3", "proto=2"), H.replace("txen=0", "txen=1"),
               H.replace("fscal3=0x0A", "fscal3=0xa"), "H," + H[2:].replace("mode=freq,", "")]
        for b in bad:
            with self.assertRaises(r.ReportError, msg=b):
                r.parse_report(b)
        with self.assertRaises(r.ReportError):
            r.parse_report(F[:20] + "\x00" + F[20:])

    def run_with(self, d, lines, clock=None):
        port = Port(lines)
        run = r.Runner(port, os.path.join(d, "log.jsonl"), clock=clock or iter(range(1000)).__next__)
        self.addCleanup(run.log.close)
        return port, run

    def armed(self, run, **kw):
        a = dict(test="t1", max_duration_us=1000, max_abs_offset=100, max_power=50,
                 max_transitions=10, max_commands=3)
        a.update(kw)
        run.set_phase("esp32-test")
        run.authorize(r.Envelope(**a))

    def test_envelope_required_any_case(self):
        with tempfile.TemporaryDirectory() as d:
            port, run = self.run_with(d, [])
            for cmd in ("TONE 0 100 10", "tone 0 100 10", "ToNe 0 100 10", "  alt 1 2 100 500 10",
                        "ALT 1 2 100 500 10", "aLt\t1 2 100 500 10"):
                for phase in ("source-off", "esp32-test", "real-e8-control"):
                    run.set_phase(phase)
                    with self.assertRaises(r.EnvelopeError, msg=(cmd, phase)):
                        run.command(cmd)
            self.assertEqual(port.out, b"")
            with self.assertRaises(r.EnvelopeError):
                r.Envelope("x", 0, 0, 0, 0, 1).validate()
            with self.assertRaises(TypeError):
                r.Envelope("x", 1000, 1, 1)           # no defaults: all fields explicit
            with self.assertRaises(r.EnvelopeError):
                r.Envelope("", 1000, 1, 1, 1, 1).validate()
            run.set_phase("esp32-test")
            run.authorize(r.Envelope("t", 1000, 100, 50, 10, 1))
            run.set_phase("source-off")               # leaving phase clears the envelope
            run.set_phase("esp32-test")
            with self.assertRaises(r.EnvelopeError):
                run.command("TONE 0 100 10")

    def test_limits(self):
        with tempfile.TemporaryDirectory() as d:
            port, run = self.run_with(d, [])
            self.armed(run)
            over = ["TONE 0 1001 10",            # duration
                    "TONE 101 100 10", "TONE -101 100 10",   # offset
                    "TONE 0 100 51", "TONE 0 100",  # power (omitted = 127)
                    "ALT 0 101 100 500 10",
                    "ALT 0 5 40 500 10", "ALT 0 5 100 500",   # 12 transitions; omitted power
                    # firmware-invalid
                    "TONE 600 100", "TONE 0 49", "TONE 0 200001", "TONE 0 100 128", "TONE 0x1 100", "TONE +1 100 1",
                    "TONE 0 100 1 1", "TONE 0", "ALT 0 1 200 100", "ALT 0 1 10 100", "ALT 0 1 50 20000",
                    "PING x", "U 1", "FOO", "tx 1", "TONE 0 100 10\nTONE 0 100 10", "TONE 0 100 10\r",
                    "TONE 0 100 10 " + " " * 90, "TONE 0 100 10;U", ""]
            for c in over:
                with self.assertRaises((r.EnvelopeError, r.CommandError), msg=c):
                    run.command(c)
            self.assertEqual(port.out, b"")
            # firmware-exact line length boundary: 95 chars parse, 96 do not
            ok95 = "TONE 0 100 10" + " " * (95 - 13)
            self.assertEqual(r.parse_esp_command(ok95)["kind"], "TONE")
            with self.assertRaises(r.CommandError):
                r.parse_esp_command(ok95 + " ")
            # 255 transition firmware limit holds even for a permissive envelope
            with self.assertRaises(r.CommandError):
                r.parse_esp_command("ALT 0 1 50 12800")
            self.assertEqual(r.parse_esp_command("ALT 0 1 50 12750")["transitions"], 255)

    def test_budget_and_ok_path(self):
        K = "K,tone,5,5,0,100,10,100,100,12345,100,00000100,00000100,00000000,00000000,00000000,0"
        with tempfile.TemporaryDirectory() as d:
            port, run = self.run_with(d, [K + "\n", "OK\n", K + "\n", "OK\n"])
            self.armed(run, max_commands=1)
            rep = run.command("TONE 5 100 10")
            self.assertTrue(rep.ok); self.assertTrue(rep.records["unkeyed"])
            with self.assertRaises(r.EnvelopeError):   # budget used
                run.command("TONE 5 100 10")
            self.assertEqual(port.out, b"TONE 5 100 10\n")

    def test_multiline(self):
        T = ["T,0,100,101,00000101", "T,1,200,202,00000102"]
        K = "K,alt,1,2,100,250,10,250,240,1,2,00000100,00000100,00000000,00000000,00000000,2"
        with tempfile.TemporaryDirectory() as d:
            lines = ["I,ready,b8=00000000\n", K + "\r\n"] + [t + "\n" for t in T] + ["OK\n",
                     "P,d8tone,1\n", "OK\n", "S,keyed=0,b8=00000000,a8=00000000\n", "OK\n", "OK\n"]
            port, run = self.run_with(d, lines)
            self.armed(run, max_commands=5)
            rep = run.command("ALT 1 2 100 250 10")
            self.assertEqual(rep.lines, [K] + T); self.assertEqual(rep.records["ntrans"], 2)
            self.assertEqual(run.command("PING").lines, ["P,d8tone,1"])
            self.assertEqual(run.command("stat").records["keyed"], 0)
            self.assertTrue(run.command("U").ok)
            self.assertEqual(port.lines, [])           # every line consumed, none left for next cmd
            log = [json.loads(x) for x in slurp(d).splitlines()]
            self.assertEqual(sum(e["event"] == "reply_line" for e in log), 10)
            self.assertTrue(all("t" in e for e in log))

    def test_err_reply(self):
        with tempfile.TemporaryDirectory() as d:
            port, run = self.run_with(d, ["ERR cmd\n"])
            rep = run.command("PING")
            self.assertFalse(rep.ok); self.assertEqual(rep.error, "ERR cmd")

    def test_stuck_key_and_overrun_fail_with_unkey(self):
        K = "K,tone,5,5,0,100,10,%d,100,12345,100,00000100,00000100,%s,00000000,00000000,0"
        # on_us tolerance: [req, req+ON_US_OVERRUN_MAX_US] (firmware spins to >= dur; slack is jitter)
        cases = [(K % (100, "00040100"), r.UnkeyError),                       # bit18 set after unkey
                 (K % (100 + r.ON_US_OVERRUN_MAX_US + 1, "00000100"), r.DurationError),
                 (K % (99, "00000100"), r.DurationError),                     # impossibly short
                 (K % (5000, "00000100"), r.DurationError)]
        for k, exc in cases:
            with tempfile.TemporaryDirectory() as d:
                port, run = self.run_with(d, [k + "\n", "OK\n"])
                self.armed(run)
                with self.assertRaises(exc, msg=k):
                    run.command("TONE 5 100 10")
                self.assertTrue(port.out.endswith(b"U\n"))
        for on in (100, 100 + r.ON_US_OVERRUN_MAX_US):                        # boundaries pass
            with tempfile.TemporaryDirectory() as d:
                port, run = self.run_with(d, [K % (on, "00000100") + "\n", "OK\n"])
                self.armed(run)
                self.assertTrue(run.command("TONE 5 100 10").ok)
                self.assertEqual(port.out, b"TONE 5 100 10\n")

    def test_bad_replies(self):
        K = "K,alt,1,2,100,250,10,250,240,1,2,00000100,00000100,00000000,00000000,00000000,2"
        cases = [
            [K + "\n", "T,0,1,1,00000001\n", "OK\n"],                        # fewer T than ntrans
            [K + "\n", "T,0,1,1,00000001\n", "T,1,1,1,00000001\n", "T,2,1,1,00000001\n", "OK\n"],
            [K.replace("alt", "tone") + "\n", "OK\n"],                         # mode mismatch
            [K.replace(",250,10,", ",251,10,") + "\n", "OK\n"],                # echo mismatch
            ["garbage\n", "OK\n"], ["OK\n"],
        ]
        for c in cases:
            with tempfile.TemporaryDirectory() as d:
                port, run = self.run_with(d, list(c))
                self.armed(run)
                with self.assertRaises(r.ResponseError, msg=c):
                    run.command("ALT 1 2 100 250 10")
                self.assertTrue(port.out.endswith(b"U\n"))   # auto-unkey after bad keying reply
        with tempfile.TemporaryDirectory() as d:
            port, run = self.run_with(d, ["P,d8tone,1\n", "P,d8tone,1\n", "OK\n"])
            with self.assertRaises(r.ResponseError):
                run.command("PING")
        with tempfile.TemporaryDirectory() as d:
            port, run = self.run_with(d, ["I,boot,reason=3\n"])
            with self.assertRaises(r.ResponseError):
                run.command("PING")

    def test_timeout(self):
        with tempfile.TemporaryDirectory() as d:
            t = [0.0]
            def clock():
                t[0] += 0.5
                return t[0]
            port, run = self.run_with(d, ["P,d8tone,1\n"], clock=clock)   # no OK ever
            with self.assertRaises(r.ResponseTimeout):
                run.command("PING", timeout_s=2)
            port, run = self.run_with(d, ["P,d8t"], clock=clock)           # partial line then silence
            with self.assertRaises(r.ResponseTimeout):
                run.command("PING", timeout_s=2)
            port, run = self.run_with(d, [], clock=clock)                  # keying timeout sends unkey
            self.armed(run)
            with self.assertRaises(r.ResponseTimeout):
                run.command("TONE 0 100 10")
            self.assertTrue(port.out.endswith(b"U\n"))
            self.assertIn('"event": "timeout"', slurp(d))

    def test_read_report(self):
        with tempfile.TemporaryDirectory() as d:
            port, run = self.run_with(d, ["X,1,2,done\r\n", "X,1,2,done", "", "F,1\n"])
            self.assertEqual(run.read_report()["reason"], "done")
            for _ in range(3):
                with self.assertRaises(r.ReportError):
                    run.read_report()
            self.assertIn("bad_report", slurp(d))


if __name__ == "__main__":
    unittest.main()
