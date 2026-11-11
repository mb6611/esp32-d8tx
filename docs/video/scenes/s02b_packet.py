"""S02B: D8 counts in ticks (1 us = 1.5 ticks) -> 1150 x 1.5 = 1725 -> 0x6bd (3 hex digits = 12 bits) -> the bracketed
20-byte packet (length, ID, bookkeeping, 8 control channels in 12 bytes, checksum) -> the 12-bit split (low 8 bits a byte,
top 4 bits share a byte with the next channel's) -> 160 bits; the camera moves in on the throttle's bits (the only camera move).
Facts: raw = (us*3+1)/2 = 1725 = 0x6bd (firmware/main/packet.c d8_us_to_raw); byte layout packet.c d8_build_body:
11, txid 42 b2, 00 counter 01, eight 12-bit channels (throttle low byte body[6], its top nibble in body[10]), CRC-16 last.
20 bytes x 8 = 160 bits (parts.PBITS); the 48 preamble/sync bits that also go on air are left out on purpose."""
import re, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import parts
from parts import *

# storyboard labels (parts.GROUPS still says header / counter / 8 stick values); packet_row reads the module global
parts.GROUPS[:] = [(0, 1, "length"), (1, 3, "ID"), (3, 6, "bookkeeping"), (6, 18, "8 control channels"), (18, 20, "checksum")]

ROW_Y = -0.6
HX_Y = ROW_Y + 1.75
HX_K = 0.6
ROW_DIM = 0.5
TINY = 0.25                       # the 160 bits first appear this small so all of them fit in the frame


def cx(i):
    return (i - 9.5) * BPITCH


def ruler(n, w, y, color=STRUCT):
    """A ruler of n equal cells, width w, centred on x = 0 at height y."""
    h = 0.32
    cells = VGroup(*[Rectangle(width=w / n, height=h, color=color, stroke_width=SW)
                     .move_to([-w / 2 + (j + 0.5) * w / n, y, 0]) for j in range(n)])
    return cells


class _Timed:
    def __init__(self, scene, cm):
        self.scene, self.cm = scene, cm

    def __enter__(self):
        tr = self.cm.__enter__()
        self.scene._t_start = self.scene.renderer.time
        print(f'[S02B] t={self.scene._t_start:6.2f} dur={tr.duration:5.2f}', flush=True)
        return tr

    def __exit__(self, *a):
        return self.cm.__exit__(*a)


