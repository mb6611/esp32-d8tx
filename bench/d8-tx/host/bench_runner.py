"""Serial bench runner: timestamped logs, phase labels, strict report/reply grammar.

Grammars are copied from the real emitters (read-only references):
  STM  bench/cc2500-rxdiag/firmware/overlay/src/main/rx/rxdiag_core.c (proto=3 freq mode):
    H,proto=3,mode=freq,fw=..,bf=..,freq_req_khz=..,...,t0_us=N      (<=480 body chars)
    F,seq,t_us,n,rej,ncs,fe_last,fe_min,fe_max,fe_mean_raw,fe_mean_hz,rssi_max_raw,
      pktstatus_last,lqi,marc,flags                                    (<=96 body chars)
      flags bit4 (16) = no carrier (ncs==0; then fe_* and means are 0)
    X,seq,t_us,done|host|radio|usb|usbstall
  ESP  bench/d8-tx/firmware/main/{cmd_parse.c,d8tone.c}: PING STAT U TONE ALT, each reply
    ends with "OK" or "ERR <why>"; TONE/ALT reply is K,... then ntrans T,... lines then OK.
The ESP firmware matches commands case-sensitively; the host treats any case of
TONE/ALT as keying and refuses everything outside the known command set.
"""
import json
import re
import time
from dataclasses import dataclass

PHASES = ("source-off", "real-e8-control", "esp32-test")

# Mirrors of cmd_parse.h
TONE_F_MAX = 511
TONE_DUR_MAX_US = 200000
TONE_DUR_MIN_US = 50
ALT_HALF_MIN_US = 50
ALT_MAX_TRANS = 255
PWR_MAX = 127
ESP_LINE_MAX = 95          # char line[96]: more than 95 chars -> "ERR long"
ESP_MAX_TOKENS = 8
SAFE_COMMANDS = ("PING", "STAT", "U")
RF_COMMANDS = ("TONE", "ALT", "PKT")
PKT_BODY_BYTES = 18        # length + 17 payload; firmware appends CRC16
PKT_FULL_BYTES = 20        # full U3 vector, CRC verbatim
PKT_AIR_BITS = 208         # 26 air bytes (D8_AIR_BITS)
PKT_DUR_US = 6700          # 208 * 7731 cycles / 240 MHz (on_us floor, integer division)
PKT_OFFSET = 1             # firmware keys f=+1 / f=-1
NOCARRIER_FLAG = 16


class ReportError(ValueError):
    pass


class EnvelopeError(RuntimeError):
    pass


class CommandError(ValueError):
    pass


class ResponseError(RuntimeError):
    pass


class UnkeyError(ResponseError):
    """K report shows the tone still keyed (b8_off bit18) after unkey."""


class DurationError(ResponseError):
    """K report on_us is not within [requested, requested + ON_US_OVERRUN_MAX_US]."""


class ResponseTimeout(ResponseError):
    pass


@dataclass(frozen=True)
class Envelope:
    """Explicit per-test limits; every field is mandatory (no defaults)."""
    test: str
    max_duration_us: int      # per keying command (dur_us)
    max_abs_offset: int       # |f| in tone step units, <= 511
    max_power: int            # PBUS value 0..127; omitted power counts as 127
    max_transitions: int      # ALT dur_us // half_us, <= 255
    max_commands: int         # number of keying commands allowed under this envelope
    max_packets: int = 0      # PKT budget; 0 (default) forbids PKT

    def validate(self):
        ints = (self.max_duration_us, self.max_abs_offset, self.max_power,
                self.max_transitions, self.max_commands, self.max_packets)
        if not self.test or not isinstance(self.test, str):
            raise EnvelopeError("envelope needs a test name")
        if any(isinstance(i, bool) or not isinstance(i, int) for i in ints):
            raise EnvelopeError("envelope fields must be integers")
        if not (TONE_DUR_MIN_US <= self.max_duration_us <= TONE_DUR_MAX_US):
            raise EnvelopeError("max_duration_us must be %d..%d" % (TONE_DUR_MIN_US, TONE_DUR_MAX_US))
        if not (0 <= self.max_abs_offset <= TONE_F_MAX):
            raise EnvelopeError("max_abs_offset must be 0..%d" % TONE_F_MAX)
        if not (0 <= self.max_power <= PWR_MAX):
            raise EnvelopeError("max_power must be 0..%d" % PWR_MAX)
        if not (0 <= self.max_transitions <= ALT_MAX_TRANS):
            raise EnvelopeError("max_transitions must be 0..%d" % ALT_MAX_TRANS)
        if self.max_commands < 1:
            raise EnvelopeError("max_commands must be >= 1")
        if self.max_packets < 0:
            raise EnvelopeError("max_packets must be >= 0")
        if self.max_packets and self.max_duration_us < PKT_DUR_US:
            raise EnvelopeError("max_packets>0 needs max_duration_us >= %d" % PKT_DUR_US)


