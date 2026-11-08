"""Protocol v1 helpers: line formatting and parsing (see d8tx/PROTOCOL.md)."""
LO, MID, HI = 1000, 1500, 2000
ARM_CH = 6  # index of ch7
ARM_LIMIT = 1300
SLOT_S = 0.008994
DEFAULT_FOFS_HZ = -75000  # LO offset for TX and RX; bench: 97.8-100% of telemetry triggers answered here
TXID = (66, 178)  # bound receiver id (frsky_spi_tx_id), echoed in telemetry replies
# TLM <every> <cap_us> <gain> <dec> <same> <stream> <ack> <mark> <retry>: trigger every 48 slots (not a multiple of
# 47 so triggers walk the hop table), 9 ms capture at dec 32, listen on the next hop channel, int8 stream, host TID acks,
# one on-chip re-trigger.
TLM_RECIPE = "TLM 48 9000 40 32 0 1 1 0 1"
MAX_LINE = 95  # firmware line buffer limit


class ProtocolError(Exception):
    def __init__(self, code, text=""):
        super().__init__(f"{code} {text}".strip())
        self.code, self.text = code, text


def check_line(line):
    """Raise ValueError if line (without newline) exceeds firmware MAX_LINE."""
    if len(line.rstrip("\r\n")) > MAX_LINE:
        raise ValueError(f"line longer than {MAX_LINE}")
    return line


def clamp(v):
    return max(LO, min(HI, int(round(v))))


def fmt_sticks(ch, allow_arm=False):
    """Return (line, clamped channels). ch7 forced to 1000 unless allow_arm."""
    ch = [clamp(v) for v in ch]
    if len(ch) != 8:
        raise ValueError("need 8 channels")
    if not allow_arm:
        ch[ARM_CH] = LO
    line = "S " + " ".join(map(str, ch)) + "\n"
    check_line(line)
    return line, ch


def _kv(tokens):
    d = {}
    for t in tokens:
        if "=" in t:
            k, v = t.split("=", 1)
            d[k] = int(v) if v.lstrip("-").isdigit() else v
        else:
            d[t] = True
    return d


def parse_line(line):
    """Parse one reply/event line. Returns ('ok', dict) | ('err', (code, text)) | ('ev', (name, dict)) | ('other', str)."""
    line = line.strip()
    if line == "OK" or line.startswith("OK "):
        return "ok", _kv(line[3:].split())
    if line.startswith("ERR"):
        parts = line.split(None, 2)
        return "err", (parts[1] if len(parts) > 1 else "unknown", parts[2] if len(parts) > 2 else "")
    if line.startswith("EV "):
        parts = line[3:].split()
        if parts:
            return "ev", (parts[0], _kv(parts[1:]))
    return "other", line
