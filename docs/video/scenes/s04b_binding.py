"""S04b the hop sequence and binding. In: seam_s04a_s04b (hop_plot(13, 13) through HP_CAM). Out: seam_s04b_s05("out").
Beats 1-6 draw two boxes (transmitter, drone) in front of the dimmed hop plot; they are built in normal frame units and
mapped into the width-18 view with F() (scale HP_K about the frame centre). Beats 6-9 go back to the plot, then the stream."""
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from parts import *

S = HP_K                        # frame units -> width-18 view
C = HP_CAM[0]


def F(m):
    """Frame-unit mobject (built around the frame centre) -> the width-18 view."""
    return m.scale(S, about_point=ORIGIN, scale_stroke=True).shift(C)


def P(x, y):
    return C + S * np.array([x, y, 0.0])


def rrect(w, h, x, y, color=STRUCT, sw=SW_THIN, fill=None, fo=0.0, dashed=False):
    r = RoundedRectangle(corner_radius=0.08, width=w, height=h, stroke_color=color, stroke_width=sw,
                         fill_color=fill or BG, fill_opacity=fo).move_to([x, y, 0])
    if dashed:
        r = DashedVMobject(r.set_fill(opacity=0), num_dashes=22, dashed_ratio=0.5)
    return r


def tag(x, y, color, text="ID", filled=False):
    """The small ID tag: outlined (empty) or filled with `color`."""
    box = rrect(1.1, 0.4, x, y, color, SW, fill=color, fo=0.9 if filled else 0.0)
    t = label(text, 22, BG if filled else color).move_to(box)
    return VGroup(box, t)


def ctext(txt, x, y, size=22, color=INK):
    return mono(txt, size, color).move_to([x, y, 0])


ROWY = [1.05 - 0.5 * i for i in range(7)]
VDOTS = lambda x, y, c=INK: Tex(r"$\vdots$", font_size=26, color=c).move_to([x, y, 0])
TX_X, DR_X, BOX_Y = -4.6, 4.6, -0.2
LANE_Y = BOX_Y


class Flow(VGroup):
    """Bind packets crossing the lane left to right, one every 0.6 s, linear. `stop_x`: the next block to reach it is caught."""

    def __init__(self, color=BLUE_A, speed=1.7):
        super().__init__()
        self.t, self.nxt, self.spawn, self.color, self.speed = 0.0, 0.0, True, color, speed
        self.stop_x, self.caught = None, None
        self.add_updater(self._upd)

    def _upd(self, m, dt):
        if dt == 0:
            return
        self.t += dt
        if self.spawn and self.t >= self.nxt:
            self.nxt = self.t + 0.6
            self.add(F(packet_block(1.0, self.color)).move_to(P(-2.3 + 0.3, LANE_Y)))
        for b in list(self.submobjects):
            b.shift(RIGHT * self.speed * S * dt)
            x = (b.get_center()[0] - C[0]) / S
            if self.stop_x is not None and x >= self.stop_x and self.caught is None:
                self.caught = b
                self.stop_x = None
                self.remove(b)
            elif x > 2.3 - 0.3:
                self.remove(b)


