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

    def __init__(self, pos=0.0, frame_fn=None, dim=False, focus=0.0):
        super().__init__()
        self.pos = ValueTracker(float(pos))
        self.focus = ValueTracker(float(focus))
        self.dimv = ValueTracker(1.0 if dim else 0.0)     # 1 = DIM state (S03b: the E8 is not on the strip)
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
        dm = interpolate(1.0, DIM, self.dimv.get_value())
        a = interpolate(MAP_EDGE_A, 1.0, f) * dm
        self.marker[0].set_fill(opacity=0.25 * dm)
        self.marker[1].set_fill(opacity=dm)
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

    def dim(self):
        return self.dimv.animate.set_value(1.0)

    def undim(self):
        return self.dimv.animate.set_value(0.0)


# ------------------------------------------------------------ packet row ----
# byte groups of the 20-byte frame (packet.c d8_build_body): 0 = length 0x11, 1-2 = txid, 3-5 = 00 counter 01,
# 6-17 = eight 12-bit stick values (low bytes 6-9, 12-15; high nibbles packed in 10, 11, 16, 17), 18-19 = CRC-16
GROUPS = [(0, 1, "length"), (1, 3, "ID"), (3, 6, "bookkeeping"), (6, 18, "8 control channels"), (18, 20, "checksum")]
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


# =====================================================================================================================
# LONG CUT (11 scenes): shared builders, so a seam frame is built by ONE function and both scenes use it.
# See scenes/README.md for the contracts. Everything above this line is the old helper set; do not change its behaviour.
# =====================================================================================================================
from math import erf as _erf

# ---- layout of the S03 rows (bits on top, row 1 frequency, row 2 carrier, row 3 wave) ----
Y1, LV = 1.3, 0.28               # row 1: the bit signal, levels at Y1 +- LV
Y2, A2 = 0.0, 0.42               # row 2: the carrier
Y3, A3 = -1.5, 0.55              # row 3: carrier + offset
XL, XR = -WAVE_W / 2, WAVE_W / 2
OPX = XL - 0.65                  # column of the + and = signs
CYC_A, CYC_B = 3.0, 5.0          # cartoon carrier cycles per bit (S04a uses 3 and 4 for the two strips)
K3 = FW / UZOOM_W                # the unrolled bits as seen at the end of S02b (scale of bit_cells at full frame)
BX = -6.1                        # x of the little labelled blocks in the left margin
DRIFT = 3.0                      # rad/s: the idle flow of the waves while the voice talks


# ---- the quad ----
def quad_top(scale=1.0, center=ORIGIN):
    """Top-view quad (two arms, four motor circles, body square), as drawn in S01. S00, S01 and S06 use it."""
    g = VGroup(Line(LEFT * .65 + UP * .42, RIGHT * .65 + DOWN * .42), Line(LEFT * .65 + DOWN * .42, RIGHT * .65 + UP * .42)).set_stroke(BLUE_DK, SW_LINE)
    for x in (-.65, .65):
        for y in (-.42, .42):
            g.add(Circle(radius=.22, color=BLUE_LT, stroke_width=SW).move_to([x, y, 0]))
    g.add(Square(.34, color=BLUE_A, stroke_width=SW))
    return g.scale(scale).move_to(center)


def quad3d():
    """The 3D quad of S05 (moved out of s05_drone.py). Returns (VGroup(body, arms, motors, props), [four prop blades])."""
    body = Prism(dimensions=[0.75, 0.75, 0.18]).set_fill(BLUE_E, 1).set_stroke(BLUE_A, SW_THIN, 0.8)
    props = VGroup(); arms = VGroup(); motors = VGroup()
    d = 1.25
    for sx, sy in [(1, 1), (-1, 1), (-1, -1), (1, -1)]:
        pos = np.array([sx * d, sy * d, 0.0])
        arms.add(Line3D(ORIGIN, pos, color=BLUE_DK, thickness=0.025))
        motors.add(Cylinder(radius=0.12, height=0.2, direction=OUT, checkerboard_colors=False, fill_color=BLUE_A, fill_opacity=1, stroke_width=0).move_to(pos + OUT * 0.1))
        blade = VGroup(Line(LEFT * 0.55, RIGHT * 0.55, color=INK, stroke_width=SW_LINE),
                       Line(UP * 0.55, DOWN * 0.55, color=INK, stroke_width=SW_LINE)).rotate(PI / 4).move_to(pos + OUT * 0.25)
        props.add(blade)
    return VGroup(body, arms, motors, props), list(props)


