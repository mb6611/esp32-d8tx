// Eight horizontal channel bars, filled from the 1500 µs centre. Updated from
// requestAnimationFrame only, with transforms, so ~108 packets/s cost no layout.
import { frac, MID } from "./channels";

export class Bars {
  private fills: HTMLElement[] = [];
  private vals: HTMLElement[] = [];
  private shown: number[] = [];

  constructor(private root: HTMLElement) {
    for (let i = 0; i < 8; i++) {
      const row = document.createElement("div");
      row.className = "grid grid-cols-[2.5rem_1fr_4.5rem] items-center gap-3";
      row.innerHTML =
        `<span class="font-sans text-sm text-muted">ch${i + 1}</span>` +
        `<div class="relative h-4 overflow-hidden rounded-sm border border-line bg-paper-2">` +
        `<div class="fill absolute inset-0 origin-left will-change-transform" style="background:var(--color-ch${i + 1});transform:scaleX(0)"></div>` +
        `<div class="absolute -inset-y-px left-1/2 w-px bg-muted/50"></div></div>` +
        `<span class="text-right font-mono text-sm tabular-nums">–</span>`;
      root.appendChild(row);
      this.fills.push(row.querySelector(".fill")!);
      this.vals.push(row.lastElementChild as HTMLElement);
    }
  }

  /** Call once per animation frame with the latest channels (or null). */
  update(ch: number[] | null, stale: boolean) {
    this.root.classList.toggle("opacity-50", stale);
    if (!ch) return;
    const m = frac(MID);
    for (let i = 0; i < 8; i++) {
      if (this.shown[i] === ch[i]) continue;
      this.shown[i] = ch[i];
      const f = frac(ch[i]);
      this.fills[i].style.transform = `translateX(${Math.min(f, m) * 100}%) scaleX(${Math.abs(f - m)})`;
      this.vals[i].textContent = `${ch[i].toFixed(0)} µs`;
    }
  }
}
