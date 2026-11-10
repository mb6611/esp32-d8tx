"""Shared style for the d8tx explainer scenes: the 3Blue1Brown look (see STYLE-3b1b.md section 4 'Look').

Sources: 3b1b/videos custom_config.yml (background #000000, text font CMU Serif) and 3b1b/manim
manimlib/default_config.yml `colors:` (BLUE_C 58C4DD, YELLOW_C FFFF00, GREEN_C 83C167, RED_C FC6255, GREY_A..E).
Manim CE ships the same hex values under the same names; the project names below shadow a few of them
(BLUE_A, GREEN_A, ...) with the *role* colours the scenes use, so always take colours from here.
All text is LaTeX (Computer Modern): `label`/`caption` are Tex (roman), `num` is Tex digits, `mono` is \texttt."""
from manim import *

# -- palette (3b1b manimlib names in the comments) --
BG = "#000000"        # custom_config.yml camera.background_color
INK = "#FFFFFF"       # WHITE: captions, the key cap letter
MUTED = "#BBBBBB"     # GREY_B: labels, braces, axis lines
STRUCT = "#888888"    # GREY_C: outlines of boxes we do not follow
GRID = "#444444"      # GREY_D: grid and structure lines (use with stroke_opacity <= 0.6)
DIM = 0.3             # opacity for everything that is not the piece while it moves
BLUE_A = "#58C4DD"    # BLUE_C: app / host, bit 1   (shadows manim's light BLUE_A on purpose)
BLUE_DK = "#29ABCA"   # BLUE_D: secondary blue (other channels, struts)
BLUE_LT = "#9CDCEB"   # BLUE_B: mechanical / drone (was purple)
GREEN_A = "#83C167"   # GREEN_C: ok / checksum good / firmware
YELLOW_A = "#FFFF00"  # YELLOW_C: the piece we follow (1150, bd, the packet)
RED_A = "#FC6255"     # RED_C: bit 0 / RF / check bytes
PURPLE_A = BLUE_LT    # no purple in the palette; kept as a name for the drone scenes
ONE = BLUE_A          # bit 1 / +39 kHz
ZERO = RED_A          # bit 0 / -39 kHz

config.background_color = BG
FW = config.frame_width   # 14.22
FH = config.frame_height  # 8

# -- strokes (frame units; CE scales them with resolution, so 480p and 1080p look alike) --
SW_THIN = 1.0         # grid, cross hairs, dashed guides
SW = 2.0              # boxes, axes, circles
SW_LINE = 3.0         # a line we follow (trace segments, arrows, hop path)
SW_FLASH = 5.0        # ShowPassingFlash pulses

_TEX_CHARS = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
              "~": r"\textasciitilde{}", "^": r"\^{}", "$": r"\$",
              "µ": r"$\mu$", "μ": r"$\mu$", "−": "$-$", "±": r"$\pm$", "×": r"$\times$", "·": r"$\cdot$",
              "✓": r"\checkmark", "→": r"$\rightarrow$", "←": r"$\leftarrow$", "↑": r"$\uparrow$", "↓": r"$\downarrow$", "÷": r"$\div$", "≈": r"$\approx$", "°": r"$^\circ$"}


def tex_escape(text):
    """Plain words (with µ − ± × · ✓) -> LaTeX text-mode source."""
    return "".join(_TEX_CHARS.get(ch, ch) for ch in text)


def caption(text, size=32):
    """Bottom caption, plain and calm, Computer Modern roman."""
    return Tex(tex_escape(text), font_size=size, color=INK).to_edge(DOWN, buff=0.5)


def caption_at(frame, text, size=32):
    """Caption pinned to the bottom of a MovingCameraScene frame, whatever its zoom."""
    s = frame.width / FW
    return Tex(tex_escape(text), font_size=size, color=INK).scale(s).move_to(frame.get_center() + DOWN * (frame.height / 2 - 0.6 * s))


def label(text, size=24, color=MUTED):
    """A word or two next to an object (CM roman)."""
    return Tex(tex_escape(text), font_size=size, color=color)


def num(text, size=26, color=INK):
    """A decimal quantity (1150): CM roman digits, like a DecimalNumber."""
    return Tex(tex_escape(str(text)), font_size=size, color=color)


def mono(text, size=26, color=INK):
    """Bytes, hex and bits: CM typewriter."""
    return Tex(r"\texttt{" + tex_escape(str(text)) + "}", font_size=size, color=color)


def scene_title(text):
    return Tex(tex_escape(text), font_size=34, color=INK).to_edge(UP, buff=0.4)


# ---- shared building blocks, so one object can carry over between scene files ----

