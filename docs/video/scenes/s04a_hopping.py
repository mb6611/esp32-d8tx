"""S04a, radio channels and hopping (long cut, STORYBOARD.md beat table 1-15).
Close view (camera CLOSE_W on the packet, lanes 0.25 per channel number) -> one pull-back to the wide hop plot (HP_CAM, 0.03
per channel number, true frequency axis) -> the camera never moves again. Starts on seam_s03c_s04a('in'), ends on
seam_s04a_s04b().
Facts: channel n = 2404 MHz + n x 299.93 kHz (packet.c d8_channel_f10); 47 entries, E8 table (common.TABLE); slot s carries
TABLE[1 + s]; one packet per 8.994 ms slot; Wi-Fi channel 6 = channel numbers 77..143 (12 of the 47 entries). The Wi-Fi bursts
are an invented illustration (STORYBOARD V6), not a capture."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from parts import *
from parts import _hp_lab

KC = CLOSE_W / FW                  # label / stroke scale in the close view
Y57 = HP_P0[1]                     # y of channel 57 (same in both views: the lanes compress about it)
X0 = HP_P0[0]
GX0, GX1 = -SLOT_W, 2 * SLOT_W     # local grid: slots -1..1
PW = PKT_W
WIFI_DASH = [i for i, c in enumerate(TABLE) if HP_WIFI[0] <= c <= HP_WIFI[1]]
assert len(WIFI_DASH) == 12, WIFI_DASH

T = {  # the narration, written form, one entry per storyboard beat (SCRIPT.md, no word changed)
    1: "The burst leaves the ESP32's antenna around one carrier frequency.",
    2: "The band is divided into numbered radio channels, 300 kHz apart, each a narrow band of frequencies with a carrier at its centre.",
    3: "On another radio channel the carrier is different, so the wave is different, but it carries the same bits.",
    4: "D8 doesn't stay on one radio channel.",
    5: "Each packet goes out on a different one, about 9 ms after the last.",
    6: "This is frequency hopping.",
    7: "D8 hops across 47 radio channels, spread over the band.",
    8: "Hopping protects the link.",
    9: "A Wi-Fi network sits on about a dozen of the 47 radio channels,",
    10: "so packets sent there can interfere with it if both are sent at the same time.",
    11: "The rest get through.",
    12: "There is a catch.",
    13: "The drone's radio can only listen to one radio channel at a time, the green bar.",
    14: "After every packet it retunes, so it is already waiting when the next packet arrives.",
    15: "The transmitter makes the same move, so both ends are always on the same radio channel.",
}


def jagged(pkt, n=14):
    """Jagged red outline around a packet (the overlap with a Wi-Fi burst)."""
    c = pkt.get_center()
    hw, hh = PW / 2 + 0.05, HP_PKT_H / 2 + 0.05
    pts = []
    per = [(-hw, -hh, hw, -hh), (hw, -hh, hw, hh), (hw, hh, -hw, hh), (-hw, hh, -hw, -hh)]
    for (ax, ay, bx, by) in per:
        m = n if abs(bx - ax) > 0.1 else n // 2
        for i in range(m):
            t = i / m
            x, y = ax + (bx - ax) * t, ay + (by - ay) * t
            off = 0.035 if i % 2 else -0.02
            nx, ny = (0, -1 if ay == by and ay < 0 else 1) if ay == by else (-1 if ax < 0 else 1, 0)
            pts.append([c[0] + x + nx * off, c[1] + y + ny * off, 0])
    pts.append(pts[0])
    v = VMobject(stroke_color=RED_A, stroke_width=SW_LINE * HP_K)
    v.set_points_as_corners(pts)
    return v


class S04A(Narrated, MovingCameraScene):
    # ---- timing helpers ----
    def at(self, t0, dur, frac):
        dt = t0 + frac * dur - self.renderer.time
        if dt > 1 / 30:
            self.wait(dt)

    def fr(self, beat, phrase):
        t = T[beat]
        return t.index(phrase) / len(t)

    def say(self, beat):
        print(f"VO beat {beat} t={self.renderer.time:.2f} {T[beat]}", flush=True)
        return self.voiceover(text=T[beat])

    def cap(self, text, size=32):
        return caption_at(self.camera.frame, text, size)

    def play_(self, *a, rt=0.5, **kw):
        self.play(*a, run_time=max(rt, 1 / 15), **kw)

    # ---- the now line, driven by an updater so packets can be cued by its position ----
    def now_updater(self, now):
        self.v = 0.0
        now.add_updater(lambda m, dt: m.shift(RIGHT * self.v * dt))

    def till(self, x):
        d = (x - self.now.get_x()) / self.v if self.v > 0 else 0
        if d > 1 / 30:
            self.wait(d)

    def land(self, hp, s, rt=0.25):
        """Packet s draws (its arrow from s-1 grows with it)."""
        anims = [FadeIn(hp.pkts[s])]
        if s > 0:
            anims.append(GrowArrow(hp.arrows[s - 1]))
        self.play(*anims, run_time=rt)

    def construct(self):
        seam_in = seam_s03c_s04a("in")
        strip = seam_in.enter(self)
        frame = self.camera.frame
        blk = seam_in.mobs                         # packet 0 (packet_block at HP_P0)
        hp = hop_plot(18, 13, now=True, bar=True)   # parts for the wide view (not added as a whole)
        hp.pkts[0] = blk
        k = HP_K
        u = ValueTracker(LANE_H)                    # plot units per channel number: 0.25 close -> 0.03 wide

        def uy(c):
            return Y57 + (c - 57) * u.get_value()

        def fade_of():
            return float(np.clip((u.get_value() - 0.06) / 0.19, 0, 1))

        # ---- close-view pieces (built now, added on cue) ----
        def grid():
            uu = u.get_value()
            o = 0.8 * fade_of()
            g = VGroup(*[Line([GX0, Y57 + b * uu, 0], [GX1, Y57 + b * uu, 0], stroke_color=GRID, stroke_width=SW_THIN * KC,
                              stroke_opacity=o) for b in (-2.5, -1.5, -0.5, 0.5, 1.5, 2.5)],
                        *[Line([x, Y57 - 2.5 * uu, 0], [x, Y57 + 2.5 * uu, 0], stroke_color=GRID, stroke_width=SW_THIN * KC,
                               stroke_opacity=0.85 * o) for x in (GX0, 0, SLOT_W, GX1)])
            return g

        grid_m = always_redraw(grid)
        grid_m.set_opacity(0)
        gbot = Y57 - 2.5 * LANE_H
        lab_t = label("time", 22).scale(KC)
        arr_t = Arrow(ORIGIN, RIGHT * 0.5, buff=0, color=MUTED, stroke_width=SW * KC, max_tip_length_to_length_ratio=0.3, tip_length=0.35 * KC)
        tgrp = VGroup(lab_t, arr_t).arrange(RIGHT, buff=0.08 * KC).move_to([X0, gbot - 0.17, 0])
        lab_f = label("frequency", 22).scale(KC).rotate(90 * DEGREES)
        arr_f = Arrow(ORIGIN, UP * 0.5, buff=0, color=MUTED, stroke_width=SW * KC, max_tip_length_to_length_ratio=0.3, tip_length=0.35 * KC)
        fgrp = VGroup(arr_f, lab_f).arrange(UP, buff=0.08 * KC).move_to([GX0 - 0.78, Y57, 0])
        carrier = DashedLine([GX0, Y57, 0], [GX1, Y57, 0], dash_length=0.07, stroke_color=INK, stroke_width=SW * KC)
        lab_car = label("its carrier", 22, INK).scale(KC).next_to(carrier, RIGHT, buff=0.06)
        nums = VGroup(*[label(str(c), 22, INK if c == 57 else MUTED).scale(KC) for c in (55, 56, 57, 58, 59)])
        for n, c in zip(nums, (55, 56, 57, 58, 59)):
            n.add_updater(lambda m, c=c: m.move_to([GX0 - 0.17, uy(c), 0]))
        outline = always_redraw(lambda: Rectangle(width=GX1 - GX0, height=u.get_value(), stroke_color=INK, stroke_width=SW_THIN * KC,
                                                  fill_opacity=0).move_to([(GX0 + GX1) / 2, Y57, 0]).set_stroke(opacity=fade_of()))
        br_line = Line([GX1 + 0.1, Y57, 0], [GX1 + 0.1, Y57 + LANE_H, 0])
        brace_k = Brace(br_line, RIGHT, buff=0.0, color=MUTED, stroke_width=SW_THIN * KC, sharpness=1.0).scale(0.6)
        brace_k.move_to([GX1 + 0.1 + 0.08, Y57 + LANE_H / 2, 0])
        lab_k = label("300 kHz", 22).scale(KC).next_to(brace_k, RIGHT, buff=0.04)
        kgrp = VGroup(brace_k, lab_k)
        # wave strips
        sw = 0.9
        wk = sw / WAVE_W

        def wave(cyc, y):
            w = fsk_wave(8.0, None, [X0, y, 0], wk, cyc=cyc)
            w.set_stroke(width=SW_LINE * KC)
            return w

        w57, w59 = wave(3, Y57), wave(4, Y57 + 2 * LANE_H)
        l57 = label("channel 57", 22).scale(KC).next_to(w57, RIGHT, buff=0.14)
        l59 = label("channel 59", 22).scale(KC).next_to(w59, RIGHT, buff=0.14)

        self.wait(0.3)
        # ================= 1 =================
        with self.say(1) as tr:
            t0, d = self.renderer.time, tr.duration
            c1 = self.cap("out of the antenna, into the air", 32)
            c1.scale(1)
            self.play(strip.open(), FadeIn(c1), run_time=0.6)
            self.play(strip.go(K_AIR), run_time=1.2, rate_func=linear)
            self.play(strip.close(), run_time=0.6)
            self.at(t0, d, self.fr(1, "around"))
            self.add(grid_m)
            self.play(grid_m.animate.set_opacity(1), FadeIn(tgrp), FadeIn(fgrp), FadeOut(c1), run_time=0.6)
            self.at(t0, d, self.fr(1, "one carrier"))
            self.play(Create(carrier), FadeIn(lab_car), run_time=0.8)
        # ================= 2 =================
        with self.say(2) as tr:
            t0, d = self.renderer.time, tr.duration
            c2 = self.cap("a radio channel: a narrow band of frequencies")
            self.play(FadeIn(c2), run_time=0.4)
            self.at(t0, d, self.fr(2, "numbered"))
            self.play(LaggedStart(*[FadeIn(n) for n in nums], lag_ratio=0.25), run_time=1.4)
            self.at(t0, d, self.fr(2, "300 kHz"))
            self.play(FadeOut(lab_car), FadeIn(kgrp), run_time=0.7)
            self.at(t0, d, self.fr(2, "each a narrow"))
            self.add(outline)
            self.play(outline.animate.set_stroke(opacity=1), run_time=0.01)
            self.wait(0.8)
            self.at(t0, d, self.fr(2, "a carrier at"))
            self.play(carrier.animate(rate_func=there_and_back).set_stroke(width=SW_LINE * KC * 1.8), run_time=1.0)
        # ================= 3 =================
        with self.say(3) as tr:
            t0, d = self.renderer.time, tr.duration
            c3 = self.cap("another channel, the same bits")
            self.play(FadeOut(c2), FadeIn(c3), run_time=0.4)
            self.add(w57.set_opacity(0))
            self.play(blk.animate.set_fill(opacity=0), w57.animate.set_opacity(1), FadeOut(carrier), run_time=0.5)
            self.play(FadeIn(l57), run_time=0.3)
            self.at(t0, d, self.fr(3, "another"))
            self.play(FadeIn(w59), FadeIn(l59), run_time=0.6)
            self.at(t0, d, self.fr(3, "the wave is"))
            self.play(w59.animate(rate_func=there_and_back).scale(1.06), run_time=0.8)
            self.at(t0, d, self.fr(3, "same bits"))
            self.play(w57.animate(rate_func=there_and_back).scale(1.06), w59.animate(rate_func=there_and_back).scale(1.06), run_time=0.8)
            self.play(FadeOut(w59), FadeOut(l59), FadeOut(l57), FadeOut(w57), blk.animate.set_fill(opacity=0.9), run_time=0.6)
        # ================= 4: view change =================
        wide_ax = hp.axes
        with self.say(4) as tr:
            self.play(FadeOut(c3), run_time=0.3)
            wide_ax.set_opacity(0)
            self.add(wide_ax)
            self.play(frame.animate.set(width=HP_CAM[1]).move_to(HP_CAM[0]),
                      u.animate.set_value(HP_UNIT),
                      FadeOut(nums), FadeOut(kgrp), FadeOut(tgrp), FadeOut(fgrp), FadeOut(outline),
                      AnimationGroup(Wait(1.1), wide_ax.animate.set_opacity(1), lag_ratio=1),
                      run_time=2.0, rate_func=smooth)
            self.remove(grid_m, outline, nums)
        # ================= 5 =================
        now = hp.now
        self.now = now
        now.set_x(blk.get_right()[0])
        self.now_updater(now)
        with self.say(5) as tr:
            t0, d = self.renderer.time, tr.duration
            cap5 = self.cap("next packet: another radio channel")
            self.play(FadeIn(now), FadeIn(cap5), run_time=0.4)
            # packet 1 lands on "a different one", the 9 ms spacing is marked on "about 9 ms"
            t_land = t0 + self.fr(5, "a different") * d + 0.1
            self.v = (hp.pkts[1].get_left()[0] - now.get_x()) / max(t_land - self.renderer.time - 0.25, 0.3)
            self.till(hp.pkts[1].get_left()[0])
            self.land(hp, 1)
            self.v = SLOT_W / 1.2
            self.at(t0, d, self.fr(5, "about 9 ms"))
            self.play(Indicate(VGroup(hp.axes[-2], hp.axes[-1]), color=INK, scale_factor=1.15), run_time=0.6)
            self.till(hp.pkts[2].get_left()[0])
            self.land(hp, 2)
        # ================= 6 =================
        with self.say(6) as tr:
            c6 = self.cap("frequency hopping")
            self.play(FadeOut(cap5), FadeIn(c6), run_time=0.3)
            for s in (3, 4):
                self.till(hp.pkts[s].get_left()[0])
                self.land(hp, s)
        # ================= 7 =================
        with self.say(7) as tr:
            t0, d = self.renderer.time, tr.duration
            self.play(FadeOut(c6), run_time=0.3)
            self.v = SLOT_W / 0.3
            hp.dashes.shift(RIGHT * 0.8).set_opacity(0)
            self.add(hp.dashes)
            nows = hp.now
            for s in range(5, 18):
                self.till(hp.pkts[s].get_left()[0])
                self.land(hp, s, rt=0.15)
                if s == 6:
                    self.play(LaggedStart(*[d_.animate.set_opacity(1) for d_ in hp.dashes], lag_ratio=0.06), run_time=1.6)
            hp.brace47 = Brace(Line([0, 0, 0], [0, HP_H - 0.8, 0]), RIGHT, buff=0.0, color=MUTED, sharpness=1.0).scale(k)
            hp.brace47.move_to([HP_W + 1.35, (HP_H - 0.8) / 2, 0])
            lab47 = _hp_lab("47 radio channels", 22).rotate(90 * DEGREES).next_to(hp.brace47, RIGHT, buff=0.1)
            self.play(FadeIn(hp.brace47), FadeIn(lab47), run_time=0.5)
            self.till(HP_W)
            self.v = 0.0
            now.set_x(HP_W)
        # ================= 8 =================
        pts = []
        for s in range(18):
            c = hp.pkts[s].get_center()
            pts += [[c[0] - PW / 2, c[1], 0], [c[0] + PW / 2, c[1], 0]]
        path = VMobject(stroke_color=INK, stroke_width=SW_LINE * HP_K * 1.8)
        path.set_points_as_corners(pts)
        with self.say(8) as tr:
            self.play(ShowPassingFlash(path, time_width=0.25), run_time=1.5, rate_func=linear)
        # ================= 9 =================
        wifi = hp.wifi
        wl = _hp_lab("Wi-Fi network", 20, RED_A)
        wl.move_to([11.65, hp_y(70), 0])
        red = VGroup(*[hp.dashes[i] for i in WIFI_DASH])
        with self.say(9) as tr:
            t0, d = self.renderer.time, tr.duration
            cap9 = self.cap("a Wi-Fi network: about 12 of the 47 radio channels")
            self.play(FadeIn(cap9), run_time=0.4)
            self.at(t0, d, self.fr(9, "Wi-Fi"))
            self.play(GrowFromEdge(wifi, LEFT), FadeIn(wl), run_time=1.0)
            self.at(t0, d, self.fr(9, "about a dozen"))
            self.play(red.animate.set_color(RED_A), run_time=0.6)
        # ================= 10 =================
        bursts = {s: Rectangle(width=SLOT_W, height=0.4, stroke_width=0, fill_color=RED_A, fill_opacity=0.6)
                  .move_to([hp_x(s), hp_y(HP_CH[s]), 0]) for s in (6, 15)}
        jag = {s: jagged(hp.pkts[s]) for s in (6, 15)}
        with self.say(10) as tr:
            t0, d = self.renderer.time, tr.duration
            cap10 = self.cap("in the band, and at the same time: they interfere")
            self.play(FadeOut(cap9), run_time=0.3)
            self.play(FadeIn(cap10), run_time=0.3)
            self.at(t0, d, self.fr(10, "can interfere"))
            self.play(Indicate(hp.pkts[1], scale_factor=1.5), Indicate(hp.pkts[10], scale_factor=1.5), run_time=0.8)
            self.at(t0, d, self.fr(10, "at the same time"))
            self.play(*[FadeIn(b) for b in bursts.values()], *[Create(j) for j in jag.values()],
                      *[hp.pkts[s].animate.set_fill(opacity=DIM) for s in (6, 15)], run_time=0.8)
        # ================= 11 =================
        okp = [s for s in range(18) if s not in (6, 15)]
        with self.say(11) as tr:
            d = tr.duration
            c11 = self.cap("the rest get through")
            self.play(FadeOut(cap10), FadeIn(c11), run_time=0.3)
            pulses = [Indicate(hp.pkts[s], scale_factor=1.4) for s in okp]
            self.play(LaggedStart(*pulses, lag_ratio=0.25, run_time=max(0.6, d - 0.9)), run_time=max(0.6, d - 0.9))
            self.play(FadeOut(wifi), FadeOut(wl), FadeOut(c11), *[FadeOut(b) for b in bursts.values()],
                      red.animate.set_color(MUTED), run_time=0.5)
        # ================= 12: rewind =================
        pk_all = [hp.pkts[s] for s in range(1, 18)]
        base = {s: hp.pkts[s].get_fill_opacity() for s in range(1, 18)}
        x_start, x_end = HP_W, blk.get_right()[0]
        with self.say(12) as tr:
            self.play(*[FadeOut(a) for a in hp.arrows[:17]], *[FadeOut(j) for j in jag.values()], FadeOut(hp.dashes),
                      FadeOut(hp.brace47), FadeOut(lab47), run_time=0.5)

            def rew(_, a):
                x = x_start + (x_end - x_start) * smooth(a)
                now.set_x(x)
                for s in range(1, 18):
                    p = hp.pkts[s]
                    f = float(np.clip((x - (p.get_x() - PW / 2)) / PW, 0, 1))
                    p.set_fill(opacity=base[s] * f)

            self.play(UpdateFromAlphaFunc(VGroup(now), rew), run_time=1.0, rate_func=linear)
        for s in range(1, 18):
            self.remove(hp.pkts[s])
        # fresh pieces for the second pass (the old ones were faded)
        hp = hop_plot(18, 13, now=True, bar=True)
        hp.pkts[0] = blk
        bar, rx, tx = hp.bar, hp.rx, hp.tx
        # ================= 13 =================
        big = bar
        big.stretch_to_fit_height(HP_H).move_to([HP_W / 2, HP_H / 2, 0]).set_fill(opacity=0.08)
        rx.next_to([HP_W, Y57, 0], RIGHT, buff=0.15)
        dr = _hp_lab("drone's radio", 20).next_to(rx, DOWN, buff=0.08).align_to(rx, LEFT)
        bk = Brace(Line([0, Y57 - HP_BAR_H / 2, 0], [0, Y57 + HP_BAR_H / 2, 0]), LEFT, buff=0.1, color=MUTED, stroke_width=SW_THIN * k,
                   sharpness=1.0).scale(k * 0.5)
        bk.move_to([-0.22, Y57, 0])
        bl = _hp_lab("one radio channel", 17).next_to(bk, LEFT, buff=0.08)
        with self.say(13) as tr:
            t0, d = self.renderer.time, tr.duration
            cap13 = self.cap("the drone hears one radio channel at a time")
            self.play(FadeIn(big), FadeIn(rx), FadeIn(dr), FadeIn(cap13), run_time=0.6)
            self.at(t0, d, self.fr(13, "one radio channel at"))
            self.play(big.animate.stretch_to_fit_height(HP_BAR_H).move_to([HP_W / 2, Y57, 0]).set_fill(opacity=0.2),
                      run_time=1.0, rate_func=smooth)
            self.play(FadeIn(bk), FadeIn(bl), run_time=0.5)
            self.at(t0, d, self.fr(13, "the green bar"))
            self.play(bar.animate.set_fill(opacity=0.45), run_time=0.5, rate_func=smooth)
            self.play(bar.animate.set_fill(opacity=0.2), run_time=0.5, rate_func=smooth)
        # ================= 14 =================
        def jump(slot, rt):
            y = hp_y(HP_CH[slot])
            anims = [bar.animate.set_y(y), rx.animate.set_y(y)]
            if tx in self.mobjects:
                anims.append(tx.animate.set_y(y))
            return anims, rt

        tx.next_to([0, Y57, 0], LEFT, buff=0.15)
        now.set_x(x_end)
        self.v = 0.0
        with self.say(14) as tr:
            t0, d = self.renderer.time, tr.duration
            cap14 = self.cap("already waiting when the packet arrives")
            # the bar retunes on the sentence's first words ("after every packet it retunes"), cap13 fades out with it
            a, _ = jump(1, 0)
            self.play(FadeOut(cap13), FadeOut(bk), FadeOut(bl), *a, FadeOut(dr), run_time=0.35, rate_func=smooth)
            self.v = SLOT_W / 0.3
            self.till(hp.pkts[1].get_left()[0])
            self.land(hp, 1, rt=0.15)
            for s in (2, 3):
                self.till(hp.pkts[s - 1].get_right()[0])
                a, _ = jump(s, 0)
                self.play(*a, run_time=0.15)
                self.till(hp.pkts[s].get_left()[0])
                self.land(hp, s, rt=0.15)
            self.till(hp.pkts[3].get_right()[0])
            self.v = 0.25 * SLOT_W / 0.6
            self.at(t0, d, 2.0 / d)        # caption on "already waiting"
            a, _ = jump(4, 0)
            self.play(*a, FadeIn(cap14), run_time=0.4, rate_func=smooth)
            self.play(bar.animate(rate_func=there_and_back).set_fill(opacity=0.5), run_time=0.7)
            # packet 4 lands on "arrives" (word timestamp)
            t_arr = t0 + frac_to_seconds(tr, self.fr(14, "arrives"))
            dtw = t_arr - self.renderer.time
            if dtw > 1 / 30:
                self.wait(dtw)
            self.v = SLOT_W / 0.6
            self.land(hp, 4, rt=0.15)
        # ================= 15 =================
        with self.say(15) as tr:
            t0, d = self.renderer.time, tr.duration
            cap15 = self.cap("both ends on the same radio channel")
            self.play(FadeOut(cap14), FadeIn(cap15), FadeIn(tx), run_time=0.4)
            # fit slots 5..12 and the last jump into the speech: per slot dt
            dt = max(0.4, (d - 0.8) / 8.5)
            self.v = SLOT_W / dt
            gap_t = (SLOT_W - PW) / self.v
            for s in range(5, 14):
                self.till(hp.pkts[s - 1].get_right()[0])
                a, _ = jump(s, 0)
                self.play(*a, run_time=max(gap_t, 1 / 15), rate_func=smooth)
                if s == 8:
                    self.play(Indicate(tx, scale_factor=1.4), run_time=0.4)
                if s <= 12:
                    self.till(hp.pkts[s].get_left()[0])
                    self.land(hp, s, rt=0.15)
            self.till(13 * SLOT_W)
            self.v = 0.0
            now.set_x(13 * SLOT_W)
            self.at(t0, d, 1.0 - 0.3 / d)   # keep the caption until the narration ends
            self.play(FadeOut(cap15), run_time=0.3)
        # ---- hand over to S04B: exactly the seam frame ----
        seam_out = seam_s04a_s04b()
        seam_in.leave(self)
        seam_out.enter(self)
        self.wait(0.5)
