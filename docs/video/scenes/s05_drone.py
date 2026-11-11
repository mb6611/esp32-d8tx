"""S05: the packet reaches the drone (map marker air -> CC2500) and the decode runs stages S03/S02 backwards with the
same pictures: the CC2500 catches the wave -> its squeezed/stretched stretches read back into 1s and 0s -> the bits
regroup into the bracketed packet row -> checksum ok -> marker CC2500 -> SPI -> flight controller -> `0x6bd` lifts
out of the throttle cells -> `1150` in the channel list -> four motor commands -> 3D quad, props spin, small lift.
Facts (experiments/08-first-flight-cloned-e8, 14-app-validation, tools/cc2500-rxdiag/README.md): Tinyhawk 3 with a
MATEKF411RX (STM32F411) flight controller and a CC2500 radio on SPI (3.375 MHz), Betaflight 4.2.11; the receiver
checks the CRC; Betaflight reads throttle 1150 us and arm (AUX3) 2000; at 1150 us the motors spin; full throttle lifted
the quad off the bench (08, test 8). Channel list order A E T R; only the throttle value is legible. Board names,
Betaflight version, DShot and PID are deliberately not on screen."""
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from parts import *

DX = np.array([5.5, -0.35, 0])     # drone silhouette centre (2D part)
WC5 = np.array([-1.4, 0.5, 0])    # wave centre on the drone side
WW5, WA5 = 7.6, 0.6               # wave width / amplitude
BITS_Y5 = 1.6
TRACE_Y5 = 2.4
ROW_Y8 = 0.55         # packet row while the SPI traces are shown
CLK_Y, CLK_H = -2.65, 0.22
ROW_C = np.array([-1.4, -1.55, 0])
ROW_K = 0.8


def drone_2d():
    arms = VGroup(Line(DL * 0.9, UR * 0.9), Line(DR * 0.9, UL * 0.9)).set_stroke(PURPLE_A, SW_LINE)
    motors = VGroup(*[Circle(radius=0.32, color=PURPLE_A, stroke_width=SW).move_to(0.9 * d) for d in (UR, UL, DL, DR)])
    body = RoundedRectangle(corner_radius=0.08, width=0.9, height=0.6, color=PURPLE_A, stroke_width=SW, fill_color=BG, fill_opacity=1)
    rx = Rectangle(width=0.5, height=0.3, color=RED_A, stroke_width=SW).move_to(body)
    rxl = label("CC2500", 20, RED_A).next_to(rx, DOWN, buff=0.35)
    return VGroup(arms, motors, body, rx, rxl).scale(0.85).move_to(DX)


class _Timed:
    def __init__(self, scene, cm):
        self.scene, self.cm = scene, cm

    def __enter__(self):
        tr = self.cm.__enter__()
        self.scene._t_start = self.scene.renderer.time
        self.scene._tr = tr
        return tr

    def __exit__(self, *a):
        return self.cm.__exit__(*a)


