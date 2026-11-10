"""Shared parts for the scenes: the map strip (where the data physically is), the bracketed packet row, the packet
unrolled into bits, and the 2-FSK wave. Style tokens come from common.py; constants for these parts live here.

Physical path (names checked against the repo): keyboard -> browser app (apps/web, Web Serial) -> USB cable (serial
921600 8N1, one `S c1..c8` line per 8.994 ms slot: protocol/PROTOCOL.md, packages/core/src/link.ts paced sender) ->
ESP32 DevKit V1 (firmware/main: packet.c builds the packet, d8tone.c keys the Wi-Fi radio's test tone per bit and
retunes per hop) -> 2.4 GHz through the air (hopping) -> drone (experiments/08: Tinyhawk 3): CC2500 radio chip
(receives, checks the CRC) -> SPI (tools/cc2500-rxdiag README: spi_hz=3375000) -> flight controller (STM32F411,
Betaflight 4.2.11: channels -> mixer -> motors) -> props."""
from common import *

# ---------------------------------------------------------------- map strip ----
K_KEY, K_APP, K_CABLE, K_ESP, K_AIR, K_RX, K_SPI, K_FC, K_MOT = range(9)
MAP_W = 12.0                 # local width of the strip
# local x of each node (boxes) or segment midpoint (cable, air, SPI); the marker interpolates between them
NODE_X = [-5.35, -3.85, -2.6, -1.35, 0.15, 1.75, 2.75, 3.85, 5.3]
MAP_EDGE_SCALE = 0.95        # strip scale when parked at the top edge
MAP_FOCUS_SCALE = 1.1        # strip scale when opened
MAP_EDGE_DY = 0.58           # distance of the strip's node row below the top edge (frame units at FW)
MAP_FOCUS_Y = 1.7            # node row y when the strip is opened (focus = 1): above the centre, clear of the piece
MAP_EDGE_A = 0.9             # opacity when parked
MAP_MARK_DY = 0.42           # marker sits just above the node row
MAP_BOX_H = 0.5
MAP_LABEL = GREY_A           # strip labels: brighter than MUTED so they read at 480p
MAP_BOX_FONT, MAP_SEG_FONT = 21, 18


def _box(name, x, w=1.25, size=MAP_BOX_FONT):
    r = RoundedRectangle(corner_radius=0.08, width=w, height=MAP_BOX_H, stroke_color=STRUCT, stroke_width=SW).move_to([x, 0, 0])
    return VGroup(r, label(name, size, MAP_LABEL).move_to(r))


def _seg_label(text, x, y=-0.42):
    return label(text, MAP_SEG_FONT, MAP_LABEL).move_to([x, y, 0])


def _link(a, b):
    return Line(a[0].get_right(), b[0].get_left(), stroke_color=STRUCT, stroke_width=SW)


def map_body():
    """The strip in local coordinates (width MAP_W, node row at y = 0)."""
    key = _box("keyboard", NODE_X[K_KEY])
    app = _box("browser", NODE_X[K_APP])
    esp = _box("ESP32", NODE_X[K_ESP], w=1.1)
    rx = _box("CC2500", NODE_X[K_RX], w=1.2)
    fc = _box("flight ctrl", NODE_X[K_FC], w=1.45)
    mot = _box("motors", NODE_X[K_MOT], w=1.1)
    k2a, cable, spi = _link(key, app), _link(app, esp), _link(rx, fc)
    x0, x1 = esp[0].get_right()[0] + 0.1, rx[0].get_left()[0] - 0.18
    air = ParametricFunction(lambda u: np.array([interpolate(x0, x1, u), 0.12 * np.sin(u * 5 * TAU), 0]),
                             t_range=[0, 1], stroke_color=STRUCT, stroke_width=SW)
    dl, dr = rx[0].get_left()[0] - 0.12, mot[0].get_right()[0] + 0.12
    drone = RoundedRectangle(corner_radius=0.12, width=dr - dl, height=0.78,
                             stroke_color=GRID, stroke_width=SW_THIN).move_to([(dl + dr) / 2, 0, 0])
    labs = VGroup(_seg_label("USB", NODE_X[K_CABLE]), _seg_label("2.4 GHz", NODE_X[K_AIR]),
                  _seg_label("SPI", NODE_X[K_SPI], -0.25), _seg_label("drone", NODE_X[K_MOT] + 0.2, -0.57))
    return VGroup(key, k2a, app, cable, esp, air, drone, rx, spi, fc, mot, labs)