# ---------------------------------------------------------------- STM reports

STM_EXIT_REASONS = ("done", "host", "radio", "usb", "usbstall")
_UINT = r"\d+"
_INT = r"-?\d+"
_HEX = lambda n: r"0x[0-9A-F]{%d}" % n
# (key, regex) in the exact emission order of the proto=3 H line
_H_FIELDS = (
    ("proto", r"3"), ("mode", r"freq"), ("fw", r"[^,=\s]+"), ("bf", r"[^,=\s]+"),
    ("freq_req_khz", _UINT), ("freq_set_hz", _UINT), ("freq_word", _HEX(6)), ("freq_rb", _HEX(6)),
    ("bw_hz", _UINT), ("agc2", _UINT), ("agc1", _UINT), ("foccfg", r"1D"), ("fsctrl0", r"0"),
    ("fsctrl1", r"0A"), ("fscal3", _HEX(2)), ("fscal2", _HEX(2)), ("fscal1", _HEX(2)),
    ("fscal0", _HEX(2)), ("cal_us", _UINT), ("hz_per_lsb", r"1587"), ("part", _HEX(2)),
    ("ver", _HEX(2)), ("spur", r"[01]"), ("ant", r"1"), ("lna", r"1"), ("txen", r"0"),
    ("spi_hz", _UINT), ("window_us", _UINT), ("duration_ms", _UINT), ("t0_us", _UINT),
)
_F_NAMES = ("seq", "t_us", "n", "rej", "ncs", "fe_last", "fe_min", "fe_max", "fe_mean_raw",
            "fe_mean_hz", "rssi_max_raw", "pktstatus_last", "lqi", "marc", "flags")
_F_SIGNED = {"fe_last", "fe_min", "fe_max", "fe_mean_raw", "fe_mean_hz", "rssi_max_raw"}


def _strip_eol(line):
    if isinstance(line, bytes):
        try:
            line = line.decode("ascii")
        except UnicodeDecodeError:
            raise ReportError("non-ascii report")
    if line.endswith("\r\n"):
        line = line[:-2]
    elif line.endswith("\n"):
        line = line[:-1]
    if not line or not all(32 <= ord(c) < 127 for c in line):
        raise ReportError("empty or non-printable report: %r" % line)
    return line


