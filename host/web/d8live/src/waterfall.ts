// Waterfall tab: scrolling spectrogram rows from the d8live backend
// (host/esp32sdr/waterfall.py, WebSocket /wf?view=base|hop).
//
// Self-mounting: adds a "Channels | Waterfall" tab bar under the header and a
// section after <main>; the socket is open only while the tab is shown, so the
// backend does no FFT work for a page on the Channels tab.
//
// Rows are uint8 (0 = no data, 1..255 = db_min..db_max) and go into a fixed
// ring (an offscreen canvas of HISTORY_S × rate rows), so memory is bounded
// whatever the run length. The display canvas draws the ring in two slices,
// newest row at the top.
import { interpolateInferno, interpolateTurbo, interpolateViridis } from "d3-scale-chromatic";
import { Select } from "./select";
import "./waterfall.css";

interface Meta {
  type: "wf_meta"; view: "base" | "hop"; views: string[]; width: number; rate: number;
  db_min: number; db_max: number; fs: number; nfft: number; center_mhz: number | null; follow: boolean;
  bins_per_ch?: number; channels?: { slot: number; mhz: number }[];
}
interface WfStats { type: "wf_stats"; cpu_frac: number; cpu_s: number; dropped: number; queued: number }

const HISTORY_S = 45;
const HDR = 16; // <BBHId: kind, reserved, width, seq, t
const MAPS: Record<string, (t: number) => string> = {
  turbo: interpolateTurbo, viridis: interpolateViridis, inferno: interpolateInferno,
};

const el = <K extends keyof HTMLElementTagNameMap>(tag: K, cls = "", html = "") => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html) e.innerHTML = html;
  return e;
};
const cssVar = (name: string, fallback: string) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;

/** "rgb(r, g, b)" or "#rrggbb" -> [r, g, b] */
function parseColor(s: string): [number, number, number] {
  const m = s.match(/\d+/g);
  if (s.startsWith("rgb") && m) return [+m[0], +m[1], +m[2]];
  const h = parseInt(s.slice(1), 16);
  return [(h >> 16) & 255, (h >> 8) & 255, h & 255];
}

/** 256-entry RGBA LUT (little-endian ABGR words); [0] = background, [256 + v] = dimmed v (held cells). */
function makeLut(name: string, bg: string): Uint32Array {
  const lut = new Uint32Array(512);
  const pack = (r: number, g: number, b: number) => (255 << 24) | (b << 16) | (g << 8) | r;
  const [br, bgc, bb] = parseColor(bg);
  lut[0] = lut[256] = pack(br, bgc, bb);
  for (let v = 1; v < 256; v++) {
    const [r, g, b] = parseColor(MAPS[name]((v - 1) / 254));
    lut[v] = pack(r, g, b);
    const k = 0.45; // held (not visited in this row) cells: blend toward the background
    lut[256 + v] = pack(br + (r - br) * k, bgc + (g - bgc) * k, bb + (b - bb) * k);
  }
  return lut;
}

// ---- DOM -----------------------------------------------------------------
const main = document.querySelector("main") as HTMLElement | null;
const nerd = document.getElementById("nerd");
const header = document.querySelector("header");
const tabs = el("nav", "wf-tabs",
  `<button data-tab="channels" class="on">Channels</button><button data-tab="waterfall">Waterfall</button><button data-tab="stats">Stats for nerds</button>` +
  `<span id="conn" class="conn text-bad" tabindex="0" data-tip="Link between this page and the d8live server, not the radio. Retries every second when it drops.">disconnected</span>`);
(header ?? document.getElementById("follow"))?.after(tabs);
const sec = el("section", "wf");
sec.hidden = true;
sec.innerHTML = `
  <p class="lede">Radio spectrum over the last 45 s, newest at the top; colour shows signal level.</p>
  <div class="wf-bar">
    <label data-tip="baseband: the 250 kHz around wherever the receiver is tuned; when hopping, that's whichever channel it is on. hop map: one strip per hop channel, by frequency, lit only while the receiver is on it."><span class="tip-u" id="wf-view-l">view</span> <span id="wf-view-slot"></span></label>
    <label><span id="wf-map-l">colours</span> <span id="wf-map-slot"></span></label>
    <label id="wf-hold-l" data-tip="Between visits, keep each channel's last row, dimmed, so the hop map doesn't flicker."><input type="checkbox" id="wf-hold" class="ui-checkbox"> <span class="tip-u">hold last visit</span></label>
    <button id="wf-pause" type="button" class="ui-button">Pause</button>
    <span class="wf-info" id="wf-info"><span id="wf-i-size">–</span><span id="wf-i-db" tabindex="0" hidden></span><span id="wf-i-t"></span><span id="wf-i-cpu" tabindex="0" hidden data-tip="Share of one CPU core the server spends on these FFTs. It only does the work while this tab is open."></span><span id="wf-i-p"></span></span>
  </div>
  <div class="wf-plot">
    <canvas id="wf-axis" class="wf-axis"></canvas>
    <canvas id="wf-canvas" class="wf-canvas"></canvas>
    <div id="wf-tip" class="wf-tip" hidden></div>
  </div>
  <p class="wf-note">The board sends 1-bit samples, so levels are dB above a flat, noise-like spectrum, not absolute power.
  In the hop map a strip lights only while the receiver is on that channel.</p>`;