class MapStrip(VGroup):
    """Dim row of boxes keyboard .. motors with a bright marker at `pos` (node index, fractional while travelling).
    `focus` 0 = parked small at the top edge of the frame, 1 = opened large near the centre. `frame_fn` returns
    (centre, width) of the camera frame so the strip stays put while a MovingCamera zooms; None = the fixed frame."""

    def __init__(self, pos=0.0, frame_fn=None):
        super().__init__()
        self.pos = ValueTracker(float(pos))
        self.focus = ValueTracker(0.0)
        self.frame_fn = frame_fn or (lambda: (ORIGIN, FW))
        self.body = map_body()
        self._w = self.body.width
        self.marker = VGroup(Dot(radius=0.2, color=YELLOW_A, fill_opacity=0.25, stroke_width=0),
                             Dot(radius=0.085, color=YELLOW_A))
        self._mw = self.marker.width
        fam = self.body.family_members_with_points()
        self._strokes = [m for m in fam if m.get_stroke_width() > 0]
        self._fills = [m for m in fam if m.get_stroke_width() == 0]
        self.add(self.body, self.marker)
        self.place()
        self.add_updater(lambda m: m.place())

    def node_x(self, p):
        p = min(max(p, 0.0), len(NODE_X) - 1.0)
        i = min(int(p), len(NODE_X) - 2)
        return interpolate(NODE_X[i], NODE_X[i + 1], p - i)

    def scale_now(self):
        c, w = self.frame_fn()
        return (w / FW) * interpolate(MAP_EDGE_SCALE, MAP_FOCUS_SCALE, self.focus.get_value())

    def place(self):
        c, w = self.frame_fn()
        s = w / FW
        f = self.focus.get_value()
        sc = s * interpolate(MAP_EDGE_SCALE, MAP_FOCUS_SCALE, f)
        y = interpolate(FH / 2 - MAP_EDGE_DY, MAP_FOCUS_Y, f) * s
        self.body.scale(self._w * sc / self.body.width, scale_stroke=True).move_to(c + UP * y)
        a = interpolate(MAP_EDGE_A, 1.0, f)
        for sm in self._strokes:
            sm.set_stroke(opacity=a)
        for sm in self._fills:
            sm.set_fill(opacity=a)
        self.marker.scale(self._mw * sc / self.marker.width)
        self.marker.move_to(c + np.array([self.node_x(self.pos.get_value()) * sc, y + MAP_MARK_DY * sc, 0]))
        return self

    # animations
    def go(self, pos):
        return self.pos.animate.set_value(float(pos))

    def open(self):
        return self.focus.animate.set_value(1.0)

    def close(self):
        return self.focus.animate.set_value(0.0)


# ------------------------------------------------------------ packet row ----
# byte groups of the 20-byte frame (packet.c d8_build_body): 0 = length 0x11, 1-2 = txid, 3-5 = 00 counter 01,
# 6-17 = eight 12-bit stick values (low bytes 6-9, 12-15; high nibbles packed in 10, 11, 16, 17), 18-19 = CRC-16
GROUPS = [(0, 1, "header"), (1, 3, "ID"), (3, 6, "counter"), (6, 18, "8 stick values"), (18, 20, "checksum")]
THROTTLE_CELLS = [(6, (0, 1)), (10, (1,))]        # cell index, which of its two hex chars belong to the throttle
HEX20 = (BODY + CRC).hex()


def packet_row(center=ORIGIN, scale=1.0, hexsize=BHEX, lab_size=18):
    """20 byte cells with braces and plain-word labels. Returns VDict(cells, braces, labels); cells[i] = (square, chars)."""
    cells = VGroup()
    for i in range(20):
        col = GREEN_A if i < 6 else (RED_A if i >= 18 else INK)
        sq = Square(BCELL, color=RED_A if i >= 18 else STRUCT, stroke_width=SW).move_to([(i - 9.5) * BPITCH, 0, 0])
        chars = VGroup(mono(HEX20[2 * i], hexsize, col), mono(HEX20[2 * i + 1], hexsize, col)).arrange(RIGHT, buff=0.03).move_to(sq)
        cells.add(VGroup(sq, chars))
    braces, labels = VGroup(), VGroup()
    for a, b, name in GROUPS:
        br = Brace(VGroup(*cells[a:b]), UP, buff=0.1, color=MUTED, sharpness=1.5)
        br.set_stroke(width=0)
        lb = label(name, lab_size).next_to(br, UP, buff=0.08)
        braces.add(br); labels.add(lb)
    g = VDict({"cells": cells, "braces": braces, "labels": labels})
    g.scale(scale, about_point=ORIGIN).shift(np.array(center) - cells.get_center())
    return g


def dim_row(row, a=DIM):
    for c in row["cells"]:
        cell_alpha(c, a)
    return row


def light_throttle(row):
    """The throttle's cells lit in yellow: cell 6 (its low byte) and the low nibble of cell 10."""
    c6, c10 = row["cells"][6], row["cells"][10]
    c6[0].set_stroke(YELLOW_A, opacity=1); c6[1].set_color(YELLOW_A).set_fill(opacity=1)
    c10[0].set_stroke(YELLOW_A, opacity=0.7); c10[1][1].set_color(YELLOW_A).set_fill(opacity=1)
    return row


def throttle_glyphs(row):
    """The three hex glyphs that hold 0x6bd: '6' in cell 10, 'b' 'd' in cell 6 (same order as the string 6bd)."""
    return VGroup(row["cells"][10][1][1], row["cells"][6][1][0], row["cells"][6][1][1])