# The hero packet: throttle 1150 µs, others 1500, arm 2000 (experiments/14: armed, throttle at the 15 % cap).
# Bytes from tools/d8-tx-host/d8_vectors.py build(0, raw) with raw = (us*3+1)//2 (firmware/main/packet.c d8_us_to_raw).
BODY = bytes.fromhex("1142b2000001bdcacaca8688cacab8ca888b")
CRC = bytes.fromhex("7109")
AIR_HEAD = bytes.fromhex("aaaaaaaad391")   # packet.c d8_air: 4 x 0xaa preamble, sync d3 91
CH = [("T", 1150), ("A", 1500), ("E", 1500), ("R", 1500), ("1", 1500), ("2", 1500), ("ARM", 2000), ("4", 1500)]
LOWI = [6, 7, 8, 9, 12, 13, 14, 15]
HIGHI = [(10, 0), (10, 4), (11, 0), (11, 4), (16, 0), (16, 4), (17, 0), (17, 4)]
HERO_BYTE = 6                                  # byte 6 = low 8 bits of throttle = 0xbd
HERO_BITS = [int(b) for b in f"{BODY[HERO_BYTE]:08b}"]  # 1 0 1 1 1 1 0 1, MSB first (packet.c sends MSB first)
BIT_PITCH = 1.3        # screen spacing of the 8 hero bits in S03 (one wave segment under each, parts.WAVE_W)
BIT_Y = 2.4


def raw(us):
    return (us * 3 + 1) // 2


def _check():
    b = bytearray(18); b[0:6] = bytes([0x11, 0x42, 0xb2, 0, 0, 1])
    for i, (_, us) in enumerate(CH):
        v = raw(us); b[LOWI[i]] = v & 255; b[HIGHI[i][0]] |= (v >> 8) << HIGHI[i][1]
    assert bytes(b) == BODY, bytes(b).hex()
    # CRC-16 poly 0x8005 init 0xffff (d8_vectors.crc16)
    c = 0xFFFF
    for x in b:
        c ^= x << 8
        for _ in range(8):
            c = ((c << 1) ^ 0x8005) & 0xFFFF if c & 0x8000 else (c << 1) & 0xFFFF
    assert bytes([c >> 8, c & 255]) == CRC, hex(c)
    assert len(AIR_HEAD) + len(BODY) + len(CRC) == 26 and 26 * 8 == 208


_check()


# ---- carry-over objects: the last frame of one scene and the first of the next are built from these ----

def hero_number(size=72):
    """`1150 µs` as it ends S01 / starts S02, centred."""
    g = VGroup(num("1150", size, YELLOW_A), label("µs", size // 2))
    g.arrange(RIGHT, buff=0.15, aligned_edge=DOWN).move_to(ORIGIN)
    return g


# byte-row geometry shared by S02 (the row) and S05 (its tiny copy)
BCELL, BPITCH = 0.6, 0.66
BHEX = 26
def bit_squares(bits=HERO_BITS, side=0.6, size=34):
    g = VGroup()
    for b in bits:
        sq = Square(side, color=ONE if b else ZERO, stroke_width=SW, fill_color=ONE if b else ZERO, fill_opacity=0.1)
        g.add(VGroup(sq, mono(str(b), size, ONE if b else ZERO).move_to(sq)))
    return g.arrange(RIGHT, buff=0.1)


# hop grid shared by S04 (the grid) and S05 (the block that arrives)
TABLE = [0] + [(2 + 55 * i) % 256 for i in range(1, 47)]   # packet.c d8_hop_table, E8 identity start 2 step 55 (packet.h)
assert len(set(TABLE)) == 47
LANES = sorted(TABLE)
SLOT_W, LANE_H = 0.7, 0.25
CLOSE_W = 5.0                  # camera width while close on one packet cell
PKT_W, PKT_H = SLOT_W * 0.75, LANE_H * 0.8   # packet 6.70 ms of the 8.994 ms slot (experiments/05, 06)


def grid_pos(slot, ch):
    return np.array([(slot + 0.5) * SLOT_W, (LANES.index(ch) + 0.5) * LANE_H, 0])


def packet_block(scale=1.0, color=YELLOW_A):
    # the one filled object: the piece itself, so it reads at any zoom (3b1b fills his highlight rects, nothing else)
    return Rectangle(width=PKT_W * scale, height=PKT_H * scale, color=color, fill_color=color, fill_opacity=0.9,
                     stroke_width=0)


def packet_block_big():
    """The packet as seen through the close camera: S04 end / S05 start, centred."""
    return packet_block(FW / CLOSE_W)


STREAM_W = 2.0                 # camera width when S04 ends zoomed on our packet in the stream row
STREAM_CAP = "our packet, carrying 1150"   # caption on the S04 end / S05 start frame


def packet_stream_close():
    """S04 end / S05 start as seen through the STREAM_W camera: VGroup(our packet, dim neighbours one slot each side)."""
    z = FW / STREAM_W
    ours = packet_block(z)
    side = VGroup(*[packet_block(z).set_fill(opacity=DIM).move_to(RIGHT * d * SLOT_W * z) for d in (-1, 1)])
    return VGroup(ours, side)


def cell_alpha(c, a):
    """Dim/undim a byte cell VGroup(square, chars) without filling the square."""
    c[0].set_stroke(opacity=a)
    c[1].set_fill(opacity=a)
    return c
