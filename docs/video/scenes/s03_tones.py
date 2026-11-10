"""S03: the classic modulation diagram, three stacked rows under the throttle's eight bits:
(1) the bit signal as a frequency offset, +39 kHz for a 1, -39 kHz for a 0; (2) channel A's carrier; (3) the sum:
the carrier squeezed by a 1 and stretched by a 0 as the cursor passes. Then the hop: the same bits on channel B's
carrier give a different wave. Then the wave alone turns into the yellow packet block (carry-over for S04).
Facts (firmware/main/d8tone.c): 2-FSK, so the bits shift the carrier's frequency (carrier + offset, not a product);
tone step 40 MHz/1024 = 39.0625 kHz, +1 step for a 1 bit, -1 for a 0 (stock D8 deviation is +-31.7 kHz); 7731 CPU
cycles per bit at 240 MHz = 32.2 us (31,044 baud). Channel n = 2404 MHz + n * 299.93 kHz: channel A is hop channel
0 = 2404.000 MHz, channel B is hop channel 57 = 2421.096 MHz (common.TABLE entries 0 and 1 of the E8 hop table; entry
1 is the channel of S04's first packet, so the wave that becomes the packet here is that packet). On screen the carrier is slowed to CYC_A cycles per bit for A and CYC_B for B, one
more for a 1 and one fewer for a 0 (the real ratio 39 kHz / 2.4 GHz is about 1 in 60,000 and would be invisible, and
A and B really differ by 0.7 %); 0.8 s of screen time per bit."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from parts import *

SEC = 0.4                        # screen seconds per bit
K3 = FW / UZOOM_W                # the unrolled bits as seen at the end of S02
CH_A, CH_B = TABLE[0], TABLE[1]  # hop channels 0 and 57
CYC_A, CYC_B = 3.0, 5.0          # cartoon carrier cycles per bit


def ch_ghz(n):
    """d8tone.c / packet.c d8_channel_f10: channel n = 2404 MHz + n * 299.93 kHz."""
    return (2404.0 + n * 0.29993) / 1000.0


assert f"{ch_ghz(CH_A):.3f}" == "2.404" and f"{ch_ghz(CH_B):.3f}" == "2.421"

Y1, LV = 1.3, 0.28               # row 1: the bit signal, levels at Y1 +- LV
Y2, A2 = 0.0, 0.42               # row 2: the carrier
Y3, A3 = -1.5, 0.55              # row 3: carrier + offset
XL, XR = -WAVE_W / 2, WAVE_W / 2
OPX = XL - 0.65                  # column of the + and = signs


def carrier_wave(cyc, y=Y2, amp=A2):
    """The unmodulated carrier as one unbroken line (fsk_wave cuts it at every bit edge)."""
    ps = fsk_pieces(0.0, 0.0, amp=amp, cyc=cyc)
    xs, ys = np.concatenate([p[0] for p in ps]), np.concatenate([p[1] for p in ps])
    v = VMobject(stroke_color=INK, stroke_width=SW_LINE, stroke_opacity=0.55)
    return v.set_points_as_corners(np.column_stack([xs, ys + y, np.zeros_like(xs)]))


DRIFT = 3.0                      # rad/s: the idle flow of the waves while the voice talks


def pieces_ph(cursor, phase, cyc, amp, bits=HERO_BITS, width=WAVE_W, n=1400):
    """Like parts.fsk_pieces, but the whole wave travels: phase offset `phase` (radians). Returns [(xs, ys, col, op)]."""
    nb = len(bits)
    xs = np.linspace(-width / 2, width / 2, n)
    u = (xs + width / 2) / (width / nb)
    idx = np.minimum(u.astype(int), nb - 1)
    barr = np.array(bits)
    f = np.full(n, float(cyc))
    m = u < cursor
    f[m] = np.where(barr[idx[m]] == 1, cyc + CYC_DEV, cyc - CYC_DEV)
    ph = np.concatenate([[0.0], np.cumsum(0.5 * (f[1:] + f[:-1]) * np.diff(u))]) * TAU
    ys = amp * np.sin(ph - phase)
    cut = min(max(float(cursor), 0.0), float(nb))
    edges = sorted(set([0.0, float(nb), cut] + [float(i) for i in range(1, nb)]))
    out = []
    for a, b in zip(edges[:-1], edges[1:]):
        sel = (u >= a - 1e-9) & (u <= b + 1e-9)
        if sel.sum() < 2:
            continue
        last = np.nonzero(sel)[0][-1]
        if last + 1 < n:
            sel[last + 1] = True
        i = min(int(a), nb - 1)
        if b <= cut + 1e-9:
            out.append((xs[sel], ys[sel], ONE if bits[i] else ZERO, 1.0))
        else:
            out.append((xs[sel], ys[sel], INK, 0.55))
    return out


def wave_ph(cursor, phase, cyc, y, amp):
    g = VGroup()
    for xs, ys, col, op in pieces_ph(cursor, phase, cyc, amp):
        v = VMobject(stroke_color=col, stroke_width=SW_LINE, stroke_opacity=op)
        v.set_points_as_corners(np.column_stack([xs, ys + y, np.zeros_like(xs)]))
        g.add(v)
    return g


def carrier_ph(cyc, phase, y=Y2, amp=A2):
    xs, ys = np.concatenate([q[0] for q in pieces_ph(0.0, phase, cyc, amp)]), np.concatenate([q[1] for q in pieces_ph(0.0, phase, cyc, amp)])
    v = VMobject(stroke_color=INK, stroke_width=SW_LINE, stroke_opacity=0.55)
    return v.set_points_as_corners(np.column_stack([xs, ys + y, np.zeros_like(xs)]))


class S03(Narrated, MovingCameraScene):
    def cap(self, text, size=32):
        return caption_at(self.camera.frame, text, size)

    def say(self, text):
        print(f"[S03 narr] t={self.renderer.time:6.2f}  {text}", flush=True)
        return self.voiceover(text=text)

    def construct(self):
        frame = self.camera.frame
        strip = MapStrip(K_ESP, lambda: (frame.get_center(), frame.width))
        self.add(strip)
        allbits = bit_cells(k=K3, center=[0, BIT_Y, 0])
        self.add(allbits)
        self.wait(0.3)

        sqs = byte_bits(allbits, HERO_BYTE)
        others = VGroup(*[b for n, b in enumerate(allbits) if not 8 * HERO_BYTE <= n < 8 * HERO_BYTE + 8])
        zero = DashedLine([XL, Y1, 0], [XR, Y1, 0], dash_length=0.08, stroke_color=GRID, stroke_width=SW_THIN)
        lev = lambda b: Y1 + (LV if b else -LV)
        segs = VGroup(*[Line([bit_x(i) - BIT_PITCH / 2, lev(b), 0], [bit_x(i) + BIT_PITCH / 2, lev(b), 0],
                             stroke_color=ONE if b else ZERO, stroke_width=SW_LINE) for i, b in enumerate(HERO_BITS)])
        risers = VGroup(*[Line([bit_x(i) + BIT_PITCH / 2, Y1 - LV, 0], [bit_x(i) + BIT_PITCH / 2, Y1 + LV, 0],
                               stroke_color=MUTED, stroke_width=SW_THIN)
                          for i in range(7) if HERO_BITS[i] != HERO_BITS[i + 1]])
        hi = label("+39 kHz", 22, ONE).next_to([XR, Y1 + LV, 0], RIGHT, buff=0.2)
        lo = label("−39 kHz", 22, ZERO).next_to([XR, Y1 - LV, 0], RIGHT, buff=0.2)
        ones = [i for i, b in enumerate(HERO_BITS) if b]
        zeros = [i for i, b in enumerate(HERO_BITS) if not b]
        t = ValueTracker(0.0)            # cursor, in bits
        cyc = ValueTracker(CYC_A)        # carrier cycles per bit on screen
        ph = ValueTracker(0.0)           # travelling-wave phase; drifts while the voice talks, back at rest at the end
        carrier = always_redraw(lambda: carrier_ph(cyc.get_value(), ph.get_value()))
        carrier0 = carrier_wave(CYC_A)
        plus = label("+", 40, INK).move_to([OPX, (Y1 + Y2) / 2, 0])
        chan = label("channel A", 22).move_to([XR + 0.95, Y2 + 0.2, 0])
        freq = label(f"{ch_ghz(CH_A):.3f} GHz", 22, INK).move_to([XR + 0.95, Y2 - 0.2, 0])
        row_box = lambda y, a: Rectangle(width=WAVE_W + 0.4, height=2 * a + 0.3, stroke_color=YELLOW_A,
                                         stroke_width=SW_THIN).move_to([0, y, 0])

        # ---- the eight throttle bits spread out ----
        with self.say("Now we need to get those bits into the air."):
            self.play(FadeOut(others), *[sqs[i].animate.move_to([bit_x(i), BIT_Y, 0]) for i in range(8)], run_time=0.9)
            self.play(*[s.animate(rate_func=there_and_back).scale(1.08) for s in sqs], run_time=1.0)

        # ---- row 2: channel A's carrier ----
        c2 = self.cap("the carrier: channel A's steady wave")
        with self.say("Each radio channel has a carrier, a steady wave at one frequency around 2.4 GHz."):
            self.play(Create(carrier0), FadeIn(chan), FadeIn(freq), FadeIn(c2), run_time=1.4)
            self.remove(carrier0); self.add(carrier, ph)
            ph.add_updater(lambda m, dt: m.increment_value(DRIFT * dt))   # the carrier flows from here on
            self.play(Indicate(freq, color=INK), run_time=1.2)

        # ---- row 1: the bits as a frequency offset (one tone step = 40 MHz / 1024 = 39.0625 kHz) ----
        c = self.cap("each bit is a small frequency offset")
        with self.say("To send a 1 we nudge the carrier up by 39 kHz,"):
            self.play(FadeOut(c2), run_time=0.3)
            self.play(FadeIn(zero), FadeIn(hi), FadeIn(c),
                      LaggedStart(*[FadeIn(segs[i], shift=DOWN * 0.6) for i in ones], lag_ratio=0.25),
                      cyc.animate.set_value(CYC_A + CYC_DEV), run_time=1.5)     # the carrier visibly squeezes
            self.play(cyc.animate.set_value(CYC_A), run_time=0.8)
        with self.say("and to send a 0 we nudge it down by 39 kHz."):
            self.play(FadeIn(lo),
                      LaggedStart(*[FadeIn(segs[i], shift=DOWN * 0.6) for i in zeros], lag_ratio=0.25),
                      cyc.animate.set_value(CYC_A - CYC_DEV), run_time=1.5)     # and stretches
            self.play(FadeIn(risers), cyc.animate.set_value(CYC_A), run_time=0.8)

        # ---- row 3: carrier + offset ----
        wave = always_redraw(lambda: wave_ph(t.get_value(), ph.get_value(), cyc.get_value(), Y3, A3))
        wave0 = lambda: carrier_ph(CYC_A, ph.get_value(), Y3, A3)
        eq = label("=", 40, INK).move_to([OPX, Y3, 0])
        note = label("wave exaggerated: the real shift is 1 in 60,000", 20).move_to([0, Y3 - A3 - 0.4, 0])
        c3 = self.cap("add them: each bit shifts the carrier's frequency")
        with self.say("That's 1 part in 60,000, so the picture exaggerates it a lot.") as tr:
            self.play(FadeOut(c), run_time=0.3)
            w0 = wave0()
            self.play(Create(w0), FadeIn(plus), FadeIn(eq), FadeIn(c3), run_time=1.0)
            self.remove(w0); self.add(wave)
            self.play(FadeIn(note), run_time=0.6)
            self.wait(max(0.0, tr.get_remaining_duration() - 0.5))
            self.play(FadeOut(c3), run_time=0.4)           # the caption goes when its sentence is done

        # ---- paragraph 2: where the carrier and the tone come from (idle highlights on the rows) ----
        BX = -6.1                                    # little labelled blocks in the left margin
        def block(words, y):
            box = RoundedRectangle(corner_radius=0.08, width=1.15, height=0.78, stroke_color=MUTED, stroke_width=SW_THIN)
            txt = VGroup(*[label(w, 21, INK) for w in words]).arrange(DOWN, buff=0.03)
            return VGroup(box, txt).move_to([BX, y, 0])
        arrow = lambda y: Arrow([BX + 0.6, y, 0], [XL - 0.05, y, 0], buff=0, stroke_width=3, color=MUTED,
                                max_tip_length_to_length_ratio=0.3)
        cpu = block(["CPU"], Y2)
        ar2 = arrow(Y2)
        cross = VGroup(Line(UL, DR), Line(UR, DL)).scale(0.12).set_stroke(ZERO, 4).move_to([(BX + 0.6 + XL - 0.05) / 2, Y2, 0])
        with self.say("The ESP32's processor can't make a 2.4 GHz wave itself."):
            self.play(FadeIn(cpu), FadeIn(ar2), run_time=0.7)
            self.play(Create(cross), Indicate(freq, color=INK), run_time=0.8)
        with self.say("Its Wi-Fi radio can, though."):
            radio = block(["Wi-Fi", "radio"], Y2)
            self.play(FadeOut(cross), FadeOut(cpu), FadeIn(radio), ar2.animate.set_color(YELLOW_A), run_time=0.9)
            self.play(Indicate(chan, color=INK), run_time=0.9)
        with self.say("A synthesizer inside it makes the carrier."):
            synth = block(["carrier", "synth"], Y2)
            self.play(FadeOut(radio), FadeIn(synth), run_time=0.7)
            self.play(ar2.animate.set_color(YELLOW_A), run_time=0.9)
            self.play(ar2.animate.set_color(MUTED), run_time=0.4)
        tone = block(["tone", "generator"], Y1)
        ar1 = arrow(Y1)
        ring = Circle(radius=0.3, stroke_color=YELLOW_A, stroke_width=SW_THIN).move_to(plus)
        tc = self.cap("a built-in test tone, mixed onto the carrier")
        with self.say("The radio also has a built-in tone generator, meant for testing, and that tone gets mixed onto the carrier."):
            self.play(FadeIn(tone), FadeIn(ar1), FadeIn(tc), run_time=0.8)
            self.play(ar1.animate.set_color(YELLOW_A), run_time=0.5)
            self.play(Create(ring), Indicate(plus, color=INK), run_time=0.8)
            self.play(FadeOut(ring), ar1.animate.set_color(MUTED), run_time=0.5)

        def cur_x():
            return XL + min(max(t.get_value(), 0.0), 8.0) * BIT_PITCH

        cursor = always_redraw(lambda: DashedLine([cur_x(), BIT_Y - 0.45, 0], [cur_x(), Y3 - A3 - 0.1, 0],
                                                  dash_length=0.08, stroke_color=MUTED, stroke_width=SW_THIN))
        for i, s in enumerate(sqs):
            s[0].add_updater(lambda m, i=i: m.set_fill(opacity=0.35 if t.get_value() > i + 0.5 else 0.1))
        self.add(cursor)
        c2 = self.cap("1 squeezes the wave; 0 stretches it")
        b0 = Brace(Line([bit_x(0) - BIT_PITCH / 2, Y1 - LV - 0.1, 0], [bit_x(0) + BIT_PITCH / 2, Y1 - LV - 0.1, 0]),
                   direction=DOWN, buff=0.0, color=MUTED, stroke_width=1).scale(0.8)
        t32 = label("32 µs", 20, INK).next_to(b0, DOWN, buff=0.05)
        lvl = lambda: HERO_BITS[min(int(t.get_value()), 7)]
        dot = always_redraw(lambda: Dot([cur_x(), Y1 + (LV if lvl() else -LV), 0], radius=0.07,
                                        color=ONE if lvl() else ZERO))
        with self.say("We key that tone up and down, one bit every 32 µs."):
            self.add(dot)
            self.play(FadeOut(tc), run_time=0.25)
            self.play(FadeIn(c2), FadeIn(b0), FadeIn(t32), ar1.animate.set_color(YELLOW_A), run_time=0.5)
            self.play(t.animate.set_value(8.0), run_time=8 * SEC, rate_func=linear)
            self.play(FadeOut(cursor), FadeOut(dot), FadeOut(b0), FadeOut(t32), FadeOut(tone), FadeOut(ar1),
                      FadeOut(synth), FadeOut(ar2), run_time=0.4)

        # ---- the hop: the same bits on channel B's carrier give a different wave ----
        chan_b = label("channel B", 22).move_to(chan)
        freq_b = label(f"{ch_ghz(CH_B):.3f} GHz", 22, INK).move_to(freq)
        hop = self.cap("another channel, same bits")
        with self.say("On another channel the carrier sits at a different frequency, so the wave is different."):
            self.play(FadeOut(c2), run_time=0.3)
            self.play(cyc.animate.set_value(CYC_B), FadeOut(chan), FadeOut(freq), FadeIn(chan_b), FadeIn(freq_b),
                      FadeIn(hop), run_time=1.6)
            self.play(Indicate(freq_b, color=INK), run_time=1.0)
        with self.say("It still carries the same bits."):
            dph = np.ceil(ph.get_value() / TAU) * TAU - ph.get_value()
            ph.clear_updaters()                    # settle the drift on a whole cycle so the wave comes to rest
            self.play(
                      *[s.animate(rate_func=there_and_back, run_time=0.9).scale(1.08) for s in sqs],
                      ph.animate(rate_func=linear, run_time=max(0.9, dph / (2 * DRIFT))).set_value(ph.get_value() + dph))

        # ---- the wave alone, then it becomes the packet (carry-over for S04: packet_block_big, centred) ----
        for s in sqs:
            s[0].clear_updaters()
        final = fsk_wave(8.0, center=[0, Y3, 0], amp=A3, cyc=CYC_B)
        self.remove(wave, carrier); self.add(final)
        carrier_b = carrier_wave(CYC_B)
        self.add(carrier_b)
        c = self.cap("one packet: one burst of this wave on one channel")
        blk = packet_block_big()
        lab = VGroup(chan_b.copy(), freq_b.copy()).arrange(RIGHT, buff=0.2).move_to([0, -1.3, 0])   # fades in at its new place
        box = Rectangle(width=WAVE_W + 0.3, height=2 * A3 + 0.3, stroke_color=YELLOW_A, stroke_width=SW,
                        fill_color=YELLOW_A, fill_opacity=0.0)
        with self.say("So one packet is one short burst of this wave on one channel."):
            self.play(FadeOut(hop), FadeOut(VGroup(sqs, zero, segs, risers, hi, lo, plus, eq, note, carrier_b)),
                      FadeOut(chan_b), FadeOut(freq_b),
                      final.animate.move_to(ORIGIN), run_time=1.0)
            self.play(FadeIn(c), Create(box), FadeIn(lab), run_time=0.9)
            self.wait(0.3)
            self.play(ReplacementTransform(box, blk),
                      final.animate.stretch_to_fit_width(blk.width * 0.9).stretch_to_fit_height(blk.height * 0.8).set_stroke(opacity=0.0),
                      run_time=1.4)
            self.remove(final)
        self.play(FadeOut(c), FadeOut(lab), run_time=0.4)
