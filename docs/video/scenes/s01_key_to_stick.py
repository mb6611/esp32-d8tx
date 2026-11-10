"""S01: a simplified Sticks page, ending on the shared throttle number."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from parts import *


class S01(Narrated, MovingCameraScene):
    def construct(self):
        frame = self.camera.frame
        strip = MapStrip(K_KEY, lambda: (frame.get_center(), frame.width))
        self.add(strip)

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
        # Small top-view quad: four motors, two arms, central body.
        drone = VGroup(Line(LEFT*.65+UP*.42, RIGHT*.65+DOWN*.42),
                       Line(LEFT*.65+DOWN*.42, RIGHT*.65+UP*.42)).set_stroke(BLUE_DK, SW_LINE)
        for x in (-.65, .65):
            for y in (-.42, .42):
                drone.add(Circle(radius=.22, color=BLUE_LT, stroke_width=SW).move_to([x,y,0]))
        drone.add(Square(.34, color=BLUE_A, stroke_width=SW))
        drone.move_to([0, .95, 0])
        drone_label = label('drone', 22).move_to([0, -.1, 0])
        names = ['THR', 'AIL', 'ELE', 'RUD', 'AUX1', 'AUX2', 'ARM', 'AUX4']
        bars = VGroup()
        for i, name in enumerate(names):
            x = (i - 3.5) * 1.05
            outline = Rectangle(width=.62, height=.85, color=STRUCT, stroke_width=SW).move_to([x,-1.3,0])
            height = .03 if i in (0,4,5,6,7) else .43
            fill = Rectangle(width=.58, height=height, stroke_width=0, fill_color=BLUE_A, fill_opacity=.5).move_to(outline.get_bottom()+UP*height/2)
            name_obj = label(name, 22).next_to(outline, DOWN, buff=.12)
            bars.add(VGroup(outline, fill, name_obj))
        # Key map (apps/web key bindings): one row of key caps, each with the stick it moves.
        kwords = ['throttle', 'yaw', 'pitch', 'roll', 'arm', 'disarm']
        words = Tex(*kwords, font_size=24, color=GREY_A)     # one Tex, so all six words share a baseline

        def keys(caps, word):
            ks = VGroup()
            for ch in caps:
                t = label(ch, 24, INK)
                box = RoundedRectangle(corner_radius=.06, width=max(.42, t.width + .2), height=.42, color=STRUCT, stroke_width=SW)
                ks.add(VGroup(box, t.move_to(box)))
            ks.arrange(RIGHT, buff=.07)
            w = words[kwords.index(word)]
            y = w.get_center()[1] - words[0].get_bottom()[1]          # height above the common baseline
            w.next_to(ks, RIGHT, buff=.14).set_y(ks.get_center()[1] - .1 + y)
            return VGroup(ks, w)
        keymap = VGroup(keys(['W', 'S'], 'throttle'), keys(['A', 'D'], 'yaw'), keys(['↑', '↓'], 'pitch'),
                        keys(['←', '→'], 'roll'), keys(['R'], 'arm'), keys(['X'], 'disarm')).arrange(RIGHT, buff=.42).move_to([0, -2.55, 0])
        for g in keymap:
            g.shift(UP * (-2.55 - g[0].get_center()[1]))
        ui = VGroup(left, right, drone, drone_label, bars, keymap)

        # Everything on the page follows two trackers, so sticks, drone, bars and key caps move as one picture.
        # u: the free stick movement (0..1); f: the focus on throttle (0..1).
        u, f = ValueTracker(0.0), ValueTracker(0.0)
        THR_END = 0.15           # 1150 µs = 15 % of 1000..2000 (the throttle cap in experiments/14)
        lk0, rk0 = np.array([-4.0, 0.95 - 1.05, 0]), np.array([4.0, 0.95, 0])
        drone0 = drone.copy().move_to(ORIGIN)
        caps = [keymap[g][0][k] for g in range(4) for k in range(2)]      # W S, A D, up down, left right

        def smooth01(x):
            x = min(max(x, 0.0), 1.0)
            return x * x * (3 - 2 * x)

        def env(x):              # the three centred sticks start and end at rest in the middle
            return smooth01(x / .12) * smooth01((1 - x) / .12)

        def thr_free(x):
            return .42 * smooth01(x / .15) + .2 * env(x) * np.sin(TAU * 1.75 * x)

        def sticks():
            """(throttle 0..1, yaw, pitch, roll -1..1) right now. The free movement is a cartoon, not a recorded flight."""
            x, e = u.get_value(), env(u.get_value())
            thr = interpolate(thr_free(x), THR_END, smooth01(f.get_value()))
            return (thr, .75 * e * np.sin(TAU * 2 * x), .7 * e * np.sin(TAU * 2.5 * x + 2.4),
                    .7 * e * np.sin(TAU * 1.5 * x + 1.0))

        def apply(_=None):
            thr, yaw, pitch, roll = sticks()
            x, fv = u.get_value(), smooth01(f.get_value())
            lk.move_to(lk0 + RIGHT * .9 * yaw + UP * 2.1 * thr).set_color(interpolate_color(ManimColor(BLUE_A), ManimColor(YELLOW_A), fv))
            rk.move_to(rk0 + RIGHT * .9 * roll + UP * .9 * pitch)
            # the drone climbs with throttle, turns with yaw and tilts with pitch and roll
            d = drone0.copy().rotate(-yaw * PI / 5, axis=OUT).rotate(pitch * PI / 3, axis=RIGHT).rotate(roll * PI / 3, axis=UP)
            drone.become(d.move_to([0, .95 + .35 * thr / THR_END if thr < THR_END else .95 + .35 + (thr - THR_END), 0]))
            # bars in channel order THR AIL ELE RUD (throttle, roll, pitch, yaw); the other four hold still
            for i, frac in enumerate((thr, .5 + .5 * roll, .5 + .5 * pitch, .5 + .5 * yaw)):
                h = max(.85 * frac, .03)
                bars[i][1].stretch_to_fit_height(h).move_to(bars[i][0].get_bottom() + UP * h / 2)
            a = interpolate(1, DIM, fv)
            for i in range(1, 8):
                bars[i][0].set_stroke(opacity=a); bars[i][1].set_fill(opacity=.5 * a); bars[i][2].set_fill(opacity=a)
            yel = interpolate_color(ManimColor(STRUCT), ManimColor(YELLOW_A), fv)
            bars[0][0].set_stroke(yel)
            bars[0][1].set_fill(interpolate_color(ManimColor(BLUE_A), ManimColor(YELLOW_A), fv), opacity=.5)
            bars[0][2].set_color(interpolate_color(ManimColor(MUTED), ManimColor(YELLOW_A), fv))
            # key caps light while their stick is pushed: W/S by the direction throttle is moving
            dthr = (thr_free(min(x + .004, 1)) - thr_free(max(x - .004, 0))) / .008
            if 0.02 < f.get_value() < 0.98:
                dthr = -1
            on = [dthr > .25, dthr < -.25, yaw < -.25, yaw > .25, pitch > .25, pitch < -.25, roll < -.25, roll > .25]
            for cap, lit in zip(caps, on):
                cap[0].set_stroke(YELLOW_A if lit else STRUCT)
                cap[1].set_color(YELLOW_A if lit else INK)

        apply()
        ui.add_updater(apply)
        T = 12.1                 # seconds of free movement (u runs 0..1 over the first four sentences)

        def move(dt, *anims):
            if dt > 0.02:
                self.play(u.animate.set_value(min(u.get_value() + dt / T, 1.0)), *anims, run_time=dt, rate_func=linear)

        def say(text):
            print('SENTENCE', round(self.renderer.time, 2), text, flush=True)
            return self.voiceover(text=text)

        with say("This is the browser app we fly the drone with.") as t:
            self.play(FadeIn(ui), strip.go(K_APP), run_time=1.2)
            c = caption_at(frame, 'The browser turns keys into channels', 32)
            move(.6, FadeIn(c)); move(t.duration - 1.8)
        with say("Everything the pilot can control is a channel, and there are eight of them.") as t:
            move(t.duration)
        with say("Four come from the sticks: throttle, yaw, pitch and roll.") as t:
            c2 = caption_at(frame, 'All four stick channels move at once', 32)
            move(.4, FadeOut(c)); move(.6, FadeIn(c2)); move(t.duration - 1.0)
        with say("Move the sticks and all four change at once.") as t:
            move(t.duration)
        # Focus: the other channels dim, throttle comes down to 1150 µs and turns yellow.
        value = num('1150', 30, YELLOW_A).next_to(bars[0][0], UP, buff=.12)
        c = caption_at(frame, "Let's focus on the throttle", 32)
        with say("Let's follow just one of them, the throttle,") as t:
            u.set_value(1.0)
            self.play(FadeOut(c2), run_time=.3)
            self.play(f.animate.set_value(1.0), FadeIn(c), run_time=1.4)
            self.play(FadeIn(value), run_time=.5)
            self.wait(max(t.duration - 2.2, 0))
        with say("from the key press all the way to the motors.") as t:
            self.wait(max(t.duration - 1.5, 0))
            ui.remove_updater(apply)
            # Preserve the exact hero_number shared with S02.
            target = hero_number()
            self.play(FadeOut(ui), FadeOut(c), ReplacementTransform(value, target), run_time=1.5)
        self.wait(.5)
