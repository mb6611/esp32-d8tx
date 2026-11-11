"""S03b how the E8 does it: the chip glides between the two frequencies (GFSK), why glide (spectrum panels), smoothing is for
the neighbours. In: seam_s03a_s03b (fsk_rows). Out: seam_s03b_s03c (row1_big, strip DIM).
The spectrum curves in the right panel are ILLUSTRATIVE (storyboard flag T4), not measured."""
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from parts import *
import parts
from math import erf as _erf


def _smooth_level(u, bits, sigma):
    """Local fix of parts._smooth_level: its first/last bit windows have the infinite ends the wrong way round (the first bit
    contributed -1 after its slot, the last 0), so the plateau levels sat off the +-1 levels. Patched into parts for freq_trace."""
    v = np.vectorize(_erf)
    nb = len(bits)
    y = np.zeros_like(u)
    for i, b in enumerate(bits):
        lo = 1.0 if i == 0 else v((u - i) / (sigma * 2 ** 0.5))
        hi = -1.0 if i == nb - 1 else v((u - (i + 1)) / (sigma * 2 ** 0.5))
        y += (1 if b else -1) * 0.5 * (lo - hi)
    return y


parts._smooth_level = _smooth_level

BITS = HERO_BITS
PITCH = WAVE_W / 8
BY, BDEV = ROW1_BIG_Y, ROW1_BIG_DEV           # big row 1: centre y 0.6, levels +-0.85
SIG = 0.14                                    # glide sigma in bits (freq_trace smooth = 1)
LAB_HI, LAB_LO = "+32 kHz", "−32 kHz"


def lvl(u):
    return float(_smooth_level(np.array([float(u)]), BITS, SIG)[0])


def dimmed(m, a=DIM):
    """A copy of m with every stroke/fill opacity times a (to Transform into: a dim without filling open curves)."""
    c = m.copy()
    for s in c.family_members_with_points():
        s.set_stroke(opacity=s.get_stroke_opacity() * a)
        s.set_fill(opacity=s.get_fill_opacity() * a)
    return c


def step60(cy=BY, dev=BDEV, width=WAVE_W):
    """Step trace pieces as 60-point polylines with the same x as freq_trace(smooth > 0), so Transform glides point by point."""
    g = VGroup()
    for i, b in enumerate(BITS):
        u = np.linspace(i, i + 1, 60)
        ys = np.full(60, cy + (dev if b else -dev))
        g.add(VMobject(stroke_color=ONE if b else ZERO, stroke_width=SW_LINE).set_points_as_corners(
            np.column_stack([-width / 2 + u * width / 8, ys, np.zeros(60)])))
    return g


def hi_label(cy, dev, size, x=XR):
    return label(LAB_HI, size, ONE).next_to([x, cy + dev, 0], RIGHT, buff=0.2)


# ---- panels (beats 9-16): left wave over time, right spectrum. Illustrative. ----
LP_C, RP_C = np.array([-3.4, -0.9, 0]), np.array([3.4, -0.9, 0])
PW, PH = 5.6, 2.6
SPEC_W, SPEC_H = PW * 0.9, PH * 0.8
BAND = 0.75                                   # half width of "our signal" band in the right panel


def left_wave(df, sharp):
    """Sine over the panel: frequency 6 cycles, switching to 14 (x df) at the middle; the switch is gradual for sharp 0."""
    n = 700
    xs = np.linspace(0, 1, n)
    wt = 0.02 + 0.4 * (1 - sharp)
    s = 0.5 * (1 + np.tanh((xs - 0.5) / wt * 2))
    f = 6 + df * 8 * s
    ph = TAU * np.concatenate([[0], np.cumsum(0.5 * (f[1:] + f[:-1]) * np.diff(xs))])
    w = 4.8
    pts = np.column_stack([LP_C[0] - w / 2 + xs * w, LP_C[1] + 0.6 * np.sin(ph), np.zeros(n)])
    return VMobject(stroke_color=INK, stroke_width=SW_LINE, stroke_opacity=0.9).set_points_as_corners(pts)


def spec_pts(grow, s, sharp):
    """Illustrative spectrum (not measured): a spike (s = 0) that spreads into a hump with skirts (s = 1, sharp = 1)."""
    w = SPEC_W
    x = np.linspace(-w / 2, w / 2, 700)
    cw = w * (0.012 + (0.045 + 0.05 * sharp - 0.012) * s)
    skw = w * (0.10 + 0.22 * sharp)
    y = np.exp(-(x / cw) ** 2) + 0.28 * sharp * s * np.exp(-np.abs(x) / skw)
    y = grow * SPEC_H * y / 1.3
    base = RP_C[1] - PH / 2 + 0.05
    return np.column_stack([x + RP_C[0], y + base, np.zeros_like(x)]), base