# S05 end frame (= S06 start frame): the quad as the old S05 left it
QUAD_PHI, QUAD_THETA = 62 * DEGREES, -0.6602426      # measured end of the old S05 (-45 deg plus the ambient turn during the last sentence)
QUAD_SCALE, QUAD_SHIFT = 1.5, np.array([1.0, -0.6, 0.3])        # scale, then shift RIGHT*1 + DOWN*.6 + OUT*.3 (lifted)
QUAD_PROP_ANGLE = 0.3127                                        # blade angle at the end of the old S05 (measured), from the initial pi/4


def quad3d_lifted():
    q, props = quad3d()
    q.scale(QUAD_SCALE).shift(QUAD_SHIFT)
    for p in props:
        p.rotate(QUAD_PROP_ANGLE, about_point=p.get_center())
    return q, props


# ---- text blocks ----
def margin_block(words, y, x=BX, w=1.15, h=0.78):
    """Small labelled box in the left margin (S03b / S03c): words = list of lines."""
    box = RoundedRectangle(corner_radius=0.08, width=w, height=h, stroke_color=MUTED, stroke_width=SW_THIN)
    txt = VGroup(*[label(t, 21, INK) for t in words]).arrange(DOWN, buff=0.03)
    return VGroup(box, txt).move_to([x, y, 0])


def margin_arrow(y, x=BX, x_end=XL - 0.05, color=MUTED):
    return Arrow([x + 0.6, y, 0], [x_end, y, 0], buff=0, stroke_width=3, color=color, max_tip_length_to_length_ratio=0.3)


# ---- carrier and wave rows (moved here from the old s03_tones.py) ----
def carrier_wave(cyc=CYC_A, y=Y2, amp=A2):
    """The unmodulated carrier as one unbroken line (fsk_wave cuts it at every bit edge)."""
    ps = fsk_pieces(0.0, 0.0, amp=amp, cyc=cyc)
    xs, ys = np.concatenate([p[0] for p in ps]), np.concatenate([p[1] for p in ps])
    v = VMobject(stroke_color=INK, stroke_width=SW_LINE, stroke_opacity=0.55)
    return v.set_points_as_corners(np.column_stack([xs, ys + y, np.zeros_like(xs)]))


def pieces_ph(cursor, phase, cyc, amp, bits=HERO_BITS, width=WAVE_W, n=1400):
    """Like fsk_pieces, but the whole wave travels: phase offset `phase` (radians). Returns [(xs, ys, col, op)]."""
    nb = len(bits)
    xs = np.linspace(-width / 2, width / 2, n)
    u = (xs + width / 2) / (width / nb)
    idx = np.minimum(u.astype(int), nb - 1)
    barr = np.array(bits)
    f = np.full(n, float(cyc))
    m = u < cursor
    f[m] = np.where(barr[idx[m]] == 1, cyc + CYC_DEV, cyc - CYC_DEV)
    ph = np.concatenate([[0.0], np.cumsum(0.5 * (f[1:] + f[:-1]) * np.diff(u))]) * TAU
    ys = amp * np.sin(ph - phase)
    cut = min(max(float(cursor), 0.0), float(nb))
    edges = sorted(set([0.0, float(nb), cut] + [float(i) for i in range(1, nb)]))
    out = []
    for a, b in zip(edges[:-1], edges[1:]):
        sel = (u >= a - 1e-9) & (u <= b + 1e-9)
        if sel.sum() < 2:
            continue
        last = np.nonzero(sel)[0][-1]
        if last + 1 < n:
            sel[last + 1] = True
        i = min(int(a), nb - 1)
        if b <= cut + 1e-9:
            out.append((xs[sel], ys[sel], ONE if bits[i] else ZERO, 1.0))
        else:
            out.append((xs[sel], ys[sel], INK, 0.55))
    return out


def wave_ph(cursor, phase, cyc, y, amp, bits=HERO_BITS):
    g = VGroup()
    for xs, ys, col, op in pieces_ph(cursor, phase, cyc, amp, bits):
        v = VMobject(stroke_color=col, stroke_width=SW_LINE, stroke_opacity=op)
        v.set_points_as_corners(np.column_stack([xs, ys + y, np.zeros_like(xs)]))
        g.add(v)
    return g


def carrier_ph(cyc, phase, y=Y2, amp=A2):
    ps = pieces_ph(0.0, phase, cyc, amp)
    xs, ys = np.concatenate([q[0] for q in ps]), np.concatenate([q[1] for q in ps])
    v = VMobject(stroke_color=INK, stroke_width=SW_LINE, stroke_opacity=0.55)
    return v.set_points_as_corners(np.column_stack([xs, ys + y, np.zeros_like(xs)]))


