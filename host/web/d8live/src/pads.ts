// Stick pads: a top-down view of a gimbal, the knob easing toward the last
// decoded position so sparse updates still read as motion.
import { fit, px } from "./canvas";
import { frac } from "./channels";
import { T, font } from "./tokens";

const pos: Record<string, { x: number; y: number }> = {};

export function drawPad(c: HTMLCanvasElement, xus: number | null, yus: number | null) {
  const { g, W, H } = fit(c);
  const cx = W / 2, cy = H / 2, R = Math.min(W, H) / 2 - 22;
  g.clearRect(0, 0, W, H);

  // travel square and centre cross
  g.lineWidth = 1;
  g.strokeStyle = T.line;
  g.strokeRect(px(cx - R), px(cy - R), Math.round(2 * R), Math.round(2 * R));
  g.strokeStyle = T.grid;
  g.beginPath();
  g.moveTo(px(cx), cy - R); g.lineTo(px(cx), cy + R);
  g.moveTo(cx - R, px(cy)); g.lineTo(cx + R, px(cy));
  g.stroke();
  // gimbal base
  g.strokeStyle = T.line;
  g.beginPath(); g.arc(cx, cy, 26, 0, 2 * Math.PI); g.stroke();

  if (xus == null || yus == null) return;
  const tx = cx + (frac(xus) * 2 - 1) * R, ty = cy - (frac(yus) * 2 - 1) * R;
  const p = (pos[c.id] ??= { x: tx, y: ty });
  p.x += (tx - p.x) * 0.25; p.y += (ty - p.y) * 0.25;

  // shaft
  g.strokeStyle = T.muted; g.lineWidth = 3; g.lineCap = "round";
  g.beginPath(); g.moveTo(cx, cy); g.lineTo(p.x, p.y); g.stroke();
  // knob
  g.lineWidth = 1;
  g.fillStyle = T.link;
  g.beginPath(); g.arc(p.x, p.y, 11, 0, 2 * Math.PI); g.fill();

  g.fillStyle = T.muted; g.font = font(11, "mono");
  g.textBaseline = "alphabetic";
  g.fillText(`${xus.toFixed(0)}, ${yus.toFixed(0)} µs`, cx - R, H - 6);
}
