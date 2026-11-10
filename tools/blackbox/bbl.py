#!/usr/bin/env python3
"""Betaflight blackbox (.bbl) helpers: capture-stream splitting, MSP v1 frame scanning, a minimal pure-Python
log parser (fallback for blackbox_decode) and a writer used to synthesise test logs.

Format reference: Betaflight 4.2.11 src/main/blackbox/blackbox.c, blackbox_encoding.c, and blackbox-tools
src/parser.c / decoders.c (the C decoder this module cross-checks against). Supports I, P, S and E frames with
every encoding Betaflight 4.2 writes (SIGNED_VB, UNSIGNED_VB, NEG_14BIT, TAG8_8SVB, TAG2_3S32, TAG8_4S16 v2, NULL).
GPS (G/H) frames are not supported (the MATEKF411RX has no GPS configured); a log with them stops at the first one.
"""
import struct
from dataclasses import dataclass, field

LOG_START = b"H Product:Blackbox flight data recorder by Nicholas Sherlock"
LOG_END = b"E\xffEnd of log\x00"  # event frame FLIGHT_LOG_EVENT_LOG_END (255) + string + NUL

# Encodings / predictors (blackbox_fielddefs.h)
SIGNED_VB, UNSIGNED_VB, NEG_14BIT, TAG8_8SVB, TAG2_3S32, TAG8_4S16, NULL = 0, 1, 3, 6, 7, 8, 9
P_0, P_PREVIOUS, P_STRAIGHT_LINE, P_AVERAGE_2, P_MINTHROTTLE, P_MOTOR_0, P_INC = 0, 1, 2, 3, 4, 5, 6
P_1500, P_VBATREF, P_LAST_MAIN_FRAME_TIME, P_MINMOTOR = 8, 9, 10, 11
EVENT_SYNC_BEEP, EVENT_LOG_END = 0, 255


# ---------------------------------------------------------------- capture-stream splitting (serial VCP capture)

@dataclass
class Session:
    start: int        # offset of "H Product:..." in the raw stream
    end: int          # offset one past the last byte belonging to the log
    complete: bool    # True when the log ended with the LOG_END event (clean disarm)


def split_stream(buf):
    """Split a raw VCP capture into blackbox sessions and the bytes outside them.

    Each session runs from a LOG_START marker to just past the following LOG_END event; if the end marker is
    missing (Ctrl-C while armed, lost bytes) it runs to the next LOG_START or end of buffer and complete=False.
    Bytes outside sessions are MSP traffic or noise. Bytes inside a session are never interpreted as MSP: the
    binary log can contain "$M>" by chance and Betaflight releases MSP on the shared port while it logs.
    Returns (sessions, outside_chunks)."""
    sessions, outside, pos = [], [], 0
    while True:
        s = buf.find(LOG_START, pos)
        if s < 0:
            outside.append(bytes(buf[pos:]))
            break
        outside.append(bytes(buf[pos:s]))
        nxt = buf.find(LOG_START, s + 1)
        e = buf.find(LOG_END, s)
        if e >= 0 and (nxt < 0 or e < nxt):
            end, ok = e + len(LOG_END), True
        else:
            end, ok = (nxt if nxt >= 0 else len(buf)), False
        sessions.append(Session(s, end, ok))
        pos = end
    return sessions, [c for c in outside if c]


def sessions_bytes(buf, sessions):
    """Concatenate session bytes: a valid multi-log .bbl, as a flash download would be."""
    return b"".join(bytes(buf[s.start:s.end]) for s in sessions)


# ---------------------------------------------------------------- MSP v1 (with jumbo frames)

def msp_checksum(data):
    c = 0
    for b in data:
        c ^= b
    return c


def msp_frames(buf):
    """Scan bytes for complete MSP v1 frames ('$M>' / '$M!' / '$M<', jumbo supported).
    Returns (frames, junk_bytes) where frames are (direction_char, cmd, payload)."""
    frames, junk, i, n = [], 0, 0, len(buf)
    while i < n:
        j = buf.find(b"$M", i)
        if j < 0:
            junk += n - i
            break
        junk += j - i
        f = parse_msp_at(buf, j)
        if f is None:
            junk += 1
            i = j + 1
            continue
        d, cmd, payload, ln = f
        frames.append((d, cmd, payload))
        i = j + ln
    return frames, junk


