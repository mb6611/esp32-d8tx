"""S03c: how the ESP32 does it. The Wi-Fi radio's undocumented test tone (one steady wave, offset from the carrier in steps of
40 MHz / 1024 = 39.06 kHz, about 1 part in 61,500 of 2.4 GHz; firmware/main/d8tone.c) is switched between two steps, +1 for a
1 and -1 for a 0, one bit every 32.2 us (7731 CPU cycles at 240 MHz). That is the "pseudo" software-defined radio: only two
tones, not any wave. The E8's glide and the ESP32's jump are compared; the spectrum curves are ILLUSTRATIVE (flag T4: the
ESP32's being wider is expected, not measured). In the air 6 bytes (4 x 0xaa, d3 91) go in front of the 20 body bytes:
208 bits x 32.2 us = 6.70 ms.
Start frame = seam_s03b_s03c(), end frame = seam_s03c_s04a("out")."""
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from parts import *
from parts import _smooth_level as _slow_smooth_level
from scipy.special import erf as _verf


def _smooth_level(u, bits, sigma):
    """Vectorised twin of parts._smooth_level (scipy erf instead of np.vectorize(math.erf)); same values."""
    u = np.asarray(u, dtype=float)
    nb = len(bits)
    k = 1.0 / (sigma * 2 ** 0.5)
    y = np.zeros_like(u)
    for i, b in enumerate(bits):
        lo = 1.0 if i == 0 else _verf((u - i) * k)
        hi = -1.0 if i == nb - 1 else _verf((u - (i + 1)) * k)
        y += (1 if b else -1) * 0.5 * (lo - hi)
    return y


_LVL_CACHE = {}


def _fast_points_equal(self, p0, p1):
    """Same test as np.allclose(p0, p1, atol=tol) (rtol 1e-5) without numpy's per-call overhead: manim calls it ~40k times
    per frame when it splits the long wave polylines into subpaths, which was most of this scene's render time."""
    atol = self.tolerance_for_point_equality
    if getattr(p0, "ndim", 1) != 1 or getattr(p1, "ndim", 1) != 1 or len(p0) != len(p1):
        return bool(np.allclose(p0, p1, atol=atol))
    for a, b in zip(p0, p1):
        if abs(a - b) > atol + 1e-5 * abs(b):
            return False
    return True


VMobject.consider_points_equals = _fast_points_equal

RY, RA = -1.6, 0.45             # row 3 (the wave) centre and amplitude while the rungs are shown
Y1C = ROW1_BIG_Y                # 0.6: row 1 centre
RUNG = 0.34                     # one tone step on screen
STEP_CYC = 0.5                  # carrier cycles per bit that one tone step squeezes on screen (cartoon)
E8_CYC = CYC_DEV * 32 / 39      # the E8's deviation relative to ours, in the cartoon


def wave_shape(theta, shp):
    """Arbitrary-signal cartoon for the morph: shp 0 = sine, 1 = squarish, 2 = sawtooth, 3 = two tones mixed."""
    s = [np.sin(theta),
         np.tanh(2.5 * np.sin(theta)) / np.tanh(2.5),
         0.9 * (2 * ((theta / TAU) % 1.0) - 1.0),
         (np.sin(theta) + 0.7 * np.sin(2.7 * theta + 1.0)) / 1.6]
    k = int(min(max(shp, 0.0), 2.999))
    f = min(max(shp, 0.0), 3.0) - k
    return (1 - f) * s[k] + f * s[min(k + 1, 3)]


def carrier_shaped(cyc, phase, shp=0.0, y=RY, amp=RA, width=WAVE_W, n=1400):
    """The uncoloured steady wave (cyc cycles per bit, phase in radians) shaped by `shp` for the arbitrary-signal morph."""
    xs = np.linspace(-width / 2, width / 2, n)
    theta = TAU * cyc * (xs + width / 2) / BIT_PITCH - phase
    ys = amp * wave_shape(theta, shp)
    return VMobject(stroke_color=INK, stroke_width=SW_LINE, stroke_opacity=0.55).set_points_as_corners(
        np.column_stack([xs, ys + y, np.zeros_like(xs)]))