# ---- frequency trace (row 1) ----
class FreqTrace(VGroup):
    """Frequency-against-time trace of `bits`. Attributes: zero (dashed centre line), segs (one coloured piece per bit),
    risers (step trace only), dots (sample dot at each slot centre, if dots=True), links (thin line from each dot up to
    `link_y`, if given), hi/lo/mid (labels at the right end, if given). The whole group is what the seams carry."""


def _smooth_level(u, bits, sigma):
    """Frequency level in -1..1 at bit position u: the bit sequence convolved with a Gaussian of width sigma (bits)."""
    v = np.vectorize(_erf)
    nb = len(bits)
    y = np.zeros_like(u)
    for i, b in enumerate(bits):
        lo = 1.0 if i == 0 else v((u - i) / (sigma * 2 ** 0.5))            # first bit extends to -inf
        hi = -1.0 if i == nb - 1 else v((u - (i + 1)) / (sigma * 2 ** 0.5))  # last bit extends to +inf
        y += (1 if b else -1) * 0.5 * (lo - hi)
    return y


def freq_trace(bits=HERO_BITS, smooth=0.0, dev=LV, center=(0.0, Y1), width=WAVE_W, hi_text=None, lo_text=None,
               mid_text=None, dots=False, link_y=None, label_size=20, n=60):
    """smooth = 0: today's step trace (levels at centre +- dev, one segment per bit, risers). smooth > 0: the same bits with a
    Gaussian glide through every bit edge (smooth = 1: sigma 0.14 bit); the pieces are still one per bit and coloured by it, so
    Transform between smooth values works. center = (x, y) of the centre line; dev = half the level spacing."""
    cx, cy = center[0], center[1]
    nb = len(bits)
    pitch = width / nb
    g = FreqTrace()
    xl, xr = cx - width / 2, cx + width / 2
    g.zero = DashedLine([xl, cy, 0], [xr, cy, 0], dash_length=0.08, stroke_color=GRID, stroke_width=SW_THIN)
    g.segs, g.risers, g.dots, g.links = VGroup(), VGroup(), VGroup(), VGroup()
    if smooth <= 0:
        for i, b in enumerate(bits):
            x0 = xl + i * pitch
            y = cy + (dev if b else -dev)
            g.segs.add(Line([x0, y, 0], [x0 + pitch, y, 0], stroke_color=ONE if b else ZERO, stroke_width=SW_LINE))
        for i in range(nb - 1):
            if bits[i] != bits[i + 1]:
                x = xl + (i + 1) * pitch
                g.risers.add(Line([x, cy - dev, 0], [x, cy + dev, 0], stroke_color=MUTED, stroke_width=SW_THIN))
    else:
        for i, b in enumerate(bits):
            u = np.linspace(i, i + 1, n)
            ys = cy + dev * _smooth_level(u, bits, 0.14 * smooth)
            seg = VMobject(stroke_color=ONE if b else ZERO, stroke_width=SW_LINE)
            seg.set_points_as_corners(np.column_stack([xl + u * pitch, ys, np.zeros(n)]))
            g.segs.add(seg)
    g.add(g.zero, g.segs, g.risers)
    if dots:
        for i, b in enumerate(bits):
            x = xl + (i + 0.5) * pitch
            g.dots.add(Dot([x, cy + (dev if b else -dev), 0], radius=0.07, color=ONE if b else ZERO))
            if link_y is not None:
                g.links.add(Line([x, cy + (dev if b else -dev) + 0.07, 0], [x, link_y, 0], stroke_color=GRID, stroke_width=SW_THIN, stroke_opacity=0.7))
        g.add(g.links, g.dots)
    g.hi = g.lo = g.mid = None
    for attr, text, col, yy in (("hi", hi_text, ONE, cy + dev), ("lo", lo_text, ZERO, cy - dev), ("mid", mid_text, MUTED, cy)):
        if text:
            setattr(g, attr, label(text, label_size, col).next_to([xr, yy, 0], RIGHT, buff=0.2))
            g.add(getattr(g, attr))
    return g


def slot_guides(y_top, y_bot, center_x=0.0, width=WAVE_W, nb=8, opacity=0.6):
    """Thin dashed guide at every bit edge (nb + 1 of them), from y_top down to y_bot."""
    pitch = width / nb
    return VGroup(*[DashedLine([center_x - width / 2 + i * pitch, y_top, 0], [center_x - width / 2 + i * pitch, y_bot, 0],
                               dash_length=0.08, stroke_color=GRID, stroke_width=SW_THIN, stroke_opacity=opacity) for i in range(nb + 1)])


