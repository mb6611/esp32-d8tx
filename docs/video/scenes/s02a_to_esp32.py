"""S02a the number and the wire. In: seam_s01_s02a (`1150 µs`, marker on browser). Out: seam_s02a_s02b (`1150 µs`, marker on ESP32).
1150 µs is a servo-style pulse length (1000 = off, 2000 = full power, 1150 = 15 %); D8 paces one packet per 8.994 ms slot; the browser
writes one serial line `S c1..c8` per slot over USB (921600 baud 8N1, CP2102 USB-to-UART bridge); the character `1` is 0x31 and
goes on the wire lowest bit first (1 0 0 0 1 1 0 0) between a start bit (low) and a stop bit (high). 921600 baud = 1.085 µs per bit."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from parts import *

BY = -1.35            # base line of the servo pulse trace
PH = 0.5              # pulse height
GY = -1.7             # gauge / time line y


class S02A(Narrated, MovingCameraScene):
    def cap(self, text, size=32):
        return caption_at(self.camera.frame, text, size)

    def voiceover(self, text=None, **kw):
        import contextlib
        cm = super().voiceover(text=text, **kw)

        @contextlib.contextmanager
        def wrap():
            with cm as tr:
                t0 = self.renderer.time
                self._vo_end = t0 + tr.duration
                print(f"[S02A sentence] t={t0:6.2f} dur={tr.duration:5.2f}  {text[:50]}", flush=True)
                yield tr
                over = self.renderer.time - (t0 + tr.duration)
                if over > 0.05:
                    print(f"[S02A OVERRUN] {over:.2f}s after {text[:30]}", flush=True)
        return wrap()

    def at(self, tr, mark):
        """Wait until the word after <bookmark mark=...> is spoken (exact: KokoroService returns word boundaries)."""
        w = tr.bookmark_times[mark] - self.renderer.time
        if w > 0.02:
            self.wait(w)
        print(f"[S02A bookmark {mark}] t={self.renderer.time:6.2f}", flush=True)

    def construct(self):
        seam = seam_s01_s02a()
        strip = seam.enter(self)
        hero = seam.mobs
        out_seam = seam_s02a_s02b()

        # ------------------------------------------------ 1 · 1150
        with self.voiceover(text="Pressing W raises the throttle to <bookmark mark='a'/>1150.") as tr:
            self.at(tr, "a")
            self.play(Indicate(hero[0], color=YELLOW_A, scale_factor=1.12), run_time=0.7)

        # ------------------------------------------------ 2 · servo pulse
        x0, x1 = -4.5, -4.5 + 3.45
        left = Line([-7.3, BY, 0], [x0, BY, 0], color=STRUCT, stroke_width=SW_LINE)
        mid = VMobject(color=YELLOW_A, stroke_width=SW_LINE).set_points_as_corners(
            [[x0, BY, 0], [x0, BY + PH, 0], [x1, BY + PH, 0], [x1, BY, 0]])
        rt = VMobject(color=STRUCT, stroke_width=SW_LINE).set_points_as_corners(
            [[x1, BY, 0], [2.7, BY, 0], [2.7, BY + PH, 0], [6.15, BY + PH, 0], [6.15, BY, 0], [7.3, BY, 0]])
        trace_lab = label("servo control pulse", 22, MUTED).move_to([-5.45, BY - 0.45, 0])
        brace = Brace(Line([x0, BY, 0], [x1, BY, 0]), DOWN, buff=0.1, color=MUTED)
        blab = label("1150 µs", 24, YELLOW_A).next_to(brace, DOWN, buff=0.08)
        c2 = self.cap("the number is the length of a pulse")
        with self.voiceover(text="That's in <bookmark mark='a'/>microseconds, a convention from <bookmark mark='b'/>servo control pulses:") as tr:
            self.at(tr, "a")
            self.play(Indicate(hero[1], color=YELLOW_A, scale_factor=1.4), run_time=0.6)
            self.at(tr, "b")
            self.play(Succession(Create(left, run_time=0.3, rate_func=linear), Create(mid, run_time=0.7, rate_func=linear),
                                 Create(rt, run_time=0.6, rate_func=linear)), FadeIn(trace_lab), FadeIn(c2), run_time=1.4)
            self.play(GrowFromCenter(brace), FadeIn(blab), run_time=0.4)

        # ------------------------------------------------ 3 · 1000 off, 2000 full power
        g0 = DashedLine([-1.5, BY + PH + 0.1, 0], [-1.5, -2.35, 0], dash_length=0.08, color=MUTED, stroke_width=SW_THIN)
        g1 = DashedLine([1.5, BY + PH + 0.1, 0], [1.5, -2.35, 0], dash_length=0.08, color=MUTED, stroke_width=SW_THIN)
        l0 = label("1000: off", 24).move_to([-1.5, -2.65, 0])
        l1 = label("2000: full power", 24).move_to([1.5, -2.65, 0])
        stretch = Line([-1.5, BY, 0], [1.5, BY, 0], color=STRUCT, stroke_width=SW_LINE)
        gl = Line([-4, GY, 0], [4, GY, 0], color=STRUCT, stroke_width=SW)
        k0 = Line([-4, GY - 0.1, 0], [-4, GY + 0.1, 0], color=STRUCT, stroke_width=SW)
        k1 = Line([4, GY - 0.1, 0], [4, GY + 0.1, 0], color=STRUCT, stroke_width=SW)
        gl0 = label("1000: off", 24).next_to(k0, DOWN, buff=0.15).align_to(k0, LEFT)
        gl1 = label("2000: full power", 24).next_to(k1, DOWN, buff=0.15).align_to(k1, RIGHT)
        edge = Dot([x1, BY, 0], color=YELLOW_A, radius=0.1)
        mk = Dot([-2.8, GY, 0], color=YELLOW_A, radius=0.1)
        with self.voiceover(text="<bookmark mark='a'/>1000 is off and <bookmark mark='b'/>2000 is full power.") as tr:
            self.at(tr, "a")
            self.play(FadeOut(brace), FadeOut(blab), FadeOut(c2), Create(g0), FadeIn(l0), FadeIn(edge), run_time=0.5)
            self.at(tr, "b")
            self.play(Create(g1), FadeIn(l1), run_time=0.5)
            # the pulse drawing leaves completely before the number line is drawn: they never share the screen
            self.play(FadeOut(left), FadeOut(rt), FadeOut(mid), FadeOut(trace_lab), FadeOut(edge), run_time=0.35)
            self.play(ReplacementTransform(g0, k0), ReplacementTransform(g1, k1), FadeIn(gl),
                      ReplacementTransform(l0, gl0), ReplacementTransform(l1, gl1), FadeIn(mk), run_time=0.65)
        # the stretched line was not in the scene; make sure the gauge is
        self.add(gl)

        # ------------------------------------------------ 4 · 15 %
        pct = label("15 %", 26, YELLOW_A).next_to([-2.8, GY, 0], UP, buff=0.3)
        with self.voiceover(text="So 1150 is a gentle <bookmark mark='a'/>15 %.") as tr:
            self.at(tr, "a")
            self.play(FadeIn(pct, shift=DOWN * 0.15), Indicate(mk, color=YELLOW_A, scale_factor=2), run_time=0.8)
        gauge = VGroup(gl, k0, k1, gl0, gl1, mk, pct)

        # ------------------------------------------------ 5 · one packet every 9 ms
        tx = [-5.5 + 1.1 * i for i in range(11)]
        tline = Line([-5.9, GY, 0], [6.1, GY, 0], color=STRUCT, stroke_width=SW)
        ticks = VGroup(*[Line([x, GY - 0.1, 0], [x, GY + 0.1, 0], color=STRUCT, stroke_width=SW) for x in tx])
        tarrow = Arrow([5.9, GY, 0], [6.9, GY, 0], buff=0, color=STRUCT, stroke_width=SW, max_stroke_width_to_length_ratio=8,
                       max_tip_length_to_length_ratio=0.3)
        tline = VGroup(tline, ticks, tarrow)
        time_lab = label("time", 22).move_to([6.4, GY - 0.35, 0])
        blocks = VGroup(*[packet_block(1.3).move_to([x, GY + 0.0, 0]) for x in tx])
        nine = Brace(Line([tx[4], GY, 0], [tx[5], GY, 0]), DOWN, buff=0.12, color=MUTED)
        nine_lab = label("about 9 ms", 22).next_to(nine, DOWN, buff=0.06)
        hund = label("a bit over 100 a second", 22).move_to([4.0, GY - 1.05, 0])
        with self.voiceover(text="D8 sends <bookmark mark='a'/>one packet <bookmark mark='b'/>about every 9 ms, <bookmark mark='c'/>a bit over a hundred a second.") as tr:
            self.play(FadeOut(gauge), FadeIn(tline), FadeIn(time_lab), run_time=0.6)
            self.at(tr, "a")
            self.play(LaggedStart(*[FadeIn(b, scale=0.5) for b in blocks], lag_ratio=1), run_time=0.8, rate_func=linear)
            self.at(tr, "b")
            self.play(GrowFromCenter(nine), FadeIn(nine_lab), run_time=0.6)
            self.at(tr, "c")
            self.play(FadeIn(hund), run_time=0.6)

        # ------------------------------------------------ 6 · the ESP32 keeps that pace
        esp_lab = label("ESP32", 22, GREEN_A).move_to([tx[0], GY - 0.45, 0])
        with self.voiceover(text="The <bookmark mark='a'/>ESP32 keeps that pace,") as tr:
            self.at(tr, "a")
            self.play(FadeIn(esp_lab), run_time=0.4)
            self.play(LaggedStart(*[Indicate(b, color=INK, scale_factor=1.5) for b in blocks], lag_ratio=0.9),
                      run_time=max(1.0, tr.duration - 0.45 - 0.4 - 0.3), rate_func=linear)   # minus the wait for the word (~0.45 s) and the fade

        # ------------------------------------------------ 7 · the browser sends it, down the USB cable
        line = mono("S 1150 1500 1500 1500 1500 1500 2000 1500", 30).move_to(ORIGIN)
        g = line[0]
        piece = VGroup(*g[1:5]).set_color(YELLOW_A)
        rest = VGroup(g[0], *g[5:])
        BR_Y = -0.95
        row = Line([-5.9, BR_Y, 0], [5.9, BR_Y, 0], color=GRID, stroke_width=SW_THIN)
        dashes = VGroup(*[Line([x, BR_Y + 0.05, 0], [x, BR_Y + 0.3, 0], color=INK, stroke_width=SW) for x in tx])
        br_lab = label("browser", 22, BLUE_A).move_to([tx[0] - 0.0, BR_Y + 0.62, 0])
        c7 = self.cap("one line of eight values, every 9 ms")
        with self.voiceover(text="and the browser sends it <bookmark mark='a'/>all eight values <bookmark mark='b'/>just as often, <bookmark mark='c'/>down the USB cable.") as tr:
            self.at(tr, "a")
            self.play(FadeOut(hero), FadeIn(c7), run_time=0.4)
            self.play(FadeIn(piece), FadeIn(rest), run_time=0.5)
            self.at(tr, "b")
            self.play(FadeIn(row), FadeIn(br_lab), LaggedStart(*[FadeIn(d, shift=DOWN * 0.1) for d in dashes], lag_ratio=1),
                      run_time=1.0, rate_func=linear)
            self.at(tr, "c")
            self.play(FadeOut(VGroup(tline, time_lab, blocks, nine, nine_lab, hund, esp_lab, row, dashes, br_lab)),
                      strip.open(), VGroup(piece, rest).animate.shift(DOWN * 0.7), run_time=0.7)
            strip.pos.set_value(float(K_APP))
            self.play(strip.go(K_ESP), run_time=0.8, rate_func=linear)

        # ------------------------------------------------ 8 · the chip
        probe = MapStrip(pos=K_APP, focus=1.0)
        esp_box, cable = probe.body[4], probe.body[3]
        ex = esp_box.get_center()[0]
        eb = esp_box.get_bottom()[1]
        cxm = cable.get_center()[0]
        CY = 0.55
        chip = VGroup(RoundedRectangle(corner_radius=0.08, width=2.5, height=0.5, stroke_color=STRUCT, stroke_width=SW),
                      label("USB to UART chip", 20, MUTED))
        chip.move_to([ex - 2.3, CY, 0])
        chip[1].move_to(chip[0])
        usb_wire = Line([cxm, 1.05, 0], [cxm, CY + 0.25, 0], color=STRUCT, stroke_width=SW)
        uart_wire = VMobject(color=INK, stroke_width=SW).set_points_as_corners(
            [[chip[0].get_right()[0], CY, 0], [ex, CY, 0], [ex, eb - 0.02, 0]])
        uart_lab = label("UART", 24, INK).move_to([(chip[0].get_right()[0] + ex) / 2, CY + 0.28, 0])
        with self.voiceover(text="On the board, <bookmark mark='a'/>a small chip turns USB into a serial connection <bookmark mark='b'/>called UART:") as tr:
            self.play(FadeOut(c7), run_time=0.4)
            self.at(tr, "a")
            self.play(FadeIn(chip), Create(usb_wire), run_time=0.8)
            self.at(tr, "b")
            self.play(Create(uart_wire), FadeIn(uart_lab), run_time=0.8)

        # ------------------------------------------------ 9 · bits on a wire
        bits = (1, 0, 0, 0, 1, 1, 0, 0)
        wire = wire_trace(bits, 0.9, (0.0, -1.6))
        lifted = g[1].copy().set_color(YELLOW_A)
        self.add(lifted)
        lifted_t = mono("1", 44, YELLOW_A).move_to([0, -0.15, 0])
        bit_row = VGroup(*[mono(str(b), 24, ONE if b else ZERO).move_to([wire.x(i), -0.9, 0]) for i, b in enumerate(bits)])
        c9 = self.cap("UART: bits on a wire, one after another")
        # path of the riding dot
        pts = []
        pk = wire.pitch
        segs = wire.segs
        for s in segs:
            pts += [s.get_start(), s.get_end()]
        path = VMobject().set_points_as_corners(pts)
        dot = Dot(pts[0], radius=0.08, color=YELLOW_A)
        seq = []
        rise_grp = VGroup()
        for k, s in enumerate(segs):
            if k and k - 1 < len(segs) and abs(segs[k - 1].get_end()[1] - s.get_start()[1]) > 0.01:
                r = Line(segs[k - 1].get_end(), s.get_start(), color=MUTED, stroke_width=SW_THIN)
                seq.append(Create(r, run_time=0.06, rate_func=linear))
                rise_grp.add(r)
            seq.append(Create(s, run_time=0.14, rate_func=linear))
        with self.voiceover(text="<bookmark mark='a'/>bits on a wire, <bookmark mark='b'/>one after another,") as tr:
            self.at(tr, "a")
            self.play(FadeOut(rest), FadeOut(piece), Transform(lifted, lifted_t), run_time=0.5)
            self.play(FadeIn(bit_row, shift=DOWN * 0.15), FadeIn(c9), run_time=0.5)
            self.at(tr, "b")
            for dg in bit_row:
                pass
            self.play(Succession(*seq), MoveAlongPath(dot, path, rate_func=linear),
                      *[ReplacementTransform(bit_row[i], wire.digits[i]) for i in range(8)],
                      run_time=0.9, rate_func=linear)
            self.play(FadeOut(dot), FadeIn(wire.hi_lab), FadeIn(wire.lo_lab), FadeIn(wire.tag_l), FadeIn(wire.tag_r), run_time=0.3)
        self.add(wire)

        # ------------------------------------------------ 10 · agreed speed
        c10 = self.cap("both ends count the same time per bit")
        sl = wire.x(1)
        bb = Brace(Line([sl - 0.45, -2.5, 0], [sl + 0.45, -2.5, 0]), DOWN, buff=0.05, color=MUTED)
        bl = label("about 1 µs", 22).next_to(bb, DOWN, buff=0.05)
        tl, tr_ = wire.tag_l.get_center()[0], wire.tag_r.get_center()[0]
        combL = VGroup(*[Line([tl + d * 0.9, -0.97, 0], [tl + d * 0.9, -0.79, 0], color=MUTED, stroke_width=SW) for d in (-1, 0, 1)])
        combR = VGroup(*[Line([tr_ + d * 0.9, -0.97, 0], [tr_ + d * 0.9, -0.79, 0], color=MUTED, stroke_width=SW) for d in (-1, 0, 1)])
        with self.voiceover(text="at a <bookmark mark='a'/>speed <bookmark mark='b'/>both ends have agreed on.") as tr:
            self.at(tr, "a")
            self.play(FadeOut(c9), FadeIn(wire.guides, lag_ratio=0.1), FadeIn(c10), GrowFromCenter(bb), FadeIn(bl), FadeIn(combL),
                      FadeIn(combR), run_time=0.8)
            self.at(tr, "b")
            for _ in range(2):
                self.play(Indicate(combL, color=INK, scale_factor=1.25), Indicate(combR, color=INK, scale_factor=1.25), run_time=0.45)

        # ------------------------------------------------ 11 · builds a packet
        hero2 = hero_number()
        wire_all = VGroup(wire.segs, rise_grp, wire.digits)
        with self.voiceover(text="The ESP32 <bookmark mark='a'/>builds a D eight packet from the values.") as tr:
            self.play(FadeOut(VGroup(bb, bl, combL, combR, wire.hi_lab, wire.lo_lab, wire.tag_l, wire.tag_r, c10,
                                     chip, usb_wire, uart_wire, uart_lab, lifted)), run_time=0.5)
            self.play(FadeOut(wire_all), FadeOut(wire), run_time=0.5)
            keep = {id(m) for m in (strip, hero2[0], hero2[1], self.camera.frame)}
            self.remove(*[m for m in self.mobjects if id(m) not in keep])   # stray copies left by the group transform
            self.play(strip.close(), FadeIn(hero2), run_time=0.7)
            self.play(Indicate(hero2[0], color=YELLOW_A, scale_factor=1.12), run_time=0.6)
        self.wait(0.1)