def wave_any(cursor, phase, cyc, y, amp, sigma, devc, bits=HERO_BITS, width=WAVE_W, n=1400):
    """Like parts.wave_ph, but the frequency may glide (Gaussian sigma in bits) instead of jumping: the E8's wave."""
    nb = len(bits)
    xs = np.linspace(-width / 2, width / 2, n)
    u = (xs + width / 2) / (width / nb)
    f = np.full(n, float(cyc))
    m = u < cursor
    if m.any():
        key = (n, float(width), float(sigma), tuple(bits))
        if key not in _LVL_CACHE:
            _LVL_CACHE[key] = _smooth_level(u, bits, sigma)
        f[m] = cyc + devc * _LVL_CACHE[key][m]
    ph = np.concatenate([[0.0], np.cumsum(0.5 * (f[1:] + f[:-1]) * np.diff(u))]) * TAU
    ys = amp * np.sin(ph - phase)
    idx = np.minimum(u.astype(int), nb - 1)
    cut = min(max(float(cursor), 0.0), float(nb))
    edges = sorted(set([0.0, float(nb), cut] + [float(i) for i in range(1, nb)]))
    g = VGroup()
    for a, b in zip(edges[:-1], edges[1:]):
        sel = (u >= a - 1e-9) & (u <= b + 1e-9)
        if sel.sum() < 2:
            continue
        last = np.nonzero(sel)[0][-1]
        if last + 1 < n:
            sel[last + 1] = True
        i = min(int(a), nb - 1)
        col, op = (ONE if bits[i] else ZERO, 1.0) if b <= cut + 1e-9 else (INK, 0.55)
        g.add(VMobject(stroke_color=col, stroke_width=SW_LINE, stroke_opacity=op).set_points_as_corners(
            np.column_stack([xs[sel], ys[sel] + y, np.zeros(int(sel.sum()))])))
    return g


def box_text(words, cx, cy, w, h, size=17, color=MUTED, text_color=INK, sw=SW_THIN):
    box = RoundedRectangle(corner_radius=0.08, width=w, height=h, stroke_color=color, stroke_width=sw)
    txt = VGroup(*[label(s, size, text_color) for s in words]).arrange(DOWN, buff=0.03)
    return VGroup(box, txt).move_to([cx, cy, 0])


