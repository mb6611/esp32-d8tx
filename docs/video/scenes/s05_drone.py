"""S05: the packet reaches the drone (map marker air -> CC2500) and the decode runs stages S03/S02 backwards with the
same pictures: the CC2500 catches the wave -> its squeezed/stretched stretches read back into 1s and 0s -> the bits
regroup into the bracketed packet row -> checksum ok -> marker CC2500 -> SPI -> flight controller -> `0x6bd` lifts
out of the throttle cells -> `1150` in the channel list -> four motor commands -> 3D quad, props spin, small lift.
Facts (experiments/08-first-flight-cloned-e8, 14-app-validation, tools/cc2500-rxdiag/README.md): Tinyhawk 3 with a
MATEKF411RX (STM32F411) flight controller and a CC2500 radio on SPI (3.375 MHz), Betaflight 4.2.11; the receiver
checks the CRC; Betaflight reads throttle 1150 us and arm (AUX3) 2000; at 1150 us the motors spin; full throttle lifted
the quad off the bench (08, test 8). Channel list order A E T R; only the throttle value is legible. Board names,
Betaflight version, DShot and PID are deliberately not on screen."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from parts import *

DX = np.array([5.5, -0.35, 0])     # drone silhouette centre (2D part)
WC5 = np.array([-1.4, 0.5, 0])    # wave centre on the drone side
WW5, WA5 = 7.6, 0.6               # wave width / amplitude
BITS_Y5 = 1.6
ROW_C = np.array([-1.4, -1.55, 0])
ROW_K = 0.8


def drone_2d():
    arms = VGroup(Line(DL * 0.9, UR * 0.9), Line(DR * 0.9, UL * 0.9)).set_stroke(PURPLE_A, SW_LINE)
    motors = VGroup(*[Circle(radius=0.32, color=PURPLE_A, stroke_width=SW).move_to(0.9 * d) for d in (UR, UL, DL, DR)])
    body = RoundedRectangle(corner_radius=0.08, width=0.9, height=0.6, color=PURPLE_A, stroke_width=SW, fill_color=BG, fill_opacity=1)
    rx = Rectangle(width=0.5, height=0.3, color=RED_A, stroke_width=SW).move_to(body)
    rxl = label("CC2500", 14, RED_A).next_to(rx, DOWN, buff=0.35)
    return VGroup(arms, motors, body, rx, rxl).scale(0.85).move_to(DX)


class S05(Narrated, ThreeDScene):
    def say(self, text):
        print("VO %.2f %s" % (self.renderer.time, text), flush=True)
        return self.voiceover(text=text)

    def cap(self, text, size=32):
        return caption(text, size)

    def fix(self, *ms):
        self.add_fixed_in_frame_mobjects(*ms)
        return ms

    def construct(self):
        strip = MapStrip(K_AIR)
        blk, side = packet_stream_close()
        self.fix(strip, side, blk)
        stream_caption = self.cap(STREAM_CAP).move_to(DOWN * (FH / 2 - 0.6))   # where S04's caption_at left it
        self.fix(stream_caption)
        self.wait(0.7)

        # ---- through the air into the drone's receiver (map marker air -> CC2500) ----
        drone = drone_2d()
        rx = drone[3]
        c = self.cap("caught by the drone's CC2500 radio")
        self.fix(drone, c)
        self.remove(drone, c)
        with self.say("The drone's CC2500 radio catches the burst."):
            self.play(FadeOut(stream_caption), strip.open(), blk.animate.scale(0.5 * STREAM_W / CLOSE_W).move_to(LEFT * 3.0),
                      *[FadeOut(n, shift=d * 3.0) for n, d in zip(side, (LEFT, RIGHT))], FadeIn(drone, shift=LEFT * 0.3), run_time=0.8)
            self.play(strip.go(K_RX), MoveAlongPath(blk, Line(LEFT * 3.0, rx.get_center())), blk.animate.scale(0.3), FadeIn(c),
                      run_time=1.4, rate_func=linear)
            self.play(strip.close(), Flash(rx, color=RED_A, line_length=0.2, flash_radius=0.4), run_time=0.6)

        # ---- inverse of S03: the wave, read back into bits ----
        waves = [fsk_wave(8.0, lit=i, center=WC5, width=WW5, amp=WA5) for i in range(9)]
        wave = waves[0]
        bits = bit_squares(side=0.5, size=28)
        for i, b in enumerate(bits):
            b.move_to([bit_x(i, WC5, WW5), BITS_Y5, 0])
        c2 = self.cap("the wave, read back into bits")
        self.fix(wave, bits, c2)
        self.remove(wave, bits, c2)
        with self.say("It reads the up and down nudges in the wave back as ones and zeros,"):
            self.play(FadeOut(c), ReplacementTransform(blk, wave), run_time=1.0)
            self.play(FadeIn(c2), run_time=0.4)
            for i in range(8):
                self.play(Transform(wave, waves[i + 1]), FadeIn(bits[i], shift=UP * 0.15), run_time=0.26, rate_func=linear)

        # ---- inverse of S02: the bits regroup into the bracketed packet ----
        row = packet_row(center=ROW_C, scale=ROW_K, hexsize=BHEX, lab_size=16)
        dim_row(row); light_throttle(row)
        cells = row["cells"]
        others = VGroup(*[cells[i] for i in range(20) if i != 6])
        c3 = self.cap("the bits, back in their packet")
        self.fix(row, c3)
        self.remove(row, c3)
        with self.say("reassembles the packet,"):
            self.play(FadeOut(c2), FadeOut(wave), ReplacementTransform(bits, cells[6]), FadeIn(others), FadeIn(row["braces"]),
                      FadeIn(row["labels"]), FadeIn(c3), run_time=1.0)

        # ---- checksum ok ----
        pulse = ShowPassingFlash(Line(cells[0].get_left(), cells[19].get_right(), color=YELLOW_A, stroke_width=SW_FLASH)
                                 .shift(DOWN * (BCELL * ROW_K / 2 + 0.06)), time_width=0.3, run_time=1.0)
        self.fix(pulse.mobject)
        with self.say("and checks the checksum."):
            self.play(FadeOut(c3), pulse)
        tick = label("✓", 30, GREEN_A).next_to(cells[19], RIGHT, buff=0.2)
        c = self.cap("checksum ok")
        self.fix(tick, c)
        self.remove(tick, c)
        with self.say("Everything checks out."):
            self.play(cells[18][0].animate.set_stroke(GREEN_A, opacity=1), cells[19][0].animate.set_stroke(GREEN_A, opacity=1),
                      cells[18][1].animate.set_fill(GREEN_A, opacity=1), cells[19][1].animate.set_fill(GREEN_A, opacity=1),
                      FadeIn(tick, scale=0.6), FadeIn(c), run_time=0.7)

        # ---- stage b: over SPI to the flight controller (map strip) ----
        c2 = self.cap("over SPI to the flight controller")
        self.fix(c2)
        self.remove(c2)
        # a small packet token rides the marker along the SPI wire; the packet row pulses as it feeds the wire
        token = VGroup(RoundedRectangle(corner_radius=0.03, width=0.46, height=0.16, color=YELLOW_A, stroke_width=SW_LINE,
                                        fill_color=BG, fill_opacity=1),
                       *[Line(UP * 0.04, DOWN * 0.04, color=YELLOW_A, stroke_width=SW_THIN).move_to(RIGHT * (k - 2) * 0.07) for k in range(5)])
        token.set_opacity(0)
        token.add_updater(lambda m: m.move_to(strip.marker.get_center() + UP * 0.3))
        flashes = [ShowPassingFlash(Line(cells[0].get_left(), cells[19].get_right(), color=YELLOW_A, stroke_width=SW_FLASH)
                                    .shift(DOWN * (BCELL * ROW_K / 2 + 0.06)), time_width=0.3, run_time=1.2) for _ in range(3)]
        self.fix(token, *[f.mobject for f in flashes])
        self.remove(token, *[f.mobject for f in flashes])
        with self.say("It passes the packet over SPI, a short wire, to the flight controller running Beta flight."):
            self.play(FadeOut(c), FadeOut(tick), strip.open(), run_time=0.6)
            self.add(token)
            self.play(strip.go(K_FC), FadeIn(c2), token.animate.set_opacity(1), Succession(*flashes), run_time=4.4, rate_func=linear)
            token.clear_updaters()
            self.play(FadeOut(token), run_time=0.01)
            self.play(strip.close(), FadeOut(c2), run_time=0.5)

        # ---- 0x6bd lifts out of the throttle cells -> 1150 in the channel list ----
        names = ["roll", "pitch", "throttle", "yaw"]
        rows = VGroup(*[label(n, 22, MUTED) for n in names]).arrange(DOWN, aligned_edge=LEFT, buff=0.28).move_to([-5.0, 1.3, 0])
        val = num("1150", 34, YELLOW_A).next_to(rows[2], RIGHT, buff=0.5)
        unit = label("µs", 20).next_to(val, RIGHT, buff=0.12, aligned_edge=DOWN)
        fc = label("flight controller", 18).next_to(rows, UP, buff=0.3, aligned_edge=LEFT)
        for r in rows:
            r.set_opacity(0.4)
        rows[2].set_opacity(1).set_color(INK)
        hx = mono("0x6bd", 40, YELLOW_A).move_to([-1.0, 0.4, 0])
        self.fix(hx, rows, val, unit, fc)
        self.remove(hx, rows, val, unit, fc)
        c = self.cap("the flight controller reads throttle 1150")
        self.fix(c)
        self.remove(c)
        with self.say("The flight controller unpacks the throttle, eleven fifty,"):
            self.play(TransformFromCopy(throttle_glyphs(row), hx), FadeIn(fc), FadeIn(rows), run_time=1.2)
            self.play(FadeTransform(hx, val), FadeIn(unit), FadeOut(row), run_time=1.0)
            self.play(FadeIn(c), run_time=0.5)

        # ---- 1150 splits into four motor commands (on the silhouette), then the quad in 3D ----
        motors2d = drone[1]
        copies = VGroup(*[num("1150", 20, YELLOW_A).move_to(m.get_center()) for m in motors2d])
        c2 = self.cap("mixed into 4 motors")
        self.fix(copies, c2)
        self.remove(copies, c2)
        with self.say("and mixes it into commands for all four motors,"):
            self.play(FadeOut(c), FadeOut(rows), FadeOut(fc), FadeOut(unit), run_time=0.5)
            self.play(LaggedStart(*[TransformFromCopy(val, cp_, path_arc=-30 * DEGREES) for cp_ in copies], lag_ratio=0.1),
                      strip.go(K_MOT), motors2d.animate.set_fill(PURPLE_A, 0.2), FadeIn(c2), run_time=2.5)
        with self.say("along with the corrections that keep the drone level."):
            self.play(LaggedStart(*[Indicate(cp_, color=YELLOW_A, scale_factor=1.3) for cp_ in copies], lag_ratio=0.25), run_time=2.5)
        quad, props = self.make_quad()
        quad.scale(1.5).shift(RIGHT * 1.0 + DOWN * 0.6)
        with self.say("The motor drivers turn those commands into spin,"):
            self.play(FadeOut(drone), FadeOut(copies), GrowFromCenter(quad), FadeOut(c2), val.animate.move_to([-4.6, 2.4, 0]).set_opacity(0.5),
                      run_time=0.8)
            self.move_camera(phi=62 * DEGREES, theta=-45 * DEGREES, zoom=1.0, run_time=1.4)
            spun = [0.0]

            def spin(m, dt):
                m.rotate(9 * dt, about_point=m.get_center())
                if m is props[0]:
                    spun[0] += 9 * dt
            for p in props:
                p.add_updater(spin)
        with self.say("and the drone lifts."):
            self.begin_ambient_camera_rotation(rate=0.08 * 1.6 / 1.5)   # same total turn as before (0.128 rad)
            self.play(quad.animate.shift(OUT * 0.3), run_time=1.5, rate_func=smooth)
        self.stop_ambient_camera_rotation()
        for p in props:
            p.clear_updaters()
        for p in props:   # land on the same prop angle as before narration (old total spin time 3.4 s)
            p.rotate(9 * 3.4 + 0.495 - spun[0], about_point=p.get_center())
        self.wait(0.5)

    def make_quad(self):
        # 3b1b 3D look: blue-family fills with a thin lighter outline, no greys; props are thin white lines
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