def hero_bit_squares(center_y=BIT_Y):
    """The eight throttle bits as squares at their slot positions (the bit_cells style at scale K3, lit)."""
    allbits = bit_cells(k=K3, center=[0, center_y, 0])
    sqs = byte_bits(allbits, HERO_BYTE)
    for i in range(8):
        sqs[i].move_to([bit_x(i), center_y, 0])
    return sqs


class FskRows(VGroup):
    """The S03a picture. Attributes: bits (8 squares), row1 (FreqTrace), carrier, carrier_lab, plus, eq, wave, note,
    guides, ax_freq (title + arrow), ax_time (title + arrow)."""


def fsk_rows(cursor=8.0):
    """S03a end frame / S03b start frame: bits at y = 2.4, row 1 (step trace, `a little higher` / `a little lower`, `centre`),
    row 2 (carrier), row 3 (carrier + bits, coloured up to `cursor`; 8 = whole wave), `+` `=` signs, `wave exaggerated`, slot
    guides, `frequency` and `time` axis titles. Wave at rest (phase 0). Parts are separate attributes so a scene can animate them in."""
    g = FskRows()
    g.bits = hero_bit_squares()
    g.row1 = freq_trace(smooth=0, hi_text="a little higher", lo_text="a little lower", mid_text="centre", label_size=18)
    g.carrier = carrier_wave(CYC_A)
    g.carrier_lab = label("carrier", 22).move_to([XR + 0.95, Y2, 0])
    g.plus = label("+", 40, INK).move_to([OPX, (Y1 + Y2) / 2, 0])
    g.eq = label("=", 40, INK).move_to([OPX, Y3, 0])
    g.wave = fsk_wave(cursor, center=[0, Y3, 0], amp=A3, cyc=CYC_A)
    g.note = label("wave exaggerated", 20).move_to([0, Y3 - A3 - 0.4, 0])
    g.guides = slot_guides(BIT_Y - 0.45, Y3 - A3 - 0.1)
    g.ax_freq = VGroup(label("frequency", 20).rotate(90 * DEGREES).move_to([OPX - 0.6, Y1, 0]))
    ty = Y3 - A3 - 0.9
    g.ax_time = VGroup(label("time", 20), Arrow(ORIGIN, RIGHT * 0.8, buff=0, color=MUTED, stroke_width=SW, max_tip_length_to_length_ratio=0.3)).arrange(RIGHT, buff=0.15).move_to([XR - 0.6, ty, 0])
    g.add(g.guides, g.bits, g.row1, g.carrier, g.carrier_lab, g.plus, g.eq, g.wave, g.note, g.ax_freq, g.ax_time)
    return g


ROW1_BIG_Y, ROW1_BIG_DEV = 0.6, 0.85     # S03b/S03c: row 1 enlarged


def row1_big(smooth=0.0, dots=True, hi_text="+32 kHz", lo_text="−32 kHz"):
    """S03b end frame / S03c start frame: bits at y = 2.4, row 1 enlarged (centre y 0.6, levels +-0.85) as a step trace with its
    sample dots (thin line from each dot up to its bit square) and slot guides. Returns VGroup(guides, bits, trace); trace is a FreqTrace."""
    sq = hero_bit_squares()
    tr = freq_trace(smooth=smooth, dev=ROW1_BIG_DEV, center=(0, ROW1_BIG_Y), hi_text=hi_text, lo_text=lo_text, dots=dots,
                    link_y=BIT_Y - 0.35, label_size=22)
    gd = slot_guides(BIT_Y - 0.45, ROW1_BIG_Y - ROW1_BIG_DEV - 0.25)
    g = VGroup(gd, sq, tr)
    g.guides, g.bits, g.trace = gd, sq, tr
    return g


# ---- bits on a wire (UART in S02a, SPI data in S05) ----
class WireTrace(VGroup):
    """Attributes: segs (one coloured level per slot), risers, digits (the bit characters under the slots), guides (dashed
    slot edges, hidden by default: add them on cue), hi_lab/lo_lab, tag_l/tag_r (end tags), pitch, x(i) = centre of slot i."""


WIRE_H = 0.3


