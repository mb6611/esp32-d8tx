// Tooltips for jargon: any element with a `data-tip` attribute (or inside one, e.g. a
// <select> in a <label data-tip>) gets one shared role="tooltip" bubble.
// WAI-ARIA APG tooltip pattern + WCAG 1.4.13: shows on hover after a short delay and
// at once-ish on keyboard focus, closes on Escape, blur and pointer leave; the pointer
// may move onto the bubble without it closing. Triggers point at it with
// aria-describedby while it is theirs. Positioning is @floating-ui/dom.
// Content can change while open (hit-map cells): call refreshTip(el) after editing data-tip.
import { autoUpdate, computePosition, flip, offset, shift } from "@floating-ui/dom";

const DELAY_MS = 300;   // hover delay (shadcn / Radix default is close to this)
const SKIP_MS = 300;    // moving to another trigger within this after a close: no delay
const GRACE_MS = 100;   // pointer may cross from trigger to bubble

const tip = document.createElement("div");
tip.id = "tip";
tip.className = "tip";
tip.setAttribute("role", "tooltip");
tip.hidden = true;
document.body.appendChild(tip);

let owner: HTMLElement | null = null;   // trigger the bubble belongs to (shown or pending)
let muted: HTMLElement | null = null;   // closed with Escape: stays closed until left
let showT = 0, hideT = 0, lastHide = 0;
let stopAuto: (() => void) | null = null;

const triggerOf = (t: EventTarget | null) =>
  t instanceof Element ? (t.closest("[data-tip]") as HTMLElement | null) : null;
/** The element that takes focus for a trigger: the control inside a <label data-tip>, else itself. */
const described = (el: HTMLElement) =>
  (el.tagName === "LABEL" && el.querySelector<HTMLElement>("input, select, button")) || el;

function place() {
  if (!owner) return;
  computePosition(owner, tip, {
    placement: "top", strategy: "fixed",
    middleware: [offset(6), flip(), shift({ padding: 6 })],
  }).then(({ x, y }) => { tip.style.left = `${x}px`; tip.style.top = `${y}px`; });
}

function open(el: HTMLElement, delay: number) {
  clearTimeout(hideT);
  if (owner === el && !tip.hidden) return;
  if (owner && owner !== el) close(false);
  owner = el;
  tip.textContent = el.dataset.tip ?? "";
  described(el).setAttribute("aria-describedby", tip.id);
  clearTimeout(showT);
  const show = () => {
    if (owner !== el) return;
    tip.hidden = false;
    stopAuto = autoUpdate(el, tip, place);
  };
  if (delay <= 0 || performance.now() - lastHide < SKIP_MS) show();
  else showT = window.setTimeout(show, delay);
}

function close(stamp = true) {
  clearTimeout(showT); clearTimeout(hideT);
  if (!owner) return;
  if (!tip.hidden && stamp) lastHide = performance.now();
  described(owner).removeAttribute("aria-describedby");
  owner = null;
  tip.hidden = true;
  stopAuto?.(); stopAuto = null;
}

/** Re-read data-tip of `el` if the bubble is currently its. */
export function refreshTip(el: HTMLElement) {
  if (owner !== el) return;
  const t = el.dataset.tip ?? "";
  if (tip.textContent !== t) { tip.textContent = t; place(); }
}

document.addEventListener("pointerover", (e) => {
  if (e.pointerType === "touch") return;
  if (tip.contains(e.target as Node)) { clearTimeout(hideT); return; }
  const el = triggerOf(e.target);
  if (el && el !== muted) open(el, DELAY_MS);
});
document.addEventListener("pointerout", (e) => {
  const from = triggerOf(e.target) ?? (tip.contains(e.target as Node) ? owner : null);
  if (!from) return;
  const to = e.relatedTarget as Node | null;
  if (to && (from.contains(to) || tip.contains(to))) return;
  if (from === muted) muted = null;
  if (from === owner && !from.contains(document.activeElement)) {
    clearTimeout(hideT);
    hideT = window.setTimeout(() => close(), GRACE_MS);
  }
});
// a click opens a native <select> list or toggles a control: get out of the way
document.addEventListener("pointerdown", () => { if (owner) { muted = owner; close(false); } });
document.addEventListener("focusin", (e) => {
  const el = triggerOf(e.target);
  if (el && el !== muted && (e.target as HTMLElement).matches(":focus-visible")) open(el, DELAY_MS / 3);
});
document.addEventListener("focusout", (e) => {
  const el = triggerOf(e.target);
  if (el === muted) muted = null;
  if (el && el === owner) close();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && owner) { muted = owner; close(false); }
});
