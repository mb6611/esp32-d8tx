// Shared canvas helpers: sharp drawing on HiDPI screens, sized from CSS.

/** Match the backing store to the CSS size × devicePixelRatio and return a
 *  context in CSS pixels. Cheap when nothing changed (two reads, no writes). */
export function fit(c: HTMLCanvasElement): { g: CanvasRenderingContext2D; W: number; H: number } {
  const g = c.getContext("2d")!;
  const dpr = window.devicePixelRatio || 1;
  const W = c.clientWidth, H = c.clientHeight;
  const bw = Math.round(W * dpr), bh = Math.round(H * dpr);
  if (c.width !== bw || c.height !== bh) { c.width = bw; c.height = bh; }
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { g, W, H };
}

/** Crisp 1 px line at a CSS-pixel coordinate. */
export const px = (v: number) => Math.round(v) + 0.5;
