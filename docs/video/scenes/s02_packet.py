"""S02: the stick value leaves the browser as one serial line, travels down the USB cable to the ESP32 (map strip),
then `1150` -> `0x6bd` -> lands in the throttle cells of the bracketed 20-byte packet -> the whole packet unrolls
into its 160 bits (camera moves in on the throttle's bits, the carry-over frame for S03).
Facts: the browser app writes `S c1..c8\\n` (µs, order T A E R 1 2 ARM 4; packages/core/src/protocol.ts fmtSticks)
over Web Serial at 921600 8N1 (protocol/PROTOCOL.md), one line per 8.994 ms slot (link.ts paced sender).
raw = (us*3+1)/2 = 1725 = 0x6bd (firmware/main/packet.c d8_us_to_raw), shown as `x 1.5`. A stick is 12 bits: the low
8 bits get a byte, the top 4 share a byte with the next stick's top 4 (roll 1500 us -> 0x8ca), so 8 sticks take 12 bytes.
Byte layout (packet.c d8_build_body, tools/d8-tx-host/d8_vectors.py): 11, txid 42 b2, 00 counter 01, eight 12-bit sticks
(throttle low byte at body[6], its top nibble in the low nibble of body[10]), CRC-16 (poly 0x8005, init 0xffff) last.
The hero body and CRC are asserted against the builder in common._check(). 20 bytes x 8 = 160 bits (parts.PBITS);
the 48 preamble/sync bits that also go on air are left out of the picture on purpose."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from parts import *

ROW_Y = -0.6
BITS_Y = ROW_Y - 1.4
HX_Y = ROW_Y + 1.75                  # where 0x6bd waits above the row
HX_K = 0.6                     # its size there, relative to the 72-point hero
ROW_DIM = 0.5                  # the packet's other bytes: readable, but behind the throttle's
ZOOM_W = 8.6                   # camera width while 0x6bd splits into its two cells


def cx(i):
    return (i - 9.5) * BPITCH


ZX, ZY = cx(9), ROW_Y + 1.05          # centre of that close view: stick bytes 6..10 in the middle


class S02(MovingCameraScene):
    def cap(self, text, size=32):
        return caption_at(self.camera.frame, text, size)

    def construct(self):
        frame = self.camera.frame
        strip = MapStrip(K_APP, lambda: (frame.get_center(), frame.width))
        self.add(strip)
        hero = hero_number()
        self.add(hero)
        self.wait(0.3)

        # ---- stage a: the browser writes one serial line; it travels down the USB cable to the ESP32 ----
        line = mono("S 1150 1500 1500 1500 1500 1500 2000 1500", 30).move_to(ORIGIN)
        g = line[0]
        piece = VGroup(*g[1:5]).set_color(YELLOW_A)          # the 1150 inside the line
        rest = VGroup(g[0], *g[5:])
        c = self.cap("one serial line, every 9 ms")
        self.play(ReplacementTransform(hero[0], piece), FadeOut(hero[1]), FadeIn(rest), FadeIn(c), run_time=1.2)
        self.wait(0.8)
        # Write may leave family members registered; remove the whole family before the next caption.
        c2 = self.cap("down the USB cable, 921600 baud")
        self.play(strip.open(), FadeOut(c), VGroup(piece, rest).animate.shift(DOWN * 0.6), run_time=0.7)
        self.remove(c, *c.family_members_with_points())
        self.play(strip.go(K_ESP), FadeIn(c2), run_time=1.6, rate_func=linear)
        self.wait(0.3)
        hero2 = hero_number()
        self.play(strip.close(), FadeOut(c2), ReplacementTransform(piece, hero2[0]), FadeIn(hero2[1]), FadeOut(rest), run_time=0.9)
        self.wait(0.3)

        # ---- 1150 us x 1.5 = 1725, the radio's units (packet.c d8_us_to_raw: (us*3+1)/2) ----
        lhs = hero_number(60)
        times = label("× 1.5", 48, INK)
        eq = label("=", 48, INK)
        r = num("1725", 60, YELLOW_A)
        VGroup(lhs, times, eq, r).arrange(RIGHT, buff=0.4).move_to(ORIGIN)
        for m in (times, eq, r):
            m.set_y(lhs[0].get_center()[1])
        c = self.cap("times 1.5: the radio's own units")
        self.play(ReplacementTransform(hero2, lhs), FadeIn(times, shift=RIGHT * 0.2), run_time=0.8)
        self.play(TransformFromCopy(lhs[0], r, path_arc=-40 * DEGREES), FadeIn(eq), FadeIn(c), run_time=1.0)
        self.wait(1.3)

        # ---- 1725 -> 0x6bd: the same number in hex, three digits of 4 bits ----
        hx = mono("0x6bd", 72, YELLOW_A).move_to(ORIGIN)
        self.play(FadeOut(c), FadeOut(lhs), FadeOut(times), FadeOut(eq), r.animate.move_to(ORIGIN), run_time=0.6)
        self.play(TransformMatchingShapes(r, hx, path_arc=-60 * DEGREES), run_time=1.2)
        c = self.cap("1725 in hex: a 12-bit value")
        self.play(FadeIn(c), run_time=0.4)
        self.wait(1.0)

        # ---- the bracketed packet ----
        row = packet_row(center=[0, ROW_Y, 0], lab_size=22)
        dim_row(row, ROW_DIM)
        cells = row["cells"]
        c6, c7, c10 = cells[6], cells[7], cells[10]
        for m in (*c6[1], *c7[1], *c10[1]):
            m.set_fill(opacity=0)                                # destinations start empty
        self.play(FadeOut(c), hx.animate.move_to([0, HX_Y + 0.15, 0]), FadeIn(cells, shift=UP * 0.2), run_time=1.0)
        c = self.cap("the ESP32 builds the packet")
        self.play(FadeIn(row["braces"]), FadeIn(row["labels"]), FadeIn(c), run_time=0.8)
        self.wait(0.8)

        # ---- move in on the stick bytes; 0x6bd splits: low 8 bits `bd`, top 4 bits `6` ----
        side = VGroup(*[VGroup(row["braces"][i], row["labels"][i]) for i in (0, 1, 2, 4)])     # cut by the close frame: hide them
        self.play(FadeOut(c), FadeOut(side), hx.animate.scale(HX_K).move_to([ZX, HX_Y, 0]),
                  frame.animate.set(width=ZOOM_W).move_to([ZX, ZY, 0]), run_time=1.0)
        s = ZOOM_W / FW
        self.remove(hx)
        g0x, g6, gbd = VGroup(*hx[0][:2]), hx[0][2], VGroup(*hx[0][3:])
        self.add(g0x, g6, gbd)
        l6 = label("top 4 bits", 24).scale(s)
        lbd = label("low 8 bits", 24).scale(s)
        c = self.cap("12 bits: one byte and a half")
        self.play(FadeOut(g0x), g6.animate.move_to([ZX - 1.0, HX_Y, 0]), gbd.animate.move_to([ZX + 1.0, HX_Y, 0]), run_time=0.8)
        l6.next_to(g6, DOWN, buff=0.14); lbd.next_to(gbd, DOWN, buff=0.14)
        self.play(FadeIn(l6), FadeIn(lbd), FadeIn(c), run_time=0.5)
        self.wait(1.4)

        # `bd` takes a whole byte (body[6]); `6` takes half of body[10]
        def land(chars, text, col):
            return VGroup(*[mono(ch, BHEX, col).move_to(m) for ch, m in zip(text, chars)])
        ld_bd, ld_6 = land(c6[1], "bd", YELLOW_A), land(c10[1][1:], "6", YELLOW_A)
        c2 = self.cap("the low 8 bits fill one byte")
        self.play(FadeOut(c), FadeOut(lbd), c6[0].animate.set_stroke(YELLOW_A, opacity=1), run_time=0.3)
        self.play(*[ReplacementTransform(gbd[j], ld_bd[j], path_arc=40 * DEGREES) for j in range(2)], FadeIn(c2), run_time=1.1)
        self.wait(0.9)
        c = self.cap("the top 4 bits take half of another")
        self.play(FadeOut(c2), FadeOut(l6), c10[0].animate.set_stroke(YELLOW_A, opacity=0.8), run_time=0.3)
        self.play(ReplacementTransform(g6, ld_6[0], path_arc=-40 * DEGREES), FadeIn(c), run_time=1.1)
        self.wait(0.9)

        # the next stick (roll, 1500 us -> 2250 = 0x8ca) fills body[7] and the other half of body[10]
        hx2 = mono("0x8ca", 72, BLUE_A).scale(HX_K).move_to([ZX, HX_Y, 0])
        l2 = label("next stick", 24).scale(s).next_to(hx2, DOWN, buff=0.14)
        ld_ca, ld_8 = land(c7[1], "ca", BLUE_A), land(c10[1][:1], "8", BLUE_A)
        c2 = self.cap("the next stick fills the other half")
        self.play(FadeOut(c), FadeIn(hx2), FadeIn(l2), run_time=0.5)
        self.remove(hx2)
        self.add(*hx2[0])
        self.play(FadeOut(VGroup(*hx2[0][:2])), FadeOut(l2), c7[0].animate.set_stroke(BLUE_A, opacity=0.8),
                  *[ReplacementTransform(hx2[0][3 + j], ld_ca[j], path_arc=40 * DEGREES) for j in range(2)],
                  ReplacementTransform(hx2[0][2], ld_8[0], path_arc=-40 * DEGREES), FadeIn(c2), run_time=1.3)
        self.wait(1.3)

        # back out: all eight sticks packed the same way
        landed = VGroup(ld_bd, ld_6)
        other = VGroup(ld_ca, ld_8)
        self.play(FadeOut(c2), FadeIn(side), frame.animate.set(width=FW).move_to(ORIGIN), other.animate.set_color(INK).set_opacity(ROW_DIM),
                  c7[0].animate.set_stroke(STRUCT, opacity=ROW_DIM), run_time=1.0)
        c = self.cap("8 sticks fit in 12 bytes, not 16")
        self.play(FadeIn(c), run_time=0.4)
        self.wait(1.4)
        c2 = c

        # ---- the whole packet unrolls into 160 bits (throttle's bits stay lit) ----
        bits = bit_cells(center=[cx(6), BITS_Y, 0])
        unroll = [TransformFromCopy(row["cells"][i], byte_bits(bits, i)) for i in range(20)]
        self.play(FadeOut(c2), FadeOut(row["braces"]), FadeOut(row["labels"]), run_time=0.5)
        self.play(LaggedStart(*unroll, lag_ratio=0.08), frame.animate.set(width=10.5).move_to([cx(6), ROW_Y - 0.7, 0]),
                  run_time=2.6)
        self.play(FadeOut(row["cells"]), FadeOut(landed), FadeOut(other), run_time=0.6)
        c = self.cap("the packet, as 160 ones and zeros")
        self.play(FadeIn(c), run_time=0.5)
        self.wait(1.0)

        # ---- return: in on the throttle's eight bits (carry-over frame for S03) ----
        self.play(FadeOut(c), frame.animate.set(width=UZOOM_W).move_to([cx(6), BITS_Y - BIT_Y * UZOOM_W / FW, 0]),
                  run_time=1.5, rate_func=smooth)
        self.wait(0.4)