def wire_trace(bits=(1, 0, 0, 0, 1, 1, 0, 0), pitch=0.9, center=(0.0, -1.6), idle=True, tag_l="chip", tag_r="ESP32", hl=WIRE_H):
    """One horizontal trace that is high for a 1 and low for a 0, one slot of `pitch` per bit. idle=True adds a dim low slot in
    front and a dim high one behind (UART start and stop, unlabelled); SPI data uses idle=False. Same heights, colours and
    slot width in S02a and S05, so the two pictures rhyme."""
    cx, cy = center
    seq = ([0] if idle else []) + list(bits) + ([1] if idle else [])
    n = len(seq)
    x0 = cx - n * pitch / 2
    g = WireTrace()
    g.pitch = pitch
    g.x = lambda i: x0 + ((1 if idle else 0) + i + 0.5) * pitch
    g.segs, g.risers, g.digits, g.guides = VGroup(), VGroup(), VGroup(), VGroup()
    for k, b in enumerate(seq):
        real = (not idle) or 0 < k < n - 1
        y = cy + (hl if b else -hl)
        s = Line([x0 + k * pitch, y, 0], [x0 + (k + 1) * pitch, y, 0], stroke_color=ONE if b else ZERO, stroke_width=SW_LINE)
        if not real:
            s.set_stroke(opacity=DIM)
        g.segs.add(s)
        if k and seq[k - 1] != b:
            g.risers.add(Line([x0 + k * pitch, cy - hl, 0], [x0 + k * pitch, cy + hl, 0], stroke_color=MUTED, stroke_width=SW_THIN))
        if real:
            g.digits.add(mono(str(b), 22, ONE if b else ZERO).move_to([x0 + (k + 0.5) * pitch, cy - hl - 0.35, 0]))
    for k in range(n + 1):
        g.guides.add(DashedLine([x0 + k * pitch, cy - hl - 0.15, 0], [x0 + k * pitch, cy + hl + 0.15, 0], dash_length=0.06,
                                stroke_color=GRID, stroke_width=SW_THIN))
    g.hi_lab = label("high = 1", 20, ONE).move_to([x0 - 1.0, cy + hl, 0])
    g.lo_lab = label("low = 0", 20, ZERO).move_to([x0 - 1.0, cy - hl, 0])
    g.tag_l = label(tag_l, 22, INK).move_to([x0 - 1.0, cy + hl + 0.75, 0]) if tag_l else None
    g.tag_r = label(tag_r, 22, INK).move_to([x0 + n * pitch + 0.6, cy + hl + 0.75, 0]) if tag_r else None
    g.add(g.segs, g.risers, g.digits, g.hi_lab, g.lo_lab, *[t for t in (g.tag_l, g.tag_r) if t is not None])
    return g


def clock_trace(n=8, pitch=0.9, center=(0.0, -2.3), idle=False, hl=WIRE_H):
    """SPI clock: a square wave, one pulse per slot (high in the first half of the slot). Returns a MUTED VMobject; its rising
    edges are at x = x0 + k * pitch (x0 = center x - n * pitch / 2, +pitch if idle)."""
    cx, cy = center
    x0 = cx - (n + (2 if idle else 0)) * pitch / 2 + (pitch if idle else 0)
    pts = [[x0, cy - hl, 0]]
    for k in range(n):
        a = x0 + k * pitch
        pts += [[a, cy - hl, 0], [a, cy + hl, 0], [a + pitch / 2, cy + hl, 0], [a + pitch / 2, cy - hl, 0]]
    pts.append([x0 + n * pitch, cy - hl, 0])
    return VMobject(stroke_color=MUTED, stroke_width=SW_LINE).set_points_as_corners(pts)


# ---- spectrum panel (S03b, S03c): ILLUSTRATIVE curves, not measured ----
def spectrum_curve(sharp, center=ORIGIN, w=5.0, h=2.0, color=YELLOW_A, wide=1.0):
    """Illustrative spectrum, NOT a measurement (storyboard flag T4): a hump whose width and skirts follow `sharp`
    (0 = smooth glide, narrow, no skirts; 1 = abrupt jump, wider hump and long low skirts). `wide` scales the width (ESP32 > E8)."""
    x = np.linspace(-w / 2, w / 2, 220)
    core_w = (0.045 + 0.05 * sharp) * w * wide
    skirt_w = (0.10 + 0.22 * sharp) * w * wide
    y = np.exp(-(x / core_w) ** 2) + 0.28 * sharp * np.exp(-np.abs(x) / skirt_w)
    y = h * y / 1.3
    return VMobject(stroke_color=color, stroke_width=SW_LINE).set_points_as_corners(
        np.column_stack([x + center[0], y + center[1] - h / 2, np.zeros_like(x)]))


