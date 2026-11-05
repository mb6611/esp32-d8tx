// Hop-follow slot hit map: one cell per hop slot (47 for D8), coloured by the
// share of locked segments on that slot that gave a CRC-valid packet.
// Fed from stats.follow.slot_ok / slot_hops / slot_mhz (host/esp32sdr/d8follow.py).
// Self-mounting: appends itself to the #follow bar on first use.
// Cells carry their numbers in a tooltip (src/tooltip.ts); the grid is one tab stop,
// arrow keys move between cells.
import "./hitmap.css";
import { refreshTip } from "./tooltip";

export interface SlotStats { slot_ok?: number[]; slot_hops?: number[]; slot_mhz?: number[] }

const COLS = 12;
let root: HTMLElement | null = null;
let cells: HTMLElement[] = [];

function mount(n: number): HTMLElement[] {
  if (!root) {
    root = document.createElement("div");
    root.className = "hitmap";
    root.innerHTML = `<span class="hitmap-label">Good packets per hop slot, in hop order ` +
      `<span class="hitmap-key">red ≤ 50 % · amber 75 % · green 100 % · outlined = not visited yet</span></span>` +
      `<div class="hitmap-grid" role="group" aria-label="hit rate per hop slot"></div>`;
    (document.getElementById("follow") ?? document.body).appendChild(root);
    root.querySelector(".hitmap-grid")!.addEventListener("keydown", (e) => {
      const k = (e as KeyboardEvent).key;
      const d = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -COLS, ArrowDown: COLS, Home: -1e3, End: 1e3 }[k];
      const i = cells.indexOf(document.activeElement as HTMLElement);
      if (d == null || i < 0) return;
      e.preventDefault();
      const j = Math.max(0, Math.min(cells.length - 1, i + d));
      cells[i].tabIndex = -1;
      cells[j].tabIndex = 0;
      cells[j].focus();
    });
  }
  const grid = root.querySelector(".hitmap-grid")!;
  if (cells.length !== n) {
    grid.innerHTML = "";
    cells = Array.from({ length: n }, (_, i) => {
      const c = grid.appendChild(document.createElement("i"));
      c.tabIndex = i ? -1 : 0;
      c.setAttribute("role", "img");
      c.setAttribute("aria-label", `slot ${i}`);
      return c;
    });
  }
  return cells;
}

/** Colour for a hit fraction: red (≤ 50 %) → amber (75 %) → green (100 %). */
function colour(p: number): string {
  const hue = Math.round(120 * Math.max(0, Math.min(1, (p - 0.5) / 0.5)));
  return `hsl(${hue}, 65%, 42%)`;
}

export function renderHitmap(follow: object | undefined) {
  const f = follow as SlotStats | undefined;
  const ok = f?.slot_ok, hops = f?.slot_hops;
  if (!ok || !hops) return;
  const cs = mount(hops.length);
  hops.forEach((h, i) => {
    const c = cs[i], o = ok[i] ?? 0;
    const mhz = f!.slot_mhz?.[i];
    const t = `slot ${i}${mhz ? `, ${mhz.toFixed(3)} MHz` : ""}: ` +
      (h ? `${o} good of ${h} visits (${((100 * o) / h).toFixed(1)} %)` : "not visited yet");
    if (c.dataset.tip !== t) { c.dataset.tip = t; refreshTip(c); }
    c.style.background = h ? colour(o / h) : "";
    c.classList.toggle("empty", !h);
  });
}