class S05(Narrated, ThreeDScene):
    def say(self, text):
        """voiceover with bookmark marks resolved locally (this voice has no word timings): a mark waits until its share of the
        spoken characters has played."""
        pos, plain = {}, ""
        for part in re.split(r"(<bookmark mark='\w+'/>)", text):
            m = re.match(r"<bookmark mark='(\w+)'/>", part)
            if m:
                pos[m.group(1)] = len(spoken(plain))
            else:
                plain += part
        self._marks = {k: v / max(1, len(spoken(plain))) for k, v in pos.items()}
        print("VO %.2f %s" % (self.renderer.time, re.sub(r"<bookmark mark='\w+'/>", "", text)), flush=True)
        return _Timed(self, self.voiceover(text=re.sub(r"<bookmark mark='\w+'/>", "", text)))

    def wait_until_bookmark(self, mark, lead=0.0):
        w = self._marks[mark] * self._tr.duration - lead - (self.renderer.time - self._t_start)
        if w > 0.02:
            self.wait(w)

    def cap(self, text, size=32):
        return caption(text, size)

    def cin(self, c):
        return FadeIn(c, rate_func=lambda t: smooth(min(1.0, max(0.0, (t - 0.4) / 0.6))))     # after the old caption has gone

    def cout(self, c):
        return FadeOut(c, rate_func=lambda t: smooth(min(1.0, t / 0.25)))

    def fix(self, *ms):
        self.add_fixed_in_frame_mobjects(*ms)
        return ms

    def construct(self):
        # incoming frame = seam_s04b_s05("in"): same pieces, built here because Seam.enter needs a MovingCamera frame
        strip = MapStrip(K_AIR)
        blk, side = packet_stream_close()
        self.fix(strip, side, blk)
        stream_caption = self.cap(STREAM_CAP).move_to(DOWN * (FH / 2 - 0.6))
        self.fix(stream_caption)
        self.wait(0.7)

        # ---- 1. the drone's radio chip ----
        drone = drone_2d()
        rx = drone[3]
        c = self.cap("the drone's radio chip: a CC2500")
        self.fix(drone, c)
        self.remove(drone, c)
        with self.say("The drone's radio chip, a CC2500, is built for FSK."):
            self.play(FadeOut(stream_caption), strip.open(), blk.animate.scale(0.5 * STREAM_W / CLOSE_W).move_to(LEFT * 3.0),
                      *[FadeOut(n, shift=d * 3.0) for n, d in zip(side, (LEFT, RIGHT))], run_time=0.8)
            self.play(strip.go(K_RX), self.cin(c), FadeIn(drone, shift=LEFT * 0.3), run_time=1.0)
            self.wait_for_voiceover()

        # ---- 2. it catches the burst; the block opens back into the wave ----
        waves = [fsk_wave(8.0, lit=i, center=WC5, width=WW5, amp=WA5) for i in range(9)]
        wave = waves[0]
        with self.say("It catches the burst,"):
            self.play(MoveAlongPath(blk, Line(LEFT * 3.0, rx.get_center())), blk.animate.scale(0.3), run_time=0.9, rate_func=linear)
            self.play(strip.close(), Flash(rx, color=RED_A, line_length=0.2, flash_radius=0.4), run_time=0.5)
            self.wait_for_voiceover()

        # ---- 3. the wave read back: trace + dots -> bit squares ----
        bits = bit_squares(side=0.5, size=28)
        for i, b in enumerate(bits):
            b.move_to([bit_x(i, WC5, WW5), BITS_Y5, 0])
        tr5 = freq_trace(HERO_BITS, 0.0, 0.22, (WC5[0], TRACE_Y5), WW5, dots=True)
        c2 = self.cap("the wave, read back into bits")
        self.fix(wave, bits, c2, tr5)
        self.remove(wave, bits, c2, tr5)
        with self.say("reads the shifts back as ones and zeros,") as tr:
            self.play(self.cout(c), ReplacementTransform(blk, wave), FadeIn(tr5.zero), run_time=0.7)
            self.play(self.cin(c2), run_time=0.3)
            step = max(0.22, (tr.duration - 1.0) / 8)
            edges = [j + 1 for j in range(7) if HERO_BITS[j] != HERO_BITS[j + 1]]
            riser_at = {e: k for k, e in enumerate(edges)}
            for i in range(8):
                self.play(Transform(wave, waves[i + 1]), Create(tr5.segs[i]),
                          *([FadeIn(tr5.risers[riser_at[i]])] if i in riser_at else []),
                          run_time=step * 0.55, rate_func=linear)
                self.play(FadeIn(tr5.dots[i], scale=1.8), TransformFromCopy(tr5.dots[i], bits[i]), run_time=step * 0.45, rate_func=linear)
            self.wait_for_voiceover()

        # ---- 4. the bits regroup into the packet ----
        row = packet_row(center=ROW_C, scale=ROW_K, hexsize=BHEX, lab_size=28)
        dim_row(row); light_throttle(row)
        cells = row["cells"]
        others = VGroup(*[cells[i] for i in range(20) if i != 6])
        c3 = self.cap("the bits, back in their packet")
        self.fix(row, c3)
        self.remove(row, c3)
        with self.say("reassembles the packet,"):
            self.play(self.cout(c2), FadeOut(wave), FadeOut(tr5), ReplacementTransform(bits, cells[6]), FadeIn(others),
                      FadeIn(row["braces"]), FadeIn(row["labels"]), self.cin(c3), run_time=1.0)
            self.wait_for_voiceover()

        # ---- 5. checksum ----
        pulse = ShowPassingFlash(Line(cells[0].get_left(), cells[19].get_right(), color=YELLOW_A, stroke_width=SW_FLASH)
                                 .shift(DOWN * (BCELL * ROW_K / 2 + 0.06)), time_width=0.3, run_time=1.0)
        self.fix(pulse.mobject)
        with self.say("and checks the checksum."):
            self.play(self.cout(c3), pulse)
            self.wait_for_voiceover()

        # ---- 6. ok ----
        tick = label("✓", 30, GREEN_A).next_to(cells[19], RIGHT, buff=0.2)
        c = self.cap("checksum ok")
        self.fix(tick, c)
        self.remove(tick, c)
        with self.say("Everything checks out."):
            self.play(cells[18][0].animate.set_stroke(GREEN_A, opacity=1), cells[19][0].animate.set_stroke(GREEN_A, opacity=1),
                      cells[18][1].animate.set_fill(GREEN_A, opacity=1), cells[19][1].animate.set_fill(GREEN_A, opacity=1),
                      FadeIn(tick, scale=0.6), self.cin(c), run_time=0.7)
            self.wait_for_voiceover()

        # ---- 7. hand-off to the flight controller over SPI ----
        c2 = self.cap("over SPI to the flight controller")
        mc = label("the drone's main computer", 18, MUTED)
        mc.move_to([NODE_X[K_FC] * MAP_FOCUS_SCALE, MAP_FOCUS_Y - 0.55, 0])
        self.fix(c2, mc)
        self.remove(c2, mc)
        with self.say("It hands the packet to the flight controller, <bookmark mark='mc'/>the drone's main computer, "
                      "over a link on the board called SPI."):
            self.play(self.cout(c), FadeOut(tick), strip.open(), run_time=0.6)
            self.play(strip.go(K_SPI), self.cin(c2), run_time=1.2)
            self.wait_until_bookmark("mc")
            self.play(FadeIn(mc), run_time=0.5)
            self.wait_for_voiceover()

        # ---- 8. like UART: bits on a wire ----
        WC_X = -0.4
        wt = wire_trace(HERO_BITS, 0.9, (WC_X, -1.2), idle=False, tag_l="CC2500", tag_r="flight ctrl")
        data_lab = label("data", 20, MUTED).move_to([-6.2, -1.2, 0])
        uart = label("UART: one wire, agreed speed", 20, MUTED).move_to([WC_X, -0.15, 0])
        c4 = self.cap("SPI: bits on a wire again")
        self.fix(wt, data_lab, uart, c4)
        self.remove(wt, data_lab, uart, c4)
        with self.say("Like <bookmark mark='u'/>UART, <bookmark mark='sb'/>SPI sends bits <bookmark mark='ow'/>over wires,"):
            self.play(self.cout(c2), FadeOut(mc), FadeOut(row["braces"]), FadeOut(row["labels"]),
                      row["cells"].animate.shift(UP * (ROW_Y8 - ROW_C[1])), run_time=0.8)
            row["braces"].set_opacity(0)
            row["labels"].set_opacity(0)
            self.wait_until_bookmark("u")
            self.play(FadeIn(uart), run_time=0.4)
            self.wait_until_bookmark("sb")
            wt.digits.set_opacity(0.0)
            self.add(wt.digits)
            self.play(*[FadeIn(wt.digits[i], shift=DOWN * 0.5) for i in range(8)],
                      *[wt.digits[i].animate.set_opacity(1) for i in range(8)], run_time=0.8)
            self.wait_until_bookmark("ow")
            self.play(Create(wt.segs, lag_ratio=1.0, rate_func=linear), FadeIn(wt.risers, lag_ratio=1.0), FadeIn(wt.hi_lab), FadeIn(wt.lo_lab),
                      FadeIn(wt.tag_l), FadeIn(wt.tag_r), FadeIn(data_lab), FadeIn(c4, rate_func=lambda t: smooth(min(1.0, t / 0.4))), run_time=1.2)
            self.wait_for_voiceover()

        # ---- 9. the clock ----
        clk = clock_trace(8, 0.9, (WC_X, CLK_Y), idle=False, hl=CLK_H)
        clk_lab = label("clock", 20, MUTED).move_to([-6.2, CLK_Y, 0])
        clk_tag = label("flight ctrl", 18, MUTED).move_to([WC_X + 4.0 + 0.6, CLK_Y, 0])
        x0 = WC_X - 4.0
        gdots, gguides = VGroup(), VGroup()
        for i, b in enumerate(HERO_BITS):
            gx = x0 + i * 0.9 + 0.225
            yd = -1.2 + (0.3 if b else -0.3)
            gguides.add(DashedLine([gx, CLK_Y + CLK_H, 0], [gx, yd, 0], dash_length=0.06, stroke_color=GRID, stroke_width=SW_THIN))
            gdots.add(Dot([gx, yd, 0], radius=0.07, color=ONE if b else ZERO))
        c5 = self.cap("the clock says when to read")
        self.fix(clk, clk_lab, clk_tag, gdots, gguides, c5)
        self.remove(clk, clk_lab, clk_tag, gdots, gguides, c5)
        with self.say("but an extra wire carries a clock <bookmark mark='w'/>that says when to read each bit."):
            self.play(self.cout(c4), Create(clk, rate_func=linear), FadeIn(clk_lab), FadeIn(clk_tag), self.cin(c5), run_time=1.5)
            self.wait_until_bookmark("w")
            self.play(FadeOut(uart), run_time=0.3)
            step = 0.4
            for i in range(8):
                self.play(Create(gguides[i]), FadeIn(gdots[i], scale=1.8), Indicate(wt.digits[i], color=YELLOW_A, scale_factor=1.4),
                          run_time=step)
            self.wait_for_voiceover()

        # ---- 10. Betaflight; the traces fold back into the row ----
        names = ["roll", "pitch", "throttle", "yaw"]
        rows = VGroup(*[label(n, 22, MUTED) for n in names]).arrange(DOWN, aligned_edge=LEFT, buff=0.28).move_to([-5.0, 1.0, 0])
        val = num("1150", 34, YELLOW_A).next_to(rows[2], RIGHT, buff=0.5)
        unit = label("µs", 20).next_to(val, RIGHT, buff=0.12, aligned_edge=DOWN)
        fc = label("flight controller", 26, INK)
        bf = label("running Betaflight", 24, MUTED)
        rows.arrange(DOWN, aligned_edge=LEFT, buff=0.16).move_to([-5.0, -0.4, 0])
        val.next_to(rows[2], RIGHT, buff=0.5); unit.next_to(val, RIGHT, buff=0.12, aligned_edge=DOWN)
        bf.next_to(rows, UP, buff=0.2, aligned_edge=LEFT); fc.next_to(bf, UP, buff=0.08, aligned_edge=LEFT)
        fc2t = label("flight ctrl", 20, RED_A).move_to(drone[4])
        fc2 = VGroup(Rectangle(width=fc2t.width + 0.2, height=fc2t.height + 0.14, stroke_width=0, fill_color=BG, fill_opacity=1).move_to(fc2t), fc2t)
        for r in rows:
            r.set_opacity(0.4)
        rows[2].set_opacity(1).set_color(INK)
        hx = mono("0x6bd", 40, YELLOW_A).move_to([-2.3, 0.4, 0])
        eq = label("= 1725 ticks ÷ 1.5", 28, INK)
        eq.next_to(hx, RIGHT, buff=0.3)
        self.fix(hx, rows, val, unit, fc, bf, eq, fc2)
        self.remove(hx, rows, val, unit, fc, bf, eq, fc2)
        c = self.cap("the flight controller reads throttle 1150")
        self.fix(c)
        self.remove(c)
        with self.say("The flight controller runs firmware called <bookmark mark='bf'/>Betaflight."):
            qf = lambda t: smooth(min(1.0, t / 0.3))     # traces and tags gone before the row slides over them
            self.play(self.cout(c5), *[FadeOut(m_, rate_func=qf) for m_ in (wt, clk, gdots, gguides, data_lab, clk_lab, clk_tag)], row["cells"].animate.shift(DOWN * (ROW_Y8 - ROW_C[1])), strip.go(K_FC),
                      FadeOut(drone[4], rate_func=qf), FadeIn(fc2, rate_func=lambda t: smooth(min(1.0, max(0.0, (t - 0.4) / 0.6)))),
                      FadeIn(fc, rate_func=lambda t: smooth(min(1.0, t / 0.5))), run_time=1.0)
            self.play(strip.close(), run_time=0.8)
            self.wait_until_bookmark("bf", lead=0.1)
            self.play(FadeIn(bf), run_time=0.4)
            self.wait_for_voiceover()

        # ---- 11. unpacks the throttle: 0x6bd -> 1725 / 1.5 -> 1150 ----
        with self.say("It <bookmark mark='un'/>unpacks the <bookmark mark='th'/>throttle, <bookmark mark='v'/>1150 again,"):
            self.play(FadeIn(rows), Indicate(throttle_glyphs(row), color=YELLOW_A, scale_factor=1.0), FadeIn(hx, shift=UP * 0.3, rate_func=lambda t: smooth(min(1.0, max(0.0, (t - 0.3) / 0.7)))), run_time=0.6)
            self.wait_until_bookmark("th", lead=0.3)
            self.play(FadeIn(eq), run_time=0.4)
            self.wait_until_bookmark("v", lead=0.5)
            self.play(FadeOut(hx), FadeOut(eq), FadeIn(val), FadeIn(unit), FadeOut(row), self.cin(c), run_time=1.0)
            self.wait_for_voiceover()

        # ---- 12. four motor commands and level corrections ----
        motors2d = drone[1]
        BW, BH = 0.16, 0.7
        base, after = [0.34, 0.34, 0.34, 0.34], [0.43, 0.27, 0.39, 0.30]   # level before / after the corrections

        def bar_fill(m, lv):
            r = Rectangle(width=BW, height=lv, stroke_width=0, fill_color=YELLOW_A, fill_opacity=0.9)
            r.move_to(m[0].get_bottom() + UP * lv / 2)
            return r
        bars = VGroup()
        for m, d in zip(motors2d, (RIGHT, LEFT, LEFT, RIGHT)):
            tr_ = Rectangle(width=BW, height=BH, color=MUTED, stroke_width=SW_THIN)
            tr_.move_to(m.get_center() + d * 0.62)
            bars.add(VGroup(tr_))
        fills0 = VGroup(*[bar_fill(b_[0], lv) for b_, lv in zip(bars, base)])
        fills1 = VGroup(*[bar_fill(b_[0], lv) for b_, lv in zip(bars, after)])
        marks = VGroup(*[label("+" if a_ > b_ else "−", 22, GREEN_A if a_ > b_ else RED_A).next_to(bx[0], UP, buff=0.08)
                         for bx, a_, b_ in zip(bars, after, base)])
        lvl = label("level corrections", 18, MUTED).next_to(drone, DOWN, buff=0.9)
        c2 = self.cap("mixed into 4 motors")
        self.fix(bars, fills0, fills1, marks, lvl, c2)
        self.remove(bars, fills0, fills1, marks, lvl, c2)
        with self.say("and mixes it into commands for the <bookmark mark='fm'/>four motors, along with the "
                      "<bookmark mark='lv'/>corrections that keep the drone level."):
            self.play(self.cout(c), FadeOut(rows), FadeOut(fc), FadeOut(bf), FadeOut(unit), run_time=0.4)
            self.wait_until_bookmark("fm")
            self.play(FadeOut(val, shift=RIGHT * 0.5), FadeIn(bars), FadeIn(fills0), motors2d.animate.set_fill(PURPLE_A, 0.2),
                      self.cin(c2), run_time=1.2)
            self.wait_until_bookmark("lv")
            self.play(FadeIn(lvl), FadeIn(marks), Transform(fills0, fills1), run_time=1.0)
            self.wait_for_voiceover()

        # ---- 13. motors spin, 14. lifts ----
        quad, props = quad3d()
        quad.scale(QUAD_SCALE).shift(RIGHT * 1.0 + DOWN * 0.6)
        spun = [0.0]

        def spin(m, dt):
            m.rotate(9 * dt, about_point=m.get_center())
            if m is props[0]:
                spun[0] += 9 * dt
        with self.say("The motor drivers turn those into spin,"):
            out_r = lambda t: smooth(min(1.0, t / 0.5))      # 2D quad and its labels fully gone by 0.4 s, then the 3D quad grows in
            # drone[4] (the CC2500 label) already faded out at the FC stage; fading it again re-adds it on top of 'flight ctrl'
            self.play(*[FadeOut(m_, rate_func=out_r) for m_ in (VGroup(*drone[:4]), fc2, fills0, bars, marks, lvl)],
                      GrowFromCenter(quad, rate_func=lambda t: smooth(min(1.0, max(0.0, (t - 0.5) / 0.5)))), self.cout(c2), strip.go(K_MOT), run_time=0.8)
            self.move_camera(phi=QUAD_PHI, theta=-45 * DEGREES, zoom=1.0, run_time=1.4)
            for p in props:
                p.add_updater(spin)
            self.wait_for_voiceover()
        done = [0.0]

        def lift(m, a):   # a shift by increments, so the spin updaters on the blades keep working (a .animate shift would overwrite them)
            m.shift(OUT * 0.3 * (smooth(a) - done[0]))
            done[0] = smooth(a)
        with self.say("and the drone lifts."):
            self.move_camera(phi=QUAD_PHI, theta=QUAD_THETA, added_anims=[UpdateFromAlphaFunc(quad, lift)], run_time=1.5, rate_func=smooth)
            self.wait_for_voiceover()
        for p in props:
            p.clear_updaters()
        for p in props:   # land on the S06 seam's blade angle
            p.rotate(QUAD_PROP_ANGLE - spun[0], about_point=p.get_center())
        self.wait(0.5)
