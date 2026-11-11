"""S06 recap (class S06, a ThreeDScene because it starts on the 3D quad). In: seam_s05_s06. Ends the video.
One slot under the opened strip (y = -0.9) holds one object at a time; each arrives by a transform from the one before.
The camera never moves: the 3D quad fades out, everything after it is a 2D object fixed in the frame."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from parts import *

SLOT = np.array([0.0, -0.9, 0.0])
TR_W = 6.5            # width of the recap trace / wave


def key_cap(size=48):
    t = label("W", size, INK)
    box = RoundedRectangle(corner_radius=0.1, width=1.0, height=1.0, color=STRUCT, stroke_width=SW)
    return VGroup(box, t.move_to(box)).move_to(SLOT)


def spinning_quad(center, scale=1.2):
    q = quad_top(scale, center)
    blades = VGroup()
    for c in q[2:6]:
        b = VGroup(Line(LEFT * 0.17 * scale, RIGHT * 0.17 * scale, color=INK, stroke_width=SW_LINE),
                   Line(UP * 0.17 * scale, DOWN * 0.17 * scale, color=INK, stroke_width=SW_LINE)).move_to(c.get_center())
        blades.add(b)
    g = VGroup(q, blades)
    return g, blades


class S06(Narrated, ThreeDScene):
    def fix(self, *ms):
        self.add_fixed_in_frame_mobjects(*ms)
        return ms[0] if len(ms) == 1 else ms

    def wait_bm(self, name):
        self.wait_until_bookmark(name)

    def construct(self):
        seam = seam_s05_s06()
        strip = seam.enter(self)
        quad = seam.quad

        row = packet_row(center=SLOT, scale=0.7)
        cells = light_throttle(row)["cells"]
        row_g = VGroup(*cells)
        cap = key_cap()
        hero = hero_number(48).move_to(SLOT)
        trace = freq_trace(center=(0.0, 0.1), width=TR_W, dev=0.3)
        wave = fsk_wave(center=(0.0, -1.35, 0.0), width=TR_W, amp=0.38)
        hi = label("+39 kHz", 34, ONE).next_to([TR_W / 2, 0.4, 0], RIGHT, buff=0.2)
        lo = label("−39 kHz", 34, ZERO).next_to([TR_W / 2, -0.2, 0], RIGHT, buff=0.2)
        tag = VGroup(label("two test", 34, YELLOW_A), label("tones", 34, YELLOW_A)).arrange(DOWN, buff=0.12).move_to([-TR_W / 2 - 1.2, 0.1, 0])
        tone_wave = VGroup(trace, wave)
        quad2, blades = spinning_quad(SLOT, 1.2)
        addr = mono("github.com/mb6611/esp32-d8tx", 30, INK).move_to([0, -2.85, 0])
        self.fix(cap, hero, row_g, tone_wave, hi, lo, tag, quad2, addr)
        for m in (cap, hero, row_g, tone_wave, hi, lo, tag, quad2, addr):
            self.remove(m)

        def clause(text, *steps):
            """One voiceover block; steps = [(animation list, run_time)], the block waits out what is left of the speech."""
            with self.voiceover(text=text) as tr:
                used = 0.0
                for anims, rt in steps:
                    self.play(*anims, run_time=rt)
                    used += rt
                if tr.duration > used:
                    self.wait(tr.duration - used)

        # 1: the strip opens, the marker travels back to the keyboard, the quad shrinks away; W key, then 1150
        with self.voiceover(text="To recap: a key press becomes a number in the browser,") as tr:
            self.play(strip.open(), strip.go(K_KEY), FadeOut(quad, scale=0.3), run_time=1.2, rate_func=smooth)
            self.play(FadeIn(cap), run_time=0.4)
            self.play(cap[0].animate.set_stroke(YELLOW_A, opacity=1), run_time=0.3)
            rest = tr.duration - 1.9 - 1.0
            if rest > 0:
                self.wait(rest)
            self.play(FadeOut(cap), FadeIn(hero), strip.go(K_APP), run_time=1.0)
        # 2: bytes
        clause("then bytes in a D8 packet,", ([FadeOut(hero), FadeIn(row_g), strip.go(K_ESP)], 0.6))
        # 3: frequency shifts
        clause("then frequency shifts,", ([FadeOut(row_g), FadeIn(tone_wave)], 1.2))
        # 4: two test tones; the marker crosses the air
        with self.voiceover(text="sent by a Wi-Fi radio switching between two test tones.") as tr:
            self.play(strip.go(K_AIR), run_time=1.5)
            rest = tr.duration - 1.5 - 0.7 - 0.6
            if rest > 0:
                self.wait(rest)
            self.play(FadeIn(hi), FadeIn(lo), FadeIn(tag), run_time=0.7)
            self.wait(0.6)
        # 5: the receiver acts
        with self.voiceover(text="The drone's receiver reads the packet and acts on it.") as tr:
            self.play(FadeOut(hi), FadeOut(lo), FadeOut(tag), FadeOut(tone_wave), FadeIn(row_g), strip.go(K_RX), run_time=1.0)
            self.play(strip.go(K_FC), run_time=0.6)
            rest = tr.duration - 1.6 - 1.0 - 0.5
            if rest > 0:
                self.wait(rest)
            self.play(FadeOut(row_g), FadeIn(hero), run_time=0.5)
            for b in blades:
                b.add_updater(lambda m, dt: m.rotate(9 * dt, about_point=m.get_center()))
            self.play(FadeOut(hero), FadeIn(quad2), strip.go(K_MOT), run_time=1.0)
        self.play(FadeIn(addr), run_time=0.8)
        self.wait(3.0)