def parse_msp_at(buf, j):
    """Parse one MSP v1 frame at buf[j]; return (dir, cmd, payload, frame_len) or None if incomplete/bad."""
    if len(buf) < j + 6 or buf[j + 2:j + 3] not in (b">", b"!", b"<"):
        return None
    size, cmd = buf[j + 3], buf[j + 4]
    hdr = 5
    if size == 255:  # jumbo: real size follows as u16
        if len(buf) < j + 7:
            return None
        size = buf[j + 5] | buf[j + 6] << 8
        hdr = 7
    end = j + hdr + size
    if len(buf) < end + 1:
        return None
    if msp_checksum(buf[j + 3:end]) != buf[end]:
        return None
    return chr(buf[j + 2]), cmd, bytes(buf[j + hdr:end]), end + 1 - j


# ---------------------------------------------------------------- bit-exact primitives

def zigzag(v):
    return ((v << 1) ^ (v >> 31)) & 0xFFFFFFFF


def unzigzag(u):
    return (u >> 1) ^ -(u & 1)


def write_uvb(out, v):
    v &= 0xFFFFFFFF
    while v > 127:
        out.append((v & 0x7F) | 0x80)
        v >>= 7
    out.append(v)


def write_svb(out, v):
    write_uvb(out, zigzag(v))


def write_tag2_3s32(out, vals):
    """Port of blackboxWriteTag2_3S32."""
    sel = 0
    for v in vals:
        if v >= 32 or v < -32:
            sel = 3
            break
        if v >= 8 or v < -8:
            sel = max(sel, 2)
        elif v >= 2 or v < -2:
            sel = max(sel, 1)
    if sel == 0:
        out.append((vals[0] & 3) << 4 | (vals[1] & 3) << 2 | (vals[2] & 3))
    elif sel == 1:
        out.append(0x40 | (vals[0] & 0xF))
        out.append(((vals[1] << 4) | (vals[2] & 0xF)) & 0xFF)
    elif sel == 2:
        out += bytes([0x80 | (vals[0] & 0x3F), vals[1] & 0xFF, vals[2] & 0xFF])
    else:
        s2 = 0
        for v in reversed(vals):
            s2 <<= 2
            s2 |= 0 if -128 <= v < 128 else 1 if -32768 <= v < 32768 else 2 if -8388608 <= v < 8388608 else 3
        out.append(0xC0 | s2)
        for v in vals:
            nb = (s2 & 3) + 1
            out += (v & 0xFFFFFFFF).to_bytes(4, "little")[:nb]
            s2 >>= 2


def write_tag8_4s16(out, vals):
    """Port of blackboxWriteTag8_4S16 (data version 2)."""
    sel = 0
    for v in reversed(vals):
        sel <<= 2
        sel |= 0 if v == 0 else 1 if -8 <= v < 8 else 2 if -128 <= v < 128 else 3
    out.append(sel)
    nib, buf = 0, 0
    for v in vals:
        k = sel & 3
        sel >>= 2
        if k == 1:
            if nib == 0:
                buf, nib = (v << 4) & 0xFF, 1
            else:
                out.append(buf | (v & 0xF))
                nib = 0
        elif k == 2:
            if nib == 0:
                out.append(v & 0xFF)
            else:
                out.append(buf | ((v >> 4) & 0xF))
                buf = (v << 4) & 0xFF
        elif k == 3:
            if nib == 0:
                out += bytes([(v >> 8) & 0xFF, v & 0xFF])
            else:
                out += bytes([buf | ((v >> 12) & 0xF), (v >> 4) & 0xFF])
                buf = (v << 4) & 0xFF
    if nib:
        out.append(buf)


def write_tag8_8svb(out, vals):
    if len(vals) == 1:
        write_svb(out, vals[0])
        return
    h = 0
    for i, v in enumerate(vals):
        if v:
            h |= 1 << i
    out.append(h)
    for v in vals:
        if v:
            write_svb(out, v)


