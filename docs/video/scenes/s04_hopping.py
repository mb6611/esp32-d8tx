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


class S04(Narrated, MovingCameraScene):
    def cap(self, text, size=32):
        return caption_at(self.camera.frame, text, size)

    def say(self, text):
        print(f"VO t={self.renderer.time:.2f} {text}", flush=True)
        return self.voiceover(text=text)

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
        with self.say("The burst leaves the ESP32's antenna."):
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
        lab_c = label("frequency", 22).scale(k).rotate(90 * DEGREES).next_to(local, LEFT, buff=0.12 * k)
        lab_c.shift(DOWN * 0.3 * k)
        lab_c_arrow = Arrow(lab_c.get_top(), lab_c.get_top() + UP * 0.6 * k, buff=0.1 * k, color=MUTED, stroke_width=SW, max_tip_length_to_length_ratio=0.3)
        tgrp, cgrp = VGroup(lab_t, lab_t_arrow), VGroup(lab_c, lab_c_arrow)
        for g in (lab_t, lab_t_arrow, lab_c, lab_c_arrow):   # the axis labels ride along with the local grid through the hops
            off = g.get_center() - local.get_center()
            g.add_updater(lambda m, off=off: m.move_to(local.get_center() + off))
        pl = label("packet", 20, YELLOW_A).scale(k).next_to(blk, UP, buff=0.12 * k)
        with self.say("The next packet doesn't go out on the same channel;"):
            self.play(FadeIn(local), run_time=1.0)
            self.play(FadeIn(pl), FadeIn(lab_t), Create(lab_t_arrow), FadeIn(lab_c), Create(lab_c_arrow), run_time=0.8)
            self.play(Indicate(pl, scale_factor=1.2), run_time=1.0)

        # ---- hop: the next packet lands on a new channel ----
        blocks = [blk]
        p1 = cell_at(1)
        b1 = packet_block().move_to(p1)
        with self.say("it goes out on a different one, about 9 ms later."):
            c = self.cap("next packet: new channel, about 9 ms later")
            self.play(FadeOut(pl), run_time=0.3)
            self.play(TransformFromCopy(blk, b1, path_arc=-70 * DEGREES), Transform(local, patch(1)), frame.animate.move_to(p1),
                      run_time=1.5)
            blocks.append(b1)
            self.play(FadeIn(c), run_time=0.4)

        # Both ends follow the sequence agreed during bind (experiments/15).
        tx = label("TX", 20, BLUE_A).scale(k).next_to(b1, LEFT, buff=0.12 * k)
        rx = label("RX", 20, GREEN_A).scale(k).next_to(b1, RIGHT, buff=0.12 * k)
        tx.set_z_index(5)
        rx.set_z_index(5)
        agreement = self.cap("hop order agreed at bind: where and when")
        with self.say("The transmitter and the drone agreed on the order when they were bound,"):
            self.play(FadeOut(c), run_time=0.2)
            self.play(FadeIn(tx), FadeIn(rx), FadeIn(agreement), run_time=0.7)
            self.play(Indicate(tx, scale_factor=1.3), Indicate(rx, scale_factor=1.3), run_time=1.0)

        p2 = cell_at(2)
        b2 = packet_block().move_to(p2)
        with self.say("so both know where the next packet will be and when."):
            self.play(TransformFromCopy(b1, b2, path_arc=-70 * DEGREES), Transform(local, patch(2)), frame.animate.move_to(p2),
                      tx.animate.shift(p2 - p1), rx.animate.shift(p2 - p1), run_time=1.0)
            blocks.append(b2)
            self.play(Indicate(tx, scale_factor=1.3), Indicate(rx, scale_factor=1.3), run_time=1.0)
        self.play(FadeOut(agreement), run_time=0.2)

        # ---- the receiver listens to one narrow channel; it retunes after every packet ----
        c2 = self.cap("one channel = a narrow band of frequencies")
        with self.say("That matters because the drone's radio can only listen to one narrow channel at a time."):
            self.play(FadeIn(c2), run_time=0.4)
            # the listening window: narrow in frequency (one lane high), closing in vertically from several lanes
            win = Rectangle(width=3 * SLOT_W, height=5 * LANE_H, stroke_color=GREEN_A, stroke_width=SW,
                            fill_color=GREEN_A, fill_opacity=0.08).move_to(p2)
            self.play(Indicate(rx, scale_factor=1.4), FadeIn(win), run_time=0.8)
            self.play(win.animate.stretch_to_fit_height(LANE_H).set_fill(opacity=0.2), run_time=1.0, rate_func=smooth)
            self.play(win.animate.set_fill(opacity=0.45), run_time=0.6, rate_func=smooth)
            self.play(win.animate.set_fill(opacity=0.2), run_time=0.6, rate_func=smooth)
            self.play(Indicate(rx, scale_factor=1.4), run_time=0.8)

        prev = p2
        with self.say("After every packet it retunes to the next channel on the list, in step with the transmitter."):
            c6 = self.cap("after every packet, the receiver retunes too")
            c6.add_updater(lambda m: m.move_to(frame.get_center() + DOWN * (frame.height / 2 - 0.6 * frame.width / FW)))
            self.play(FadeOut(c2), FadeIn(c6), run_time=0.3)
            for s in (3, 4):
                ps = cell_at(s)
                bs = packet_block().move_to(ps)
                self.play(TransformFromCopy(blocks[-1], bs, path_arc=-70 * DEGREES), Transform(local, patch(s)), frame.animate.move_to(ps),
                          tx.animate.shift(ps - prev), rx.animate.shift(ps - prev), win.animate.move_to(ps), run_time=1.0)
                blocks.append(bs)
                prev = ps
                self.play(Indicate(rx, scale_factor=1.3), Indicate(tx, scale_factor=1.3),
                          win.animate(rate_func=there_and_back).set_fill(opacity=0.5), run_time=0.9)

        # ---- pull-back 5: 47 channels, the pattern ----
        rest = [packet_block().move_to(cell_at(s)) for s in range(5, NSLOT)]
        arrows = VGroup(*[Arrow(cell_at(i), cell_at(i + 1), buff=0.16,
                                color=YELLOW_A, stroke_width=SW,
                                max_tip_length_to_length_ratio=0.15)
                          for i in range(NSLOT - 1)])
        gc = np.array([GW / 2, GH / 2, 0])
        border = Rectangle(width=GW, height=GH, stroke_color=STRUCT, stroke_width=SW).move_to(gc)
        brace = Brace(Line([0, 0, 0], [0, GH, 0]), LEFT, buff=0.3, color=MUTED, sharpness=1.0)
        with self.say("D 8 hops across 47 channels."):
            c6.clear_updaters()
            self.play(frame.animate.set(width=32).move_to(gc + LEFT * 0.5 + DOWN * 0.5),
                      FadeOut(local), FadeOut(tx), FadeOut(rx), FadeOut(win), FadeOut(tgrp), FadeOut(cgrp), FadeOut(c6),
                      run_time=1.5, rate_func=smooth)
            for g in (lab_t, lab_t_arrow, lab_c, lab_c_arrow):
                g.clear_updaters()
            btxt = label("47 channels", 24).scale(2.6).rotate(90 * DEGREES).next_to(brace, LEFT, buff=0.2)
            ax_t = VGroup(label("time", 24).scale(2.6), Arrow(ORIGIN, RIGHT * 2.4, buff=0, color=MUTED, stroke_width=4.5, max_tip_length_to_length_ratio=0.25))
            ax_t.arrange(RIGHT, buff=0.3).next_to(border, DOWN, buff=0.3)
            ax_f = VGroup(label("frequency", 24).scale(2.6).rotate(90 * DEGREES), Arrow(ORIGIN, UP * 2.4, buff=0, color=MUTED, stroke_width=4.5, max_tip_length_to_length_ratio=0.25))
            ax_f.arrange(UP, buff=0.3).next_to(btxt, LEFT, buff=0.3).align_to(border, DOWN)
            c = self.cap("47 channels, one hop every 9 ms")
            self.play(FadeIn(border), FadeIn(lanes), FadeIn(ticks), GrowFromCenter(brace), FadeIn(btxt), FadeIn(c), FadeIn(ax_t), FadeIn(ax_f), run_time=0.7)

        # Narrow filtering rejects off-channel interference (experiments/04, 06).
        # A single persistently noisy lane affects one of the 47 hops, not the link.
        lane_y = cell_at(6)[1]
        noise = Line([0, lane_y, 0], [GW, lane_y, 0], color=RED_A, stroke_width=8, stroke_opacity=0.6)
        cnoise = self.cap("one noisy channel costs 1 packet in 47")
        with self.say("If one of them is noisy, say a Wi-Fi network sits on top of it,"):
            self.play(LaggedStart(*[FadeIn(b, scale=2.0) for b in rest], lag_ratio=0.15),
                      LaggedStart(*[GrowArrow(a) for a in arrows], lag_ratio=0.12), run_time=2.0)
            blocks += rest
            self.play(FadeOut(c), run_time=0.2)
            self.play(FadeIn(cnoise), Create(noise), run_time=0.5)
        bad = Cross(blocks[6], stroke_color=RED_A, stroke_width=4).scale(1.7)
        c3 = self.cap("one in 47 packets lost, link continues")
        with self.say("we lose one packet in every 47, and the link carries on."):
            self.play(FadeOut(cnoise), run_time=0.2)
            self.play(FadeIn(c3), Create(bad), blocks[6].animate.set_opacity(DIM), run_time=0.8)
            self.play(Indicate(brace, scale_factor=1.05), run_time=1.0)
            self.play(noise.animate.set_stroke(opacity=0.25), run_time=1.6, rate_func=smooth)

        # The hops drop out of their channels into one row in time order: the stream, running off both edges.
        row_y = gc[1]
        row_x = lambda s: (s + 0.5) * SLOT_W
        extra = [packet_block().move_to([row_x(s), row_y, 0]) for s in list(range(-14, 0)) + list(range(NSLOT, NSLOT + 14))]
        row_c = np.array([row_x(4), row_y, 0])
        with self.say("From the drone's side, this is just a steady stream of packets."):
            self.play(FadeOut(c3), FadeOut(brace), FadeOut(btxt), FadeOut(arrows), FadeOut(ax_t), FadeOut(ax_f),
                      FadeOut(border), FadeOut(noise), FadeOut(bad), FadeOut(lanes), FadeOut(ticks), run_time=0.4)
            self.play(*[b.animate.move_to([row_x(s), row_y, 0]).set_fill(opacity=0.9) for s, b in enumerate(blocks)],
                      run_time=0.8)
            self.play(frame.animate.set(width=10.0).move_to(row_c),
                      LaggedStart(*[FadeIn(e) for e in extra], lag_ratio=0.03), run_time=1.2)
            c4 = self.cap("continuous stream of packets")
            self.play(FadeIn(c4), run_time=0.5)

        # Zoom into our packet (the first one, the wave that carried 1150): exact shared S05 carry-over frame.
        ours = blocks[0]
        with self.say("One of them is ours, carrying eleven fifty."):
            self.play(FadeOut(c4), run_time=0.2)
            self.play(frame.animate.set(width=STREAM_W).move_to(ours.get_center()),
                      *[b.animate.set_fill(opacity=DIM) for b in blocks[1:] + extra], run_time=1.8, rate_func=smooth)
            c5 = self.cap(STREAM_CAP)
            self.play(FadeIn(c5), run_time=0.5)
        self.wait(0.7)