def spectrum_panel(sharp=0.0, center=ORIGIN, w=5.6, h=2.6, curve=True):
    """Small axes (horizontal `frequency`, vertical `strength`) and one curve. Attributes: axes, curve, x_lab, y_lab."""
    g = VGroup()
    cx, cy = center[0], center[1]
    ax = VGroup(Arrow([cx - w / 2, cy - h / 2, 0], [cx + w / 2, cy - h / 2, 0], buff=0, color=MUTED, stroke_width=SW, max_tip_length_to_length_ratio=0.05),
                Arrow([cx - w / 2, cy - h / 2, 0], [cx - w / 2, cy + h / 2, 0], buff=0, color=MUTED, stroke_width=SW, max_tip_length_to_length_ratio=0.07))
    g.axes = ax
    g.x_lab = label("frequency", 20).next_to([cx + w / 2, cy - h / 2, 0], DOWN, buff=0.1).align_to([cx + w / 2, 0, 0], RIGHT)
    g.y_lab = label("strength", 20).rotate(90 * DEGREES).next_to([cx - w / 2, cy + h / 2, 0], LEFT, buff=0.1).align_to([0, cy + h / 2, 0], UP)
    g.curve = spectrum_curve(sharp, [cx, cy - 0.0, 0], w * 0.9, h * 0.8) if curve else VMobject()
    g.add(ax, g.x_lab, g.y_lab, g.curve)
    return g


# ---- the hop plot on a TRUE frequency axis (S04a, S04b) ----
HP_W = 18 * SLOT_W                       # 12.6: 18 slots
HP_H = 7.4                               # channel numbers 0..246
HP_UNIT = HP_H / 246.0                   # plot units per channel number (0.03)
HP_K = 18.0 / FW                         # label / stroke scale so text looks like normal size in the width-18 view
HP_CAM = (np.array([6.2, 3.7, 0.0]), 18.0)   # camera centre and width of the wide view
HP_PKT_H, HP_BAR_H = 0.2, 0.25           # packet and green bar heights in plot units (about 7 and 8 channel numbers)
HP_CH = [TABLE[1 + s] for s in range(18)]    # channel of slot s: 57, 112, 167, 222, 21, 76, ...
HP_WIFI = (77, 143)                      # Wi-Fi channel 6 (2427-2447 MHz) as channel numbers
HP_P0 = None                             # set below: centre of packet 0 in plot coordinates


def hp_x(slot):
    return (slot + 0.5) * SLOT_W


def hp_y(ch):
    return ch * HP_UNIT


HP_P0 = np.array([hp_x(0), hp_y(HP_CH[0]), 0.0])


class HopPlot(VGroup):
    """The wide hop plot. Attributes: axes (VGroup: arrows, titles, tick labels, GHz labels, `about 9 ms` brace), pkts (all 18
    packet blocks, positioned; only the first n_packets are in the group), arrows (arrow i joins packet i to i+1), bar (green
    one-lane rectangle across the plot), rx, tx (tags), now (the now line), dashes + brace47 + wifi (built, NOT in the group:
    scenes add them on cue). Helpers: slot_x(s), chan_y(ch), bar_y(slot)."""
    slot_x = staticmethod(hp_x)
    chan_y = staticmethod(hp_y)

    def bar_y(self, slot):
        return hp_y(HP_CH[slot])


def _hp_lab(text, size=22, color=MUTED):
    return label(text, size, color).scale(HP_K)