def _sx(v, bits):
    m = 1 << (bits - 1)
    return (v & (m - 1)) - (v & m)


class Reader:
    def __init__(self, data, pos=0, end=None):
        self.d, self.p, self.end = data, pos, len(data) if end is None else end

    def eof(self):
        return self.p >= self.end

    def byte(self):
        if self.p >= self.end:
            raise EOFError
        b = self.d[self.p]
        self.p += 1
        return b

    def uvb(self):
        r, shift = 0, 0
        for _ in range(5):
            c = self.byte()
            r |= (c & 0x7F) << shift
            if c < 128:
                return r & 0xFFFFFFFF
            shift += 7
        raise ValueError("overlong varint")

    def svb(self):
        return unzigzag(self.uvb())

    def tag2_3s32(self):
        lead = self.byte()
        k = lead >> 6
        if k == 0:
            return [_sx(lead >> 4 & 3, 2), _sx(lead >> 2 & 3, 2), _sx(lead & 3, 2)]
        if k == 1:
            b = self.byte()
            return [_sx(lead & 0xF, 4), _sx(b >> 4, 4), _sx(b & 0xF, 4)]
        if k == 2:
            return [_sx(lead & 0x3F, 6), _sx(self.byte() & 0x3F, 6), _sx(self.byte() & 0x3F, 6)]
        vals = []
        for _ in range(3):
            nb = (lead & 3) + 1
            raw = bytes(self.byte() for _ in range(nb))
            vals.append(_sx(int.from_bytes(raw, "little"), nb * 8))
            lead >>= 2
        return vals

    def tag8_4s16(self):
        sel = self.byte()
        vals, nib, buf = [], 0, 0
        for _ in range(4):
            k = sel & 3
            sel >>= 2
            if k == 0:
                vals.append(0)
            elif k == 1:
                if nib == 0:
                    buf = self.byte()
                    vals.append(_sx(buf >> 4, 4))
                    nib = 1
                else:
                    vals.append(_sx(buf & 0xF, 4))
                    nib = 0
            elif k == 2:
                if nib == 0:
                    vals.append(_sx(self.byte(), 8))
                else:
                    c1 = (buf << 4) & 0xFF
                    buf = self.byte()
                    vals.append(_sx(c1 | buf >> 4, 8))
            else:
                if nib == 0:
                    c1, c2 = self.byte(), self.byte()
                    vals.append(_sx(c1 << 8 | c2, 16))
                else:
                    c1, c2 = self.byte(), self.byte()
                    vals.append(_sx(((buf << 12) | (c1 << 4) | (c2 >> 4)) & 0xFFFF, 16))
                    buf = c2
        return vals

    def tag8_8svb(self, n):
        if n == 1:
            return [self.svb()]
        h = self.byte()
        return [self.svb() if h >> i & 1 else 0 for i in range(n)]


# ---------------------------------------------------------------- parser

@dataclass
class FrameDef:
    names: list
    signed: list
    predictor: list
    encoding: list


@dataclass
class Log:
    headers: dict = field(default_factory=dict)
    defs: dict = field(default_factory=dict)        # 'I', 'P', 'S' -> FrameDef (P shares names/signed with I)
    main: list = field(default_factory=list)        # rows of ints in defs['I'].names order
    slow: list = field(default_factory=list)        # (main_row_index, values)
    events: list = field(default_factory=list)      # (type, payload)
    corrupt: int = 0                                # bytes skipped while resyncing
    ended: bool = False                             # saw LOG_END

    @property
    def fields(self):
        return self.defs["I"].names

    def column(self, name):
        i = self.fields.index(name)
        return [r[i] for r in self.main]


def _ints(s):
    return [int(x) for x in s.split(",")] if s else []


def find_logs(data):
    """Offsets of each log start in a (possibly multi-log) file."""
    out, i = [], data.find(LOG_START)
    while i >= 0:
        out.append(i)
        i = data.find(LOG_START, i + 1)
    return out


def parse(data):
    """Parse every log in a .bbl byte string. Returns a list of Log."""
    starts = find_logs(data)
    return [parse_one(data, s, starts[k + 1] if k + 1 < len(starts) else len(data)) for k, s in enumerate(starts)]


