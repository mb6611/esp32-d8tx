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

SEC = 0.8                        # screen seconds per bit
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


class S03(MovingCameraScene):
    def cap(self, text, size=32):
        return caption_at(self.camera.frame, text, size)

    def construct(self):
        frame = self.camera.frame
        strip = MapStrip(K_ESP, lambda: (frame.get_center(), frame.width))
        self.add(strip)
        allbits = bit_cells(k=K3, center=[0, BIT_Y, 0])
        self.add(allbits)
        self.wait(0.3)

        # ---- the eight throttle bits spread out; the rest of the packet waits off to the sides ----
        sqs = byte_bits(allbits, HERO_BYTE)
        others = VGroup(*[b for n, b in enumerate(allbits) if not 8 * HERO_BYTE <= n < 8 * HERO_BYTE + 8])
        self.play(FadeOut(others), *[sqs[i].animate.move_to([bit_x(i), BIT_Y, 0]) for i in range(8)], run_time=0.9)

        # ---- row 1: the bits as a frequency offset (d8tone.c: one tone step = 40 MHz / 1024 = 39.0625 kHz) ----
        zero = DashedLine([XL, Y1, 0], [XR, Y1, 0], dash_length=0.08, stroke_color=GRID, stroke_width=SW_THIN)
        lev = lambda b: Y1 + (LV if b else -LV)
        segs = VGroup(*[Line([bit_x(i) - BIT_PITCH / 2, lev(b), 0], [bit_x(i) + BIT_PITCH / 2, lev(b), 0],
                             stroke_color=ONE if b else ZERO, stroke_width=SW_LINE) for i, b in enumerate(HERO_BITS)])
        risers = VGroup(*[Line([bit_x(i) + BIT_PITCH / 2, Y1 - LV, 0], [bit_x(i) + BIT_PITCH / 2, Y1 + LV, 0],
                               stroke_color=MUTED, stroke_width=SW_THIN)
                          for i in range(7) if HERO_BITS[i] != HERO_BITS[i + 1]])
        hi = label("+39 kHz", 22, ONE).next_to([XR, Y1 + LV, 0], RIGHT, buff=0.2)
        lo = label("−39 kHz", 22, ZERO).next_to([XR, Y1 - LV, 0], RIGHT, buff=0.2)
        c = self.cap("each bit is a small frequency offset")
        self.play(FadeIn(zero), LaggedStart(*[TransformFromCopy(sqs[i][0], segs[i]) for i in range(8)], lag_ratio=0.25),
                  FadeIn(c), run_time=1.8)
        self.play(FadeIn(risers), FadeIn(hi), FadeIn(lo), run_time=0.5)
        self.wait(1.3)

        # ---- row 2: channel A's carrier ----
        t = ValueTracker(0.0)            # cursor, in bits
        cyc = ValueTracker(CYC_A)        # carrier cycles per bit on screen
        carrier = always_redraw(lambda: carrier_wave(cyc.get_value()))
        carrier0 = carrier_wave(CYC_A)
        plus = label("+", 40, INK).move_to([OPX, (Y1 + Y2) / 2, 0])
        chan = label("channel A", 22).move_to([XR + 0.95, Y2 + 0.2, 0])
        freq = label(f"{ch_ghz(CH_A):.3f} GHz", 22, INK).move_to([XR + 0.95, Y2 - 0.2, 0])
        c2 = self.cap("the carrier: channel A's steady wave")
        self.play(FadeOut(c), run_time=0.3)
        self.play(Create(carrier0), FadeIn(plus), FadeIn(chan), FadeIn(freq), FadeIn(c2), run_time=1.2)
        self.remove(carrier0); self.add(carrier)
        self.wait(1.6)

        # ---- row 3: carrier + offset. The carrier drops in, then each bit shifts its frequency as the cursor passes ----
        wave = always_redraw(lambda: fsk_wave(t.get_value(), center=[0, Y3, 0], amp=A3, cyc=cyc.get_value()))
        wave0 = carrier_wave(CYC_A, Y3, A3)
        eq = label("=", 40, INK).move_to([OPX, Y3, 0])
        note = label("wave exaggerated: the real shift is 1 in 60,000", 20).move_to([0, Y3 - A3 - 0.4, 0])
        c = self.cap("add them: each bit shifts the carrier's frequency")
        self.play(FadeOut(c2), run_time=0.3)
        self.play(TransformFromCopy(carrier0.copy().set_opacity(0), wave0), FadeIn(eq), FadeIn(c), run_time=1.0)
        self.remove(wave0); self.add(wave)

        def cur_x():
            return XL + min(max(t.get_value(), 0.0), 8.0) * BIT_PITCH

        cursor = always_redraw(lambda: DashedLine([cur_x(), BIT_Y - 0.45, 0], [cur_x(), Y3 - A3 - 0.1, 0],
                                                  dash_length=0.08, stroke_color=MUTED, stroke_width=SW_THIN))
        for i, s in enumerate(sqs):
            s[0].add_updater(lambda m, i=i: m.set_fill(opacity=0.35 if t.get_value() > i + 0.5 else 0.1))
        self.add(cursor)
        self.play(t.animate.set_value(8.0), run_time=8 * SEC, rate_func=linear)
        c2 = self.cap("1 squeezes the wave; 0 stretches it")
        self.play(FadeOut(c), FadeOut(cursor), run_time=0.3)
        self.play(FadeIn(c2), FadeIn(note), run_time=0.6)
        self.wait(2.0)

        # ---- the hop: the same bits on channel B's carrier give a different wave ----
        chan_b = label("channel B", 22).move_to(chan)
        freq_b = label(f"{ch_ghz(CH_B):.3f} GHz", 22, INK).move_to(freq)
        hop = self.cap("next hop: same bits, channel B's carrier")
        self.play(FadeOut(c2), run_time=0.3)
        self.play(cyc.animate.set_value(CYC_B), FadeOut(chan), FadeOut(freq), FadeIn(chan_b), FadeIn(freq_b), FadeIn(hop),
                  run_time=1.6)
        self.wait(1.0)
        hop2 = self.cap("a different wave, carrying the same bits")
        self.play(FadeOut(hop), run_time=0.3)
        self.play(FadeIn(hop2), run_time=0.5)
        self.wait(1.6)

        # ---- the wave alone, then it becomes the packet (carry-over for S04: packet_block_big, centred) ----
        for s in sqs:
            s[0].clear_updaters()
        final = fsk_wave(8.0, center=[0, Y3, 0], amp=A3, cyc=CYC_B)
        self.remove(wave, carrier); self.add(final)
        carrier_b = carrier_wave(CYC_B)
        self.add(carrier_b)
        self.play(FadeOut(hop2), FadeOut(VGroup(sqs, zero, segs, risers, hi, lo, plus, eq, note, carrier_b)),
                  VGroup(chan_b, freq_b).animate.arrange(RIGHT, buff=0.2).move_to([0, -1.3, 0]),
                  final.animate.move_to(ORIGIN), run_time=1.0)
        c = self.cap("one packet: one burst of this wave on one channel")
        blk = packet_block_big()
        # a yellow box closes around the burst, then box and wave shrink together into the filled packet block
        box = Rectangle(width=WAVE_W + 0.3, height=2 * A3 + 0.3, stroke_color=YELLOW_A, stroke_width=SW,
                        fill_color=YELLOW_A, fill_opacity=0.0)
        self.play(FadeIn(c), Create(box), run_time=0.9)
        self.wait(0.8)
        self.play(ReplacementTransform(box, blk),
                  final.animate.stretch_to_fit_width(blk.width * 0.9).stretch_to_fit_height(blk.height * 0.8).set_stroke(opacity=0.0),
                  run_time=1.4)
        self.remove(final)
        self.wait(1.2)
        self.play(FadeOut(c), FadeOut(chan_b), FadeOut(freq_b), run_time=0.6)
        self.wait(0.4)