(main ?? tabs).after(sec);
const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const viewSel = new Select({ id: "wf-view", labelledBy: "wf-view-l", value: "base", options: [
  { value: "base", label: "baseband ±125 kHz" }, { value: "hop", label: "hop map (47 ch)" }] });
const mapSel = new Select({ id: "wf-map", labelledBy: "wf-map-l", value: "viridis",
  options: ["viridis", "turbo", "inferno"].map((v) => ({ value: v, label: v })) });
$("wf-view-slot").replaceWith(viewSel.el);
$("wf-map-slot").replaceWith(mapSel.el);
const holdBox = $<HTMLInputElement>("wf-hold"), pauseBtn = $<HTMLButtonElement>("wf-pause");
const axisC = $<HTMLCanvasElement>("wf-axis"), cv = $<HTMLCanvasElement>("wf-canvas");
const tip = $("wf-tip");
const iSize = $("wf-i-size"), iDb = $("wf-i-db"), iT = $("wf-i-t"), iCpu = $("wf-i-cpu"), iP = $("wf-i-p");
const setText = (e: HTMLElement, t: string) => { if (e.textContent !== t) e.textContent = t; };
const wrap = sec.parentElement;

/** Size the waterfall canvas so the whole tab fits the window without scrolling. */
function fitHeight() {
  if (!open) return;
  // Grow or shrink the canvas by however much the page over- or under-fills the window.
  const spare = window.innerHeight - document.documentElement.scrollHeight;
  cv.style.height = `${Math.max(240, Math.floor(cv.offsetHeight + spare))}px`;
  dirty = true;
}

// ---- state ---------------------------------------------------------------
let ws: WebSocket | null = null;
let meta: Meta | null = null;
let open = false, paused = false, dirty = false;
let flat: HTMLCanvasElement | null = null;
let ring: HTMLCanvasElement | null = null, ringG: CanvasRenderingContext2D | null = null;
let rowImg: ImageData | null = null, rowPx: Uint32Array | null = null;
let N = 0, head = 0;
let held = new Uint8Array(0);
let lut = makeLut("viridis", "#000");
let rows = 0, rowsT0 = performance.now(), rowRate = 0, lastT = 0;
let stats: WfStats | null = null;
let wantView = "";

function bg() { return cssVar("--color-paper-2", "#0b0e11"); }

function reset(m: Meta) {
  meta = m;
  N = Math.max(10, Math.round(HISTORY_S * m.rate));
  ring = document.createElement("canvas");
  ring.width = m.width; ring.height = N;
  ringG = ring.getContext("2d")!;
  ringG.fillStyle = bg(); ringG.fillRect(0, 0, m.width, N);
  rowImg = ringG.createImageData(m.width, 1);
  rowPx = new Uint32Array(rowImg.data.buffer);
  held = new Uint8Array(m.width);
  head = 0;
  viewSel.setDisabled("hop", !m.views.includes("hop"));
  viewSel.value = m.view;
  $("wf-hold-l").hidden = m.view !== "hop";
  drawAxis();
  dirty = true;
}

function onRow(buf: ArrayBuffer) {
  if (!meta || !ringG || !rowImg || !rowPx) return;
  const dv = new DataView(buf);
  const w = dv.getUint16(2, true);
  if (w !== meta.width) return;
  lastT = dv.getFloat64(8, true);
  const row = new Uint8Array(buf, HDR, w);
  const hold = meta.view === "hop" && holdBox.checked;
  for (let i = 0; i < w; i++) {
    const v = row[i];
    if (v) { held[i] = v; rowPx[i] = lut[v]; }
    else rowPx[i] = hold && held[i] ? lut[256 + held[i]] : lut[0];
  }
  head = (head - 1 + N) % N; // newest row at `head`, older rows follow it (wrapping)
  ringG.putImageData(rowImg, 0, head);
  rows++;
  dirty = true;
}