def parse_one(data, start, end):
    log, p = Log(), start
    # Header: lines "H name:value\n" until the first non-'H' frame byte
    while p < end and data[p:p + 2] == b"H ":
        nl = data.find(b"\n", p, end)
        if nl < 0:
            break
        line = data[p + 2:nl].decode("latin1")
        p = nl + 1
        k, _, v = line.partition(":")
        log.headers[k] = v
    h = log.headers
    names = h.get("Field I name", "").split(",")
    signed = _ints(h.get("Field I signed", ""))
    log.defs["I"] = FrameDef(names, signed, _ints(h.get("Field I predictor", "")), _ints(h.get("Field I encoding", "")))
    log.defs["P"] = FrameDef(names, signed, _ints(h.get("Field P predictor", "")), _ints(h.get("Field P encoding", "")))
    if "Field S name" in h:
        log.defs["S"] = FrameDef(h["Field S name"].split(","), _ints(h.get("Field S signed", "")),
                                 _ints(h.get("Field S predictor", "")), _ints(h.get("Field S encoding", "")))
    if int(h.get("Data version", "2")) < 2:
        raise ValueError("data version 1 (TAG8_4S16 v1) not supported by the Python parser")
    pint = h.get("P interval", "1/1")
    # Same rule as blackbox-tools: only "num/denom" is honoured; Betaflight 4.x writes a bare integer -> 1/1.
    pnum, pden = (int(x) for x in pint.split("/")) if "/" in pint else (1, 1)
    iint = max(1, int(h.get("I interval", "32")))
    ctx = {
        "minthrottle": int(h.get("minthrottle", "1150")),
        "motorlow": _ints(h.get("motorOutput", "0,0"))[0],
        "vbatref": int(h.get("vbatref", "0")),
    }
    motor0 = names.index("motor[0]") if "motor[0]" in names else -1

    def should_have(idx):
        return (idx % iint + pnum - 1) % pden < pnum

    def predict(i, pred, v, cur, prev, prev2):
        if pred == P_0:
            return v
        if pred == P_MINTHROTTLE:
            return v + ctx["minthrottle"]
        if pred == P_MINMOTOR:
            return v + ctx["motorlow"]
        if pred == P_1500:
            return v + 1500
        if pred == P_MOTOR_0:
            return v + cur[motor0]
        if pred == P_VBATREF:
            return v + ctx["vbatref"]
        if pred == P_PREVIOUS:
            return v + prev[i] if prev else v
        if pred == P_STRAIGHT_LINE:
            return v + 2 * prev[i] - prev2[i] if prev else v
        if pred == P_AVERAGE_2:
            return v + int((prev[i] + prev2[i]) / 2) if prev else v  # C division truncates toward zero
        raise ValueError("unsupported predictor %d" % pred)

    def read_frame(r, fd, prev, prev2, skipped):
        n = len(fd.names)
        cur = [0] * n
        i = 0
        while i < n:
            pred, enc = fd.predictor[i], fd.encoding[i]
            if pred == P_INC:
                cur[i] = skipped + 1 + (prev[i] if prev else 0)
                i += 1
                continue
            if enc in (TAG8_4S16, TAG2_3S32, TAG8_8SVB):
                if enc == TAG8_4S16:
                    vals = r.tag8_4s16()
                elif enc == TAG2_3S32:
                    vals = r.tag2_3s32()
                else:
                    j = i + 1
                    while j < i + 8 and j < n and fd.encoding[j] == TAG8_8SVB:
                        j += 1
                    vals = r.tag8_8svb(j - i)
                for v in vals:
                    cur[i] = predict(i, fd.predictor[i], v, cur, prev, prev2)
                    i += 1
                continue
            if enc == SIGNED_VB:
                v = r.svb()
            elif enc == UNSIGNED_VB:
                v = r.uvb()
            elif enc == NEG_14BIT:
                v = -_sx(r.uvb() & 0x3FFF, 14)
            elif enc == NULL:
                v = 0
            else:
                raise ValueError("unsupported encoding %d" % enc)
            v = predict(i, pred, v, cur, prev, prev2)
            sg = fd.signed[i] if i < len(fd.signed) else 0
            v = _sx(v & 0xFFFFFFFF, 32) if sg else v & 0xFFFFFFFF
            cur[i] = v
            i += 1
        return cur

    r = Reader(data, p, end)
    prev = prev2 = None
    last_iter = None
    markers = b"IPSEGH"
    while not r.eof():
        fstart = r.p
        t = r.byte()
        try:
            if t == ord("I"):
                cur = read_frame(r, log.defs["I"], prev, prev, 0)
                kind = "I"
            elif t == ord("P"):
                if prev is None:
                    raise ValueError("P frame without I frame")
                skipped = 0
                if last_iter is not None:
                    idx = last_iter + 1
                    while not should_have(idx) and skipped < 10000:
                        skipped += 1
                        idx += 1
                cur = read_frame(r, log.defs["P"], prev, prev2, skipped)
                kind = "P"
            elif t == ord("S") and "S" in log.defs:
                fd = log.defs["S"]
                vals = read_frame(r, fd, None, None, 0)
                kind = "S"
            elif t == ord("E"):
                et = r.byte()
                if et == EVENT_LOG_END:
                    msg = bytes(r.byte() for _ in range(11))
                    if msg == b"End of log\x00":
                        log.events.append((et, msg))
                        log.ended = True
                        break
                    raise ValueError("bad LOG_END")
                elif et == EVENT_SYNC_BEEP:
                    log.events.append((et, r.uvb()))
                else:
                    raise ValueError("unsupported event %d" % et)
                kind = "E"
            else:
                raise ValueError("bad frame marker %r" % chr(t))
            # Like blackbox-tools: a frame is only accepted if the next byte is a frame marker or end of data
            if not r.eof() and r.d[r.p] not in markers:
                raise ValueError("frame not followed by a marker")
        except (ValueError, EOFError):
            log.corrupt += 1
            r.p = fstart + 1
            if t in (ord("I"), ord("P")):
                prev = prev2 = None  # wait for the next I frame, as the C decoder does
            continue
        if kind == "I":
            prev = prev2 = cur
            log.main.append(cur)
            last_iter = cur[0]
        elif kind == "P":
            prev2, prev = prev, cur
            log.main.append(cur)
            last_iter = cur[0]
        elif kind == "S":
            log.slow.append((len(log.main), vals))
    return log