def parse_report(line):
    """Parse one STM H/F/X line strictly; anything else raises ReportError."""
    line = _strip_eol(line)
    kind = line[0]
    if kind == "H":
        if len(line) > 480:
            raise ReportError("H line too long")
        parts = line.split(",")
        if parts[0] != "H" or len(parts) - 1 != len(_H_FIELDS):
            raise ReportError("H: wrong field count")
        out = {"kind": "H"}
        for part, (key, pat) in zip(parts[1:], _H_FIELDS):
            k, eq, v = part.partition("=")
            if not eq or k != key or not re.fullmatch(pat, v):
                raise ReportError("H: bad field %r (want %s)" % (part, key))
            out[key] = int(v, 16) if v.startswith("0x") else (int(v) if re.fullmatch(_INT, v) else v)
        return out
    if len(line) > 96:
        raise ReportError("record too long")
    parts = line.split(",")
    if kind == "F":
        if parts[0] != "F" or len(parts) != 1 + len(_F_NAMES):
            raise ReportError("F: wrong field count")
        out = {"kind": "F"}
        for name, v in zip(_F_NAMES, parts[1:]):
            if not re.fullmatch(_INT if name in _F_SIGNED else _UINT, v) or (v.startswith("0") and len(v) > 1) \
                    or v.startswith("-0") or len(v) > 11:
                raise ReportError("F: bad %s=%r" % (name, v))
            out[name] = int(v)
        for n in ("fe_last", "fe_min", "fe_max", "rssi_max_raw"):
            if not -128 <= out[n] <= 127:
                raise ReportError("F: %s out of int8 range" % n)
        for n in ("pktstatus_last", "lqi", "marc"):
            if out[n] > 255:
                raise ReportError("F: %s out of byte range" % n)
        if out["flags"] > 31:
            raise ReportError("F: flags out of range")
        if out["n"] < 1 or out["rej"] > out["n"] or out["ncs"] > out["n"]:
            raise ReportError("F: inconsistent counts")
        nocarrier = bool(out["flags"] & NOCARRIER_FLAG)
        if nocarrier != (out["ncs"] == 0):
            raise ReportError("F: no-carrier flag disagrees with ncs")
        if out["ncs"] == 0:
            if any(out[n] for n in ("fe_last", "fe_min", "fe_max", "fe_mean_raw", "fe_mean_hz")):
                raise ReportError("F: no-carrier window must report zero estimates")
        elif not (out["fe_min"] <= out["fe_last"] <= out["fe_max"]
                  and out["fe_min"] <= out["fe_mean_raw"] <= out["fe_max"]):
            raise ReportError("F: freq estimate ordering violated")
        out["carrier"] = not nocarrier
        return out
    if kind == "X":
        if parts[0] != "X" or len(parts) != 4:
            raise ReportError("X: wrong field count")
        for v in parts[1:3]:
            if not re.fullmatch(_UINT, v):
                raise ReportError("X: bad number %r" % v)
        if parts[3] not in STM_EXIT_REASONS:
            raise ReportError("X: unknown reason %r" % parts[3])
        return {"kind": "X", "seq": int(parts[1]), "t_us": int(parts[2]), "reason": parts[3]}
    raise ReportError("unknown report: %r" % line)


# ---------------------------------------------------------------- ESP commands



def _num(tok, lo, hi, what):
    # strtol accepts leading +/-; the host accepts only plain decimal ASCII digits
    if not re.fullmatch(r"-?[0-9]+", tok):
        raise CommandError("%s: not a decimal integer: %r" % (what, tok))
    v = int(tok)
    if not lo <= v <= hi:
        raise CommandError("%s=%d outside %d..%d" % (what, v, lo, hi))
    return v