def hop_plot(n_packets=13, bar_slot=13, now=True, bar=True):
    """S04a end frame / S04b start frame = hop_plot(13, 13): packets 0..n_packets-1 with their arrows, the green bar waiting on
    the channel of slot `bar_slot` (None for no bar), RX and TX tags at its ends, the now line in the gap before `bar_slot`.
    Everything is in plot coordinates (x 0..12.6 = 18 slots of 0.7, y 0..7.4 = channel 0..246); view it with HP_CAM
    (centre (6.2, 3.7), width 18). Channel n is 2404 MHz + n x 299.93 kHz: 0 -> 2.404 GHz, 245 -> 2.478 GHz."""
    g = HopPlot()
    k = HP_K
    # axes
    tarrow = Arrow([0, -1.0, 0], [HP_W, -1.0, 0], buff=0, color=MUTED, stroke_width=SW * k, max_tip_length_to_length_ratio=0.02)
    tlab = _hp_lab("time").next_to([HP_W / 2, -1.0, 0], DOWN, buff=0.08)
    farrow = Arrow([-2.3, 0, 0], [-2.3, HP_H, 0], buff=0, color=MUTED, stroke_width=SW * k, max_tip_length_to_length_ratio=0.03)
    flab = _hp_lab("frequency").rotate(90 * DEGREES).next_to(farrow, LEFT, buff=0.08)
    ticks = VGroup()
    for t, c, dy in (("channel 0", 0, 0.0), ("channel 100", 100, 0.0), ("channel 200", 200, 0.0), ("2.404 GHz", 0, -0.4), ("2.478 GHz", 246, 0.0)):
        o = _hp_lab(t, 18)
        ticks.add(o.move_to([-0.9 - o.width / 2, hp_y(c) + dy, 0]))
    ticks[3:].set_opacity(0.8)
    brace = Brace(Line([0.1 * SLOT_W, -0.1, 0], [0.9 * SLOT_W, -0.1, 0]), DOWN, buff=0.0, color=MUTED, stroke_width=1).scale(k)
    nine = _hp_lab("about 9 ms", 20).next_to(brace, DOWN, buff=0.05)
    g.axes = VGroup(tarrow, tlab, farrow, flab, ticks, brace, nine)
    # packets, arrows
    g.pkts = [Rectangle(width=PKT_W, height=HP_PKT_H, color=YELLOW_A, fill_color=YELLOW_A, fill_opacity=0.9, stroke_width=0)
              .move_to([hp_x(s), hp_y(HP_CH[s]), 0]) for s in range(18)]
    g.arrows = [Arrow(g.pkts[s].get_right(), g.pkts[s + 1].get_left(), buff=0.03, color=YELLOW_A, stroke_width=SW_THIN * k,
                      tip_length=0.14, max_tip_length_to_length_ratio=0.25, max_stroke_width_to_length_ratio=20) for s in range(17)]
    # green bar and tags
    g.bar = Rectangle(width=HP_W, height=HP_BAR_H, stroke_color=GREEN_A, stroke_width=SW * k, fill_color=GREEN_A, fill_opacity=0.2)
    g.rx = _hp_lab("RX", 22, GREEN_A)
    g.tx = _hp_lab("TX", 22, BLUE_A)
    g.now = Line([0, -0.1, 0], [0, HP_H + 0.1, 0], stroke_color=MUTED, stroke_width=SW_THIN * k)
    if bar_slot is not None:
        y = hp_y(HP_CH[bar_slot])
        g.bar.move_to([HP_W / 2, y, 0])
        g.rx.next_to(g.bar, RIGHT, buff=0.15)
        g.tx.next_to(g.bar, LEFT, buff=0.15)
    g.now.set_x(bar_slot * SLOT_W if bar_slot is not None else n_packets * SLOT_W)
    # optional pieces, built but not added
    g.dashes = VGroup(*[Line([HP_W + 0.12, hp_y(c), 0], [HP_W + 0.45, hp_y(c), 0], stroke_color=MUTED, stroke_width=SW * k) for c in TABLE])
    g.brace47 = VGroup(Brace(Line([0, 0, 0], [0, HP_H, 0]), RIGHT, buff=0.0, color=MUTED, sharpness=1.0).scale(k).shift(RIGHT * (HP_W + 0.55)))
    g.wifi = Rectangle(width=HP_W, height=(HP_WIFI[1] - HP_WIFI[0]) * HP_UNIT, stroke_width=0, fill_color=RED_A, fill_opacity=0.25).move_to(
        [HP_W / 2, hp_y(sum(HP_WIFI) / 2), 0])
    g.add(g.axes, *g.pkts[:n_packets], *g.arrows[:max(n_packets - 1, 0)])
    if bar and bar_slot is not None:
        g.add(g.bar, g.rx, g.tx)
    if now:
        g.add(g.now)
    return g


# ---- the strip, the seams ----
class Seam:
    """The exact carry-over between two scenes. `mobs` = VGroup of mobjects (positioned for `cam`), `cam` = (centre, width) of
    the MovingCamera frame, `strip` = dict(pos, dim, focus), `caption` = text or None, `three_d` = dict(phi, theta) for a
    ThreeDScene. `.enter(scene)` puts the whole frame on a fresh scene and returns the strip so the scene can animate it."""

    def __init__(self, mobs=None, cam=(ORIGIN, FW), strip=None, caption=None, three_d=None, note=""):
        self.mobs = mobs if mobs is not None else VGroup()
        self.cam, self.strip_kw, self.caption_text, self.three_d, self.note = cam, strip or dict(pos=K_KEY), caption, three_d, note
        self.strip = None
        self.caption = None

    def enter(self, scene):
        if self.three_d:
            scene.set_camera_orientation(phi=self.three_d["phi"], theta=self.three_d["theta"])
            self.strip = MapStrip(**self.strip_kw)
            scene.add(self.mobs)
            scene.add_fixed_in_frame_mobjects(self.strip)
            return self.strip
        frame = scene.camera.frame
        frame.set(width=self.cam[1]).move_to(self.cam[0])
        self.strip = MapStrip(frame_fn=lambda: (frame.get_center(), frame.width), **self.strip_kw)
        scene.add(self.strip, self.mobs)
        if self.caption_text:
            self.caption = caption_at(frame, self.caption_text, 32)
            scene.add(self.caption)
        return self.strip

    def leave(self, scene):
        keep = getattr(scene.camera, "frame", None)
        scene.remove(*[m for m in scene.mobjects if m is not keep])
        for m in scene.foreground_mobjects[:] if hasattr(scene, "foreground_mobjects") else []:
            scene.remove(m)