# --------------------------------------------------------- unrolled bits ----
PBITS = [int(b) for x in BODY + CRC for b in f"{x:08b}"]     # the 20 bytes as 160 bits, MSB first (packet.c sends MSB first)
NBITS = len(PBITS)
assert NBITS == 160
THROTTLE_BIT_IDX = set(range(8 * 6, 8 * 7)) | set(range(8 * 10 + 4, 8 * 11))   # byte 6, and the low nibble of byte 10
UB_SIDE, UB_PITCH, UB_FONT = 0.30, 0.34, 15     # bit squares as unrolled in S02
S3_PITCH = 0.7                                   # pitch the 8 throttle bits have at the start of S03 (full frame)
UZOOM_W = FW * UB_PITCH / S3_PITCH               # camera width at the end of S02 (6.9): S02 end == S03 start
BYTE6_C = 8 * HERO_BYTE + 3.5                    # bit index at the centre of byte 6's eight bits


def bit_cells(k=1.0, center=ORIGIN, lit=THROTTLE_BIT_IDX):
    """All 160 bits as small squares in one row, byte 6 centred on `center`; the throttle's bits lit, the rest dim."""
    g = VGroup()
    for n, b in enumerate(PBITS):
        col = ONE if b else ZERO
        sq = Square(UB_SIDE * k, color=col, stroke_width=SW * k, fill_color=col, fill_opacity=0.1)
        d = mono(str(b), UB_FONT * k, col).move_to(sq)
        c = VGroup(sq, d).move_to(np.array(center) + RIGHT * (n - BYTE6_C) * UB_PITCH * k)
        if n not in lit:
            sq.set_stroke(opacity=DIM).set_fill(opacity=0.03); d.set_fill(opacity=DIM)
        g.add(c)
    return g


def byte_bits(bits, i):
    return VGroup(*bits[8 * i:8 * i + 8])


# -------------------------------------------------------------- 2-FSK wave ----
# 2-FSK (firmware/main/d8tone.c): a 1 keys the test tone one step (40 MHz/1024 = 39.06 kHz) above the channel centre,
# a 0 one step below; 32.2 us per bit. On screen the carrier is a cartoon: 3 cycles per bit, 4 for a 1, 2 for a 0.
WAVE_W = 8 * BIT_PITCH       # 10.4: the 8 throttle bits at BIT_PITCH, one wave segment under each
WAVE_A = 0.8
CYC_C, CYC_DEV = 3.0, 1.0


def fsk_pieces(cursor=8.0, lit=None, bits=HERO_BITS, width=WAVE_W, amp=WAVE_A, n=1400, cyc=CYC_C):
    """Phase-continuous wave: carrier frequency everywhere, modulated by the bits up to `cursor` (bit units), coloured
    by the bits up to `lit` (default cursor). Returns [(xs, ys, colour, opacity)], x centred on 0."""
    if lit is None:
        lit = cursor
    nb = len(bits)
    pitch = width / nb
    xs = np.linspace(-width / 2, width / 2, n)
    u = (xs + width / 2) / pitch
    idx = np.minimum(u.astype(int), nb - 1)
    barr = np.array(bits)
    f = np.full(n, float(cyc))   # cyc = carrier cycles per bit on screen (S03 draws channel B with more than channel A)
    m = u < cursor
    f[m] = np.where(barr[idx[m]] == 1, cyc + CYC_DEV, cyc - CYC_DEV)
    phase = np.concatenate([[0.0], np.cumsum(0.5 * (f[1:] + f[:-1]) * np.diff(u))]) * TAU
    ys = amp * np.sin(phase)
    cut = min(max(float(lit), 0.0), float(nb))
    edges = sorted(set([0.0, float(nb), cut] + [float(i) for i in range(1, nb)]))
    out = []
    for a, b in zip(edges[:-1], edges[1:]):
        sel = (u >= a - 1e-9) & (u <= b + 1e-9)
        if sel.sum() < 2:
            continue
        last = np.nonzero(sel)[0][-1]
        if last + 1 < n:
            sel[last + 1] = True     # share one sample with the next piece, so the line has no gap at a bit edge
        i = min(int(a), nb - 1)
        if b <= cut + 1e-9:
            out.append((xs[sel], ys[sel], ONE if bits[i] else ZERO, 1.0))
        else:
            out.append((xs[sel], ys[sel], INK, 0.55))
    return out


def fsk_wave(cursor=8.0, lit=None, center=ORIGIN, k=1.0, width=WAVE_W, amp=WAVE_A, bits=HERO_BITS, cyc=CYC_C):
    """The wave as a VGroup of coloured pieces. fsk_wave() (all 8 bits) is the carry-over S03 end -> S04 start."""
    g = VGroup()
    for xs, ys, col, op in fsk_pieces(cursor, lit, bits, width, amp, cyc=cyc):
        v = VMobject(stroke_color=col, stroke_width=SW_LINE * k, stroke_opacity=op)
        v.set_points_as_corners(np.column_stack([xs * k, ys * k, np.zeros_like(xs)]) + np.array(center))
        g.add(v)
    return g


def bit_x(i, center=ORIGIN, width=WAVE_W, nb=8):
    """x of the centre of bit i's segment of a wave of `width` centred on `center`."""
    return center[0] - width / 2 + (i + 0.5) * width / nb