def to_csv(log, path):
    """Main-frame CSV with blackbox_decode-compatible column names (time column is 'time (us)')."""
    names = ["time (us)" if n == "time" else n for n in log.fields]
    with open(path, "w") as f:
        f.write(", ".join(names) + "\n")
        for row in log.main:
            f.write(", ".join(str(v) for v in row) + "\n")


# ---------------------------------------------------------------- writer (synthetic logs for tests)

# Betaflight 4.2 main field table (blackbox.c) for a quad without mag/baro/rangefinder, yaw D = 0, debug off.
BF42_MAIN = [
    # name, signed, Ipred, Ienc, Ppred, Penc
    ("loopIteration", 0, P_0, UNSIGNED_VB, P_INC, NULL),
    ("time", 0, P_0, UNSIGNED_VB, P_STRAIGHT_LINE, SIGNED_VB),
] + [("axisP[%d]" % i, 1, P_0, SIGNED_VB, P_PREVIOUS, SIGNED_VB) for i in range(3)] \
  + [("axisI[%d]" % i, 1, P_0, SIGNED_VB, P_PREVIOUS, TAG2_3S32) for i in range(3)] \
  + [("axisD[%d]" % i, 1, P_0, SIGNED_VB, P_PREVIOUS, SIGNED_VB) for i in range(2)] \
  + [("axisF[%d]" % i, 1, P_0, SIGNED_VB, P_PREVIOUS, SIGNED_VB) for i in range(3)] \
  + [("rcCommand[%d]" % i, 1, P_0, SIGNED_VB, P_PREVIOUS, TAG8_4S16) for i in range(3)] \
  + [("rcCommand[3]", 0, P_0, UNSIGNED_VB, P_PREVIOUS, TAG8_4S16)] \
  + [("setpoint[%d]" % i, 1, P_0, SIGNED_VB, P_PREVIOUS, TAG8_4S16) for i in range(4)] \
  + [("vbatLatest", 0, P_VBATREF, NEG_14BIT, P_PREVIOUS, TAG8_8SVB),
     ("amperageLatest", 1, P_0, SIGNED_VB, P_PREVIOUS, TAG8_8SVB),
     ("rssi", 0, P_0, UNSIGNED_VB, P_PREVIOUS, TAG8_8SVB)] \
  + [("gyroADC[%d]" % i, 1, P_0, SIGNED_VB, P_AVERAGE_2, SIGNED_VB) for i in range(3)] \
  + [("accSmooth[%d]" % i, 1, P_0, SIGNED_VB, P_AVERAGE_2, SIGNED_VB) for i in range(3)] \
  + [("motor[0]", 0, P_MINMOTOR, UNSIGNED_VB, P_AVERAGE_2, SIGNED_VB)] \
  + [("motor[%d]" % i, 0, P_MOTOR_0, SIGNED_VB, P_AVERAGE_2, SIGNED_VB) for i in range(1, 4)]