class S02B(Narrated, MovingCameraScene):
    def cap(self, text, size=32):
        return caption_at(self.camera.frame, text, size)

    def say(self, text):
        """voiceover with bookmark marks resolved locally (this voice has no word timings): a mark waits until its share of the
        spoken characters has played. Returns the voiceover context; self._t0 / self._marks feed self.at()."""
        pos, plain, out = {}, "", []
        for part in re.split(r"(<bookmark mark='\w+'/>)", text):
            m = re.match(r"<bookmark mark='(\w+)'/>", part)
            if m:
                pos[m.group(1)] = len(spoken(plain))
            else:
                plain += part
        self._marks = {k: v / max(1, len(spoken(plain))) for k, v in pos.items()}
        return _Timed(self, self.voiceover(text=re.sub(r"<bookmark mark='\w+'/>", "", text)))

    def at(self, tr, mark):
        w = self._marks[mark] * tr.duration - (self.renderer.time - self._t_start)
        if w > 0.02:
            self.wait(w)

    def construct(self):
        frame = self.camera.frame
        seam = seam_s02a_s02b()
        strip = seam.enter(self)
        hero = seam.mobs                                     # `1150 µs`, centred
        self.wait(0.3)

        # ---- 1. ticks: 1 us = 1.5 ticks (two rulers of the same length, 2 cells and 3 cells) ----
        RW = 3.0
        up, lo = ruler(2, RW, -1.7), ruler(3, RW, -2.2)
        lbl_tk = label("ticks", 26, YELLOW_A).next_to(lo, RIGHT, buff=0.25)
        lbl_us = label("µs", 26).next_to(up, RIGHT, buff=0.25)
        b_up = Brace(up[0], UP, buff=0.08, color=MUTED, sharpness=1.5).set_stroke(width=0)
        t_up = label("1 µs", 24, YELLOW_A).next_to(b_up, UP, buff=0.06)
        one_cell = VGroup(up[0])
        b_lo = Brace(Line(lo[0].get_left(), [lo[0].get_left()[0] + RW / 2, -2.2, 0]), DOWN, buff=0.22, color=MUTED, sharpness=1.5).set_stroke(width=0)
        t_lo = label("1.5 ticks", 24, YELLOW_A).next_to(b_lo, DOWN, buff=0.06)
        cap1 = self.cap("1 µs = 1.5 ticks")
        with self.say("D8 counts in <bookmark mark='a'/>smaller ticks, <bookmark mark='b'/>one and a half to a <bookmark mark='c'/>microsecond, "
                                 "so each value is <bookmark mark='d'/>multiplied by 1.5, and <bookmark mark='e'/>1150 becomes 1725: "
                                 "<bookmark mark='f'/>the same throttle in a <bookmark mark='g'/>smaller unit.") as tr:
            self.wait(0.3)                                  # ruler draws as "smaller ticks" is spoken (was ~1.4 s late)
            self.play(Create(lo), FadeIn(lbl_tk), run_time=0.7)
            self.at(tr, 'b')
            self.play(Create(up), FadeIn(lbl_us), FadeIn(cap1), run_time=0.7)
            self.play(FadeIn(b_lo), FadeIn(t_lo), run_time=0.5)
            self.at(tr, 'c')
            self.play(FadeIn(b_up), FadeIn(t_up), Indicate(hero[1], color=YELLOW_A, scale_factor=1.3), run_time=0.8)

            lhs = hero_number(54)
            times = label("× 1.5", 54, INK)
            eq = label("=", 54, INK)
            r = num("1725", 54, YELLOW_A)
            tk = label("ticks", 27, YELLOW_A)
            row = VGroup(lhs, times, eq, r, tk).arrange(RIGHT, buff=0.3).move_to([0, 0.3, 0])
            tk.align_to(r, DOWN)
            times.set_y(lhs[0].get_center()[1]); eq.set_y(lhs[0].get_center()[1])
            self.at(tr, 'd')
            self.play(ReplacementTransform(hero, lhs), FadeOut(VGroup(up, lo, lbl_us, lbl_tk, b_up, t_up, b_lo, t_lo)),
                      FadeOut(cap1), FadeIn(times, shift=RIGHT * 0.2), run_time=1.0)
            self.at(tr, 'e')
            self.play(FadeIn(eq), run_time=0.3)
            self.play(FadeIn(r), FadeIn(tk), run_time=0.6)

            # ---- 3. the gauge returns: same position, smaller unit ----
            gy = -1.9
            gl = Line([-4, gy, 0], [4, gy, 0], color=STRUCT, stroke_width=SW)
            k0 = Line([-4, gy - 0.1, 0], [-4, gy + 0.1, 0], color=STRUCT, stroke_width=SW)
            k1 = Line([4, gy - 0.1, 0], [4, gy + 0.1, 0], color=STRUCT, stroke_width=SW)
            l0 = label("1000", 24).next_to(k0, DOWN, buff=0.15)
            l1 = label("2000", 24).next_to(k1, DOWN, buff=0.15)
            u0 = label("µs", 20).next_to(l0, RIGHT, buff=0.1, aligned_edge=DOWN)
            u1 = label("µs", 20).next_to(l1, RIGHT, buff=0.1, aligned_edge=DOWN)
            mk = Dot([-2.8, gy, 0], color=YELLOW_A, radius=0.1)
            pct = label("15 %", 24, YELLOW_A).next_to(mk, UP, buff=0.3)
            gauge = VGroup(gl, k0, k1, l0, l1, u0, u1, mk, pct)
            cap3 = self.cap("same position, smaller unit")
            self.at(tr, 'f')
            self.play(FadeIn(gauge, shift=UP * 0.15), run_time=0.8)
            self.at(tr, 'g')
            n0 = label("1500", 24).move_to(l0).align_to(l0, LEFT)
            n1 = label("3000", 24).move_to(l1).align_to(l1, RIGHT)
            v0 = label("ticks", 20).next_to(n0, RIGHT, buff=0.1, aligned_edge=DOWN)
            v1 = label("ticks", 20).next_to(n1, RIGHT, buff=0.1, aligned_edge=DOWN)
            self.play(Transform(l0, n0), Transform(l1, n1), Transform(u0, v0), Transform(u1, v1), FadeIn(cap3), run_time=0.9)

        # ---- 4. 1725 -> 0x6bd: three hex digits, 12 bits ----
        hx = mono("0x6bd", 80, YELLOW_A).move_to([0, 0.5, 0])
        digits = [hx[0][2], hx[0][3], hx[0][4]]
        capx = self.cap("1725 in hex: a 12-bit value")
        grp = [mono(s, 30, YELLOW_A) for s in ("0110", "1011", "1101")]
        spread = [-1.4, 0.0, 1.4]                           # the digits drift apart so each has room for its four bits
        for g, x in zip(grp, spread):
            g.move_to([x, 0.5 - 1.0, 0])
        brs = [Brace(g, DOWN, buff=0.08, color=MUTED, sharpness=1.5).set_stroke(width=0) for g in grp]
        l12 = label("12 bits", 28, YELLOW_A).next_to(VGroup(*brs), DOWN, buff=0.12)
        with self.say("In hex that is <bookmark mark='a'/>6BD: <bookmark mark='b'/>three hex digits, which is <bookmark mark='c'/>12 bits.") as tr:
            self.at(tr, 'a')
            r.generate_target(); r.target.move_to([0, 0.5, 0])
            self.play(FadeOut(lhs), FadeOut(times), FadeOut(eq), FadeOut(tk), FadeOut(gauge), FadeOut(cap3), MoveToTarget(r), run_time=0.5)
            self.play(TransformMatchingShapes(r, hx, path_arc=-60 * DEGREES), FadeIn(capx), run_time=0.8)
            self.at(tr, 'b')
            self.play(*[d.animate.set_x(x) for d, x in zip(digits, spread)], hx[0][0].animate.set_x(-2.7), hx[0][1].animate.set_x(-2.3), run_time=0.4)
            for g, b in zip(grp, brs):
                self.play(FadeIn(g, shift=DOWN * 0.15), FadeIn(b), run_time=0.3)
            self.at(tr, 'c')
            self.play(FadeIn(l12), run_time=0.5)

        # ---- 5-10. the bracketed packet ----
        prow = packet_row(center=[0, ROW_Y, 0], lab_size=22)
        cells, br, lb = prow["cells"], prow["braces"], prow["labels"]
        c6, c7, c10 = cells[6], cells[7], cells[10]
        cap = self.cap("one D8 packet: 20 bytes")
        with self.say("A D8 packet is 20 bytes.") as tr:
            self.play(FadeOut(capx), FadeOut(VGroup(*grp, *brs, l12)), run_time=0.35)
            self.play(hx.animate.scale(HX_K).move_to([0, HX_Y + 0.15, 0]),
                      FadeIn(cells), FadeIn(cap), run_time=1.0)

        def light(a, b, prev=None):
            anims = []
            if prev:
                anims += [cell_alpha_anim(cells[i], ROW_DIM) for i in range(*prev)]
            anims += [cell_alpha_anim(cells[i], 1.0) for i in range(a, b)]
            return anims

        with self.say("A length byte.") as tr:
            self.play(FadeOut(cap), FadeIn(br[0]), FadeIn(lb[0]), *light(0, 1),
                      *[cell_alpha_anim(cells[i], ROW_DIM) for i in range(1, 20)], run_time=0.7)
        with self.say("The transmitter's two-byte ID, so the drone only listens to its own transmitter.") as tr:
            self.play(FadeIn(br[1]), FadeIn(lb[1]), *light(1, 3, (0, 1)), run_time=0.7)
        cnt = label("counter", 20, YELLOW_A).next_to(c6[0], DOWN, buff=0.1)      # placeholder, repositioned below
        cnt.next_to(cells[4], DOWN, buff=0.12)
        seq = mono("00, 01, 02, …", 18, MUTED).set_opacity(0.6).next_to(cnt, RIGHT, buff=0.15)
        with self.say("Three bookkeeping bytes, one of them <bookmark mark='a'/>a counter that numbers the packets.") as tr:
            self.play(FadeIn(br[2]), FadeIn(lb[2]), *light(3, 6, (1, 3)), run_time=0.7)
            self.at(tr, 'a')
            self.play(Indicate(cells[4], color=YELLOW_A, scale_factor=1.2), FadeIn(cnt), FadeIn(seq), run_time=0.9)
        cnt12 = label("12 bytes", 22, YELLOW_A)
        cb = Brace(VGroup(*cells[6:18]), DOWN, buff=0.1, color=MUTED, sharpness=1.5).set_stroke(width=0)
        cnt12.next_to(cb, DOWN, buff=0.06)
        with self.say("The eight control channel values, in <bookmark mark='a'/>12 bytes.") as tr:
            self.play(FadeOut(VGroup(cnt, seq)), FadeIn(br[3]), FadeIn(lb[3]), *light(6, 18, (3, 6)), run_time=0.8)
            self.at(tr, 'a')
            self.play(FadeIn(cb), FadeIn(cnt12), run_time=0.5)
        with self.say("And a <bookmark mark='a'/>two-byte checksum, so the receiver can check that <bookmark mark='b'/>nothing got corrupted in the air.") as tr:
            self.play(FadeOut(VGroup(cb, cnt12)), *[cell_alpha_anim(cells[i], ROW_DIM) for i in range(6, 18)], run_time=0.5)
            self.at(tr, 'a')
            self.play(FadeIn(br[4]), FadeIn(lb[4]), *light(18, 20), run_time=0.6)
            self.at(tr, 'b')
            self.play(Indicate(VGroup(cells[18], cells[19]), color=RED_A, scale_factor=1.15), run_time=1.2)

        # ---- 11-14. the 12-bit split ----
        g0x, g6, gbd = VGroup(*hx[0][:2]), hx[0][2], VGroup(*hx[0][3:])
        capb = self.cap("12 bits: one byte and a half")
        l6 = label("top 4 bits", 24)
        lbd = label("low 8 bits", 24)
        with self.say("Twelve bits is a byte and a half, so D8 <bookmark mark='a'/>splits each value.") as tr:
            self.play(FadeOut(br), FadeOut(lb), *[cell_alpha_anim(cells[i], ROW_DIM) for i in (18, 19)],
                      *[cell_alpha_anim(cells[i], ROW_DIM) for i in range(0, 0)], FadeIn(capb), run_time=0.7)
            self.remove(hx)
            self.add(g0x, g6, gbd)
            self.at(tr, 'a')
            self.play(FadeOut(g0x), g6.animate.move_to([cx(10) - 0.15, HX_Y, 0]), gbd[0].animate.move_to([cx(6) - 0.14, HX_Y, 0]),
                      gbd[1].animate.move_to([cx(6) + 0.14, HX_Y, 0]), run_time=0.8)
            l6.next_to(g6, UP, buff=0.14); lbd.next_to(gbd, UP, buff=0.14)
            self.play(FadeIn(l6), FadeIn(lbd), run_time=0.5)

        def land(chars, text, col):
            return VGroup(*[mono(ch, BHEX, col).move_to(m) for ch, m in zip(text, chars)])
        ld_bd, ld_6 = land(c6[1], "bd", YELLOW_A), land(c10[1][1:], "6", YELLOW_A)
        ld_ca, ld_8 = land(c7[1], "ca", BLUE_A), land(c10[1][:1], "8", BLUE_A)
        for m in (*c6[1], *c10[1]):
            m.set_fill(opacity=0)                           # destinations start empty (the copies above are invisible)
        c2 = self.cap("the low 8 bits fill one byte")
        with self.say("The low 8 bits, BD, get a byte of their own.") as tr:
            self.play(FadeOut(capb), FadeOut(lbd), FadeOut(l6), c6[0].animate.set_stroke(YELLOW_A, opacity=1), run_time=0.4)
            self.play(*[ReplacementTransform(gbd[j], ld_bd[j], path_arc=40 * DEGREES) for j in range(2)], FadeIn(c2), run_time=1.0)
        c3 = self.cap("the top 4 bits take half of another")
        c4 = self.cap("the next channel fills the other half")
        hx2 = mono("0x8ca", 72, BLUE_A).scale(HX_K).move_to([cx(8), HX_Y, 0])
        l2 = label("next channel", 24).next_to(hx2, UP, buff=0.14)
        with self.say("The top 4 bits, the 6, share a byte <bookmark mark='a'/>with the top 4 of the next channel.") as tr:
            self.play(FadeOut(c2), c10[0].animate.set_stroke(YELLOW_A, opacity=0.9), run_time=0.3)
            self.play(ReplacementTransform(g6, ld_6[0], path_arc=-40 * DEGREES), FadeIn(c3), run_time=1.0)
            self.at(tr, 'a')
            for m in c7[1]:
                m.set_fill(opacity=0)
            self.remove(hx2); self.add(*hx2[0])
            self.play(FadeOut(c3), FadeIn(hx2[0]), FadeIn(l2), run_time=0.5)
            self.play(FadeOut(VGroup(*hx2[0][:2])), FadeOut(l2), FadeIn(c4), c7[0].animate.set_stroke(BLUE_A, opacity=0.9),
                      *[ReplacementTransform(hx2[0][3 + j], ld_ca[j], path_arc=40 * DEGREES) for j in range(2)],
                      ReplacementTransform(hx2[0][2], ld_8[0], path_arc=-40 * DEGREES), run_time=1.1)
        c5 = self.cap("8 channels fit in 12 bytes, not 16")
        with self.say("So eight channels fit in 12 bytes instead of 16.") as tr:
            self.play(FadeOut(c4), FadeIn(c5), ld_ca.animate.set_color(INK).set_opacity(ROW_DIM),
                      ld_8.animate.set_color(INK), c7[0].animate.set_stroke(STRUCT, opacity=ROW_DIM), run_time=0.8)
            rem = tr.duration - 0.8 - 0.3
            if rem > 1.0:
                self.play(LaggedStart(*[Indicate(cells[i], color=YELLOW_A, scale_factor=1.15) for i in range(6, 18)], lag_ratio=0.12),
                          run_time=rem)

        # ---- 15. 160 bits; the camera moves in on the throttle's eight bits ----
        tiny = bit_cells(k=TINY, center=[-(79.5 - BYTE6_C) * UB_PITCH * TINY, -2.0, 0])
        final = bit_cells(k=1.0, center=ORIGIN)
        cam_c = np.array([0, -BIT_Y * UZOOM_W / FW, 0])
        c6cap = self.cap("the packet, as 160 ones and zeros")
        unroll = [TransformFromCopy(cells[i], byte_bits(tiny, i)) for i in range(20)]
        with self.say("Written out, the 20 bytes are <bookmark mark='a'/>160 ones and zeros.") as tr:
            self.play(FadeOut(c5), run_time=0.3)
            self.play(LaggedStart(*unroll, lag_ratio=0.08), FadeIn(c6cap), run_time=1.8)
            self.add(tiny)
            self.play(FadeOut(cells), FadeOut(ld_bd), FadeOut(ld_6), FadeOut(ld_ca), FadeOut(ld_8), FadeOut(c6cap), run_time=0.5)
            self.at(tr, 'a')
            self.wait(0.2)
            self.play(ReplacementTransform(tiny, final), frame.animate.set(width=UZOOM_W).move_to(cam_c), run_time=1.6, rate_func=smooth)
        self.wait(0.4)


def cell_alpha_anim(c, a):
    """Animation: byte cell VGroup(square, chars) to opacity a (square outline and characters)."""
    return AnimationGroup(c[0].animate.set_stroke(opacity=a), c[1].animate.set_fill(opacity=a))