function connect() {
  if (!open) return;
  const q = wantView ? `?view=${wantView}` : "";
  const s = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/wf${q}`);
  s.binaryType = "arraybuffer";
  ws = s;
  s.onmessage = (ev) => {
    if (typeof ev.data !== "string") return onRow(ev.data as ArrayBuffer);
    const m = JSON.parse(ev.data);
    if (m.type === "wf_meta") reset(m);
    else if (m.type === "wf_stats") stats = m;
  };
  s.onclose = () => {
    if (ws === s) { ws = null; meta = null; setText(iSize, "disconnected"); iDb.hidden = iCpu.hidden = true; setText(iT, ""); setTimeout(connect, 1000); }
  };
}
function disconnect() {
  const s = ws;
  ws = null;
  s?.close();
}

function showTab(name: string) {
  open = name === "waterfall";
  tabs.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.tab === name));
  if (main) main.hidden = name !== "channels";
  if (nerd) nerd.hidden = name !== "stats";
  sec.hidden = !open;
  wrap?.classList.toggle("wf-wide", open);
  if (open) fitHeight();
  history.replaceState(null, "", name !== "channels" ? `#${name}` : location.pathname + location.search);
  if (open && !ws) connect();
  if (!open) disconnect();
}
tabs.addEventListener("click", (e) => {
  const b = (e.target as HTMLElement).closest("button");
  if (b?.dataset.tab) showTab(b.dataset.tab);
});
viewSel.onchange = () => { wantView = viewSel.value; disconnect(); connect(); };
mapSel.onchange = () => { lut = makeLut(mapSel.value, bg()); };
pauseBtn.onclick = () => {
  paused = !paused;
  pauseBtn.textContent = paused ? "Resume" : "Pause";
  pauseBtn.classList.toggle("on", paused);
  dirty = true;
};

// ---- drawing ---------------------------------------------------------------
const AXIS_H_BASE = 22, AXIS_H_HOP = 48, LEFT = 44;

function fit(c: HTMLCanvasElement) {
  const g = c.getContext("2d")!;
  const dpr = window.devicePixelRatio || 1;
  const W = c.clientWidth, H = c.clientHeight;
  if (c.width !== Math.round(W * dpr) || c.height !== Math.round(H * dpr)) {
    c.width = Math.round(W * dpr); c.height = Math.round(H * dpr);
  }
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { g, W, H };
}

/** x (CSS px within the plot area) -> label for the hover readout */
function xInfo(fx: number): string {
  if (!meta) return "";
  if (meta.view === "hop" && meta.channels && meta.bins_per_ch) {
    const k = Math.min(meta.channels.length - 1, Math.floor(fx * meta.channels.length));
    const c = meta.channels[k];
    const off = ((fx * meta.channels.length - k) - 0.5) * meta.fs / 1e3;
    return `slot ${c.slot} · ${c.mhz.toFixed(3)} MHz ${off >= 0 ? "+" : ""}${off.toFixed(0)} kHz`;
  }
  const off = (fx - 0.5) * meta.fs / 1e3;
  return meta.center_mhz != null ? `${(meta.center_mhz + off / 1e3).toFixed(4)} MHz` : `${off.toFixed(1)} kHz`;
}

function drawAxis() {
  if (!meta) return;
  axisC.style.height = `${meta.view === "hop" ? AXIS_H_HOP : AXIS_H_BASE}px`;
  fitHeight();
  const { g, W, H } = fit(axisC);
  const fg = cssVar("--color-muted", "#8a95a3"), line = cssVar("--color-line", "#2a313b");
  g.clearRect(0, 0, W, H);
  const pw = W - LEFT;
  g.strokeStyle = line; g.fillStyle = fg;
  g.font = `10px ${cssVar("--font-mono", "ui-monospace, monospace")}`;
  if (meta.view === "hop" && meta.channels) {
    const n = meta.channels.length;
    g.textAlign = "left"; // rotated -90°: text runs upward from the tick
    meta.channels.forEach((c, k) => {
      const x = LEFT + (k + 0.5) * pw / n;
      g.beginPath(); g.moveTo(Math.round(x) + 0.5, H - 4); g.lineTo(Math.round(x) + 0.5, H); g.stroke();
      g.save(); g.translate(x + 3, H - 6); g.rotate(-Math.PI / 2);
      g.fillText(c.mhz.toFixed(1), 0, 0); g.restore();
    });
  } else {
    g.textAlign = "center";
    for (const k of [-100, -50, 0, 50, 100]) {
      const x = LEFT + (0.5 + k * 1e3 / meta.fs) * pw;
      g.beginPath(); g.moveTo(Math.round(x) + 0.5, H - 5); g.lineTo(Math.round(x) + 0.5, H); g.stroke();
      const lab = meta.center_mhz != null ? (k === 0 ? `${meta.center_mhz.toFixed(3)} MHz` : `${k > 0 ? "+" : ""}${k}k`)
        : `${k} kHz`;
      g.fillText(lab, x, H - 8);
    }
  }
}

