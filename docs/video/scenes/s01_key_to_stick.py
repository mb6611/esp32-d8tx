"""S01 (long cut): the browser app, eight control channels, ending on the shared throttle number."""
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from parts import *


class S01(Narrated, MovingCameraScene):
    def construct(self):
        frame = self.camera.frame
        seam_in = seam_s00_s01()
        strip = seam_in.enter(self)       # strip parked, marker on `keyboard`, nothing else

        def gimbal(x, title, low=False):
            center = np.array([x, 0.95, 0])
            box = Square(2.35, color=STRUCT, stroke_width=SW).move_to(center)
            cross = VGroup(Line(center + LEFT*1.17, center + RIGHT*1.17),
                           Line(center + UP*1.17, center + DOWN*1.17)).set_stroke(GRID, SW_THIN, 0.6)
            knob = Dot(center + (DOWN*1.05 if low else ORIGIN), radius=0.12, color=BLUE_A)
            name = label(title, 24).next_to(box, UP, buff=0.16)
            return VGroup(box, cross, knob, name), knob

        left, lk = gimbal(-4.0, 'yaw / throttle', True)
        right, rk = gimbal(4.0, 'roll / pitch')
        drone = VGroup(Line(LEFT*.65+UP*.42, RIGHT*.65+DOWN*.42),
                       Line(LEFT*.65+DOWN*.42, RIGHT*.65+UP*.42)).set_stroke(BLUE_DK, SW_LINE)
        for x in (-.65, .65):
            for y in (-.42, .42):
                drone.add(Circle(radius=.22, color=BLUE_LT, stroke_width=SW).move_to([x,y,0]))
        drone.add(Square(.34, color=BLUE_A, stroke_width=SW))
        drone.move_to([0, .95, 0])
        drone_label = label('drone', 22).move_to([0, -.1, 0])
        # bars in the packet's channel order
        names = ['throttle', 'roll', 'pitch', 'yaw', 'aux1', 'aux2', 'arm', 'aux4']
        bars = VGroup()
        for i, name in enumerate(names):
            x = (i - 3.5) * 1.05
            outline = Rectangle(width=.62, height=.85, color=STRUCT, stroke_width=SW).move_to([x,-1.3,0])
            fill = Rectangle(width=.58, height=.03, stroke_width=0, fill_color=BLUE_A, fill_opacity=.5).move_to(outline.get_bottom()+UP*.015)
            name_obj = label(name, 18).next_to(outline, DOWN, buff=.12)
            name_obj.shift(UP * (outline.get_bottom()[1] - .32 - name_obj.get_center()[1]))      # common height, ascenders or not
            bars.add(VGroup(outline, fill, name_obj))
        nums = VGroup(*[DecimalNumber(1000, num_decimal_places=0, group_with_commas=False, font_size=20, color=INK).move_to([(i-3.5)*1.05, -.66, 0]) for i in range(8)])
        # Key map (apps/web key bindings): one row of key caps, each with the stick it moves.
        kwords = ['throttle', 'yaw', 'pitch', 'roll', 'arm', 'disarm']
        words = Tex(*kwords, font_size=24, color=GREY_A)

        def keys(caps, word):
            ks = VGroup()
            for ch in caps:
                t = label(ch, 24, INK)
                box = RoundedRectangle(corner_radius=.06, width=max(.42, t.width + .2), height=.42, color=STRUCT, stroke_width=SW)
                ks.add(VGroup(box, t.move_to(box)))
            ks.arrange(RIGHT, buff=.07)
            w = words[kwords.index(word)]
            y = w.get_center()[1] - words[0].get_bottom()[1]
            w.next_to(ks, RIGHT, buff=.14).set_y(ks.get_center()[1] - .1 + y)
            return VGroup(ks, w)
        keymap = VGroup(keys(['W', 'S'], 'throttle'), keys(['A', 'D'], 'yaw'), keys(['↑', '↓'], 'pitch'),
                        keys(['←', '→'], 'roll'), keys(['R'], 'arm'), keys(['X'], 'disarm')).arrange(RIGHT, buff=.42).move_to([0, -2.55, 0])
        for g in keymap:
            g.shift(UP * (-2.55 - g[0].get_center()[1]))
        ui = VGroup(left, right, drone, drone_label, bars)

        # u: free stick movement (0..1); f: focus on throttle; n*: single nudges; arm: arm switch 0..1
        u, f = ValueTracker(0.0), ValueTracker(0.0)
        nt, ny, npi, nr, arm = (ValueTracker(0.0) for _ in range(5))
        THR_END = 0.15           # 1150 µs = 15 % of 1000..2000
        lk0, rk0 = np.array([-4.0, 0.95 - 1.05, 0]), np.array([4.0, 0.95, 0])
        drone0 = drone.copy().move_to(ORIGIN)
        caps = [keymap[g][0][k] for g in range(4) for k in range(2)] + [keymap[4][0][0]]
        last = [None] * 8

        def smooth01(x):
            x = min(max(x, 0.0), 1.0)
            return x * x * (3 - 2 * x)

        def env(x):
            return smooth01(x / .12) * smooth01((1 - x) / .12)

        def thr_free(x):
            return .42 * smooth01(x / .15) + .2 * env(x) * np.sin(TAU * 1.75 * x) - .37 * smooth01((x - .75) / .25)

        def sticks():
            x, e = u.get_value(), env(u.get_value())
            thr = interpolate(thr_free(x), THR_END, smooth01(f.get_value())) + .35 * nt.get_value()
            return (thr, .75 * e * np.sin(TAU * 2 * x) + .8 * ny.get_value(), .7 * e * np.sin(TAU * 2.5 * x + 2.4) + .8 * npi.get_value(),
                    .7 * e * np.sin(TAU * 1.5 * x + 1.0) + .8 * nr.get_value())

        def apply(_=None):
            thr, yaw, pitch, roll = sticks()
            x, fv = u.get_value(), smooth01(f.get_value())
            lk.move_to(lk0 + RIGHT * .9 * yaw + UP * 2.1 * thr).set_color(interpolate_color(ManimColor(BLUE_A), ManimColor(YELLOW_A), fv))
            rk.move_to(rk0 + RIGHT * .9 * roll + UP * .9 * pitch)
            d = drone0.copy().rotate(-yaw * PI / 5, axis=OUT).rotate(pitch * PI / 3, axis=RIGHT).rotate(roll * PI / 3, axis=UP)
            drone.become(d.move_to([0, .95 + .35 * thr / THR_END if thr < THR_END else .95 + .35 + (thr - THR_END), 0]))
            a = interpolate(1, DIM, fv)
            fracs = (thr, .5 + .5 * roll, .5 + .5 * pitch, .5 + .5 * yaw, .5, .5, arm.get_value(), .5)
            for i, frac in enumerate(fracs):
                h = max(.85 * min(max(frac, 0), 1), .03)
                bars[i][1].stretch_to_fit_height(h).move_to(bars[i][0].get_bottom() + UP * h / 2)
                v = int(round(1000 + 1000 * min(max(frac, 0), 1)))
                if v != last[i]:
                    nums[i].set_value(v); last[i] = v
                nums[i].move_to([(i - 3.5) * 1.05, -.66, 0])
            for i in range(1, 8):
                bars[i][0].set_stroke(opacity=a); bars[i][1].set_fill(opacity=.5 * a); bars[i][2].set_fill(opacity=a)
                nums[i].set_color(INK).set_fill(opacity=a)
            yel = interpolate_color(ManimColor(STRUCT), ManimColor(YELLOW_A), fv)
            bars[0][0].set_stroke(yel)
            bars[0][1].set_fill(interpolate_color(ManimColor(BLUE_A), ManimColor(YELLOW_A), fv), opacity=.5)
            bars[0][2].set_color(interpolate_color(ManimColor(MUTED), ManimColor(YELLOW_A), fv))
            nums[0].set_color(interpolate_color(ManimColor(INK), ManimColor(YELLOW_A), fv))
            dthr = (thr_free(min(x + .004, 1)) - thr_free(max(x - .004, 0))) / .008
            if 0.02 < f.get_value() < 0.98:
                dthr = 1
            if 0.02 < nt.get_value() < 0.98:
                dthr = 1
            on = [dthr > .25, dthr < -.25, yaw < -.25, yaw > .25, pitch > .25, pitch < -.25, roll < -.25, roll > .25,
                  0.02 < arm.get_value() < 0.98]
            for cap, lit in zip(caps, on):
                cap[0].set_stroke(YELLOW_A if lit else STRUCT)
                cap[1].set_color(YELLOW_A if lit else INK)

        apply()
        driver = Mobject()               # carries the updater, so FadeIn/FadeOut of parts of the page cannot drop it
        driver.add_updater(apply)
        self.add(driver)

        marks = {}

        def say(text):
            print('SENTENCE', round(self.renderer.time, 2), text, flush=True)
            # the voice gives no word times: a bookmark is placed at its share of the spoken characters
            sp = spoken(text)
            plain = re.sub(r"<bookmark[^>]*/>", "", sp)
            marks.clear()
            for m in re.finditer(r"<bookmark\s*mark\s*=\s*['\"](\w+)['\"]\s*/>", sp):
                marks[m.group(1)] = len(re.sub(r"<bookmark[^>]*/>", "", sp[:m.start()])) / max(len(plain), 1)
            return self.voiceover(text=text)

        def until(mark_):
            c_ = cur[0]
            dt = c_.t0 + frac_to_seconds(c_.tr, marks[mark_]) - self.renderer.time
            if dt > 0.02:
                self.wait(dt)

        cur = [None]

        class Clock:
            """Time left in a voiceover block, so each block's last wait fills exactly the sentence."""
            def __init__(c, tr):
                c.tr, c.t0 = tr, self.renderer.time
                cur[0] = c

            def left(c):
                return c.tr.duration - (self.renderer.time - c.t0)

            def rest(c, keep=0.0):
                if c.left() - keep > 0.02:
                    self.wait(c.left() - keep)

        def pulse(*mobs, rt=.6):
            rects = [SurroundingRectangle(m, color=YELLOW_A, buff=.06, stroke_width=SW) for m in mobs]
            self.play(AnimationGroup(*[Succession(FadeIn(r, run_time=rt / 2), FadeOut(r, run_time=rt / 2)) for r in rects]))

        def nudge(tracker, extra=()):
            self.play(tracker.animate.set_value(1.0).set_rate_func(there_and_back) if False else
                      UpdateFromAlphaFunc(tracker, lambda m, a: m.set_value(np.sin(PI * a)), run_time=.6), *extra)

        def cap_(text, size=32, mono_=False):
            if mono_:
                return mono(text, 28).move_to(frame.get_center() + DOWN * (frame.height / 2 - .6))
            return caption_at(frame, text, size)

        # 1
        with say("This is the <bookmark mark='a'/>browser app that flies the drone; you can try it at the <bookmark mark='b'/>address on screen.") as t:
            ck = Clock(t)
            until('a')
            self.play(FadeIn(ui), FadeIn(keymap), strip.go(K_APP), run_time=1.2)
            until('b')
            url = mono('d8tx.mb6611.workers.dev', 28).move_to([-3.7, -3.4, 0])
            self.play(FadeIn(url), run_time=.5)
            ck.rest()
        # 2
        with say("Everything the pilot controls <bookmark mark='a'/>is a number, called a <bookmark mark='b'/>control channel.") as t:
            ck = Clock(t)
            until('a')
            self.play(LaggedStart(*[FadeIn(n_) for n_ in nums], lag_ratio=.2, run_time=1.0))
            until('b')
            c = cap_('a control channel: one number').set_x(3.9)
            self.play(FadeIn(c), run_time=.5)
            ck.rest()
        # 3
        brace = Brace(bars, DOWN, buff=.3, color=MUTED)
        blabel = label('8 control channels', 24, INK).next_to(brace, DOWN, buff=.12)
        with say("There are <bookmark mark='a'/>eight:") as t:
            ck = Clock(t)
            self.play(FadeOut(keymap), run_time=.3)
            until('a')
            self.play(GrowFromCenter(brace), FadeIn(blabel), run_time=.6)
            ck.rest()
        # 4
        with say("<bookmark mark='t'/>throttle, <bookmark mark='y'/>yaw, <bookmark mark='p'/>pitch and <bookmark mark='r'/>roll from <bookmark mark='s'/>the two sticks,") as t:
            ck = Clock(t)
            self.play(FadeOut(brace), FadeOut(blabel), FadeOut(c), FadeOut(url), run_time=.45)
            self.play(FadeIn(keymap), run_time=.25)
            until('t'); nudge(nt, [])
            until('y'); nudge(ny, [])
            until('p'); nudge(npi, [])
            until('r'); nudge(nr, [])
            until('s'); pulse(left[0], right[0])
            ck.rest()
        # 5
        with say("and four <bookmark mark='a'/>auxiliary ones, such as the <bookmark mark='b'/>arm switch.") as t:
            ck = Clock(t)
            until('a'); pulse(*[bars[i][0] for i in (4, 5, 6, 7)], rt=.5)
            until('b')
            self.play(arm.animate.set_value(1.0), run_time=1.0, rate_func=linear)
            ck.rest()
        # 6
        c2 = cap_('all four stick channels move at once')
        with say("<bookmark mark='a'/>Moving the sticks changes all four stick channels at once.") as t:
            ck = Clock(t)
            self.play(FadeIn(c2), run_time=.4)
            self.play(u.animate.set_value(1.0), run_time=max(ck.left(), .1), rate_func=linear)
        # 7
        c = cap_("Let's follow the throttle")
        with say("Let's follow the throttle.") as t:
            ck = Clock(t)
            self.play(Succession(FadeOut(c2, run_time=.3), FadeIn(c, run_time=.4), Wait(.5)), f.animate.set_value(1.0), run_time=1.2)
            ck.rest()
        # end on the seam frame: hero number, strip marker on browser
        driver.remove_updater(apply)
        value = num('1150', 20, YELLOW_A).move_to(nums[0])
        nums[0].set_opacity(0)
        self.add(value)
        target = hero_number()
        self.play(FadeOut(ui), FadeOut(keymap), FadeOut(nums), FadeOut(c), run_time=.5)
        target.set_opacity(0)
        self.add(target)
        self.play(FadeOut(value, shift=ORIGIN), target.animate.set_opacity(1), run_time=.7)
        self.wait(.3)
