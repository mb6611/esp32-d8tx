// The 20 s channel plot: one line per channel, newest on the right.
import { fit, px } from "./canvas";
import { frac } from "./channels";
import { T, font } from "./tokens";

export const PLOT_S = 20;

/** Ring of (wall-clock ms, channels) samples; trimmed from the front in O(1). */
export class History {
  w: number[] = [];
  ch: number[][] = [];
  private head = 0;
  push(w: number, ch: number[]) {
    this.w.push(w); this.ch.push(ch);
    while (this.head < this.w.length && w - this.w[this.head] > PLOT_S * 1000) this.head++;
    if (this.head > 4096) { this.w = this.w.slice(this.head); this.ch = this.ch.slice(this.head); this.head = 0; }
  }
  get start() { return this.head; }
}

export function drawPlot(c: HTMLCanvasElement, h: History, now: number) {
  const { g, W, H } = fit(c);
  g.clearRect(0, 0, W, H);
  const top = 8, bot = H - 20, left = 40;
  const yOf = (us: number) => bot - frac(us) * (bot - top);
  const xOf = (w: number) => W - ((now - w) / (PLOT_S * 1000)) * (W - left);

  g.lineWidth = 1; g.strokeStyle = T.grid; g.fillStyle = T.muted;
  g.font = font(11, "mono"); g.textBaseline = "middle"; g.textAlign = "right";
  g.beginPath();
  for (const us of [1000, 1500, 2000]) {
    const y = px(yOf(us));
    g.moveTo(left, y); g.lineTo(W, y);
    g.fillText(String(us), left - 6, y);
  }
  g.textAlign = "center"; g.textBaseline = "alphabetic";
  for (let s = 0; s <= PLOT_S; s += 5) {
    const x = px(W - (s / PLOT_S) * (W - left));
    g.moveTo(x, top); g.lineTo(x, bot);
    g.fillText(s ? `−${s} s` : "now", Math.min(Math.max(x, left + 14), W - 14), H - 4);
  }
  g.stroke();

  g.lineWidth = 1.5; g.lineJoin = "round";
  for (let i = 0; i < 8; i++) {
    g.strokeStyle = T.ch[i]; g.beginPath();
    for (let k = h.start; k < h.w.length; k++) {
      const x = xOf(h.w[k]), y = yOf(h.ch[k][i]);
      if (k === h.start) g.moveTo(x, y); else g.lineTo(x, y);
    }
    g.stroke();
  }
}