def spec_curve(grow, s, sharp):
    pts, _ = spec_pts(grow, s, sharp)
    return VMobject(stroke_color=YELLOW_A, stroke_width=SW_LINE).set_points_as_corners(pts)


def red_fill(sharp):
    pts, base = spec_pts(1.0, 1.0, sharp)
    g = VGroup()
    for side in (-1, 1):
        sel = pts[(pts[:, 0] - RP_C[0]) * side >= BAND]
        if side == -1:
            sel = sel[::-1]
        poly = np.vstack([sel, [[sel[-1][0], base, 0], [sel[0][0], base, 0]]])
        g.add(VMobject(stroke_width=0, fill_color=RED_A, fill_opacity=0.4).set_points_as_corners(poly))
    return g


class S03B(Narrated, MovingCameraScene):
    """"""

    # macOS `say` gives no word times: a bookmark sits at its share of the spoken characters (as in s00_intro.py)
    def vo(self, text, **kw):
        """kw: next_text / seed for the speech service (see common.ElevenLabsService)."""
        tags = re.compile(r"<bookmark\s*mark\s*=\s*'(\w+)'\s*/>")
        sp = spoken(text)
        total = max(len(tags.sub("", sp)), 1)
        self._marks, pos = {}, 0
        for part in re.split(r"(<bookmark[^>]*/>)", sp):
            m = tags.fullmatch(part)
            if m:
                self._marks[m.group(1)] = pos / total
            else:
                pos += len(part)
        print(f"VOSTART {self.renderer.time:.2f} {tags.sub('', text)[:50]}", flush=True)
        return self.voiceover(text=tags.sub("", text), **kw)

    def until(self, name):
        tr = self.current_tracker
        return tr.start_t + frac_to_seconds(tr, self._marks[name]) - self.renderer.time

    def wait_mark(self, name):
        t = self.until(name)
        if t > 1e-3:
            self.wait(t)

    def wait_early(self, name, lead):
        t = self.until(name) - lead
        if t > 1e-3:
            self.wait(t)

    def swap_cap(self, text=None):
        """Old caption out, then the new one in (never both on screen: they would overlap)."""
        old, self.cap = self.cap, (caption_at(self.camera.frame, text, 32) if text else None)
        parts_ = []
        if old is not None:
            parts_.append(FadeOut(old, run_time=0.2))
        if self.cap is not None:
            parts_.append(FadeIn(self.cap, run_time=0.3))
        return [Succession(*parts_)] if parts_ else []

    def construct(self):
        self.cap = None
        seam = seam_s03a_s03b()
        strip = seam.enter(self)
        g = seam.mobs
        self.remove(g)
        guides, bits, row1 = g.guides, g.bits, g.row1
        carrier, carrier_lab, plus, eq, wave, note = g.carrier, g.carrier_lab, g.plus, g.eq, g.wave, g.note
        ax_freq, ax_time = g.ax_freq, g.ax_time
        self.add(guides, bits, row1, carrier, carrier_lab, plus, eq, wave, note, ax_freq, ax_time)
        xl = XL

        # ---- 1. The E8 has a radio chip built for FSK. -------------------------------------------------------------
        bc = np.array([-6.05, -0.12, 0.0])
        outer = RoundedRectangle(corner_radius=0.08, width=1.0, height=1.05, stroke_color=MUTED, stroke_width=SW_THIN).move_to(bc)
        e8_t = label("E8", 22, INK).move_to(bc + UP * 0.33)
        chip_box = RoundedRectangle(corner_radius=0.06, width=0.9, height=0.55, stroke_color=YELLOW_A, stroke_width=SW).move_to(bc + DOWN * 0.17)
        chip_t = VGroup(label("radio", 16, INK), label("chip", 16, INK)).arrange(DOWN, buff=0.02).move_to(chip_box)
        blk = VGroup(outer, e8_t)
        with self.vo("The <bookmark mark='a'/>E8 has a <bookmark mark='b'/>radio chip built for FSK.") as tr:
            self.play(FadeIn(blk), strip.dimv.animate.set_value(1.0), run_time=0.8)
            self.wait_mark("b")
            self.play(FadeIn(VGroup(chip_box, chip_t)), run_time=0.6)

        # ---- 2+3. bytes into the chip; +-32 kHz --------------------------------------------------------------------
        row = packet_row(scale=0.4)
        cells = VGroup(*[row["cells"][i].copy() for i in (5, 6, 7, 8)]).arrange_in_grid(2, 2, buff=0.04)
        c6 = cells[1]
        c6[0].set_stroke(YELLOW_A, opacity=1)
        c6[1].set_color(YELLOW_A)
        cells.scale(2.0).move_to(bc)
        back = Rectangle(width=cells.width + 0.14, height=cells.height + 0.14, stroke_width=0, fill_color=BLACK, fill_opacity=1).move_to(cells)
        cells = VGroup(back, cells)
        arrow = Arrow([-5.5, 0, 0], [-4.95, 0, 0], buff=0, stroke_width=3, color=MUTED, max_tip_length_to_length_ratio=0.4)
        new_hi = hi_label(Y1, LV, 18)
        new_lo = label(LAB_LO, 18, ZERO).next_to([XR, Y1 - LV, 0], RIGHT, buff=0.2)
        with self.vo("It hands the chip the <bookmark mark='a'/>packet's bytes, and <bookmark mark='b'/>for each bit the chip moves the "
                                 "frequency <bookmark mark='c'/>about 32 kHz up or down.") as tr:
            self.wait_early("a", 0.2)
            chipg = VGroup(chip_box, chip_t, e8_t, outer)
            self.play(FadeOut(chipg), run_time=0.3)
            self.play(FadeIn(cells, shift=RIGHT * 0.5), run_time=0.5)
            self.wait(0.35)
            self.play(AnimationGroup(cells.animate.scale(0.45).move_to(bc + DOWN * 0.17).set_run_time(0.7),
                                     Succession(Wait(0.4), FadeOut(cells, run_time=0.3))))
            self.play(FadeIn(chipg), run_time=0.3)
            self.wait_mark("b")
            self.play(FadeIn(arrow), run_time=0.2)
            self.play(arrow.animate.set_color(YELLOW_A), run_time=0.3)
            self.wait_mark("c")
            self.play(Transform(row1.hi, new_hi), Transform(row1.lo, new_lo),
                      ShowPassingFlash(wave.copy().set_stroke(YELLOW_A, width=SW_FLASH), time_width=0.7), run_time=0.9)

        # ---- 4. 32 µs, 31,000 bits a second -------------------------------------------------------------------------
        brace = Brace(Line([xl, -2.15, 0], [xl + PITCH, -2.15, 0]), DOWN, buff=0.05, color=MUTED)
        brace_t = label("32 µs", 22).next_to(brace, DOWN, buff=0.08)
        with self.vo("Each bit lasts <bookmark mark='a'/>32 µs, <bookmark mark='b'/>about 31,000 bits a second.") as tr:
            self.wait_mark("a")
            self.play(FadeIn(brace), FadeIn(brace_t), run_time=0.5)
            self.wait_mark("b")
            self.play(*self.swap_cap("about 31,000 bits a second"), run_time=0.5)

        # ---- 5. doesn't jump: row 1 grows --------------------------------------------------------------------------
        mid = row1.mid
        row1.remove(mid)
        self.add(mid)
        big = freq_trace(smooth=0, dev=BDEV, center=(0, BY), hi_text=LAB_HI, lo_text=LAB_LO, label_size=22)
        rest = VGroup(carrier, plus, eq, wave, note, ax_freq, ax_time, bits, brace, brace_t)
        with self.vo("With D8's settings, the chip <bookmark mark='a'/>doesn't <bookmark mark='b'/>jump between the two frequencies.") as tr:
            self.wait_mark("a")
            self.play(*self.swap_cap(None), FadeOut(mid), Transform(row1, big),
                      *[Transform(m, dimmed(m)) for m in rest], FadeOut(guides), FadeOut(carrier_lab), run_time=1.2)
            flash = big.risers.copy().set_stroke(YELLOW_A, width=SW_FLASH)
            self.wait_mark("b")
            self.play(ShowPassingFlash(flash, time_width=1.0), run_time=0.6)

        # ---- 6. It glides. ------------------------------------------------------------------------------------------
        row1.segs.become(step60())
        smooth_tr = freq_trace(smooth=1, dev=BDEV, center=(0, BY), hi_text=LAB_HI, lo_text=LAB_LO, label_size=22)
        ghost = VGroup(row1.segs.copy(), row1.risers.copy())
        ghost.set_stroke(opacity=DIM)
        dot = Dot(radius=0.09, color=YELLOW_A)
        u = ValueTracker(0.0)
        dot.add_updater(lambda d: d.move_to([xl + u.get_value() * PITCH, BY + BDEV * lvl(u.get_value()), 0]))
        guides2 = slot_guides(BIT_Y - 0.45, BY - BDEV - 0.25)
        # Chris (ElevenLabs) said this short line alone with a rising, question-like end (88 -> 143 Hz); with the next sentence
        # as context and seed 2 it falls (114 -> 81 Hz). Takes and measurements: frames/v13/audio/.
        with self.vo("It <bookmark mark='a'/>glides.", seed=2,
                     next_text="The smoothing has a bell-curve shape, a Gaussian, so this is Gaussian FSK, or GFSK.") as tr:
            self.add(ghost)
            self.remove(guides)
            self.add(guides2)
            self.play(*self.swap_cap("the frequency glides"), run_time=0.5)
            self.wait_mark("a")
            rs = row1.risers
            row1.remove(rs)
            self.add(rs)
            self.play(FadeOut(rs), Transform(row1.segs, smooth_tr.segs), run_time=1.2)
            self.add(dot)
            self.play(u.animate.set_value(3.0), run_time=1.0, rate_func=linear)
            self.play(FadeOut(dot), run_time=0.2)
            dot.clear_updaters()

        # ---- 7. Gaussian FSK ----------------------------------------------------------------------------------------
        xb = np.linspace(-0.45, 0.45, 60)
        bell = VMobject(stroke_color=YELLOW_A, stroke_width=SW_LINE).set_points_as_corners(
            np.column_stack([xb, 0.38 * np.exp(-xb ** 2 / (2 * 0.15 ** 2)), np.zeros(60)]))
        bell.move_to([xl + PITCH, 1.78, 0])
        with self.vo("The smoothing has a <bookmark mark='a'/>bell-curve shape, <bookmark mark='b'/>a Gaussian, so this is "
                                 "<bookmark mark='c'/>Gaussian FSK, or GFSK.") as tr:
            self.wait_early("a", 1.3)
            self.play(FadeIn(bell), run_time=0.6)
            self.wait_mark("b")
            total = max(self.until("c") + 1.0, 2.8)
            edges = list(range(2, 8))
            per = (total - 6 * 0.15) / 6
            for e in edges:
                self.play(bell.animate.move_to([xl + e * PITCH, 1.78, 0]), run_time=per)
                self.wait(0.15)
            self.wait_mark("c")
            self.play(*self.swap_cap("Gaussian FSK (GFSK)"), run_time=0.5)

        # ---- 8. two frequencies, one bit at a time, the move ---------------------------------------------------------
        lines = VGroup(*[DashedLine([xl, BY + s * BDEV, 0], [XR, BY + s * BDEV, 0], dash_length=0.1,
                                    stroke_color=ONE if s > 0 else ZERO, stroke_width=SW, stroke_opacity=0.9) for s in (1, -1)])
        glides = VGroup()
        for i in range(1, 8):
            if BITS[i - 1] != BITS[i]:
                uu = np.linspace(i - 0.35, i + 0.35, 40)
                glides.add(VMobject(stroke_color=YELLOW_A, stroke_width=SW_FLASH).set_points_as_corners(
                    np.column_stack([xl + uu * PITCH, BY + BDEV * np.array([lvl(x) for x in uu]), np.zeros(40)])))
        with self.vo("Still <bookmark mark='a'/>two frequencies, <bookmark mark='b'/>one bit at a time; only "
                                 "<bookmark mark='c'/>the move between them is smooth.") as tr:
            self.play(*self.swap_cap(None), FadeOut(bell), run_time=0.4)
            self.wait_mark("a")
            self.play(Create(lines), run_time=0.6)
            self.wait_mark("b")
            self.play(FadeOut(lines), guides2.animate.set_stroke(INK, width=SW, opacity=1), run_time=0.4)
            self.play(guides2.animate.set_stroke(GRID, width=SW_THIN, opacity=0.6), run_time=0.3)
            self.wait_mark("c")
            self.play(FadeIn(glides), run_time=0.4)
            self.wait(0.3)
            self.play(FadeOut(glides), run_time=0.4)

        # ---- 9. Why glide? -------------------------------------------------------------------------------------------
        small = freq_trace(smooth=1, dev=LV, center=(0, 2.0), hi_text=LAB_HI, lo_text=LAB_LO, label_size=18)
        t_left = label("the wave over time", 22).move_to([LP_C[0], 0.62, 0])
        t_axis = Arrow([LP_C[0] - PW / 2, LP_C[1] - PH / 2, 0], [LP_C[0] + PW / 2, LP_C[1] - PH / 2, 0], buff=0, color=MUTED,
                       stroke_width=SW, max_tip_length_to_length_ratio=0.05)
        t_lab = label("time", 20).next_to([LP_C[0] + PW / 2, LP_C[1] - PH / 2, 0], DOWN, buff=0.25).align_to([LP_C[0] + PW / 2, 0, 0], RIGHT)
        rpanel = spectrum_panel(0.0, RP_C, PW, PH, curve=False)
        rpanel.x_lab.shift(DOWN * 0.15)
        rpanel.y_lab.shift(LEFT * 0.15)
        left_group = VGroup(t_left, t_axis, t_lab)
        with self.vo("Why glide?") as tr:
            self.play(FadeOut(VGroup(*rest, ghost, guides2, blk, chip_box, chip_t, arrow)), Transform(row1, small),
                      FadeIn(left_group), FadeIn(rpanel), run_time=1.2)

        # ---- 10. steady wave, one frequency --------------------------------------------------------------------------
        df, sharp, grow, spread = ValueTracker(0.0), ValueTracker(1.0), ValueTracker(0.0), ValueTracker(0.0)
        wave_dyn = always_redraw(lambda: left_wave(df.get_value(), sharp.get_value()))
        spec_dyn = always_redraw(lambda: spec_curve(grow.get_value(), spread.get_value(), sharp.get_value()))
        with self.vo("A steady <bookmark mark='a'/>wave sits at exactly <bookmark mark='b'/>one frequency.") as tr:
            first = left_wave(0.0, 1.0)
            self.play(Create(first), run_time=0.9)
            self.remove(first)
            self.add(wave_dyn)
            self.wait_mark("b")
            self.add(spec_dyn)
            self.play(grow.animate.set_value(1.0), run_time=0.8)

        # ---- 11+12. sudden change, many frequencies; sharper -> wider -------------------------------------------------
        arrs = VGroup(*[Arrow([RP_C[0] + s * 0.15, -1.9, 0], [RP_C[0] + s * 0.6, -1.9, 0], buff=0, stroke_width=3, color=MUTED,
                              max_tip_length_to_length_ratio=0.4) for s in (-1, 1)])
        with self.vo("A <bookmark mark='a'/>sudden change is made of <bookmark mark='b'/>many frequencies <bookmark mark='c'/>at once, "
                                 "and <bookmark mark='d'/>the sharper the change, <bookmark mark='e'/>the wider they spread.") as tr:
            self.wait_mark("a")
            self.play(*self.swap_cap("a sudden change spreads over many frequencies"), df.animate.set_value(1.0), run_time=0.9)
            self.wait_mark("b")
            self.play(spread.animate.set_value(1.0), run_time=1.2)
            self.wait_mark("c")
            self.play(FadeIn(arrs), run_time=0.4)
            self.wait_mark("d")
            self.play(sharp.animate.set_value(0.0), run_time=0.75, rate_func=smooth)
            self.play(sharp.animate.set_value(1.0), run_time=0.75, rate_func=smooth)
            self.wait_mark("e")
            self.play(sharp.animate.set_value(0.0), run_time=0.75, rate_func=smooth)
            self.play(sharp.animate.set_value(1.0), run_time=0.75, rate_func=smooth)

        # ---- 13. Fourier analysis --------------------------------------------------------------------------------------
        f_arrow = Arrow([-0.55, -0.9, 0], [0.55, -0.9, 0], buff=0, stroke_width=SW, color=MUTED, max_tip_length_to_length_ratio=0.3)
        f_lab = VGroup(label("Fourier", 20), label("analysis", 20)).arrange(DOWN, buff=0.04).next_to(f_arrow, DOWN, buff=0.12)
        with self.vo("<bookmark mark='a'/>Fourier analysis explains why; <bookmark mark='b'/>we won't go into it.") as tr:
            self.play(FadeIn(f_arrow), FadeIn(f_lab), run_time=0.6)
            self.wait_mark("b")
            self.play(f_lab.animate.set_opacity(DIM), f_arrow.animate.set_stroke(opacity=DIM), run_time=0.5)

        # ---- 14. leaks into neighbours ----------------------------------------------------------------------------------
        base_y = RP_C[1] - PH / 2
        bl = VGroup(*[DashedLine([RP_C[0] + s * BAND, base_y, 0], [RP_C[0] + s * BAND, base_y + 2.4, 0], dash_length=0.08,
                                 stroke_color=MUTED, stroke_width=SW_THIN) for s in (-1, 1)])
        bl_lab = VGroup(*[label(t, 20).move_to([RP_C[0] + dx, base_y - 0.72, 0]) for t, dx in
                          (("neighbour", -1.85), ("our signal", 0.0), ("neighbour", 1.85))])
        fill = always_redraw(lambda: red_fill(sharp.get_value()))
        ticks = VGroup()
        for s in (-1, 1):
            x = RP_C[0] + s * 1.85
            ticks.add(Line([x, base_y + 0.05, 0], [x, base_y + 0.65, 0], stroke_color=GREEN_A, stroke_width=SW),
                      Dot([x, base_y + 0.65, 0], radius=0.07, color=GREEN_A))
        with self.vo("So <bookmark mark='a'/>a signal that jumps <bookmark mark='b'/>leaks into neighbouring frequencies, "
                                 "<bookmark mark='c'/>where other radios may be listening.") as tr:
            self.wait_mark("a")
            self.play(FadeOut(arrs), FadeIn(bl), FadeIn(bl_lab), *self.swap_cap("a signal that jumps leaks into its neighbours"), run_time=0.8)
            self.wait_early("b", 0.8)
            self.add(fill)
            self.play(FadeIn(fill), run_time=0.6)
            self.wait_mark("c")
            self.play(FadeIn(ticks), run_time=0.6)

        # ---- 15. Gliding keeps it narrow ---------------------------------------------------------------------------------
        with self.vo("Gliding keeps it <bookmark mark='a'/>narrow.") as tr:
            self.play(*self.swap_cap("gliding keeps the signal narrow"), run_time=0.4)
            self.wait_mark("a")
            self.play(sharp.animate.set_value(0.0), ShowPassingFlash(row1.segs.copy().set_stroke(YELLOW_A, width=SW_FLASH), time_width=0.8),
                      run_time=1.5, rate_func=smooth)

        # ---- 16. for the neighbours, not the receiver ----------------------------------------------------------------------
        big2 = freq_trace(smooth=1, dev=BDEV, center=(0, BY), hi_text=LAB_HI, lo_text=LAB_LO, label_size=22)
        dsrc = freq_trace(smooth=1, dev=BDEV, center=(0, BY), dots=True, link_y=BIT_Y - 0.35)
        sq = hero_bit_squares()
        g3 = slot_guides(BIT_Y - 0.45, BY - BDEV - 0.25)
        panels = VGroup(left_group, rpanel, wave_dyn, spec_dyn, fill, bl, bl_lab, ticks, f_arrow, f_lab)
        with self.vo("The smoothing is for <bookmark mark='a'/>the neighbours, <bookmark mark='b'/>not the receiver.") as tr:
            self.wait_mark("a")
            self.play(Indicate(bl_lab[0]), Indicate(bl_lab[2]), run_time=0.8)
            self.wait_mark("b")
            self.play(*self.swap_cap("the receiver asks: above the centre, or below?"), FadeOut(panels), Transform(row1, big2),
                      FadeIn(sq), FadeIn(g3), run_time=1.2)
            for i in range(8):
                self.play(FadeIn(dsrc.links[i]), FadeIn(dsrc.dots[i]), Indicate(sq[i], scale_factor=1.15), run_time=0.22)

        # ---- 17. plain 2-FSK ---------------------------------------------------------------------------------------------
        stepf = freq_trace(smooth=0, dev=BDEV, center=(0, BY), hi_text=LAB_HI, lo_text=LAB_LO, label_size=22)
        with self.vo("The drone can read <bookmark mark='a'/>plain 2-FSK <bookmark mark='b'/>without it.") as tr:
            self.play(*self.swap_cap("plain 2-FSK: the same bits"), run_time=0.4)
            self.wait_mark("a")
            self.play(*[Indicate(m, scale_factor=1.3) for m in list(dsrc.dots) + list(sq)], run_time=0.8)
            self.wait_mark("b")
            self.play(Transform(row1.segs, step60()), FadeIn(stepf.risers), run_time=1.0)
        self.play(*self.swap_cap(None), run_time=0.4)
        self.wait(0.3)

        # ---- the seam out: build the S03c start frame exactly ------------------------------------------------------------
        seam.leave(self)
        out = seam_s03b_s03c()
        out.enter(self)
        self.wait(0.4)