class S03C(Narrated, MovingCameraScene):
    # the macOS `say` service gives no word timings: place each bookmark at its fraction of the spoken characters (as S00 does)
    def vo(self, text):
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
        cm = self.voiceover(text=tags.sub("", text))
        print(f"VOSTART {self.renderer.time:.2f} {tags.sub('', text)[:50]}", flush=True)
        return cm

    def at(self, name):
        tr = self.current_tracker
        d = tr.start_t + self._marks[name] * tr.duration - self.renderer.time
        if d > 1e-3:
            self.wait(d)

    def rest(self, tr, pad=0.05):
        d = tr.get_remaining_duration() - pad
        if d > 0.02:
            self.wait(d)

    def capin(self, text, out=True):
        """Animations that swap the caption (old FadeOut, new FadeIn). text=None only removes."""
        a = []
        if self.cur is not None and out:
            a.append(FadeOut(self.cur))
            self.cur = None
        if text:
            self.cur = caption_at(self.camera.frame, text, 32)
            a.append(FadeIn(self.cur))
        return a

    def construct(self):
        self.cur = None
        seam = seam_s03b_s03c()
        strip = seam.enter(self)
        out_seam = seam_s03c_s04a("out")
        base = seam.mobs
        gd, sq, e8 = base.guides, base.bits, base.trace
        # split the carried group into its parts (same picture) so they can leave one by one
        self.remove(base)
        self.add(gd, sq, e8.zero, e8.segs, e8.risers, e8.links, e8.dots, e8.hi, e8.lo)
        zero = e8.zero
        e8_parts = [e8.segs, e8.risers, e8.links, e8.dots, e8.hi, e8.lo]

        t = ValueTracker(0.0)        # cursor in bits (0 = plain steady wave in row 3)
        ph = ValueTracker(0.0)
        cyc = ValueTracker(CYC_A)    # carrier cycles per bit
        lvl = ValueTracker(0.0)      # test tone offset in steps
        shp = ValueTracker(0.0)      # arbitrary-signal morph
        y3 = ValueTracker(RY)
        a3 = ValueTracker(RA)
        ph.add_updater(lambda m, dt: m.increment_value(DRIFT * dt))
        self.add(ph)

        def row3():
            if t.get_value() > 0:
                return wave_ph(t.get_value(), ph.get_value(), cyc.get_value(), y3.get_value(), a3.get_value())
            return carrier_shaped(cyc.get_value() + STEP_CYC * lvl.get_value(), ph.get_value(), shp.get_value(),
                                  y3.get_value(), a3.get_value())

        wave = always_redraw(row3)

        # ---- margin block: ESP32 { test tone, Wi-Fi radio } ----
        BXL = -6.12
        LX = -6.62                  # left edge of left-margin labels (>= ~65 px from the frame edge)
        outer = RoundedRectangle(corner_radius=0.1, width=1.0, height=2.4, stroke_color=MUTED, stroke_width=SW_THIN).move_to([BXL, -0.85, 0])
        title = label("ESP32", 18, INK).move_to([BXL, -1.8, 0])
        radio = box_text(["Wi-Fi", "radio"], BXL, -1.0, 0.86, 0.7)
        tone_box = box_text(["test", "tone"], BXL, -0.1, 0.86, 0.7, color=YELLOW_A)
        blk_arrow = Arrow([BXL + 0.5, RY, 0], [XL - 0.08, RY, 0], buff=0, stroke_width=3, color=MUTED, max_tip_length_to_length_ratio=0.35)
        ghz = label("about 2.4 GHz", 22).move_to([XR + 0.95, RY, 0])
        tag_wifi = label("Wi-Fi", 20).move_to([BXL - 0.1, -2.35, 0]).align_to([LX, 0, 0], LEFT)
        tag_bt = label("Bluetooth", 20).move_to([BXL - 0.1, -2.7, 0]).align_to([LX, 0, 0], LEFT)

        # =========== 1 ===========
        with self.vo("The ESP32's <bookmark mark='r'/>Wi-Fi radio works in <bookmark mark='b'/>the same band and can "
                                 "<bookmark mark='t'/>tune its carrier where we want.") as tr:
            self.play(FadeIn(outer), FadeIn(title), strip.undim(), run_time=0.8)
            self.at('r')
            self.play(FadeIn(radio), *[m.animate.set_opacity(DIM) for m in e8_parts], run_time=0.8)
            self.at('b')
            w0 = carrier_shaped(CYC_A, 0.0)
            self.play(Create(w0), FadeIn(ghz), run_time=1.0)
            self.remove(w0)
            self.add(wave)
            self.at('t')
            blk_arrow.set_color(YELLOW_A)
            self.play(FadeIn(blk_arrow), cyc.animate.set_value(CYC_A + STEP_CYC),
                      run_time=0.6)
            self.play(cyc.animate.set_value(CYC_A - STEP_CYC), run_time=0.6)
            self.play(cyc.animate.set_value(CYC_A), run_time=0.5)
            self.rest(tr)

        # =========== 2 ===========
        with self.vo("But it is built for <bookmark mark='w'/>Wi-Fi and <bookmark mark='b'/>Bluetooth.") as tr:
            self.play(blk_arrow.animate.set_color(MUTED), run_time=0.3)
            self.at('w')
            self.play(FadeIn(tag_wifi), run_time=0.4)
            self.at('b')
            self.play(FadeIn(tag_bt), run_time=0.4)
            self.rest(tr)

        # =========== 3 ===========
        ghost_tr = freq_trace(smooth=1, dev=ROW1_BIG_DEV, center=(0, Y1C))
        ghost = DashedVMobject(VMobject(stroke_color=MUTED, stroke_width=SW_LINE).set_points_as_corners(
            np.concatenate([s.points[::3] for s in ghost_tr.segs])), num_dashes=70).set_color(MUTED)
        ghost_lab = label("the E8's glide", 22).next_to([XR, Y1C + ROW1_BIG_DEV, 0], RIGHT, buff=0.2)
        cross = VGroup(Line(UL, DR), Line(UR, DL)).scale(0.14).set_stroke(ZERO, 4).move_to([(BXL + 0.5 + XL - 0.08) / 2, RY, 0])
        with self.vo("Copying the glide would take <bookmark mark='a'/>an arbitrary signal, <bookmark mark='m'/>any wave we choose, "
                                 "which is <bookmark mark='h'/>hard to get out of it.") as tr:
            self.play(*[FadeOut(m) for m in e8_parts], FadeOut(tag_wifi), FadeOut(tag_bt), FadeIn(ghost), FadeIn(ghost_lab),
                      *self.capin("an arbitrary signal: any wave we choose"), run_time=0.9)
            self.at('m')
            self.play(shp.animate.set_value(1.0), run_time=0.6, rate_func=linear)
            self.play(shp.animate.set_value(2.0), run_time=0.6, rate_func=linear)
            self.play(shp.animate.set_value(3.0), run_time=0.6, rate_func=linear)
            self.at('h')
            self.play(Create(cross), shp.animate.set_value(0.0), run_time=0.9)
            self.rest(tr)

        # =========== 4 ===========
        with self.vo("But it has an undocumented <bookmark mark='f'/>test feature, a test tone:") as tr:
            self.play(FadeOut(cross), FadeOut(ghost), FadeOut(ghost_lab), *self.capin(None), run_time=0.6)
            self.at('f')
            self.play(FadeIn(tone_box), run_time=0.6)
            self.rest(tr)

        # =========== 5 ===========
        flat0 = Line([XL, Y1C, 0], [XR, Y1C, 0], stroke_color=INK, stroke_width=SW_LINE)
        tone_line = always_redraw(lambda: Line([XL, Y1C + RUNG * lvl.get_value(), 0], [XR, Y1C + RUNG * lvl.get_value(), 0],
                                               stroke_color=INK, stroke_width=SW_LINE))
        with self.vo("one steady wave at a <bookmark mark='s'/>single frequency,") as tr:
            self.play(blk_arrow.animate.set_color(YELLOW_A), *self.capin("the test tone: one steady frequency"), run_time=0.5)
            self.at('s')
            self.play(Create(flat0), run_time=0.9)
            self.remove(flat0)
            self.add(tone_line)
            self.rest(tr)

        # =========== 6 ===========
        rung_k = [-3, -2, -1, 1, 2, 3]
        rungs = {k: DashedLine([XL, Y1C + RUNG * k, 0], [XR, Y1C + RUNG * k, 0], dash_length=0.08, stroke_color=GRID,
                               stroke_width=SW_THIN, stroke_opacity=0.9) for k in rung_k}
        nums = {k: label("0" if k == 0 else (f"+{k}" if k > 0 else f"−{-k}"), 20).move_to([XR + 0.3, Y1C + RUNG * k, 0])
                for k in (-2, -1, 0, 1, 2)}
        brace = Brace(Line([0, Y1C, 0], [0, Y1C + RUNG, 0]), direction=RIGHT, buff=0.0, color=MUTED, stroke_width=1).scale(0.8)
        brace.move_to([XR + 0.64, Y1C + RUNG / 2, 0])
        brace_lab = VGroup(label("about", 20, INK), label("39 kHz", 20, INK)).arrange(DOWN, buff=0.02).next_to(brace, RIGHT, buff=0.1)
        with self.vo("<bookmark mark='o'/>offset from the carrier <bookmark mark='s'/>in steps of about <bookmark mark='k'/>39 kHz,") as tr:
            self.play(*[Create(r) for r in rungs.values()], *[FadeIn(n) for n in nums.values()], run_time=0.9)
            self.at('s')
            for v in (1, 2, 1, 0, -1, 0):
                self.play(lvl.animate.set_value(v), run_time=0.15, rate_func=smooth)
                self.wait(0.2)
            self.at('k')
            self.play(FadeIn(brace), FadeIn(brace_lab), run_time=0.5)
            self.rest(tr)

        # =========== 7 ===========
        ppm = label("about 1 part in 60,000 of the carrier", 22).move_to([0.6, -0.78, 0])
        with self.vo("about 1 part in 60,000 of the carrier.") as tr:
            self.play(FadeIn(ppm), *self.capin(None), run_time=0.6)
            self.rest(tr)

        # =========== 8 ===========
        with self.vo("And D8 doesn't need an arbitrary signal.") as tr:
            self.rest(tr)

        # =========== 9 ===========
        tint_up = Rectangle(width=WAVE_W, height=RUNG * 3, stroke_width=0, fill_color=ONE, fill_opacity=0.12).move_to([0, Y1C + RUNG * 1.5, 0])
        tint_dn = Rectangle(width=WAVE_W, height=RUNG * 3, stroke_width=0, fill_color=ZERO, fill_opacity=0.12).move_to([0, Y1C - RUNG * 1.5, 0])
        lab_up = label("above: 1", 22, ONE).move_to([XR + 1.25, Y1C + 0.95, 0])
        lab_dn = label("below: 0", 22, ZERO).move_to([XR + 1.25, Y1C - 0.95, 0])
        with self.vo("The receiver only asks whether <bookmark mark='f'/>the frequency is <bookmark mark='a'/>above the centre or "
                                 "<bookmark mark='b'/>below.") as tr:
            self.play(FadeOut(ppm), *self.capin("above the centre, or below?"), run_time=0.5)
            self.at('f')
            self.play(zero.animate(rate_func=there_and_back).set_stroke(INK, width=4), run_time=0.8)
            self.at('a')
            self.play(FadeIn(tint_up), FadeIn(lab_up), run_time=0.5)
            self.at('b')
            self.play(FadeIn(tint_dn), FadeIn(lab_dn), run_time=0.5)
            self.rest(tr)

        # =========== 10 ===========
        esp = freq_trace(smooth=0, dev=RUNG, center=(0, Y1C), dots=True, link_y=BIT_Y - 0.35)
        hi39 = label("+39 kHz", 22, ONE).next_to([XR, Y1C + RUNG, 0], RIGHT, buff=0.2)
        lo39 = label("−39 kHz", 22, ZERO).next_to([XR, Y1C - RUNG, 0], RIGHT, buff=0.2)
        ones = [i for i, b in enumerate(HERO_BITS) if b]
        zeros = [i for i, b in enumerate(HERO_BITS) if not b]
        with self.vo("So <bookmark mark='t'/>two tones are enough: <bookmark mark='u'/>one step above for a 1, "
                                 "<bookmark mark='d'/>one step below for a 0.") as tr:
            self.play(*self.capin("two tones: one step above, one step below"), run_time=0.4)
            self.at('t')
            self.play(*[FadeOut(rungs[k]) for k in (-3, -2, 2, 3)], *[FadeOut(n) for n in nums.values()], FadeOut(brace), FadeOut(brace_lab),
                      rungs[1].animate.set_stroke(ONE, 2, 1.0), rungs[-1].animate.set_stroke(ZERO, 2, 1.0), run_time=0.7)
            self.at('u')
            self.play(FadeOut(tone_line), FadeIn(hi39), LaggedStart(*[FadeIn(esp.segs[i], shift=DOWN * 0.4) for i in ones], lag_ratio=0.2),
                      run_time=1.2)
            self.at('d')
            self.play(FadeIn(lo39), LaggedStart(*[FadeIn(esp.segs[i], shift=UP * 0.4) for i in zeros], lag_ratio=0.25),
                      FadeIn(esp.risers), run_time=1.2)
            self.rest(tr)

        # =========== 11 ===========
        e8_lines = VGroup(*[DashedLine([XL, Y1C + s * RUNG * 32 / 39, 0], [XR, Y1C + s * RUNG * 32 / 39, 0], dash_length=0.08,
                                       stroke_color=MUTED, stroke_width=SW_THIN) for s in (1, -1)])
        e8_lab = label("E8: 32 kHz", 20).move_to([BXL, Y1C + RUNG + 0.1, 0]).align_to([LX, 0, 0], LEFT)
        with self.vo("That's 39 kHz where the E8 <bookmark mark='l'/>uses 32, which makes <bookmark mark='n'/>no difference to that "
                                 "<bookmark mark='q'/>question.") as tr:
            self.play(*self.capin(None), Indicate(hi39, color=ONE, scale_factor=1.1), Indicate(lo39, color=ZERO, scale_factor=1.1), run_time=0.8)
            self.at('l')
            self.play(Create(e8_lines), FadeIn(e8_lab), run_time=0.7)
            self.at('n')
            self.play(LaggedStart(*[AnimationGroup(FadeIn(esp.links[i]), FadeIn(esp.dots[i])) for i in range(8)], lag_ratio=0.25), run_time=1.6)
            self.at('q')
            self.play(*[s.animate(rate_func=there_and_back).scale(1.1) for s in sq], run_time=0.7)
            self.play(FadeOut(e8_lines), FadeOut(e8_lab), FadeOut(tint_up), FadeOut(tint_dn), FadeOut(lab_up), FadeOut(lab_dn), run_time=0.5)
            self.rest(tr)

        # =========== 12 ===========
        sw_box = box_text(["software"], BXL, 1.05, 1.0, 0.45, size=17)
        sw_arrow = Arrow([BXL, 0.8, 0], [BXL, -0.08 + 0.35 - 0.06, 0], buff=0, stroke_width=3, color=MUTED, max_tip_length_to_length_ratio=0.35)
        ext = slot_guides(Y1C - ROW1_BIG_DEV - 0.25, -2.15)
        b0 = Brace(Line([bit_x(0) - BIT_PITCH / 2, Y1C - RUNG - 0.08, 0], [bit_x(0) + BIT_PITCH / 2, Y1C - RUNG - 0.08, 0]),
                   direction=DOWN, buff=0.0, color=MUTED, stroke_width=1).scale(0.8)
        t32 = label("32 µs", 20, INK).next_to(b0, DOWN, buff=0.05)
        edges = [1, 2, 6, 7]

        def cur_x():
            return XL + min(max(t.get_value(), 0.0), 8.0) * BIT_PITCH

        def bit_now():
            return HERO_BITS[min(int(t.get_value()), 7)]

        def sweep(dur, flash=True):
            cursor = always_redraw(lambda: DashedLine([cur_x(), BIT_Y - 0.45, 0], [cur_x(), RY - RA - 0.1, 0], dash_length=0.08,
                                                       stroke_color=MUTED, stroke_width=SW_THIN))
            dot = always_redraw(lambda: Dot([cur_x(), Y1C + (RUNG if bit_now() else -RUNG), 0], radius=0.07,
                                            color=ONE if bit_now() else ZERO))
            if flash:
                sw_arrow.add_updater(lambda m: m.set_color(YELLOW_A if any(abs(t.get_value() - k) < 0.12 for k in edges) else MUTED))
            self.add(cursor, dot)
            self.play(t.animate.set_value(8.0), run_time=dur, rate_func=linear)
            sw_arrow.clear_updaters()
            sw_arrow.set_color(MUTED)
            self.play(FadeOut(cursor), FadeOut(dot), run_time=0.3)

        with self.vo("Software <bookmark mark='s'/>switches the radio between the two tones, one bit every 32 µs.") as tr:
            self.play(FadeIn(sw_box), FadeIn(sw_arrow), FadeIn(ext), FadeIn(b0), FadeIn(t32), *self.capin("one tone or the other, 32 µs at a time"),
                      *[FadeOut(c) for c in list(esp.links) + list(esp.dots)], run_time=0.9)
            self.at('s')
            sweep(3.2)
            self.rest(tr)

        # =========== 13 ===========
        sdr = label("software-defined radio", 20, INK).move_to([LX, -2.7, 0]).align_to([LX, 0, 0], LEFT)
        with self.vo("Software picks <bookmark mark='w'/>which tone goes out, and when: that is the <bookmark mark='d'/>software-defined part.") as tr:
            self.play(*self.capin(None), sw_box[0].animate(rate_func=there_and_back).set_stroke(YELLOW_A, 3), FadeOut(b0), FadeOut(t32), run_time=0.7)
            self.at('w')
            t.set_value(0.0)
            sweep(1.6)
            self.at('d')
            self.play(FadeIn(sdr), run_time=0.5)
            self.rest(tr)

        # =========== 14 ===========
        pseudo = label("pseudo", 20, INK).move_to([LX, -2.35, 0]).align_to([LX, 0, 0], LEFT)
        ghost2 = ghost.copy().set_stroke(opacity=DIM)
        cross2 = VGroup(Line(UL, DR), Line(UR, DL)).scale(0.3).set_stroke(ZERO, 5).move_to([0, Y1C, 0])
        with self.vo("It has <bookmark mark='o'/>only these tones, not <bookmark mark='a'/>any wave: that is the <bookmark mark='p'/>pseudo part.") as tr:
            self.play(*[r.animate(rate_func=there_and_back).set_stroke(width=5) for r in (rungs[1], rungs[-1])], run_time=0.8)
            self.at('a')
            self.play(FadeIn(ghost2), Create(cross2), run_time=0.6)
            self.wait(0.4)
            self.play(FadeOut(ghost2), FadeOut(cross2), run_time=0.4)
            self.at('p')
            self.play(FadeIn(pseudo), run_time=0.5)
            self.rest(tr)

        # =========== 15 ===========
        Y_E8T, Y_E8W, Y_ESPT, Y_ESPW = 1.35, 0.45, -0.75, -1.65
        e8n = freq_trace(smooth=1, dev=0.25, center=(0, Y_E8T), dots=True, link_y=BIT_Y - 0.35)
        esp2 = freq_trace(smooth=0, dev=0.25, center=(0, Y_ESPT), dots=True, link_y=BIT_Y - 0.35)
        rl = {k: label(k, 20).move_to([BXL, y, 0]) for k, y in (("E8", Y_E8T), ("E8 wave", Y_E8W), ("ESP32", Y_ESPT), ("ESP32 wave", Y_ESPW))}
        for m in rl.values():
            m.align_to([LX, 0, 0], LEFT)
        e8wave = always_redraw(lambda: wave_any(t.get_value(), ph.get_value(), cyc.get_value(), Y_E8W, 0.32, 0.14, E8_CYC))

        def lv_e8():
            u = min(max(t.get_value(), 0.0), 8.0)
            return float(_smooth_level(np.array([u]), HERO_BITS, 0.14)[0])

        dot_e8 = always_redraw(lambda: Dot([cur_x(), Y_E8T + 0.25 * lv_e8(), 0], radius=0.07, color=ONE if bit_now() else ZERO))
        dot_esp = always_redraw(lambda: Dot([cur_x(), Y_ESPT + (0.25 if bit_now() else -0.25), 0], radius=0.07, color=ONE if bit_now() else ZERO))
        cursor4 = always_redraw(lambda: DashedLine([cur_x(), BIT_Y - 0.45, 0], [cur_x(), Y_ESPW - 0.32 - 0.1, 0], dash_length=0.08,
                                                    stroke_color=MUTED, stroke_width=SW_THIN))
        with self.vo("<bookmark mark='s'/>So the E8's frequency <bookmark mark='g'/>glides and the ESP32's <bookmark mark='j'/>jumps.") as tr:
            self.play(*self.capin("E8: glides. ESP32: jumps."),
                      *[FadeOut(m) for m in (sw_box, sw_arrow, tone_box, radio, outer, title, blk_arrow, ghz, sdr, pseudo, hi39, lo39)],
                      FadeOut(rungs[1]), FadeOut(rungs[-1]),
                      *[ReplacementTransform(esp.segs[i], esp2.segs[i]) for i in range(8)], ReplacementTransform(esp.risers, esp2.risers), ReplacementTransform(zero, esp2.zero),
                      FadeIn(e8n.segs), FadeIn(e8n.zero), FadeIn(e8wave), *[FadeIn(m) for m in rl.values()],
                      y3.animate.set_value(Y_ESPW), a3.animate.set_value(0.32),
                      run_time=1.2)
            t.set_value(0.0)
            self.add(cursor4, dot_e8, dot_esp)
            d = max(1.5, tr.get_remaining_duration() - 0.9)
            self.play(t.animate.set_value(8.0), run_time=d, rate_func=linear)
            self.play(FadeOut(cursor4), FadeOut(dot_e8), FadeOut(dot_esp), run_time=0.3)
            self.rest(tr)

        # =========== 16 ===========
        pc = np.array([0.0, -1.2, 0.0])
        panel = spectrum_panel(0.0, pc, 8.0, 2.2, curve=False)
        e8c = spectrum_curve(0.0, pc, 7.2, 1.76, INK)            # ILLUSTRATIVE (T4): not a measurement
        sharp = ValueTracker(0.0)
        espc = always_redraw(lambda: spectrum_curve(sharp.get_value(), pc, 7.2, 1.76, YELLOW_A, 1.0 + 0.5 * sharp.get_value()))  # ILLUSTRATIVE
        e8_l = label("E8", 22, INK).move_to([pc[0] - 1.3, pc[1] + 0.25, 0])
        panel.x_lab.shift(LEFT * 0.55 + DOWN * 0.08)
        esp_l = label("ESP32", 22, YELLOW_A).move_to([pc[0] + 2.7, pc[1] - 0.5, 0])
        with self.vo("The ESP32's signal should be the <bookmark mark='w'/>wider of the two, though I <bookmark mark='c'/>haven't measured it.") as tr:
            self.play(FadeOut(e8wave), FadeOut(wave), *[FadeOut(c) for c in esp2.segs], FadeOut(esp2.risers), FadeOut(esp2.zero), FadeOut(gd), FadeOut(ext),
                      *self.capin(None), FadeOut(rl["E8 wave"]), FadeOut(rl["ESP32"]), FadeOut(rl["ESP32 wave"]), FadeIn(panel), FadeIn(e8c), FadeIn(e8_l), run_time=0.9)
            self.at('w')
            self.add(espc)
            self.play(sharp.animate.set_value(1.0), FadeIn(esp_l), run_time=1.5)
            self.at('c')
            self.play(*self.capin("expected: a wider signal (not measured)"), run_time=0.5)
            self.rest(tr)

        # =========== 17 ===========
        with self.vo("The drone reads <bookmark mark='s'/>the same bits from <bookmark mark='b'/>both.") as tr:
            self.play(FadeOut(panel), FadeOut(e8c), FadeOut(espc), FadeOut(e8_l), FadeOut(esp_l), *self.capin(None),
                      FadeIn(gd), *[FadeIn(c) for c in esp2.segs], FadeIn(esp2.risers), FadeIn(esp2.zero), FadeIn(rl["ESP32"]), run_time=0.4)
            self.play(*self.capin("the same bits from both"), run_time=0.3)
            self.at('s')
            self.play(LaggedStart(*[AnimationGroup(FadeIn(e8n.links[i]), FadeIn(e8n.dots[i]), FadeIn(esp2.links[i]), FadeIn(esp2.dots[i]))
                                    for i in range(8)], lag_ratio=0.2), run_time=1.4)
            self.at('b')
            self.play(*[s.animate(rate_func=there_and_back).scale(1.1) for s in sq], run_time=0.7)
            self.rest(tr)

        # =========== 18 ===========
        PW = 0.055
        total = 208 * PW
        x0 = -total / 2
        pat_w = 48 * PW
        pk_x0 = x0 + pat_w
        pat_bits = [int(b) for x in AIR_HEAD for b in f"{x:08b}"]

        def ticks(bits, xs0, hot=()):
            g = VGroup()
            for i, b in enumerate(bits):
                x = xs0 + (i + 0.5) * PW
                if i in hot:
                    g.add(Line([x, -0.2, 0], [x, 0.2, 0], stroke_color=YELLOW_A, stroke_width=2.5))
                else:
                    g.add(Line([x, -0.2, 0], [x, 0.2, 0], stroke_color=ONE if b else ZERO, stroke_width=2.5, stroke_opacity=0.4))
            return g

        pk_bar = Rectangle(width=160 * PW, height=0.5, stroke_color=STRUCT, stroke_width=SW).move_to([pk_x0 + 80 * PW, 0, 0])
        pk_ticks = ticks(PBITS, pk_x0, THROTTLE_BIT_IDX)
        pk_brace = Brace(pk_bar, UP, buff=0.1, color=MUTED, stroke_width=1)
        pk_lab = label("the packet: 20 bytes", 22, INK).next_to(pk_brace, UP, buff=0.08)
        pt_bar = Rectangle(width=pat_w, height=0.5, stroke_color=GREEN_A, stroke_width=SW).move_to([x0 + pat_w / 2, 0, 0])
        pt_ticks = ticks(pat_bits, x0)
        pt_grp = VGroup(pt_bar, pt_ticks)
        pt_lab = label("fixed pattern", 22, GREEN_A).next_to(pt_bar, UP, buff=0.25)
        scan = Line([x0, -0.45, 0], [x0, 0.45, 0], stroke_color=GREEN_A, stroke_width=3)
        start_lab = label("the packet starts here", 22, GREEN_A).move_to([pk_x0, -0.8, 0])
        with self.vo("<bookmark mark='a'/>In the air, a short fixed pattern <bookmark mark='p'/>goes in front of the packet, so the receiver can "
                                 "<bookmark mark='f'/>find its start.") as tr:
            self.remove(*[m for m in self.mobjects if isinstance(m, ValueTracker)])
            ph.clear_updaters()
            gone = [m for m in self.mobjects if m is not strip and m is not self.camera.frame and m is not self.cur]
            self.play(*[FadeOut(m) for m in gone], FadeOut(self.cur), run_time=0.6)
            self.cur = None
            self.play(Create(pk_bar), FadeIn(pk_ticks), *self.capin("the same pattern before every packet"), FadeIn(pk_brace), FadeIn(pk_lab), run_time=1.0)
            self.at('p')
            self.play(FadeIn(pt_grp, shift=RIGHT * 1.0), FadeIn(pt_lab), run_time=0.9)
            self.at('f')
            self.add(scan)
            self.play(scan.animate.shift(RIGHT * pat_w), run_time=1.2, rate_func=linear)
            self.play(FadeIn(start_lab), run_time=0.4)
            self.rest(tr)

        # =========== 19 ===========
        allbars = VGroup(pk_bar, pk_ticks, pt_grp, pk_brace, pk_lab, pt_lab, scan, start_lab)
        brace7 = Brace(VGroup(pt_bar, pk_bar), DOWN, buff=0.55, color=MUTED, stroke_width=1)
        ms7 = label("about 7 ms", 22, INK).next_to(brace7, DOWN, buff=0.08)
        box = Rectangle(width=total + 0.3, height=0.8, stroke_color=YELLOW_A, stroke_width=SW).move_to([0, 0, 0])
        blk = packet_block_big()
        with self.vo("One packet is one short burst of this wave, about <bookmark mark='m'/>7 ms long.") as tr:
            self.play(FadeOut(start_lab), *self.capin("one packet: one burst, about 7 ms"), run_time=0.8)
            d0 = tr.start_t + self._marks['m'] * tr.duration - self.renderer.time - 0.2
            if d0 > 0.02:
                self.wait(d0)
            self.play(FadeIn(brace7), FadeIn(ms7), run_time=0.4)
            self.at('m')
            self.play(Create(box), run_time=0.6)
            d = max(1.0, tr.get_remaining_duration() - 0.3)
            if d - 1.8 > 0.02:
                self.wait(d - 1.8)
            self.play(ReplacementTransform(box, blk), FadeOut(VGroup(pk_bar, pk_ticks, pt_grp, pk_brace, pk_lab, pt_lab, scan, brace7, ms7)),
                      *self.capin(None), run_time=1.4)
            self.rest(tr, 0.0)

        # hard cut onto the exact outgoing seam frame (same picture)
        out_seam.leave(self)
        out_seam.enter(self)
        self.wait(0.5)
