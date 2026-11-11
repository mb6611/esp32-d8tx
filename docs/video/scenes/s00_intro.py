"""S00 intro: the drone and the E8, D8 packets, the ESP32 hacked to speak D8, pseudo SDR, then the path strip builds.
Starts on a blank frame; ends on seam_s00_s01() (strip parked, marker on keyboard)."""
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from parts import *

Y0 = 0.6                      # the row everything sits on in the first half
EX, DX = -4.5, 4.5            # E8 and drone x
LX = -4.9                     # laptop x (a little further left than the storyboard so the SDR label clears it)
BX_ESP = -2.2                 # the ESP32 box / radio-module box x
RY = -2.0                     # the frequency ruler row
WAVE_A0 = 0.18
SPEED = 2.0                   # block speed along the wave (units/s)


class Stream(VGroup):
    """Yellow packet blocks travelling right along the wave, one every 0.7 s."""

    def __init__(self, x0=-3.1, x1=3.2):
        super().__init__()
        self.x0, self.x1, self.emit, self.speed, self.timer, self.held = x0, x1, False, SPEED, 0.0, None
        self.add_updater(self._upd)

    def _upd(self, m, dt):
        if self.emit:
            self.timer += dt
            if self.timer >= 0.7:
                self.timer = 0.0
                self.add(packet_block(1.0).move_to([self.x0, Y0, 0]))
        for b in list(self.submobjects):
            if b is self.held:
                continue
            b.shift(RIGHT * self.speed * dt)
            if b.get_center()[0] > self.x1:
                b.set_fill(opacity=0)      # arrived: invisible (kept in the group, so a running animation can't resurrect it)


def gimbal_small(center):
    box = Square(0.62, color=STRUCT, stroke_width=SW_THIN).move_to(center)
    cross = VGroup(Line(box.get_left(), box.get_right()), Line(box.get_top(), box.get_bottom())).set_stroke(GRID, SW_THIN, 0.6)
    knob = Dot(center, radius=0.06, color=BLUE_A)
    return VGroup(box, cross, knob), knob


def tbox(words, center, w, h, size=20, color=STRUCT, dashed=False):
    r = RoundedRectangle(corner_radius=0.08, width=w, height=h, stroke_color=color, stroke_width=SW).move_to(center)
    if dashed:
        r = DashedVMobject(r, num_dashes=28)
    return VGroup(r, label(words, size, MAP_LABEL).move_to(center))