function draw() {
  const { g, W, H } = fit(cv);
  const fg = cssVar("--color-muted", "#8a95a3"), line = cssVar("--color-line", "#2a313b");
  g.fillStyle = bg(); g.fillRect(0, 0, W, H);
  if (!meta || !ring) return;
  const pw = W - LEFT;
  // 1) unwrap the ring (rows head..N-1 then 0..head-1, newest at the top) into a
  //    canvas that is `width` bins wide and as tall as the display: the vertical
  //    resample is smoothed (averages rows when there are more rows than pixels,
  //    so short bursts still show), the bins keep their own columns.
  const dpr = window.devicePixelRatio || 1;
  const hh = Math.max(1, Math.round(H * dpr));
  if (!flat || flat.width !== meta.width || flat.height !== hh) {
    flat = document.createElement("canvas");
    flat.width = meta.width; flat.height = hh;
  }
  const fg2 = flat.getContext("2d")!;
  fg2.imageSmoothingEnabled = true; fg2.imageSmoothingQuality = "high";
  const a = N - head, rh = hh / N;
  fg2.drawImage(ring, 0, head, meta.width, a, 0, 0, meta.width, a * rh);
  if (head) fg2.drawImage(ring, 0, 0, meta.width, head, 0, a * rh, meta.width, head * rh);
  // 2) stretch the bins horizontally without smoothing (sharp channel strips)
  g.imageSmoothingEnabled = false;
  g.drawImage(flat, 0, 0, meta.width, hh, LEFT, 0, pw, H);
  // channel separators (hop map)
  if (meta.view === "hop" && meta.channels) {
    g.strokeStyle = cssVar("--color-paper", "#fff");
    const n = meta.channels.length;
    g.beginPath();
    for (let k = 1; k < n; k++) { const x = Math.round(LEFT + k * pw / n) + 0.5; g.moveTo(x, 0); g.lineTo(x, H); }
    g.stroke();
  }
  // time axis
  g.fillStyle = fg; g.strokeStyle = line; g.textAlign = "right";
  g.font = `10px ${cssVar("--font-mono", "ui-monospace, monospace")}`;
  for (let s = 0; s <= HISTORY_S; s += 5) {
    const y = Math.min(H - 1, (s / HISTORY_S) * H);
    g.beginPath(); g.moveTo(LEFT - 4, Math.round(y) + 0.5); g.lineTo(LEFT, Math.round(y) + 0.5); g.stroke();
    g.fillText(s ? `-${s}s` : "now", LEFT - 6, Math.max(10, y + 3));
  }
}

cv.addEventListener("mousemove", (e) => {
  if (!meta) return;
  const r = cv.getBoundingClientRect();
  const fx = (e.clientX - r.left - LEFT) / (r.width - LEFT);
  if (fx < 0 || fx > 1) { tip.hidden = true; return; }
  const age = ((e.clientY - r.top) / r.height) * HISTORY_S;
  tip.textContent = `${xInfo(fx)} · -${age.toFixed(1)} s`;
  tip.style.left = `${e.clientX - r.left + 12}px`;
  tip.style.top = `${e.clientY - r.top + 12}px`;
  tip.hidden = false;
});
cv.addEventListener("mouseleave", () => { tip.hidden = true; });
window.addEventListener("resize", () => { drawAxis(); fitHeight(); dirty = true; });

function frame(now: number) {
  if (open) {
    if (now - rowsT0 > 1000) { rowRate = rows * 1000 / (now - rowsT0); rows = 0; rowsT0 = now; }
    if (dirty && !paused) { draw(); dirty = false; }
    if (meta) {
      // split into spans so the dB range and CPU figure can carry tooltips
      setText(iSize, `${meta.view === "hop" ? `${meta.channels?.length} channels` : `${meta.nfft} bins`} · ` +
        `${rowRate.toFixed(1)} rows/s · `);
      const db = `${meta.db_min}…${meta.db_max} dB`;
      setText(iDb, db);
      iDb.hidden = false;
      const dbTip = `Colour scale: the low end of the colour map is ${meta.db_min} dB, the high end ${meta.db_max} dB, both relative to a flat, noise-like spectrum.`;
      if (iDb.dataset.tip !== dbTip) iDb.dataset.tip = dbTip;
      setText(iT, ` · t ${lastT.toFixed(1)} s` + (stats ? " · " : ""));
      iCpu.hidden = !stats;
      if (stats) setText(iCpu, `backend FFT ${(stats.cpu_frac * 100).toFixed(1)}% CPU` +
        (stats.dropped ? `, dropped ${stats.dropped}` : ""));
      setText(iP, paused ? " · paused" : "");
    }
  }
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);
lut = makeLut("viridis", bg());
if (location.hash === "#waterfall" || location.hash === "#stats") showTab(location.hash.slice(1));
