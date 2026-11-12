"""YouTube thumbnail for the d8tx explainer: a Wi-Fi chip, a two-tone wave, the drone, and one line of text.
Render: .venv/bin/manim -s -r 1280,720 --media_dir media/thumbnail -o thumbnail thumbnail.py Thumbnail
ThumbnailPlay is the same picture with a play button, for the README link (docs/media/video-thumb.png):
        .venv/bin/manim -s -r 1280,720 --media_dir media/thumbnail -o video-thumb thumbnail.py ThumbnailPlay
Lines are much thicker than in the scenes on purpose: a thumbnail is seen about 170 px wide."""
import numpy as np
from common import *

BITS = (1, 0, 1, 1, 0, 1)
Y = -1.15


def chip(center, s=2.5):
    g = VGroup()
    body = RoundedRectangle(corner_radius=0.22, width=s, height=s).set_stroke(BLUE_A, 10).set_fill("#0B2A33", 1)
    for i in range(5):
        t = (i - 2) * s / 6
        for d in (UP, DOWN, LEFT, RIGHT):
            a = d * s / 2 + (RIGHT if d[0] == 0 else UP) * t
            g.add(Line(a, a + d * 0.32).set_stroke(BLUE_A, 9))
    g.add(body)
    base = DOWN * 0.62
    g.add(Dot(base, radius=0.15, color=INK))
    for r in (0.5, 0.9, 1.3):
        g.add(Arc(radius=r, start_angle=PI / 4, angle=PI / 2, arc_center=base).set_stroke(INK, 11).set_cap_style(CapStyleType.ROUND))
    return g.move_to(center)


def drone(center, k=1.0):
    g = VGroup()
    ax, ay = 1.25, 0.95
    for sx, sy in ((1, 1), (-1, -1), (1, -1), (-1, 1)):
        g.add(Line(ORIGIN, [sx * ax, sy * ay, 0]).set_stroke(BLUE_DK, 14))
    for sx, sy in ((1, 1), (-1, -1), (1, -1), (-1, 1)):
        p = np.array([sx * ax, sy * ay, 0])
        g.add(Circle(radius=0.62).set_stroke(BLUE_LT, 9).set_fill(BLUE_LT, 0.18).move_to(p))
        g.add(Dot(p, radius=0.13, color=INK))
    g.add(RoundedRectangle(corner_radius=0.12, width=0.95, height=0.95).set_stroke(BLUE_A, 9).set_fill("#0B2A33", 1))
    return g.scale(k).move_to(center)


def wave(x0, x1, y, amp=0.62):
    n = len(BITS); w = (x1 - x0) / n
    g = VGroup(); ph = 0.0
    for i, b in enumerate(BITS):
        cyc = 3.0 if b else 1.5
        xs = np.linspace(0, 1, 120)
        pts = [[x0 + (i + u) * w, y + amp * np.sin(ph + TAU * cyc * u), 0] for u in xs]
        g.add(VMobject().set_points_smoothly(pts).set_stroke(ONE if b else ZERO, 11))
        ph += TAU * cyc
    return g


class Thumbnail(Scene):
    def construct(self):
        c = chip([-4.9, Y, 0])
        d = drone([4.55, Y, 0], 1.12)
        w = wave(-2.8, 2.15, Y)
        t = Tex(r"\textbf{Wi-Fi chip}", r"\ $\boldsymbol{\rightarrow}$\ ", r"\textbf{drone remote}", tex_template=TexTemplate().add_to_preamble(r"\usepackage{amsmath}\usepackage{amssymb}"))
        t.set_color(INK); t[1].set_color(YELLOW_A)
        t.scale_to_fit_width(13.0).move_to([0, 2.55, 0])
        self.add(w, c, d, t)


class ThumbnailPlay(Thumbnail):
    def construct(self):
        super().construct()
        disc = Circle(radius=1.05).set_stroke(INK, 8).set_fill(BG, 0.82).move_to([-0.32, Y, 0])
        tri = Triangle().set_stroke(width=0).set_fill(INK, 1).rotate(-PI / 2).scale_to_fit_height(0.95).move_to(disc).shift(RIGHT * 0.08)
        self.add(disc, tri)