class S00(Narrated, MovingCameraScene):
    """No incoming seam (blank frame); outgoing: strip parked on keyboard."""

    # manim-voiceover bookmarks need word boundaries, which the macOS `say` service does not give: place each mark at the
    # fraction of the sentence's spoken characters before it (linear text -> time), measured from the voiceover start.
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
        print(f"VOSTART {self.renderer.time:.2f} {tags.sub('', text)[:40]}", flush=True)
        return cm

    def wait_mark(self, name):
        tr = self.current_tracker
        t = tr.start_t + frac_to_seconds(tr, self._marks[name]) - self.renderer.time
        if t > 1e-3:
            self.wait(t)

    def construct(self):
        mark = self.wait_mark

        # ---------------------------------------------------------------- shared wave state
        ph = ValueTracker(0.0)
        ph.add_updater(lambda m, dt: m.increment_value(dt * DRIFT))
        self.add(ph)
        X0, X1 = ValueTracker(EX + 1.4), ValueTracker(DX - 1.3)
        rv, wa = ValueTracker(0.0), ValueTracker(1.0)        # revealed fraction, opacity
        cpl, amod, fskm = ValueTracker(1.9), ValueTracker(0.0), ValueTracker(0.0)

        def wave_fn():
            f = rv.get_value()
            if f < 0.002:
                return VMobject()
            x0, x1 = X0.get_value(), X1.get_value()
            xs = np.linspace(x0, x0 + (x1 - x0) * f, max(int(260 * f), 4))
            u = (xs - x0) / (x1 - x0)
            bits = np.array(HERO_BITS)[np.clip((u * 8).astype(int), 0, 7)]
            fr = cpl.get_value() * (1 + fskm.get_value() * 0.5 * (2 * bits - 1))
            phase = np.concatenate([[0.0], np.cumsum(0.5 * (fr[1:] + fr[:-1]) * np.diff(xs))]) * TAU
            m = amod.get_value()
            amp = WAVE_A0 * (1 - m + m * (0.5 + 0.5 * np.sin(TAU * 1.25 * u)))
            ys = Y0 + amp * np.sin(phase - ph.get_value())
            v = VMobject(stroke_color=STRUCT, stroke_width=SW, stroke_opacity=wa.get_value())
            v.set_points_as_corners(np.column_stack([xs, ys, np.zeros_like(xs)]))
            return v

        wave = always_redraw(wave_fn)
        stream = Stream()

        # ---------------------------------------------------------------- beat 1: the drone
        quad = quad_top(2.2 / 1.74, [DX, Y0, 0])
        blades = VGroup()
        for c in quad[2:6]:
            b = VGroup(Line(LEFT * .16, RIGHT * .16), Line(DOWN * .16, UP * .16)).set_stroke(BLUE_LT, SW_THIN).move_to(c)
            b.add_updater(lambda m, dt: m.rotate(dt * 2.5))
            blades.add(b)
        lab_q = label("Tinyhawk 3", 24).next_to(quad, DOWN, buff=0.45)
        with self.vo("This drone is a <bookmark mark='q'/>Tinyhawk 3.") as tr:
            self.play(FadeIn(quad), FadeIn(blades), run_time=0.8)
            mark("q")
            self.play(FadeIn(lab_q), run_time=0.6)

        # ---------------------------------------------------------------- beat 2: the E8
        body = RoundedRectangle(corner_radius=0.2, width=2.6, height=1.6, stroke_color=STRUCT, stroke_width=SW).move_to([EX, Y0, 0])
        gl, glk = gimbal_small([EX - 0.7, Y0, 0])
        gr, grk = gimbal_small([EX + 0.7, Y0, 0])
        e8 = VGroup(body, gl, gr)
        lab_e = label("E8", 24, INK).move_to([EX, Y0 - 1.1, 0])
        lab_t = label("the transmitter", 22, BLUE_A).next_to(lab_e, DOWN, buff=0.12)
        with self.vo("It is normally flown with a <bookmark mark='h'/>handheld transmitter, the <bookmark mark='e'/>E8.") as tr:
            self.play(FadeIn(e8), run_time=0.7)
            mark("e")
            self.play(FadeIn(lab_e), FadeIn(lab_t), run_time=0.6)

        # ---------------------------------------------------------------- beats 3, 4: the radio link, FrSky D8
        lab_d8 = label("FrSky D8", 28, INK).move_to([0, Y0 + 0.75, 0])
        self.add(wave)
        with self.vo("The two <bookmark mark='r'/>talk by radio in a protocol called <bookmark mark='p'/>FrSky D8.") as tr:
            mark("r")
            self.play(rv.animate.set_value(1.0), run_time=1.0, rate_func=linear)
            mark("p")
            self.play(FadeIn(lab_d8), run_time=0.7)

        # ---------------------------------------------------------------- beat 5: a protocol, blocks flow
        cap = caption_at(self.camera.frame, "a protocol: the agreed format of the messages")
        self.add(stream)
        with self.vo("A <bookmark mark='a'/>protocol is an agreed format for messages.") as tr:
            mark("a")
            stream.emit = True
            self.play(FadeIn(cap), run_time=0.6)
            self.wait(0.1)

        # ---------------------------------------------------------------- beats 6, 7: the packet, 2.4 GHz
        row = packet_row(center=[0, Y0, 0], scale=0.45)["cells"]
        bright = ValueTracker(0.0)
        ex = ValueTracker(0.0)         # 0 = the yellow block, 1 = the 20-byte row; one object grows into the other
        row_l, row_r = row.get_left()[0], row.get_right()[0]
        row_h = row[0][0].height
        gb = packet_block(1.0)
        bw, bh = gb.width, gb.height
        sm = lambda x: float(np.clip(x, 0, 1)) ** 2 * (3 - 2 * np.clip(x, 0, 1))

        def _grow(m):
            e = ex.get_value()
            st = sm(e / 0.55)                      # the block stretches to the row's outline
            w = interpolate(bw, row_r - row_l, st)
            h = interpolate(bh, row_h, st)
            gb.become(Rectangle(width=w, height=h, color=YELLOW_A, fill_color=YELLOW_A, fill_opacity=0.9 * (1 - sm((e - 0.4) / 0.3)),
                                stroke_width=0).move_to([(row_l + row_r) / 2, Y0, 0]))
            ca = sm((e - 0.4) / 0.3)               # the cell outlines
            ta = sm((e - 0.65) / 0.35)             # then the digits
            b = bright.get_value()
            for i, c in enumerate(row):
                a = interpolate(DIM, 1.0, b) if 6 <= i < 18 else DIM
                c[0].set_stroke(opacity=a * ca)
                c[1].set_fill(opacity=a * ta)
        row.add_updater(_grow)
        lab_p = label("one packet", 24).move_to([0, Y0 - 0.55, 0])
        cap6 = caption_at(self.camera.frame, "one packet: a few bytes with the stick positions")
        # ruler pieces
        s = 9.0 / 80.0
        fx = lambda mhz: -4.5 + (mhz - 2400) * s
        ruler = VGroup(Line([-4.5, RY, 0], [4.5, RY, 0]).set_stroke(MUTED, SW),
                       Arrow([4.5, RY, 0], [5.1, RY, 0], buff=0, color=MUTED, stroke_width=SW, tip_length=0.15))
        ruler.add(Line([-4.5, RY - 0.08, 0], [-4.5, RY + 0.08, 0]).set_stroke(MUTED, SW),
                  Line([4.5, RY - 0.08, 0], [4.5, RY + 0.08, 0]).set_stroke(MUTED, SW))
        r_lab = VGroup(label("2.40 GHz", 20).move_to([-4.5, RY - 0.35, 0]), label("2.48 GHz", 20).move_to([4.5, RY - 0.35, 0]),
                       label("frequency", 22).move_to([6.15, RY, 0]))
        d8_ticks = VGroup(*[Line([fx(2404 + 0.29993 * k), RY, 0], [fx(2404 + 0.29993 * k), RY - 0.28, 0]).set_stroke(YELLOW_A, SW_THIN)
                            for k in TABLE])
        d8_lab = label("D8", 22, YELLOW_A).move_to([-5.45, RY - 0.14, 0])
        humps, hlabs = VGroup(), VGroup()
        for mhz, name in ((2412, "1"), (2437, "6"), (2462, "11")):
            cx = fx(mhz)
            h = ParametricFunction(lambda t, cx=cx: np.array([cx + t * 1.125, RY + 0.7 * np.cos(t * PI / 2) ** 2, 0]),
                                   t_range=[-1, 1], stroke_color=BLUE_DK, stroke_width=SW)
            humps.add(h)
            hlabs.add(label("Wi-Fi", 20, BLUE_DK).move_to([cx, RY + 0.95, 0]))
        with self.vo("In D8 each message is a <bookmark mark='s'/>short packet, a few bytes carrying the <bookmark mark='k'/>stick positions, "
                                 "sent at <bookmark mark='g'/>about 2.4 GHz, the band <bookmark mark='w'/>Wi-Fi uses.") as tr:
            stream.emit = False
            mark("s")
            blk = min(stream.submobjects, key=lambda b: abs(b.get_center()[0]))
            stream.held = blk
            self.play(FadeOut(cap), blk.animate.move_to([0, Y0, 0]), wa.animate.set_value(0.0), run_time=0.5)
            stream.remove(blk)
            self.add(blk)
            self.remove(blk)
            self.add(gb, row)
            self.play(ex.animate.set_value(1.0), FadeIn(lab_p), FadeIn(cap6), run_time=0.9)
            mark("k")
            self.play(bright.animate.set_value(1.0), glk.animate.shift(UP * 0.1 + LEFT * 0.08), grk.animate.shift(DOWN * 0.1 + RIGHT * 0.08), run_time=0.4)
            mark("g")
            cap7 = caption_at(self.camera.frame, "about 2.4 GHz: the band Wi-Fi uses")
            self.play(ex.animate.set_value(0.0), FadeOut(lab_p), FadeOut(cap6), wa.animate.set_value(1.0),
                      glk.animate.shift(DOWN * 0.1 + RIGHT * 0.08), grk.animate.shift(UP * 0.1 + LEFT * 0.08),
                      FadeIn(ruler), FadeIn(r_lab), FadeIn(d8_ticks), FadeIn(d8_lab), FadeIn(cap7), run_time=0.7)
            row.clear_updaters(); gb.clear_updaters()
            self.remove(row, gb)
            blk2 = packet_block(1.0).move_to([0, Y0, 0])
            self.add(blk2)
            stream.add(blk2); stream.held = None; stream.emit = True
            mark("w")
            self.play(*[Create(h) for h in humps], FadeIn(hlabs), run_time=1.6)

        # ---------------------------------------------------------------- beat 8: my computer
        lap_scr = Rectangle(width=1.8, height=1.1, color=BLUE_A, stroke_width=SW, fill_color=BG, fill_opacity=1)
        lap_base = Line(LEFT * 1.1, RIGHT * 1.1).set_stroke(BLUE_A, SW).next_to(lap_scr, DOWN, buff=0)
        laptop = VGroup(lap_scr, lap_base).move_to([LX, -0.2, 0])
        lab_c = label("computer", 24, BLUE_A).next_to(laptop, DOWN, buff=0.15)
        with self.vo("I wanted to fly the drone from <bookmark mark='c'/>my computer, without an extra <bookmark mark='m'/>radio module made for D8.") as tr:
            stream.emit = False
            self.play(FadeOut(lab_e), FadeOut(lab_t), FadeOut(e8), FadeOut(cap7),
                      wa.animate.set_value(DIM), *[b.animate.set_fill(opacity=0) for b in stream.submobjects if b.get_fill_opacity() > 0.5], run_time=0.7)
            stream.speed = 0
            mark("c")
            self.play(FadeIn(laptop), FadeIn(lab_c), run_time=0.8)
            # ---- beat 9
            mark("m")
            rm = tbox("radio module", [BX_ESP, Y0, 0], 1.3, 0.6, 18, STRUCT, dashed=True)
            rm.add_to_back(Rectangle(width=1.3, height=0.6, stroke_width=0, fill_color=BG, fill_opacity=1).move_to([BX_ESP, Y0, 0]))
            rm.set_z_index(10)
            link0 = Line([LX + 0.9, -0.2, 0], [BX_ESP - 0.65, Y0, 0]).set_stroke(STRUCT, SW)
            self.play(FadeIn(rm), FadeIn(link0), wa.animate.set_value(0.0), run_time=0.7)
            self.wait(0.3)
            self.play(FadeOut(rm), FadeOut(link0), wa.animate.set_value(DIM), run_time=0.4)

        # ---------------------------------------------------------------- beats 10, 11: the ESP32
        esp_r = RoundedRectangle(corner_radius=0.08, width=1.6, height=1.0, stroke_color=STRUCT, stroke_width=SW, fill_color=BG, fill_opacity=1).move_to([BX_ESP, Y0, 0])
        esp_l = label("ESP32", 20, MAP_LABEL).move_to([BX_ESP, Y0 + 0.3, 0])
        esp = VGroup(esp_r, esp_l)
        inner = tbox("Wi-Fi radio", [BX_ESP, Y0 - 0.17, 0], 1.3, 0.42, 15)
        link1 = Line([LX + 0.9, -0.2, 0], [BX_ESP - 0.8, Y0 - 0.15, 0]).set_stroke(STRUCT, SW)
        lab_usb = label("USB", 20).move_to([-3.25, -0.2, 0])
        with self.vo("What I had was an <bookmark mark='x'/>ESP32, a small board with a <bookmark mark='y'/>Wi-Fi radio, "
                                 "so I <bookmark mark='z'/>hacked that radio to <bookmark mark='d'/>speak D8.") as tr:
            mark("x")
            self.play(FadeIn(esp), FadeIn(link1), FadeIn(lab_usb), run_time=0.7)
            mark("y")
            self.play(FadeIn(inner), humps.animate.set_stroke(color=BLUE_A, width=4), run_time=0.5)
            self.play(humps.animate.set_stroke(color=BLUE_DK, width=SW), run_time=0.5)
            mark("z")
            cap11 = caption_at(self.camera.frame, "the Wi-Fi radio, made to speak D8")
            self.play(inner[0].animate.set_stroke(YELLOW_A), FadeIn(cap11), run_time=0.6)
            mark("d")
            # redraw the wave from the ESP32 box to the drone (the E8 already faded out in beat 8; fading it again re-adds it: flash)
            old = list(stream.submobjects)
            stream.x0 = BX_ESP + 0.9
            X0.set_value(BX_ESP + 0.9); rv.set_value(0.0); wa.set_value(1.0)
            stream.speed = SPEED
            self.play(*[FadeOut(b) for b in old], humps.animate.set_stroke(opacity=DIM),
                      hlabs.animate.set_opacity(DIM), run_time=0.5)
            for b in old:
                stream.remove(b)
            self.play(rv.animate.set_value(1.0), d8_ticks.animate.set_stroke(width=2.5), run_time=0.8, rate_func=linear)
            stream.emit = True

        # ---------------------------------------------------------------- beat 12: pseudo SDR
        l_pseudo = label("pseudo", 24, INK)
        l_sdr = label("software-defined radio (SDR)", 20, INK)
        VGroup(l_pseudo, l_sdr).arrange(DOWN, buff=0.1).move_to([BX_ESP, Y0 - 0.95, 0])
        with self.vo("That makes the ESP32 a pseudo <bookmark mark='sd'/>software-defined radio, or SDR:") as tr:
            self.play(FadeOut(cap11), FadeIn(l_pseudo), run_time=0.5)
            mark("sd")
            self.play(FadeIn(l_sdr), FadeOut(VGroup(ruler, r_lab, d8_ticks, d8_lab, humps, hlabs)), run_time=0.8)

        # ---------------------------------------------------------------- beat 13: software decides the wave
        soft = tbox("software", [BX_ESP, Y0 + 1.5, 0], 1.3, 0.5, 20)
        arr = Arrow([BX_ESP, Y0 + 1.25, 0], [BX_ESP, Y0 + 0.55, 0], buff=0, color=MUTED, stroke_width=SW_LINE, tip_length=0.18)
        cap13 = caption_at(self.camera.frame, "software decides what wave goes out")
        with self.vo("a radio where <bookmark mark='sw'/>software <bookmark mark='dc'/>decides what wave goes out.") as tr:
            stream.emit = False
            mark("sw")
            self.play(FadeIn(soft), FadeIn(arr), FadeIn(cap13), *[FadeOut(b) for b in stream.submobjects], run_time=0.7)
            stream.remove(*stream.submobjects)
            mark("dc")
            self.play(cpl.animate.set_value(3.4), arr.animate.set_color(YELLOW_A), run_time=0.8)
            self.play(cpl.animate.set_value(1.9), amod.animate.set_value(1.0), arr.animate.set_color(MUTED), run_time=0.8)
            self.play(amod.animate.set_value(0.0), arr.animate.set_color(YELLOW_A), run_time=0.8)
            self.play(arr.animate.set_color(MUTED), run_time=0.2)

        # ---------------------------------------------------------------- beat 14: only partly
        with self.vo("This one is only <bookmark mark='op'/>partly that, as we'll see.") as tr:
            mark("op")
            self.play(fskm.animate.set_value(1.0), cpl.animate.set_value(1.6), FadeOut(cap13), Indicate(l_pseudo, color=INK, scale_factor=1.2), run_time=1.2)
            self.wait(0.3)

        # ---------------------------------------------------------------- beats 15, 16: the strip
        strip = MapStrip(pos=0, focus=1.0)
        strip.place()
        cp = strip.body.copy()
        cp_marker = strip.marker.copy()
        pieces = {i: cp[i] for i in range(len(cp))}
        frozen = VMobject(); frozen.become(wave_fn())
        wave.clear_updaters(); self.remove(wave)
        self.add(frozen)
        stream.clear_updaters(); self.remove(stream)
        blades.clear_updaters()
        names = ["key", "k2a", "app", "cable", "esp", "air", "drone", "rx", "spi", "fc", "mot", "labs"]
        P = dict(zip(names, cp))
        labs = P["labs"]
        quad_tgt = VGroup(P["drone"], P["rx"], P["fc"], P["mot"], P["spi"])
        with self.vo("We'll follow one <bookmark mark='f'/>key press all the way to the motors: through a <bookmark mark='b'/>browser, a <bookmark mark='u'/>USB cable, "
                                 "the <bookmark mark='e32'/>ESP32, the <bookmark mark='ai'/>air, and the <bookmark mark='dr'/>drone.") as tr:
            mark("f")
            olds = [m for m in self.mobjects if isinstance(m, VMobject) and not isinstance(m, (Stream,))]
            self.play(AnimationGroup(FadeOut(VGroup(*olds), run_time=0.6), AnimationGroup(FadeIn(cp), FadeIn(cp_marker), run_time=0.9),
                                     lag_ratio=0.5))
            self.remove(*[m for m in self.mobjects if m is not self.camera.frame])
            self.add(strip)
            marks_seq = [("b", 1, "app"), ("u", 2, "cable"), ("e32", 3, "esp"), ("ai", 4, "air"), ("dr", 8, "drone")]
            for mk, p, nm in marks_seq:
                mark(mk)
                tgt = P[nm] if nm != "drone" else P["drone"]
                hl = SurroundingRectangle(tgt, color=YELLOW_A, buff=0.08, stroke_width=SW)
                self.play(strip.go(p), ShowPassingFlash(hl, time_width=1.0), run_time=0.7)
            self.play(strip.close(), strip.go(0), run_time=1.2)
        self.wait(0.5)