class S04B(Narrated, MovingCameraScene):
    """"""

    # MacSayService gives no word timings, so bookmarks are placed linearly by character position in the spoken text.
    def voiceover(self, text=None, **kw):
        plain = re.sub(r"<bookmark\s*mark\s*=\s*['\"]\w*['\"]\s*/>", "", spoken(text))
        self._bk, pos = {}, 0
        for part in re.split(r"(<bookmark\s*mark\s*=\s*['\"]\w*['\"]\s*/>)", spoken(text)):
            m = re.match(r"<bookmark\s*mark\s*=\s*['\"](\w*)['\"]", part)
            if m:
                self._bk[m.group(1)] = pos / max(len(plain), 1)
            else:
                pos += len(part)
        self._t0 = self.renderer.time
        cm = super().voiceover(text=text, **kw)
        return cm

    def wait_until_bookmark(self, mark, off=0.0):
        dur = self.current_tracker.duration
        d = self._t0 + frac_to_seconds(self.current_tracker, self._bk[mark]) - self.renderer.time - off
        if d > 0.05:
            self.wait(d)

    def cap(self, text):
        return caption_at(self.camera.frame, text, 32)

    def construct(self):
        seam = seam_s04a_s04b()
        seam.enter(self)
        g = seam.mobs
        frame = self.camera.frame

        # ---- opacity control of the plot (a tracker times each member's own opacity) ----
        fam = [m for m in g.family_members_with_points()]
        base = [(m.get_fill_opacity(), m.get_stroke_opacity()) for m in fam]
        a = ValueTracker(1.0)

        ax_ids = {id(m) for o in (g.axes, g.rx, g.tx) for m in o.family_members_with_points()}

        def apply(_):
            v = a.get_value()
            va = max(0.0, (v - DIM) / (1 - DIM))      # axis labels and tags leave while the plot dims (boxes sit over them)
            for m, (f, st) in zip(fam, base):
                k = va if id(m) in ax_ids else v
                m.set_fill(opacity=f * k)
                m.set_stroke(opacity=st * k)
        g.add_updater(apply)

        # ---- the two boxes ----
        def column(x, color, name):
            box = rrect(2.4, 4.4, x, BOX_Y, STRUCT, SW, fill=BG, fo=0.9)
            hdr = label(name, 28, color).move_to([x, 2.6, 0])
            rows = [rrect(1.7, 0.38, x, y) for y in ROWY]
            idt = tag(x, 1.65, MUTED)
            return box, hdr, rows, idt

        txb, txh, txr, txid = column(TX_X, BLUE_A, "transmitter")
        drb, drh, drr, drid = column(DR_X, GREEN_A, "drone")
        for m in (txb, txh, *txr, txid, drb, drh, *drr, drid):
            F(m)

        # ===== 1. the hop sequence =====
        cap1 = self.cap("the hop sequence: radio channels, in order")
        src = [mono(str(TABLE[i]), 22).scale(S).move_to(g.pkts[max(i - 1, 0)].get_center() + UP * 0.6 * S + (LEFT * 0.0 if i else LEFT * SLOT_W * 1.4))
               for i in range(6)]
        for t in src:
            t.set_stroke(BG, width=7, opacity=1, background=True)
        panel = F(rrect(1.1, 4.4, 0, BOX_Y, STRUCT, SW_THIN, fill=BG, fo=0.95))
        mid = [F(ctext(str(TABLE[i]), 0, ROWY[i])) for i in range(6)] + [F(VDOTS(0, ROWY[6]))]
        with self.voiceover(text="For <bookmark mark='a'/>that, both need the same list of <bookmark mark='r'/>radio channels <bookmark mark='b'/>"
                                 "in the same order: <bookmark mark='c'/>the hop sequence.") as tr:
            self.play(LaggedStart(*[FadeIn(t, shift=UP * 0.15) for t in src], lag_ratio=0.1), run_time=0.7)
            self.wait_until_bookmark("a")
            # dim the plot and give the list a clear backing first, then the numbers fly one at a time
            self.bring_to_front(*src)
            self.play(a.animate.set_value(DIM), FadeIn(panel), run_time=0.5)
            cap_delay = max(0.0, self._t0 + frac_to_seconds(self.current_tracker, self._bk["r"]) - self.renderer.time)
            self.play(LaggedStart(*[src[i].animate.move_to(mid[i]) for i in range(6)], lag_ratio=0.3),
                      FadeIn(mid[6]), Succession(Wait(cap_delay), FadeIn(cap1, run_time=0.4)), run_time=1.6)
            self.remove(*src)
            self.add(*mid[:6])
            self.wait_until_bookmark("b")
            cp = [m.copy() for m in mid]
            self.play(*[FadeIn(m) for m in (txb, drb, txh, drh, *txr, *drr, txid, drid)], FadeOut(panel), run_time=0.4)
            self.bring_to_front(*mid)
            self.add(*cp)
            tx_nums, dr_nums = mid, cp
            # the two copies start on top of each other: the transmitter's column leaves first, the drone's follows
            # once it is clear (0.15 s later, a few units away; the launch is front-loaded so the pair clears within one frame), so the flying numbers never overlap
            lag = lambda t0, d: (lambda t: (1 - 2.0 ** (-10 * min(1.0, (t * 0.8 - t0) / d))) / (1 - 2.0 ** -10) if t * 0.8 > t0 else 0.0)
            self.play(*[tx_nums[i].animate(rate_func=lag(0.0, 0.6)).move_to(P(TX_X, ROWY[i])) for i in range(7)],
                      *[dr_nums[i].animate(rate_func=lag(0.15, 0.65)).move_to(P(DR_X, ROWY[i])) for i in range(7)],
                      run_time=0.8)
            self.wait_until_bookmark("c")
            hl_t = F(rrect(1.7, 0.38, TX_X, ROWY[0], INK, SW))
            hl_d = F(rrect(1.7, 0.38, DR_X, ROWY[0], INK, SW))
            self.add(hl_t, hl_d)
            for i in range(1, 6):
                self.play(hl_t.animate.move_to(P(TX_X, ROWY[i])), hl_d.animate.move_to(P(DR_X, ROWY[i])), run_time=0.18,
                          rate_func=linear)
            self.play(FadeOut(hl_t), FadeOut(hl_d), run_time=0.2)
            br_t = F(Brace(Line([TX_X + 0.95, ROWY[6] - 0.2, 0], [TX_X + 0.95, ROWY[0] + 0.2, 0]), RIGHT, buff=0.05, color=MUTED))
            br_d = F(Brace(Line([DR_X - 0.95, ROWY[6] - 0.2, 0], [DR_X - 0.95, ROWY[0] + 0.2, 0]), LEFT, buff=0.05, color=MUTED))
            hs_t = label("hop sequence", 22).scale(S).next_to(br_t, RIGHT, buff=0.1)
            hs_d = label("hop sequence", 22).scale(S).next_to(br_d, LEFT, buff=0.1)
            n47 = label("47 entries", 22).scale(S).next_to(hs_t, DOWN, buff=0.1 * S)
            self.play(FadeIn(br_t), FadeIn(br_d), FadeIn(hs_t), FadeIn(hs_d), FadeIn(n47), run_time=0.7)
            self.wait_for_voiceover()

        # ===== 2. binding =====
        cap2 = self.cap("binding")
        dr_dash = [F(rrect(1.7, 0.38, DR_X, y, STRUCT, SW_THIN, dashed=True)) for y in ROWY]
        id_dash = F(rrect(1.1, 0.4, DR_X, 1.65, STRUCT, SW_THIN, dashed=True))
        tx_id_new = F(tag(TX_X, 1.65, BLUE_A, filled=True))
        with self.voiceover(text="The drone gets it once, in a step called <bookmark mark='a'/>binding.") as tr:
            self.play(FadeOut(cap1), FadeOut(br_t), FadeOut(br_d), FadeOut(hs_t), FadeOut(hs_d), FadeOut(n47),
                      *[FadeOut(n) for n in dr_nums], *[FadeOut(r) for r in drr], FadeOut(drid),
                      *[FadeIn(d) for d in dr_dash], FadeIn(id_dash), FadeOut(txid), FadeIn(tx_id_new),
                      a.animate.set_value(0.0), run_time=1.4)
            self.remove(g)
            self.wait_until_bookmark("a")
            self.play(FadeIn(cap2), run_time=0.5)
            self.wait_for_voiceover()
        txid = tx_id_new

        # ===== 3. bind mode =====
        bar = F(Rectangle(width=4.6, height=0.25, stroke_color=GREEN_A, stroke_width=SW, fill_color=GREEN_A,
                          fill_opacity=0.2).move_to([0, LANE_Y, 0]))
        rc0 = F(label("radio channel 0", 22).move_to([0, LANE_Y - 0.5, 0]))
        bm = F(VGroup(rrect(1.3, 0.34, DR_X, 2.27, GREEN_A, SW_THIN), label("bind mode", 20, GREEN_A).move_to([DR_X, 2.27, 0])))
        flow = Flow()
        with self.voiceover(text="In <bookmark mark='a'/>bind mode it listens on <bookmark mark='b'/>radio channel 0, "
                                 "where the transmitter <bookmark mark='c'/>sends bind packets.") as tr:
            self.play(FadeOut(cap2), run_time=0.3)
            self.wait_until_bookmark("a")
            self.play(FadeIn(bm), run_time=0.5)
            self.wait_until_bookmark("b")
            self.play(FadeIn(bar), FadeIn(rc0), run_time=0.6)
            self.wait_until_bookmark("c")
            self.add(flow)
            self.wait_for_voiceover()

        # ===== 4. the bind packet =====
        cap4 = self.cap("a bind packet: the ID and five entries")
        with self.voiceover(text="<bookmark mark='a'/>They carry the <bookmark mark='b'/>transmitter's ID and the hop sequence, "
                                 "<bookmark mark='c'/>a few entries at a time, <bookmark mark='d0'/>and the drone <bookmark mark='d'/>stores both.") as tr:
            flow.stop_x = 0.0
            while flow.caught is None:
                self.wait(0.1)
            blk = flow.caught
            CY = 0.75
            cells = []
            for i in range(6):
                x = (i - 2.5) * 0.74
                bx = rrect(0.68, 0.4, x, CY, STRUCT, SW_THIN)
                txt = label("ID", 22, BLUE_A) if i == 0 else ctext(str(TABLE[i - 1]), x, CY, 20)
                if i == 0:
                    bx.set_stroke(BLUE_A, width=SW)
                    txt.move_to([x, CY, 0])
                cells.append(F(VGroup(bx, txt)))
            br_id = F(Brace(Line([-2.5 * 0.74 - 0.34, CY + 0.2, 0], [-2.5 * 0.74 + 0.34, CY + 0.2, 0]), UP, buff=0.05, color=MUTED))
            br_5 = F(Brace(Line([-1.5 * 0.74 - 0.34, CY + 0.2, 0], [2.5 * 0.74 + 0.34, CY + 0.2, 0]), UP, buff=0.05, color=MUTED))
            l_id = label("ID", 20).scale(S).next_to(br_id, UP, buff=0.05)
            l_5 = label("5 entries", 20).scale(S).next_to(br_5, UP, buff=0.05)
            self.wait_until_bookmark("a")
            self.play(blk.animate.move_to(P(0, LANE_Y)), run_time=0.2)
            self.play(LaggedStart(*[FadeIn(c, shift=DOWN * 0.1 * S) for c in cells], lag_ratio=0.15), run_time=1.0)
            self.wait_until_bookmark("b")
            self.play(FadeIn(br_id), FadeIn(l_id), Indicate(cells[0], color=BLUE_A, scale_factor=1.15), run_time=0.8)
            self.wait_until_bookmark("c")
            self.play(FadeIn(br_5), FadeIn(l_5), FadeIn(cap4), run_time=0.7)
            self.wait_until_bookmark("d0")
            self.play(*[FadeOut(m) for m in (br_id, br_5, l_id, l_5)],
                      *[c.animate.move_to(blk).scale(0.3).set_opacity(0) for c in cells],
                      blk.animate.move_to(P(2.0, LANE_Y)), run_time=0.4, rate_func=linear)
            self.remove(*cells)
            nums = [F(ctext(str(TABLE[i]), 2.0, LANE_Y)).set_opacity(0) for i in range(5)]
            dr_id = F(tag(2.0, LANE_Y, BLUE_A, filled=True)).set_opacity(0)
            self.add(*nums, dr_id)
            self.wait_until_bookmark("d", off=1.0)   # no-op: the fill starts right after the block arrives, on 'stores'
            new_tx = list(tx_nums[:6])
            self.play(FadeOut(blk), FadeOut(id_dash),
                      LaggedStart(*[m.animate.set_opacity(1).move_to(P(DR_X, y)) for m, y in
                                    [(dr_id, 1.65)] + [(nums[i], ROWY[i]) for i in range(5)]], lag_ratio=0.12),
                      run_time=0.6, rate_func=smooth)
            self.wait_for_voiceover()
        # two more blocks fill more rows (the transmitter's list is already redrawn)
        more = [F(ctext("21", DR_X, ROWY[5])), F(VDOTS(DR_X, ROWY[6]))]
        self.play(FadeIn(more[0], shift=RIGHT * 0.3 * S), run_time=0.5)
        self.play(FadeIn(more[1], shift=RIGHT * 0.3 * S), run_time=0.5)

        # ===== 5. the ESP32 binds the same way =====
        txh2 = F(label("ESP32", 28, BLUE_A).move_to([TX_X, 2.6, 0]))
        with self.voiceover(text="The <bookmark mark='a'/>ESP32 binds the same way, with <bookmark mark='b'/>its own ID.") as tr:
            self.play(FadeOut(cap4), run_time=0.3)
            self.wait_until_bookmark("a")
            self.play(ReplacementTransform(txh, txh2), run_time=0.6)
            self.wait_until_bookmark("b")
            self.play(txid[0].animate.set_fill(YELLOW_A).set_stroke(YELLOW_A), run_time=0.5)
            self.play(dr_id[0].animate.set_fill(YELLOW_A).set_stroke(YELLOW_A), run_time=0.5)
            self.wait_for_voiceover()
        txh = txh2

        # ===== 6. only that ID; back to the plot =====
        cap6 = self.cap("other IDs are ignored")

        def chip_block(color):
            return F(VGroup(packet_block(1.0, BLUE_A), Square(0.14, stroke_width=0, fill_color=color, fill_opacity=1)))

        red = chip_block(RED_A).move_to(P(-2.3, LANE_Y))
        yel = chip_block(YELLOW_A).move_to(P(-2.3, LANE_Y))
        cross = F(Tex(r"$\times$", font_size=40, color=RED_A).move_to([3.05, LANE_Y + 0.4, 0]))
        tick = F(Tex(r"\checkmark", font_size=40, color=GREEN_A).move_to([3.75, LANE_Y + 0.4, 0]))
        self._arrows, self._ticks = [], []
        barg = VGroup(g.bar, g.rx, g.tx)
        with self.voiceover(text="From then on the drone <bookmark mark='a'/>only listens to <bookmark mark='b'/>that ID, "
                                 "and <bookmark mark='c'/>it knows <bookmark mark='d'/>which radio channel comes next.") as tr:
            flow.spawn = False
            self.add(red)
            self.wait_until_bookmark("a")
            # caption in, then out again at the end of 'only listens to that ID' (0.4 s fade)
            self.play(Succession(FadeIn(cap6, run_time=0.3), Wait(0.1), FadeOut(cap6, run_time=0.4)),
                      red.animate.move_to(P(3.0, LANE_Y)), run_time=0.8, rate_func=linear)
            self.play(FadeIn(cross), run_time=0.15)
            self.add(yel)
            self.play(FadeOut(red), FadeOut(cross), yel.animate.move_to(P(3.8, LANE_Y)), run_time=0.6, rate_func=linear)
            self.play(FadeIn(tick), run_time=0.3)
            self.wait_until_bookmark("c")
            a.set_value(0.0)
            self.add(g)
            boxes_all = [txb, drb, txh, drh, txid, dr_id, bar, rc0, bm, *txr, *dr_dash, *new_tx, tx_nums[6], *nums, *more, yel, tick]
            self.play(*[FadeOut(m) for m in boxes_all], flow.animate.set_opacity(0), a.animate.set_value(1.0), run_time=0.8)
            self.remove(flow)
            self.wait_until_bookmark("d")
            self._slot(g, barg, 13, tick=False)
            self._slot(g, barg, 14, tick=False)
            self.wait_for_voiceover()
        g.clear_updaters()

        # ===== 7. the timing comes from the packets =====
        cap7 = self.cap("each packet times the next hop")
        with self.voiceover(text="The <bookmark mark='a'/>timing it takes from the packets themselves.") as tr:
            self.play(FadeIn(cap7), FadeOut(g.pkts[13]), FadeOut(g.pkts[14]), *[FadeOut(x) for x in self._arrows],
                      barg.animate.shift(DOWN * (hp_y(HP_CH[15]) - hp_y(HP_CH[13]))), g.now.animate.set_x(13 * SLOT_W),
                      run_time=0.6)
            self._arrows = []
            self.wait_until_bookmark("a")
            self._slot(g, barg, 13, tick=True)
            self._slot(g, barg, 14, tick=True)
            self.wait_for_voiceover()

        # ===== 8. a steady stream of packets =====
        row_y = HP_CAM[0][1]
        row_x = lambda s: hp_x(s)
        extra = [packet_block().move_to([row_x(s), row_y, 0]) for s in list(range(-14, 0)) + list(range(15, 30))]
        pk = g.pkts[:15]
        gone = [g.axes, g.bar, g.rx, g.tx, g.now, *g.arrows[:12], *self._arrows, *self._ticks]
        with self.voiceover(text="To the drone, <bookmark mark='a'/>this is a steady stream of packets.") as tr:
            self.play(FadeOut(cap7), *[FadeOut(m) for m in gone], run_time=0.4)
            self.remove(*gone)
            cap8 = caption_at(frame.copy().set(width=10).move_to([row_x(6), row_y, 0]), "a steady stream of packets", 32)
            self.play(*[p.animate.move_to([row_x(s), row_y, 0]) for s, p in enumerate(pk)],
                      frame.animate.set(width=10.0).move_to([row_x(6), row_y, 0]),
                      LaggedStart(*[FadeIn(e) for e in extra], lag_ratio=0.03),
                      Succession(Wait(0.5), FadeIn(cap8, run_time=0.5)), run_time=1.2)
            self.wait_for_voiceover()

        # ===== 9. ours =====
        ours = pk[0]
        cap9 = caption_at(frame.copy().set(width=STREAM_W).move_to(ours.get_center()), STREAM_CAP, 32)
        with self.voiceover(text="One of them is ours, <bookmark mark='a'/>carrying 1150.") as tr:
            self.play(FadeOut(cap8), frame.animate.set(width=STREAM_W).move_to(ours.get_center()),
                      *[p.animate.set_fill(opacity=DIM) for p in pk[1:] + extra],
                      Succession(Wait(0.9), FadeIn(cap9, run_time=0.5)), run_time=1.5, rate_func=smooth)
            self.wait_for_voiceover()
        self.wait(0.5)
        # pin the end frame exactly on the seam

    # one slot of the hop plot: the packet lands on the waiting bar, then the bar retunes for the next one
    def _slot(self, g, barg, s, tick):
        pkt = g.pkts[s]
        arr = g.arrows[s - 1]
        self._arrows.append(arr)
        self.play(FadeIn(pkt), FadeIn(arr), run_time=0.25)
        if tick:
            x = pkt.get_left()[0]
            tk = Line([x, pkt.get_center()[1] - 0.1, 0], [x, -1.0, 0], stroke_color=MUTED, stroke_width=SW_THIN * HP_K)
            self._ticks.append(tk)
            self.play(Create(tk), run_time=0.25, rate_func=linear)
        dy = hp_y(HP_CH[s + 1]) - hp_y(HP_CH[s])
        self.play(barg.animate.shift(UP * dy), g.now.animate.shift(RIGHT * SLOT_W), run_time=0.45)