BF42_SLOW = [("flightModeFlags", 0, P_0, UNSIGNED_VB), ("stateFlags", 0, P_0, UNSIGNED_VB),
             ("failsafePhase", 0, P_0, TAG2_3S32), ("rxSignalReceived", 0, P_0, TAG2_3S32),
             ("rxFlightChannelsValid", 0, P_0, TAG2_3S32)]


class Writer:
    """Encode frames the way Betaflight 4.2 does (same field table, predictors and encoders)."""

    def __init__(self, main=BF42_MAIN, slow=BF42_SLOW, motorlow=48, vbatref=0, iint=128, pint=4,
                 extra_headers=()):
        self.main, self.slow = main, slow
        self.motorlow, self.vbatref = motorlow, vbatref
        self.iint, self.pint = iint, pint
        self.extra = list(extra_headers)
        self.out = bytearray()
        self.prev = self.prev2 = None

    def header(self):
        m, s = self.main, self.slow
        j = lambda col, rows: ",".join(str(r[col]) for r in rows)
        lines = [LOG_START.decode()[2:], "Data version:2",
                 "I interval:%d" % self.iint, "P interval:%d" % self.pint, "P ratio:32",
                 "Field I name:" + j(0, m), "Field I signed:" + j(1, m), "Field I predictor:" + j(2, m),
                 "Field I encoding:" + j(3, m), "Field P predictor:" + j(4, m), "Field P encoding:" + j(5, m),
                 "Field S name:" + j(0, s), "Field S signed:" + j(1, s), "Field S predictor:" + j(2, s),
                 "Field S encoding:" + j(3, s),
                 "Firmware type:Cleanflight", "Firmware revision:Betaflight 4.2.11 (948ba6339) MATEKF411RX",
                 "minthrottle:1070", "maxthrottle:2000", "motorOutput:%d,2047" % self.motorlow,
                 "vbatref:%d" % self.vbatref, "acc_1G:2048", "gyro_scale:0x3f800000"] + self.extra
        for ln in lines:
            self.out += b"H " + ln.encode() + b"\n"

    def _fields(self, vals, enc_col, pred_col, prev, prev2):
        m, o, i, n = self.main, self.out, 0, len(self.main)
        while i < n:
            pred, enc = m[i][pred_col], m[i][enc_col]
            if pred == P_INC:
                i += 1
                continue
            res = lambda k: vals[k] - self._pred(k, m[k][pred_col], vals, prev, prev2)
            if enc in (TAG8_4S16, TAG2_3S32):
                g = 4 if enc == TAG8_4S16 else 3
                (write_tag8_4s16 if g == 4 else write_tag2_3s32)(o, [res(k) for k in range(i, i + g)])
                i += g
            elif enc == TAG8_8SVB:
                j = i + 1
                while j < i + 8 and j < n and m[j][enc_col] == TAG8_8SVB:
                    j += 1
                write_tag8_8svb(o, [res(k) for k in range(i, j)])
                i = j
            elif enc == SIGNED_VB:
                write_svb(o, res(i))
                i += 1
            elif enc == UNSIGNED_VB:
                write_uvb(o, res(i))
                i += 1
            elif enc == NEG_14BIT:
                write_uvb(o, (-res(i)) & 0x3FFF)
                i += 1
            else:
                i += 1

    def _pred(self, k, pred, vals, prev, prev2):
        if pred == P_0:
            return 0
        if pred == P_MINMOTOR:
            return self.motorlow
        if pred == P_MOTOR_0:
            return vals[[r[0] for r in self.main].index("motor[0]")]
        if pred == P_VBATREF:
            return self.vbatref
        if pred == P_PREVIOUS:
            return prev[k]
        if pred == P_STRAIGHT_LINE:
            return 2 * prev[k] - prev2[k]
        if pred == P_AVERAGE_2:
            return int((prev[k] + prev2[k]) / 2)
        raise ValueError(pred)

    def iframe(self, vals):
        self.out += b"I"
        self._fields(vals, 3, 2, None, None)
        self.prev = self.prev2 = list(vals)

    def pframe(self, vals):
        self.out += b"P"
        self._fields(vals, 5, 4, self.prev, self.prev2)
        self.prev2, self.prev = self.prev, list(vals)

    def sframe(self, vals):
        self.out += b"S"
        write_uvb(self.out, vals[0])
        write_uvb(self.out, vals[1])
        write_tag2_3s32(self.out, vals[2:5])

    def sync_beep(self, t_us):
        self.out += b"E\x00"
        write_uvb(self.out, t_us)

    def end(self):
        self.out += LOG_END