def seam_s00_s01():
    """S00 end = S01 start: the strip parked, marker on `keyboard`, nothing else."""
    return Seam(strip=dict(pos=K_KEY))


def seam_s01_s02a():
    """S01 end = S02a start: `1150 µs` centred, strip parked, marker on `browser`."""
    return Seam(hero_number(), strip=dict(pos=K_APP))


def seam_s02a_s02b():
    """S02a end = S02b start: `1150 µs` centred, strip parked, marker on `ESP32`."""
    return Seam(hero_number(), strip=dict(pos=K_ESP))


def seam_s02b_s03a(side="out"):
    """S02b end (side='out': camera width UZOOM_W on the bits at scale 1) = S03a start (side='in': full frame, bits at scale K3
    centred at y = BIT_Y). The same picture: the throttle's eight bits lit, the other 152 dim, strip parked on `ESP32`."""
    if side == "in":
        return Seam(bit_cells(k=K3, center=[0, BIT_Y, 0]), strip=dict(pos=K_ESP))
    return Seam(bit_cells(k=1.0, center=ORIGIN), cam=(np.array([0, -BIT_Y * UZOOM_W / FW, 0]), UZOOM_W), strip=dict(pos=K_ESP))


def seam_s03a_s03b():
    """S03a end = S03b start: fsk_rows() (bits, three rows, slot guides, wave at rest), strip parked on `ESP32`, not dimmed yet."""
    return Seam(fsk_rows(), strip=dict(pos=K_ESP))


def seam_s03b_s03c():
    """S03b end = S03c start: bits at y = 2.4 and row 1 enlarged (step trace +-32 kHz, sample dots, slot guides); strip DIM."""
    return Seam(row1_big(), strip=dict(pos=K_ESP, dim=True))


def seam_s03c_s04a(side="out"):
    """S03c end (side='out': packet_block_big() centred, full frame) = S04a start (side='in': packet_block() at HP_P0 seen
    through a CLOSE_W camera). Same picture; strip parked on `ESP32`. HP_P0 is packet 0 in hop-plot coordinates."""
    if side == "in":
        return Seam(packet_block().move_to(HP_P0), cam=(HP_P0, CLOSE_W), strip=dict(pos=K_ESP))
    return Seam(packet_block_big(), strip=dict(pos=K_ESP))


def seam_s04a_s04b():
    """S04a end = S04b start: the wide hop plot hop_plot(13, 13) seen through HP_CAM; strip parked, marker on `2.4 GHz`."""
    return Seam(hop_plot(13, 13), cam=HP_CAM, strip=dict(pos=K_AIR))


def seam_s04b_s05(side="out"):
    """S04b end (side='out': camera width STREAM_W on our packet, neighbours dim, caption STREAM_CAP) = S05 start (side='in': the
    same seen at full frame: packet_stream_close(), caption at the bottom; S05 is a ThreeDScene, so its objects are fixed in frame)."""
    if side == "in":
        blk, side_blocks = packet_stream_close()
        return Seam(VGroup(side_blocks, blk), strip=dict(pos=K_AIR), caption=STREAM_CAP)
    c = np.array([0, 0, 0.0])
    ours = packet_block().move_to(c)
    side_blocks = VGroup(*[packet_block().set_fill(opacity=DIM).move_to(c + RIGHT * d * SLOT_W) for d in (-1, 1)])
    return Seam(VGroup(side_blocks, ours), cam=(c, STREAM_W), strip=dict(pos=K_AIR), caption=STREAM_CAP)


def seam_s05_s06():
    """S05 end = S06 start (both ThreeDScene): the lifted 3D quad (quad3d_lifted()) at QUAD_PHI/QUAD_THETA, strip parked on
    `motors`. Returns the Seam; `.quad`, `.props` are the quad and its blades."""
    q, props = quad3d_lifted()
    s = Seam(q, strip=dict(pos=K_MOT), three_d=dict(phi=QUAD_PHI, theta=QUAD_THETA))
    s.quad, s.props = q, props
    return s


def skeleton(scene, name, seam_in, seam_out):
    """Skeleton body for a scene file: enter the incoming seam, one narrated second, cut to the outgoing seam, hold briefly."""
    seam_in.enter(scene)
    with scene.voiceover(text=f"Scene {name}.") as tr:
        scene.wait(max(tr.duration, 1.0))
    seam_in.leave(scene)
    seam_out.enter(scene)
    scene.wait(0.5)