def parse_esp_command(text):
    """Validate one ESP command line against cmd_parse.c semantics (case-insensitive verb).

    Returns dict(kind=PING|STAT|U|TONE|ALT, ...). Raises CommandError for anything the
    firmware would reject, anything overlong, and any unknown verb."""
    if not isinstance(text, str):
        raise CommandError("command must be str")
    if not text or not all(32 <= ord(c) < 127 or c == "\t" for c in text):
        raise CommandError("empty or control/non-ASCII characters in command")
    if len(text) > ESP_LINE_MAX:
        raise CommandError("command longer than %d chars" % ESP_LINE_MAX)
    tok = text.replace("\t", " ").split()
    if not tok:
        raise CommandError("empty command")
    if len(tok) > ESP_MAX_TOKENS:
        raise CommandError("too many tokens")
    verb = tok[0].upper()
    if verb in SAFE_COMMANDS:
        if len(tok) != 1:
            raise CommandError("%s takes no arguments" % verb)
        return {"kind": verb}
    if verb == "PKT":
        if not 2 <= len(tok) <= 3:
            raise CommandError("PKT hex [pwr]")
        h = tok[1]
        if len(h) not in (2 * PKT_BODY_BYTES, 2 * PKT_FULL_BYTES) or not re.fullmatch(r"[0-9a-fA-F]+", h):
            raise CommandError("PKT needs 36 or 40 hex digits")
        pkt = bytes.fromhex(h)
        if pkt[0] != 0x11:
            raise CommandError("PKT length byte must be 0x11")
        pwr = _num(tok[2], 0, PWR_MAX, "pwr") if len(tok) == 3 else PWR_MAX
        return {"kind": "PKT", "f_a": -PKT_OFFSET, "f_b": PKT_OFFSET, "half_us": 0, "dur_us": PKT_DUR_US,
                "pwr": pwr, "transitions": 0, "packet": pkt}
    if verb == "TONE":
        if not 3 <= len(tok) <= 4:
            raise CommandError("TONE f dur_us [pwr]")
        f = _num(tok[1], -TONE_F_MAX, TONE_F_MAX, "freq")
        dur = _num(tok[2], TONE_DUR_MIN_US, TONE_DUR_MAX_US, "dur")
        pwr = _num(tok[3], 0, PWR_MAX, "pwr") if len(tok) == 4 else PWR_MAX
        return {"kind": "TONE", "f_a": f, "f_b": f, "half_us": 0, "dur_us": dur, "pwr": pwr,
                "transitions": 0}
    if verb == "ALT":
        if not 5 <= len(tok) <= 6:
            raise CommandError("ALT fa fb half_us dur_us [pwr]")
        fa = _num(tok[1], -TONE_F_MAX, TONE_F_MAX, "freq")
        fb = _num(tok[2], -TONE_F_MAX, TONE_F_MAX, "freq")
        half = _num(tok[3], ALT_HALF_MIN_US, TONE_DUR_MAX_US, "half")
        dur = _num(tok[4], TONE_DUR_MIN_US, TONE_DUR_MAX_US, "dur")
        if half > dur:
            raise CommandError("half>dur")
        if dur // half > ALT_MAX_TRANS:
            raise CommandError("transitions %d > %d" % (dur // half, ALT_MAX_TRANS))
        pwr = _num(tok[5], 0, PWR_MAX, "pwr") if len(tok) == 6 else PWR_MAX
        return {"kind": "ALT", "f_a": fa, "f_b": fb, "half_us": half, "dur_us": dur, "pwr": pwr,
                "transitions": dur // half}
    raise CommandError("unknown ESP command %r (allowed: PING STAT U TONE ALT PKT)" % tok[0])


def check_envelope(cmd, env):
    """Raise EnvelopeError unless the parsed keying command fits the envelope."""
    if env.max_commands < 1:
        raise EnvelopeError("envelope command budget exhausted")
    if cmd["kind"] == "PKT" and env.max_packets < 1:
        raise EnvelopeError("envelope packet budget exhausted (max_packets=%d)" % env.max_packets)
    if cmd["dur_us"] > env.max_duration_us:
        raise EnvelopeError("dur_us %d > envelope %d" % (cmd["dur_us"], env.max_duration_us))
    if max(abs(cmd["f_a"]), abs(cmd["f_b"])) > env.max_abs_offset:
        raise EnvelopeError("offset exceeds envelope %d" % env.max_abs_offset)
    if cmd["pwr"] > env.max_power:
        raise EnvelopeError("power %d > envelope %d (omitted power = %d)" % (cmd["pwr"], env.max_power, PWR_MAX))
    if cmd["transitions"] > env.max_transitions:
        raise EnvelopeError("transitions %d > envelope %d" % (cmd["transitions"], env.max_transitions))


# ---------------------------------------------------------------- ESP replies

# Firmware (d8tone.c run_window) spins until cyc()-t0 >= dur, then reports (u0-t0)/240 where u0 is
# taken right after that loop (before unkey()). So on_us >= requested always (integer division of
# >= dur cycles), and the excess is only loop/ALT tone_set latency inside a critical section:
# a few us. Key/unkey overhead is outside on_us (reported separately as key_cyc/unkey_cyc).
# Allow 100 us of slack; beyond that the window overran (RF on longer than authorised) = failure.
ON_US_OVERRUN_MAX_US = 100

_H8 = r"[0-9a-f]{8}"
_K_RE = re.compile(r"K,(tone|alt),(-?\d+),(-?\d+),(\d+),(\d+),(\d+),(\d+),(-?\d+),(\d+),(\d+),"
                   r"(%s),(%s),(%s),(%s),(%s),(\d+)\Z" % ((_H8,) * 5))
_T_RE = re.compile(r"T,(\d+),(\d+),(\d+),(%s)\Z" % _H8)
_S_RE = re.compile(r"S,keyed=([01]),b8=(%s),a8=(%s)\Z" % (_H8, _H8))
_ERR_RE = re.compile(r"ERR [A-Za-z0-9<>_-]+\Z")


@dataclass
class Reply:
    command: str
    lines: list
    ok: bool
    error: str = None
    records: dict = None


def _check_reply(cmd, lines):
    """lines: all lines up to and excluding the terminal OK/ERR line. Returns records."""
    kind = cmd["kind"]
    if kind == "U":
        if lines:
            raise ResponseError("U: unexpected lines %r" % lines)
        return {}
    if kind == "PING":
        if lines != ["P,d8tone,1"]:
            raise ResponseError("PING: bad reply %r" % lines)
        return {}
    if kind == "STAT":
        m = len(lines) == 1 and _S_RE.match(lines[0])
        if not m:
            raise ResponseError("STAT: bad reply %r" % lines)
        return {"keyed": int(m.group(1)), "b8": int(m.group(2), 16), "a8": int(m.group(3), 16)}
    if kind == "PKT":
        return check_pkt_reply(cmd, lines)
    m = _K_RE.match(lines[0]) if lines else None
    if not m:
        raise ResponseError("%s: missing/bad K line: %r" % (kind, lines[:1]))
    g = m.groups()
    mode = g[0]
    nums = [int(x) for x in g[1:7]]          # fa fb half req pwr on_us
    exp = [cmd["f_a"], cmd["f_b"], cmd["half_us"], cmd["dur_us"], cmd["pwr"]]
    if mode != kind.lower() or nums[:5] != exp:
        raise ResponseError("K line does not echo the command: %r" % lines[0])
    ntrans = int(g[-1])
    if ntrans > ALT_MAX_TRANS or (kind == "TONE" and ntrans) or len(lines) - 1 != ntrans:
        raise ResponseError("K ntrans=%d disagrees with %d T lines" % (ntrans, len(lines) - 1))
    for i, t in enumerate(lines[1:]):
        tm = _T_RE.match(t)
        if not tm or int(tm.group(1)) != i:
            raise ResponseError("bad T line %r" % t)
    b8_off = int(g[12], 16)
    if b8_off & (1 << 18):
        raise UnkeyError("K b8_off=%08x has bit18 set: tone still keyed after unkey" % b8_off)
    on_us, req = nums[5], cmd["dur_us"]
    if not req <= on_us <= req + ON_US_OVERRUN_MAX_US:
        raise DurationError("K on_us=%d outside [%d, %d] for requested %d us"
                            % (on_us, req, req + ON_US_OVERRUN_MAX_US, req))
    return {"mode": mode, "ntrans": ntrans, "on_us": nums[5], "b8_off": b8_off,
            "unkeyed": not (b8_off & (1 << 18))}


PKT_KEY_CYC_MAX = 48000        # 200 us at 240 MHz: key overhead before the first bit
PKT_UNKEY_CYC_MAX = 48000
PKT_MAX_LATE_NS_MAX = 5000     # worst bit-edge lateness; a bit is ~32200 ns
_PKT_K_RE = re.compile(
    r"K,pkt,bits=(\d+),pwr=(\d+),on_us=(\d+),key_cycles=(\d+),unkey_cycles=(\d+),max_late_ns=(\d+),"
    r"late_bits=(\d+),b8_on=(%s),b8_end=(%s),b8_off=(%s),a8_on=(%s),a8_off=(%s)\Z" % ((_H8,) * 5))


def check_pkt_reply(cmd, lines):
    """Validate the single K,pkt line (lines excludes OK). Raises ResponseError subclasses."""
    m = _PKT_K_RE.match(lines[0]) if len(lines) == 1 else None
    if not m:
        raise ResponseError("PKT: bad/missing single K,pkt line: %r" % (lines,))
    g = m.groups()
    bits, pwr, on_us, key_c, unkey_c, late_ns, late_bits = (int(x) for x in g[:7])
    b8_on, b8_end, b8_off, a8_on, a8_off = (int(x, 16) for x in g[7:])
    if bits != PKT_AIR_BITS or pwr != cmd["pwr"]:
        raise ResponseError("K,pkt bits/pwr do not echo command: bits=%d pwr=%d" % (bits, pwr))
    if b8_off & (1 << 18):
        raise UnkeyError("K,pkt b8_off=%08x has bit18 set: still keyed after unkey" % b8_off)
    if not PKT_DUR_US <= on_us <= PKT_DUR_US + ON_US_OVERRUN_MAX_US:
        raise DurationError("K,pkt on_us=%d outside [%d, %d]" % (on_us, PKT_DUR_US, PKT_DUR_US + ON_US_OVERRUN_MAX_US))
    if key_c > PKT_KEY_CYC_MAX or unkey_c > PKT_UNKEY_CYC_MAX:
        raise DurationError("K,pkt key/unkey cycles too large: %d/%d" % (key_c, unkey_c))
    if late_ns > PKT_MAX_LATE_NS_MAX:
        raise DurationError("K,pkt max_late_ns=%d > %d" % (late_ns, PKT_MAX_LATE_NS_MAX))
    if late_bits > bits:
        raise ResponseError("K,pkt late_bits=%d > bits" % late_bits)
    return {"mode": "pkt", "on_us": on_us, "key_cycles": key_c, "unkey_cycles": unkey_c,
            "max_late_ns": late_ns, "late_bits": late_bits, "b8_off": b8_off,
            "unkeyed": True}


# ------------------------------------------------- STM proto=4 (rxdiag pkt) records

_PKT_H_REQUIRED = ("fw", "bf", "freq_req_khz", "freq_set_hz", "freq_word", "freq_rb", "bw_hz", "cal_us",
                   "part", "ver", "spur", "quiet_us", "duration_ms", "t0_us")
_PKT_H_FIXED = {"proto": "4", "mode": "pkt", "chan": "0", "hop": "0", "cfg_rb_ok": "1", "sync": "0xD391",
                "ant": "1", "lna": "1", "txen": "0"}
PKT_E_CODES = ("ECFG", "EFIFO", "EGDO", "EMOTOR", "ENOCHIP", "ENOSAMP", "EOVF", "EPART", "ESTATE", "ECAL")
P_MAX = 240


def _uint(tok, what, hi=None):
    if not re.fullmatch(r"0|[1-9][0-9]{0,10}", tok):
        raise ReportError("%s: bad unsigned %r" % (what, tok))
    v = int(tok)
    if hi is not None and v > hi:
        raise ReportError("%s=%d > %d" % (what, v, hi))
    return v


def parse_pkt_record(line):
    """Strictly parse one `rxdiag pkt` line: H (proto=4), P, E or X. Anything else raises ReportError.

    P,seq,t_us,len,<UPPERCASE hex>,rssi,lqi,crc_ok -> dict(kind='P', seq, t_us, len, data(bytes),
    rssi (signed), lqi (0..127), crc_ok (0/1), whole (len 18 or 20)). len must equal the hex byte count;
    a partial FIFO is len<18 with rssi=lqi=crc_ok=0 (preceded by an E,EPART)."""
    line = _strip_eol(line)
    if len(line) > P_MAX + 240:
        raise ReportError("record too long")
    parts = line.split(",")
    kind = parts[0]
    if kind == "P":
        if len(parts) != 8:
            raise ReportError("P: wrong field count %d" % len(parts))
        seq, t_us = _uint(parts[1], "seq"), _uint(parts[2], "t_us")
        n = _uint(parts[3], "len", 64)
        hx = parts[4]
        if n < 1 or not re.fullmatch(r"(?:[0-9A-F]{2})+", hx) or len(hx) != 2 * n:
            raise ReportError("P: hex %r does not match len=%d (uppercase hex only)" % (hx, n))
        if not re.fullmatch(r"-?[0-9]+", parts[5]) or parts[5].startswith("-0") or \
                (parts[5][0:1] == "0" and len(parts[5]) > 1):
            raise ReportError("P: bad rssi %r" % parts[5])
        rssi = int(parts[5])
        if not -128 <= rssi <= 127:
            raise ReportError("P: rssi out of int8 range")
        lqi, crc = _uint(parts[6], "lqi", 127), _uint(parts[7], "crc_ok", 1)
        if n < PKT_BODY_BYTES and (rssi or lqi or crc):
            raise ReportError("P: partial record must have rssi=lqi=crc_ok=0")
        return {"kind": "P", "seq": seq, "t_us": t_us, "len": n, "data": bytes.fromhex(hx),
                "rssi": rssi, "lqi": lqi, "crc_ok": crc, "whole": n in (PKT_BODY_BYTES, PKT_FULL_BYTES)}
    if kind == "E":
        if len(parts) != 4:
            raise ReportError("E: wrong field count")
        if parts[2] not in PKT_E_CODES:
            raise ReportError("E: unknown code %r" % parts[2])
        if not parts[3]:
            raise ReportError("E: empty detail")
        return {"kind": "E", "t_us": _uint(parts[1], "t_us"), "code": parts[2], "detail": parts[3]}
    if kind == "X":
        if len(parts) != 4:
            raise ReportError("X: wrong field count")
        if parts[3] not in STM_EXIT_REASONS:
            raise ReportError("X: unknown reason %r" % parts[3])
        return {"kind": "X", "seq": _uint(parts[1], "seq"), "t_us": _uint(parts[2], "t_us"),
                "reason": parts[3]}
    if kind == "H":
        kv = {}
        for p in parts[1:]:
            k, eq, v = p.partition("=")
            if not eq or not k or not v or k in kv:
                raise ReportError("H: bad/duplicate field %r" % p)
            kv[k] = v
        for k, want in _PKT_H_FIXED.items():
            if kv.get(k) != want:
                raise ReportError("H: %s must be %s (got %r) - not a proto=4 pkt header" % (k, want, kv.get(k)))
        for k in _PKT_H_REQUIRED:
            if k not in kv:
                raise ReportError("H: missing %s" % k)
        for k in ("freq_req_khz", "freq_set_hz", "bw_hz", "cal_us", "spur", "quiet_us", "duration_ms", "t0_us"):
            _uint(kv[k], k)
        out = {"kind": "H"}
        out.update({k: (int(v, 16) if v.startswith("0x") else int(v) if v.isdigit() else v)
                    for k, v in kv.items()})
        return out
    raise ReportError("unknown pkt record: %r" % line)


def compare_p_to_vector(p, vector):
    """Compare a parsed P record to a U3 vector (bytes of 18 or 20).

    Real rxdiag P records are 18 bytes (length + 17 payload): the CC2500 strips the CRC and reports
    crc_ok separately. The 18-byte body is compared to the vector body and crc_ok must be 1. A 20-byte
    P record is accepted only if the vector's own CRC16 matches too (then CRC bytes are compared).
    Returns dict(ok, diffs) with field-by-field diffs: length, named byte positions, crc_ok."""
    from d8_vectors import crc16
    vec = bytes(vector)
    if len(vec) not in (PKT_BODY_BYTES, PKT_FULL_BYTES):
        raise ValueError("vector must be 18 or 20 bytes")
    if p.get("kind") != "P":
        raise ValueError("need a parsed P record")
    c = crc16(vec[:PKT_BODY_BYTES])
    crc_bytes = bytes([c >> 8, c & 0xFF])
    diffs = []
    if len(vec) == PKT_FULL_BYTES and vec[PKT_BODY_BYTES:] != crc_bytes:
        diffs.append("vector crc mismatch: has %s want %s" % (vec[PKT_BODY_BYTES:].hex(), crc_bytes.hex()))
    got = p["data"]
    want = vec[:PKT_BODY_BYTES] + (crc_bytes if p["len"] == PKT_FULL_BYTES else b"")
    names = {0: "length", 1: "id0", 2: "id1", 3: "zero", 4: "hop_counter", 5: "one",
             18: "crc_hi", 19: "crc_lo"}
    if p["len"] != len(want):
        diffs.append("len: got %d want %d" % (p["len"], len(want)))
    for i in range(max(len(got), len(want))):
        g = got[i] if i < len(got) else None
        w = want[i] if i < len(want) else None
        if g != w:
            nm = names.get(i, "payload[%d]" % i)
            diffs.append("byte %d (%s): got %s want %s" % (
                i, nm, "missing" if g is None else "%02X" % g, "extra" if w is None else "%02X" % w))
    if p["crc_ok"] != 1:
        diffs.append("crc_ok: got %d want 1" % p["crc_ok"])
    return {"ok": not diffs, "diffs": diffs, "bytes_equal": got == want,
            "crc_ok": p["crc_ok"], "rssi": p["rssi"], "lqi": p["lqi"]}


class Runner:
    def __init__(self, port, log_path, clock=time.time, reply_timeout_s=2.0):
        """port: object with write(bytes) and readline()->bytes (b'' or partial on timeout)."""
        self.port, self.clock = port, clock
        self.reply_timeout_s = reply_timeout_s
        self.log = open(log_path, "a")
        self.phase = None
        self.envelope = None

    def _rec(self, **kw):
        kw["t"] = self.clock()
        kw["phase"] = self.phase
        self.log.write(json.dumps(kw, default=lambda b: b.hex()) + "\n")
        self.log.flush()

    def set_phase(self, phase):
        if phase not in PHASES:
            raise ValueError("phase must be one of %s" % (PHASES,))
        self.phase = phase
        if phase != "esp32-test":
            self.envelope = None
        self._rec(event="phase")

    def authorize(self, envelope):
        envelope.validate()
        self.envelope = envelope
        self._rec(event="envelope", envelope=envelope.__dict__)

    def command(self, text, *, timeout_s=None):
        """Send one ESP32 command and consume its complete reply through OK/ERR.

        Every command is parsed against the firmware grammar first; TONE/ALT in any
        letter case need phase esp32-test and an envelope that covers them."""
        try:
            cmd = parse_esp_command(text)
        except CommandError as e:
            self._rec(event="refused", text=text, error=str(e))
            raise
        keying = cmd["kind"] in RF_COMMANDS
        if keying:
            try:
                if self.envelope is None or self.phase != "esp32-test":
                    raise EnvelopeError("RF command %r needs esp32-test phase and an explicit envelope" % text)
                check_envelope(cmd, self.envelope)
            except EnvelopeError as e:
                self._rec(event="refused", text=text, error=str(e))
                raise
            self.envelope = _replace_budget(self.envelope, cmd)
        if timeout_s is None:
            timeout_s = self.reply_timeout_s + (cmd["dur_us"] / 1e6 if keying else 0)
        self._rec(event="cmd", text=text)
        self.port.write((text.strip() + "\n").encode("ascii"))
        deadline = self.clock() + timeout_s
        lines, partial = [], b""
        while True:
            raw = self.port.readline()
            if raw:
                partial += raw
                if not partial.endswith(b"\n"):
                    self._rec(event="partial", text=partial.decode("ascii", "replace"))
                    if self.clock() > deadline:
                        self._timeout(keying, text)
                    continue
                line = partial.decode("ascii", "replace").rstrip("\r\n")
                partial = b""
                self._rec(event="reply_line", text=line)
                if line == "OK" or _ERR_RE.match(line):
                    break
                if line.startswith("I,"):
                    self._rec(event="device_notice", text=line)
                    if line.startswith("I,boot"):
                        raise ResponseError("device rebooted during %r: %s" % (text, line))
                    continue
                lines.append(line)
                continue
            if self.clock() > deadline:
                self._timeout(keying, text)
        if line == "OK":
            try:
                records = _check_reply(cmd, lines)
            except ResponseError as e:
                self._rec(event="bad_reply", text=text, error=str(e))
                if keying:
                    self._safe_unkey()
                raise
            return Reply(text, lines, True, None, records)
        if lines:
            self._rec(event="bad_reply", text=text, error="lines before ERR: %r" % lines)
        return Reply(text, lines, False, line, {})

    def _safe_unkey(self):
        try:
            self.port.write(b"U\n")
            self._rec(event="cmd", text="U", note="auto-unkey")
        except Exception as e:  # best effort
            self._rec(event="unkey_failed", error=repr(e))

    def _timeout(self, keying, text):
        self._rec(event="timeout", text=text)
        if keying:
            self._safe_unkey()
        raise ResponseTimeout("no OK/ERR for %r" % text)

    def read_report(self):
        raw = self.port.readline()
        text = raw.decode("ascii", "replace") if isinstance(raw, bytes) else raw
        try:
            if not text.endswith("\n"):
                raise ReportError("truncated or empty report (no newline): %r" % text)
            rep = parse_report(text)
        except ReportError as e:
            self._rec(event="bad_report", text=text, error=str(e))
            raise
        self._rec(event="report", report=rep)
        return rep


def _replace_budget(env, cmd=None):
    from dataclasses import replace
    pk = env.max_packets - 1 if cmd and cmd["kind"] == "PKT" else env.max_packets
    return replace(env, max_commands=env.max_commands - 1, max_packets=pk)
