"""S03a carrier and 2-FSK. In: seam_s02b_s03a("in"). Out: seam_s03a_s03b (the scene ends by swapping to that seam's exact frame)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from parts import *


class S03A(Narrated, MovingCameraScene):
    """Carrier, then the bits as a frequency shift of it: 2-FSK."""

    def cap(self, text, size=32):
        return caption_at(self.camera.frame, text, size)

    def say(self, text):
        """Voiceover with local bookmarks: the free voice has no word boundaries, so a bookmark's time is estimated from its
        share of the spoken characters (a pause weighs a few characters)."""
        import re
        sp = spoken(text)
        parts = re.split(r"<bookmark\s*mark\s*=\s*['\"](\w+)['\"]\s*/>", sp)
        clean, self._marks, n = "", {}, 0.0
        weigh = len     # exact word times from the voice: plain character offsets
        for k, part in enumerate(parts):
            if k % 2:
                self._marks[part] = n
            else:
                clean += part
                n += weigh(part)
        self._total = n
        print(f"[S03A narr] t={self.renderer.time:6.2f}  {clean[:60]}", flush=True)
        return super(Narrated, self).voiceover(text=clean)

    def mark(self, name):
        tr = self.current_tracker
        due = tr.start_t.__float__() + frac_to_seconds(tr, self._marks[name] / self._total) if hasattr(tr, "start_t") else None
        now = float(self.renderer.time)
        if due - now > 0.02:
            self.wait(due - now)
        print(f"[S03A mark {name}] t={self.renderer.time:6.2f}", flush=True)

    def construct(self):
        seam_in = seam_s02b_s03a("in")
        seam_out = seam_s03a_s03b()
        R = seam_out.mobs                      # the end frame; its parts are animated in one by one, then the seam is entered exactly
        seam_in.enter(self)
        allbits = seam_in.mobs
        sqs = byte_bits(allbits, HERO_BYTE)
        others = VGroup(*[b for n, b in enumerate(allbits) if not 8 * HERO_BYTE <= n < 8 * HERO_BYTE + 8])
        self.wait(0.3)

        t = ValueTracker(0.0)              # cursor, in bits
        cyc = ValueTracker(CYC_A)          # carrier cycles per bit on screen
        ph = ValueTracker(0.0)             # travelling-wave phase
        carrier = always_redraw(lambda: carrier_ph(cyc.get_value(), ph.get_value()))
        wave = always_redraw(lambda: wave_ph(t.get_value(), ph.get_value(), cyc.get_value(), Y3, A3))
        ones = [i for i, b in enumerate(HERO_BITS) if b]
        zeros = [i for i, b in enumerate(HERO_BITS) if not b]
        row1 = R.row1

        # ---- 1: the eight bits spread out ----
        with self.say("Now those bits have to get into the air."):
            self.play(FadeOut(others), *[sqs[i].animate.move_to([bit_x(i), BIT_Y, 0]) for i in range(8)], run_time=0.9)
            self.play(*[s.animate(rate_func=there_and_back).scale(1.08) for s in sqs], run_time=1.0)

        # ---- 2 and 3: the carrier, 2.4 GHz ----
        c2 = self.cap("the carrier: a steady wave at one frequency")
        dot = always_redraw(lambda: Dot([XL, Y2 - A2 * np.sin(ph.get_value()), 0], radius=0.08, color=YELLOW_A))
        carrier_lab = R.carrier_lab
        l_ghz = label("about 2.4 GHz", 20, INK)
        l_bill = VGroup(label("2,400,000,000", 20), label("swings a second", 20)).arrange(DOWN, buff=0.06, aligned_edge=LEFT)
        cw = BIT_PITCH / CYC_A                       # one cycle on screen
        cyc_line = Line([XL, Y2 + A2 + 0.12, 0], [XL + cw, Y2 + A2 + 0.12, 0])
        brace = Brace(cyc_line, direction=UP, buff=0.0, color=MUTED, stroke_width=1).scale(0.8)
        one_swing = label("one swing", 20, INK).next_to(brace, UP, buff=0.08)
        carrier_lab.move_to([XR + 0.25 + carrier_lab.width / 2, Y2 + 0.3, 0])
        l_ghz.move_to([XR + 0.25 + l_ghz.width / 2, Y2 - 0.1, 0])
        l_bill.move_to([XR + 0.25 + l_bill.width / 2, Y2 - 0.6, 0])
        l_bill.align_to(l_ghz, LEFT)
        ghz_group = VGroup(l_ghz, l_bill)

        with self.say("A radio signal is built around a carrier: <bookmark mark='a'/>a steady wave at one frequency, "
                      "<bookmark mark='b'/>here about <bookmark mark='c'/>2.4 GHz, or <bookmark mark='d'/>2.4 billion "
                      "<bookmark mark='e'/>swings a second."):
            c0 = carrier_wave(CYC_A)
            self.play(Create(c0), FadeIn(carrier_lab), FadeIn(c2), run_time=1.4)
            self.remove(c0); self.add(carrier, ph)
            ph.add_updater(lambda m, dt: m.increment_value(DRIFT * dt))
            self.mark("a")
            self.play(FadeIn(dot), run_time=0.4)
            self.mark("b")
            self.play(FadeOut(c2), run_time=0.3)
            self.mark("c")
            self.play(FadeIn(l_ghz), run_time=0.5)
            self.mark("d")
            self.play(FadeIn(l_bill), run_time=0.6)
            self.mark("e")
            self.play(FadeIn(brace), FadeIn(one_swing), run_time=0.5)

        # ---- 4, 5, 6: the bits shift the frequency ----
        c4 = self.cap("the bits shift the carrier's frequency")
        hi_pieces = [row1.segs[i] for i in ones]
        lo_pieces = [row1.segs[i] for i in zeros]
        with self.say("D8 sends bits by shifting <bookmark mark='a'/>that frequency: <bookmark mark='b'/>a little up for a 1, "
                      "<bookmark mark='c'/>a little down for a 0, <bookmark mark='d'/>each bit in its own slot of time."):
            self.play(FadeOut(brace), FadeOut(one_swing), FadeOut(l_bill), FadeOut(dot), FadeIn(c4), run_time=0.5)
            self.play(cyc.animate.set_value(CYC_A + CYC_DEV), run_time=0.4)
            self.play(cyc.animate.set_value(CYC_A - CYC_DEV), run_time=0.8)
            self.play(cyc.animate.set_value(CYC_A), run_time=0.4)
            self.play(FadeOut(l_ghz), run_time=0.3)
            self.mark("b")
            self.play(FadeIn(row1.zero), FadeIn(row1.mid), FadeIn(R.ax_freq), FadeIn(row1.hi),
                      LaggedStart(*[FadeIn(s, shift=DOWN * 0.6) for s in hi_pieces], lag_ratio=0.25),
                      cyc.animate.set_value(CYC_A + CYC_DEV), run_time=1.3)
            self.play(cyc.animate.set_value(CYC_A), run_time=0.4)
            self.mark("c")
            self.play(FadeIn(row1.lo), FadeIn(row1.risers),
                      LaggedStart(*[FadeIn(s, shift=DOWN * 0.6) for s in lo_pieces], lag_ratio=0.25),
                      cyc.animate.set_value(CYC_A - CYC_DEV), run_time=1.3)
            self.play(cyc.animate.set_value(CYC_A), run_time=0.4)
            self.mark("d")
            # ---- 7: slots, row 3 ----
            w0 = carrier_ph(CYC_A, ph.get_value(), Y3, A3)
            plus = R.plus
            sl = Line([bit_x(0) - BIT_PITCH / 2, Y3 - A3 - 0.12, 0], [bit_x(0) + BIT_PITCH / 2, Y3 - A3 - 0.12, 0])
            b0 = Brace(sl, direction=DOWN, buff=0.0, color=MUTED, stroke_width=1).scale(0.8)
            one_bit = label("one bit", 20, INK).next_to(b0, DOWN, buff=0.05)
            self.play(FadeOut(c4), LaggedStart(*[FadeIn(g) for g in R.guides], lag_ratio=0.2),
                      Create(w0), FadeIn(plus), FadeIn(R.eq), FadeIn(R.ax_time), run_time=1.6)
            self.remove(w0); self.add(wave)
            self.play(FadeIn(b0), FadeIn(one_bit), run_time=0.5)

        # ---- 8: the sweep ----
        def cur_x():
            return XL + min(max(t.get_value(), 0.0), 8.0) * BIT_PITCH
        cursor = always_redraw(lambda: DashedLine([cur_x(), BIT_Y - 0.45, 0], [cur_x(), Y3 - A3 - 0.1, 0],
                                                  dash_length=0.08, stroke_color=MUTED, stroke_width=SW_THIN))
        lvl = lambda: HERO_BITS[min(int(t.get_value()), 7)]
        hop = always_redraw(lambda: Dot([cur_x(), Y1 + (LV if lvl() else -LV), 0], radius=0.07, color=ONE if lvl() else ZERO))
        c8a = self.cap("frequency-shift keying (FSK)")
        c8b = self.cap("two frequencies: 2-FSK")
        pulse = lambda g: g.animate(rate_func=there_and_back).set_stroke(width=SW_LINE * 2.4)
        with self.say("This is <bookmark mark='a'/>frequency-shift keying, or FSK; <bookmark mark='b'/>with two frequencies, 2-FSK."):
            self.add(cursor, hop)
            self.play(FadeOut(b0), FadeOut(one_bit), FadeIn(c8a), run_time=0.4)
            self.mark("a")
            for i in range(8):
                self.play(t.animate(rate_func=linear).set_value(i + 1),
                          sqs[i].animate(rate_func=there_and_back).scale(1.12), run_time=0.4)
            self.remove(cursor, hop)
            self.mark("b")
            self.play(FadeOut(c8a), FadeIn(c8b), run_time=0.3)
            self.play(pulse(VGroup(*hi_pieces)), run_time=0.7)
            self.play(pulse(VGroup(*lo_pieces)), run_time=0.7)

        # ---- 9: exaggerated ----
        with self.say("The real shift is far too small to see, so the picture <bookmark mark='a'/>exaggerates it."):
            self.play(FadeOut(c8b), run_time=0.4)
            ph.clear_updaters()
            target = np.ceil(ph.get_value() / TAU) * TAU
            self.play(ph.animate(rate_func=linear, run_time=max(0.5, (target - ph.get_value()) / DRIFT)).set_value(target))
            self.mark("a")
            self.play(FadeIn(R.note), run_time=0.6)

        # ---- exact end frame ----
        self.remove(carrier, wave, ph, t, cyc)
        seam_in.leave(self)
        carrier_lab.move_to([XR + 0.95, Y2, 0])    # it was moved earlier; restore the seam's exact position
        seam_out.enter(self)
        self.wait(0.5)
