// Dropdown select in the shadcn/ui "Select" look (new-york), black and white, no React.
// WAI-ARIA APG "select-only combobox": the trigger is a <button role="combobox">, the
// popup a role="listbox" of role="option"s with aria-activedescendant on the trigger
// (focus stays on the button). Keys: closed — Enter/Space/Down/Up/Alt+Down open, Home/End
// open at first/last, printable chars type-ahead; open — arrows/Home/End/PageUp/PageDown
// move, type-ahead, Enter/Space select, Escape closes, Tab selects and moves on. Click
// outside closes. Positioning is @floating-ui/dom; the popup lives in <body>, so it is
// never clipped and never inside the <label data-tip> of the trigger (tooltip.ts).
//
// Mimics the bits of HTMLSelectElement the callers use: `.value`, `.onchange`
// (fired only on user changes, like a native <select>), and per-option disabled.
import { autoUpdate, computePosition, flip, offset, shift, size } from "@floating-ui/dom";
import "./select.css";

export interface SelectOption { value: string; label: string; disabled?: boolean }

const CHEVRON = `<svg class="ui-select-icon" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>`;
const CHECK = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>`;

let uid = 0;
const TYPEAHEAD_MS = 500;

export class Select {
  /** The trigger button; put it where the native <select> was. */
  readonly el: HTMLButtonElement;
  onchange: ((this: Select, ev: Event) => void) | null = null;
  private list: HTMLDivElement;
  private valueEl: HTMLSpanElement;
  private opts: SelectOption[];
  private items: HTMLDivElement[] = [];
  private cur = 0;          // selected index
  private active = -1;      // highlighted index while open
  private stopAuto: (() => void) | null = null;
  private typed = "";
  private typedT = 0;

  constructor(opts: { id: string; options: SelectOption[]; value?: string; labelledBy?: string; className?: string }) {
    const n = ++uid;
    this.opts = opts.options.map((o) => ({ ...o }));
    this.el = document.createElement("button");
    this.el.type = "button";
    this.el.id = opts.id;
    this.el.className = "ui-select" + (opts.className ? " " + opts.className : "");
    this.el.setAttribute("role", "combobox");
    this.el.setAttribute("aria-haspopup", "listbox");
    this.el.setAttribute("aria-expanded", "false");
    const listId = `${opts.id}-listbox`;
    this.el.setAttribute("aria-controls", listId);
    this.valueEl = document.createElement("span");
    this.valueEl.className = "ui-select-value";
    this.valueEl.id = `${opts.id}-value-${n}`;
    this.el.append(this.valueEl);
    this.el.insertAdjacentHTML("beforeend", CHEVRON);
    if (opts.labelledBy) this.el.setAttribute("aria-labelledby", `${opts.labelledBy} ${this.valueEl.id}`);

    this.list = document.createElement("div");
    this.list.id = listId;
    this.list.className = "ui-select-content";
    this.list.setAttribute("role", "listbox");
    this.list.tabIndex = -1;
    if (opts.labelledBy) this.list.setAttribute("aria-labelledby", opts.labelledBy);
    this.list.hidden = true;
    this.opts.forEach((o, i) => {
      const it = document.createElement("div");
      it.id = `${listId}-${i}`;
      it.className = "ui-select-item";
      it.setAttribute("role", "option");
      it.innerHTML = `<span class="ui-select-check">${CHECK}</span>`;
      const t = document.createElement("span");
      t.textContent = o.label;
      it.append(t);
      it.addEventListener("pointermove", () => { if (!this.opts[i].disabled && this.active !== i) this.highlight(i); });
      it.addEventListener("click", () => { if (!this.opts[i].disabled) { this.pick(i); this.close(); } });
      this.items.push(it);
      this.list.append(it);
    });
    // keep focus on the trigger while clicking in the list
    this.list.addEventListener("mousedown", (e) => e.preventDefault());
    document.body.append(this.list);

    const i0 = opts.value != null ? this.opts.findIndex((o) => o.value === opts.value) : 0;
    this.cur = Math.max(0, i0);
    this.render();

    this.el.addEventListener("click", () => (this.isOpen ? this.close() : this.open(this.cur)));
    this.el.addEventListener("keydown", (e) => this.onKey(e));
    this.el.addEventListener("blur", () => this.close(false));
    document.addEventListener("pointerdown", (e) => {
      const t = e.target as Node;
      if (this.isOpen && !this.el.contains(t) && !this.list.contains(t)) this.close(false);
    });
  }

  get isOpen() { return !this.list.hidden; }
  get value() { return this.opts[this.cur]?.value ?? ""; }
  set value(v: string) {
    const i = this.opts.findIndex((o) => o.value === v);
    if (i >= 0 && i !== this.cur) { this.cur = i; this.render(); }
  }
  setDisabled(value: string, disabled: boolean) {
    const i = this.opts.findIndex((o) => o.value === value);
    if (i >= 0 && !!this.opts[i].disabled !== disabled) { this.opts[i].disabled = disabled; this.render(); }
  }

  private render() {
    this.valueEl.textContent = this.opts[this.cur]?.label ?? "";
    this.items.forEach((it, i) => {
      it.setAttribute("aria-selected", String(i === this.cur));
      it.toggleAttribute("data-disabled", !!this.opts[i].disabled);
      if (this.opts[i].disabled) it.setAttribute("aria-disabled", "true"); else it.removeAttribute("aria-disabled");
    });
  }

  private highlight(i: number) {
    this.active = i;
    this.items.forEach((it, k) => it.toggleAttribute("data-highlighted", k === i));
    if (i >= 0) {
      this.el.setAttribute("aria-activedescendant", this.items[i].id);
      this.items[i].scrollIntoView({ block: "nearest" });
    } else this.el.removeAttribute("aria-activedescendant");
  }

  private enabled(i: number) { return i >= 0 && i < this.opts.length && !this.opts[i].disabled; }
  /** next enabled index from `from` stepping `dir`, clamped (no wrap, as in the APG example) */
  private step(from: number, dir: 1 | -1) {
    for (let i = from + dir; i >= 0 && i < this.opts.length; i += dir) if (this.enabled(i)) return i;
    return from;
  }
  private first() { return this.step(-1, 1); }
  private last() { return this.step(this.opts.length, -1); }

  open(at = this.cur) {
    if (this.isOpen) return;
    this.list.hidden = false;
    this.list.style.minWidth = `${this.el.offsetWidth}px`;
    this.el.setAttribute("aria-expanded", "true");
    this.el.dataset.state = "open";
    this.highlight(this.enabled(at) ? at : this.first());
    const place = () =>
      computePosition(this.el, this.list, {
        placement: "bottom-start", strategy: "fixed",
        middleware: [offset(4), flip({ padding: 6 }), shift({ padding: 6 }),
          size({ padding: 6, apply: ({ availableHeight }) => { this.list.style.maxHeight = `${Math.max(80, availableHeight)}px`; } })],
      }).then(({ x, y }) => { this.list.style.left = `${x}px`; this.list.style.top = `${y}px`; });
    this.stopAuto = autoUpdate(this.el, this.list, place);
  }

  close(refocus = true) {
    if (!this.isOpen) return;
    this.list.hidden = true;
    this.el.setAttribute("aria-expanded", "false");
    delete this.el.dataset.state;
    this.highlight(-1);
    this.stopAuto?.(); this.stopAuto = null;
    if (refocus && document.activeElement !== this.el) this.el.focus();
  }

  private pick(i: number) {
    if (!this.enabled(i) || i === this.cur) return;
    this.cur = i;
    this.render();
    const ev = new Event("change", { bubbles: true });
    this.onchange?.call(this, ev);
    this.el.dispatchEvent(ev);
  }

  private typeahead(ch: string) {
    clearTimeout(this.typedT);
    this.typedT = window.setTimeout(() => { this.typed = ""; }, TYPEAHEAD_MS);
    this.typed += ch.toLowerCase();
    const from = this.isOpen ? this.active : this.cur;
    // repeated same letter cycles; otherwise search from the current item
    const all = this.typed.split("").every((c) => c === this.typed[0]);
    const q = all ? this.typed[0] : this.typed;
    const start = all ? from + 1 : from;
    for (let k = 0; k < this.opts.length; k++) {
      const i = (start + k + this.opts.length) % this.opts.length;
      if (this.enabled(i) && this.opts[i].label.toLowerCase().startsWith(q)) return i;
    }
    return -1;
  }

  private onKey(e: KeyboardEvent) {
    const k = e.key;
    if (!this.isOpen) {
      if (k === "Enter" || k === " " || k === "ArrowDown" || k === "ArrowUp") { e.preventDefault(); this.open(); }
      else if (k === "Home") { e.preventDefault(); this.open(this.first()); }
      else if (k === "End") { e.preventDefault(); this.open(this.last()); }
      else if (k.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
        const i = this.typeahead(k);
        if (i >= 0) { this.open(i); }
      }
      return;
    }
    switch (k) {
      case "ArrowDown": e.preventDefault(); if (e.altKey) break; this.highlight(this.step(this.active, 1)); return;
      case "ArrowUp":
        e.preventDefault();
        if (e.altKey) { this.pick(this.active); this.close(); return; }
        this.highlight(this.step(this.active, -1)); return;
      case "Home": e.preventDefault(); this.highlight(this.first()); return;
      case "End": e.preventDefault(); this.highlight(this.last()); return;
      case "PageDown": e.preventDefault(); { let i = this.active; for (let n = 0; n < 10; n++) i = this.step(i, 1); this.highlight(i); } return;
      case "PageUp": e.preventDefault(); { let i = this.active; for (let n = 0; n < 10; n++) i = this.step(i, -1); this.highlight(i); } return;
      case "Enter": case " ":
        if (k === " " && this.typed) { e.preventDefault(); const i = this.typeahead(k); if (i >= 0) this.highlight(i); return; }
        e.preventDefault(); this.pick(this.active); this.close(); return;
      case "Escape": e.preventDefault(); e.stopPropagation(); this.close(); return;
      case "Tab": this.pick(this.active); this.close(false); return;
    }
    if (k.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
      const i = this.typeahead(k);
      if (i >= 0) this.highlight(i);
    }
  }
}