def synth_session(n_frames=600, t0_us=5_000_000, seed=1, pint=4, looptime_us=250, motorlow=48):
    """A Betaflight-4.2-shaped log: 1 kHz frames (4 kHz PID / P interval 4), stick sweeps, noisy gyro,
    one flight-mode change. Returns (bytes, list of expected main rows)."""
    import math, random
    rnd = random.Random(seed)
    w = Writer(motorlow=motorlow, pint=pint)
    w.header()
    names = [f[0] for f in w.main]
    rows = []
    w.sync_beep(t0_us - 1000)
    it = 0
    for k in range(n_frames):
        t = t0_us + it * looptime_us
        ph = 2 * math.pi * k / 400.0
        rc = [int(300 * math.sin(ph)), int(200 * math.sin(2 * ph)), int(100 * math.cos(ph)), 1000 + int(400 * (1 + math.sin(ph / 2)) / 2)]
        sp = [int(rc[0] * 1.3), int(rc[1] * 1.3), int(-rc[2] * 1.1), rc[3] - 1000]
        gyro = [int(sp[a] * 0.9 + rnd.gauss(0, 6)) for a in range(3)]
        mot = [motorlow + int((rc[3] - 1000) * 1.9) + d + rnd.randint(-3, 3) for d in (10, -10, 5, -5)]
        v = {"loopIteration": it, "time": t}
        for a in range(3):
            v["axisP[%d]" % a] = (sp[a] - gyro[a]) // 3
            v["axisI[%d]" % a] = int(20 * math.sin(ph + a))
            v["axisF[%d]" % a] = sp[a] // 8
            v["gyroADC[%d]" % a] = gyro[a]
            v["accSmooth[%d]" % a] = (2048 if a == 2 else 0) + rnd.randint(-40, 40)
        for a in range(2):
            v["axisD[%d]" % a] = rnd.randint(-30, 30)
        for a in range(4):
            v["rcCommand[%d]" % a] = rc[a]
            v["setpoint[%d]" % a] = sp[a]
            v["motor[%d]" % a] = mot[a]
        v["vbatLatest"], v["amperageLatest"], v["rssi"] = 2 + (k // 200), 0, 1023 - (k % 7)
        vals = [v[n] for n in names]
        if it % w.iint == 0:
            w.iframe(vals)
        else:
            w.pframe(vals)
        if k == 0:
            w.sframe([1, 0, 0, 1, 1])        # ANGLE_MODE (flightModeFlags bit 0)
        if k == n_frames // 2:
            w.sframe([1 | 2, 0, 0, 1, 1])    # + HORIZON_MODE
        rows.append(vals)
        it += pint
    w.end()
    return bytes(w.out), names, rows
