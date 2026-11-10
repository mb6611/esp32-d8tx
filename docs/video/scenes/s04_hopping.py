"""S04, stage 6: opens on the packet block S03 ended on (the wave became the packet there); the map marker leaves the ESP32 for the air; the packet sits in one hop slot -> the next packet lands on another
channel about 9 ms later (camera follows) -> pull-back: 47 channels x 16 slots, the hop pattern and its path ->
the packets drop into one row in time order (the stream, running off both edges) -> zoom into our packet (carry-over for S05).
Facts: 47 hop channels (packet.h D8_HOP_CHANNELS); table entry i = (start + step*i) mod 256 with the E8 identity
start 2, step 55 (packet.c d8_hop_table, protocol/PROTOCOL.md); one packet per 8.994 ms slot, 6.70 ms on air
(experiments/05, 06); channel n = 2404.000 MHz + n x 299.93 kHz (packet.c d8_channel_f10) - not shown; retune
takes at most 0.39 ms (experiments/07) - not shown. Slots 0..15 here use table entries 1..16."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from parts import *

NSLOT = 16
ENTRY0 = 1
GW, GH = NSLOT * SLOT_W, 47 * LANE_H


def cell_at(slot):
    return grid_pos(slot, TABLE[ENTRY0 + slot])


def patch(slot, ns=1, nl=2):
    """The grid near one cell only (slots slot-ns..slot+ns, lanes +-nl), so the close view stays inside the frame."""
    p = cell_at(slot)
    li = LANES.index(TABLE[ENTRY0 + slot])
    x0, x1 = (slot - ns) * SLOT_W, (slot + ns + 1) * SLOT_W
    y0, y1 = (li - nl) * LANE_H, (li + nl + 1) * LANE_H
    g = VGroup(*[Line([x0, (li + j) * LANE_H, 0], [x1, (li + j) * LANE_H, 0], stroke_color=GRID, stroke_width=SW_THIN,
                      stroke_opacity=0.6) for j in range(-nl, nl + 2)],
               *[Line([(slot + j) * SLOT_W, y0, 0], [(slot + j) * SLOT_W, y1, 0], stroke_color=GRID, stroke_width=SW_THIN,
                      stroke_opacity=0.5) for j in range(-ns, ns + 2)])
    return g


class S04(MovingCameraScene):
    def cap(self, text, size=32):
        return caption_at(self.camera.frame, text, size)

    def construct(self):
        frame = self.camera.frame
        k = CLOSE_W / FW
        p0 = cell_at(0)
        frame.set(width=CLOSE_W).move_to(p0)
        strip = MapStrip(K_ESP, lambda: (frame.get_center(), frame.width))
        self.add(strip)
        blk = packet_block().move_to(p0)   # S03's last frame: packet_block_big() centred, seen through the close camera
        self.add(blk)
        self.wait(0.3)

        # ---- out of the antenna, into the air (map strip) ----
        c = self.cap("out of the antenna, into the air")
        self.play(strip.open(), run_time=0.6)
        self.play(strip.go(K_AIR), FadeIn(c), run_time=1.2, rate_func=linear)
        self.wait(0.2)
        self.play(strip.close(), FadeOut(c), run_time=0.6)

        # ---- the grid (faint) and the packet in its cell ----
        lanes = VGroup(*[Line([0, i * LANE_H, 0], [GW, i * LANE_H, 0], stroke_color=GRID, stroke_width=SW_THIN, stroke_opacity=0.5)
                         for i in range(48)])
        ticks = VGroup(*[Line([s * SLOT_W, 0, 0], [s * SLOT_W, GH, 0], stroke_color=GRID, stroke_width=SW_THIN, stroke_opacity=0.4)
                         for s in range(NSLOT + 1)])
        local = patch(0)
        lab_t = label("time", 22).scale(k).next_to(local, DOWN, buff=0.1 * k)
        lab_t_arrow = Arrow(lab_t.get_right(), lab_t.get_right() + RIGHT * 0.6 * k, buff=0.1 * k, color=MUTED, stroke_width=SW, max_tip_length_to_length_ratio=0.3)
        lab_c = label("channel", 22).scale(k).rotate(90 * DEGREES).next_to(local, LEFT, buff=0.12 * k)
        lab_c.shift(DOWN * 0.3 * k)
        lab_c_arrow = Arrow(lab_c.get_top(), lab_c.get_top() + UP * 0.6 * k, buff=0.1 * k, color=MUTED, stroke_width=SW, max_tip_length_to_length_ratio=0.3)
        pl = label("packet", 20, YELLOW_A).scale(k).next_to(blk, UP, buff=0.12 * k)
        self.play(FadeIn(local), run_time=1.0)
        self.play(FadeIn(pl), FadeIn(lab_t), Create(lab_t_arrow), FadeIn(lab_c), Create(lab_c_arrow), run_time=0.8)
        self.wait(0.6)

        # Both ends follow the sequence agreed during bind (experiments/15).
        tx = label("TX", 20, BLUE_A).scale(k).next_to(blk, LEFT, buff=0.12 * k)
        rx = label("RX", 20, GREEN_A).scale(k).next_to(blk, RIGHT, buff=0.12 * k)
        agreement = self.cap("hop order agreed at bind: where and when")
        self.play(FadeIn(tx), FadeIn(rx), FadeIn(agreement), run_time=0.7)
        self.wait(1.0)
        self.play(FadeOut(agreement), run_time=0.2)

        # ---- hop: both markers land on the same next cell together ----
        blocks = [blk]
        c = self.cap("next packet: new channel, about 9 ms later")
        p1 = cell_at(1)
        b1 = packet_block().move_to(p1)
        self.play(FadeOut(pl), FadeOut(lab_t), FadeOut(lab_t_arrow), FadeOut(lab_c), FadeOut(lab_c_arrow), run_time=0.3)
        self.play(TransformFromCopy(blk, b1, path_arc=-70 * DEGREES), Transform(local, patch(1)), frame.animate.move_to(p1), tx.animate.shift(p1 - p0), rx.animate.shift(p1 - p0),
                  run_time=1.5)
        blocks.append(b1)
        c = self.cap("next packet: new channel, about 9 ms later")
        self.play(FadeIn(c), run_time=0.4)
        self.wait(1.0)
        b2 = packet_block().move_to(cell_at(2))
        self.play(TransformFromCopy(b1, b2, path_arc=-70 * DEGREES), Transform(local, patch(2)), frame.animate.move_to(cell_at(2)), tx.animate.shift(cell_at(2) - p1), rx.animate.shift(cell_at(2) - p1), FadeOut(c), run_time=1.0)
        blocks.append(b2)
        self.wait(0.2)

        # ---- pull-back 5: 47 channels, the pattern ----
        rest = [packet_block().move_to(cell_at(s)) for s in range(3, NSLOT)]
        arrows = VGroup(*[Arrow(cell_at(i), cell_at(i + 1), buff=0.16,
                                color=YELLOW_A, stroke_width=SW,
                                max_tip_length_to_length_ratio=0.15)
                          for i in range(NSLOT - 1)])
        gc = np.array([GW / 2, GH / 2, 0])
        border = Rectangle(width=GW, height=GH, stroke_color=STRUCT, stroke_width=SW).move_to(gc)
        brace = Brace(Line([0, 0, 0], [0, GH, 0]), LEFT, buff=0.3, color=MUTED, sharpness=1.0)
        btxt = label("47 channels", 24).scale(1.8).rotate(90 * DEGREES).next_to(brace, LEFT, buff=0.2)
        self.play(frame.animate.set(width=32).move_to(gc + LEFT * 0.5 + UP * 0.5), FadeIn(border), FadeIn(lanes), FadeIn(ticks), FadeOut(local), FadeOut(tx), FadeOut(rx), run_time=2.0, rate_func=smooth)
        self.play(LaggedStart(*[FadeIn(b, scale=2.0) for b in rest], lag_ratio=0.15),
                  LaggedStart(*[GrowArrow(a) for a in arrows], lag_ratio=0.12), run_time=2.0)
        blocks += rest
        c = self.cap("47 channels, one hop every 9 ms")
        self.play(GrowFromCenter(brace), FadeIn(btxt), FadeIn(c), run_time=0.8)
        self.wait(1.2)

        # Narrow filtering rejects off-channel interference (experiments/04, 06).
        # A single persistently noisy lane affects one of the 47 hops, not the link.
        lane_y = cell_at(6)[1]
        noise = Line([0, lane_y, 0], [GW, lane_y, 0], color=RED_A, stroke_width=8, stroke_opacity=0.6)
        bad = Cross(blocks[6], stroke_color=RED_A, stroke_width=4).scale(1.7)
        c2 = self.cap("the receiver listens to one narrow channel")
        self.play(FadeOut(c), run_time=0.2)
        self.play(FadeIn(c2), run_time=0.5)
        self.wait(1.0)
        cnoise = self.cap("less noise and interference; one lane is noisy")
        self.play(FadeOut(c2), run_time=0.2)
        self.play(FadeIn(cnoise), Create(noise), run_time=0.5)
        self.wait(1.0)
        c2 = cnoise
        c3 = self.cap("one in 47 packets lost, link continues")
        self.play(FadeOut(c2), run_time=0.2)
        self.play(FadeIn(c3), Create(bad), blocks[6].animate.set_opacity(DIM), run_time=0.8)
        self.wait(1.0)

        # The hops drop out of their channels into one row in time order: the stream, running off both edges.
        row_y = gc[1]
        row_x = lambda s: (s + 0.5) * SLOT_W
        extra = [packet_block().move_to([row_x(s), row_y, 0]) for s in list(range(-14, 0)) + list(range(NSLOT, NSLOT + 14))]
        row_c = np.array([row_x(4), row_y, 0])
        self.play(FadeOut(c3), FadeOut(brace), FadeOut(btxt), FadeOut(arrows),
                  FadeOut(border), FadeOut(noise), FadeOut(bad), FadeOut(lanes), FadeOut(ticks),
                  *[b.animate.move_to([row_x(s), row_y, 0]).set_fill(opacity=0.9) for s, b in enumerate(blocks)],
                  frame.animate.set(width=10.0).move_to(row_c), run_time=1.8)
        self.play(LaggedStart(*[FadeIn(e) for e in extra], lag_ratio=0.03), run_time=0.6)
        c4 = self.cap("continuous stream of packets")
        self.play(FadeIn(c4), run_time=0.5)
        self.wait(1.2)

        # Zoom into our packet (the first one, the wave that carried 1150): exact shared S05 carry-over frame.
        ours = blocks[0]
        self.play(FadeOut(c4), run_time=0.2)
        self.play(frame.animate.set(width=STREAM_W).move_to(ours.get_center()),
                  *[b.animate.set_fill(opacity=DIM) for b in blocks[1:] + extra], run_time=1.8, rate_func=smooth)
        c5 = self.cap(STREAM_CAP)
        self.play(FadeIn(c5), run_time=0.5)
        self.wait(0.8)
