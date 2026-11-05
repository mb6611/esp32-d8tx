import "./style.css";

// Messages from the d8live backend (host/esp32sdr/d8_live.py).
interface PacketMsg {
  type: "packet"; t: number; tx_id: [number, number]; counter: number;
  ch: number[]; raw: number[]; crc_ok: boolean; cfo: number; mode: string; latency_ms: number;
}
interface StatsMsg {
  type: "stats"; uptime: number; packets_per_s: number; crc_rate: number | null; n_ok: number; n_all: number;
  mode: string; period_ms: number; decode_frac: number; latency_ms: number | null; frames: number;
  samples: number; lost_samples: number; loss_frac: number; bad_crc: number; short_frames: number;
  center_mhz: number; gain: number | string; gain_index: number | null;
}

const LO = 980, HI = 2020, MID = 1500;
const COLORS = ["#ff6b6b", "#ffa94d", "#ffd43b", "#69db7c", "#38d9a9", "#4dabf7", "#9775fa", "#f783ac"];
const PLOT_S = 20;

const $ = (id: string) => document.getElementById(id)!;
const bars = $("bars");
const fills: HTMLElement[] = [], vals: HTMLElement[] = [];
for (let i = 0; i < 8; i++) {
  const row = document.createElement("div");
  row.className = "bar";
  row.innerHTML = `<span style="color:${COLORS[i]}">ch${i + 1}</span><div class="track"><div class="fill" style="background:${COLORS[i]}"></div><div class="mid"></div></div><span class="val">–</span>`;
  bars.appendChild(row);
  fills.push(row.querySelector(".fill")!);
  vals.push(row.querySelector(".val")!);
}

let last: PacketMsg | null = null;
let lastWall = 0; // performance.now() of the last CRC-ok packet
const hist: { w: number; ch: number[] }[] = [];

const frac = (us: number) => Math.min(1, Math.max(0, (us - LO) / (HI - LO)));

function onPacket(p: PacketMsg) {
  if (!p.crc_ok) return;
  last = p;
  lastWall = performance.now();
  hist.push({ w: lastWall, ch: p.ch });
  while (hist.length && lastWall - hist[0].w > PLOT_S * 1000) hist.shift();
  $("tx").textContent = `${p.tx_id[0]},${p.tx_id[1]} (0x${((p.tx_id[0] << 8) | p.tx_id[1]).toString(16).padStart(4, "0")})`;
  $("ctr").textContent = String(p.counter);
  p.ch.forEach((us, i) => {
    const f = frac(us), m = frac(MID);
    fills[i].style.left = `${Math.min(f, m) * 100}%`;
    fills[i].style.width = `${Math.abs(f - m) * 100}%`;
    vals[i].textContent = `${us.toFixed(0)} µs`;
  });
}

function onStats(s: StatsMsg) {
  $("rate").textContent = `${s.packets_per_s.toFixed(2)}/s`;
  $("crc").textContent = s.crc_rate == null ? "–" : `${(s.crc_rate * 100).toFixed(0)}%`;
  $("mode").textContent = `${s.mode}${s.mode === "locked" ? ` (${s.period_ms.toFixed(1)} ms)` : ""}`;
  $("stream").textContent =
    `${s.center_mhz} MHz, gain ${s.gain} (frame idx ${s.gain_index ?? "?"}) · up ${s.uptime.toFixed(0)} s · ` +
    `${s.n_ok}/${s.n_all} packets CRC ok · stream ${s.frames} frames, lost ${s.lost_samples} samples ` +
    `(${(s.loss_frac * 100).toFixed(3)}%), bad CRC ${s.bad_crc}, short ${s.short_frames} · ` +
    `decoder sees ${(s.decode_frac * 100).toFixed(1)}% of samples · latency ${s.latency_ms ?? "–"} ms`;
}

function connect() {
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  const conn = $("conn");
  ws.onopen = () => { conn.textContent = "connected"; conn.className = "pill ok"; };
  ws.onclose = () => {
    conn.textContent = "disconnected"; conn.className = "pill bad";
    setTimeout(connect, 1000);
  };
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.type === "packet") onPacket(m);
    else if (m.type === "stats") onStats(m);
  };
}
connect();

const padPos: Record<string, { x: number; y: number }> = {};
function drawPad(id: string, xus: number, yus: number) {
  const c = $(id) as HTMLCanvasElement, g = c.getContext("2d")!;
  const W = c.width, H = c.height, cx = W / 2, cy = H / 2, R = Math.min(W, H) / 2 - 14;
  g.clearRect(0, 0, W, H);
  // housing
  g.fillStyle = "#11161c"; g.beginPath(); g.roundRect(6, 6, W - 12, H - 12, 18); g.fill();
  g.strokeStyle = "#2a313b"; g.lineWidth = 1; g.stroke();
  // gimbal travel square + centre cross
  g.strokeStyle = "#1f2731"; g.strokeRect(cx - R, cy - R, 2 * R, 2 * R);
  g.beginPath(); g.moveTo(cx, cy - R); g.lineTo(cx, cy + R); g.moveTo(cx - R, cy); g.lineTo(cx + R, cy); g.stroke();
  // gimbal base ring
  const base = g.createRadialGradient(cx, cy, 4, cx, cy, 30);
  base.addColorStop(0, "#2b333d"); base.addColorStop(1, "#151a20");
  g.fillStyle = base; g.beginPath(); g.arc(cx, cy, 30, 0, 2 * Math.PI); g.fill();
  g.strokeStyle = "#39424e"; g.stroke();
  if (!last) return;
  // ease toward target so ~2.4 Hz updates look like motion
  const tx = cx + (frac(xus) * 2 - 1) * R, ty = cy - (frac(yus) * 2 - 1) * R;
  const p = (padPos[id] ??= { x: tx, y: ty });
  p.x += (tx - p.x) * 0.25; p.y += (ty - p.y) * 0.25;
  // shaft
  g.strokeStyle = "#5c6774"; g.lineWidth = 10; g.lineCap = "round";
  g.beginPath(); g.moveTo(cx, cy); g.lineTo(p.x, p.y); g.stroke();
  g.lineWidth = 1;
  // knob with shadow + highlight
  g.fillStyle = "rgba(0,0,0,0.45)"; g.beginPath(); g.arc(p.x + 3, p.y + 4, 17, 0, 2 * Math.PI); g.fill();
  const k = g.createRadialGradient(p.x - 5, p.y - 6, 2, p.x, p.y, 17);
  k.addColorStop(0, "#9fd1ff"); k.addColorStop(0.5, "#4dabf7"); k.addColorStop(1, "#1c5f99");
  g.fillStyle = k; g.beginPath(); g.arc(p.x, p.y, 17, 0, 2 * Math.PI); g.fill();
  g.fillStyle = "#8a95a3"; g.font = "11px ui-monospace, monospace";
  g.fillText(`${xus.toFixed(0)}, ${yus.toFixed(0)} us`, 16, H - 14);
}

function drawPlot(now: number) {
  const c = $("plot") as HTMLCanvasElement, g = c.getContext("2d")!;
  const dpr = window.devicePixelRatio || 1;
  const W = c.clientWidth, H = c.clientHeight;
  if (c.width !== W * dpr) { c.width = W * dpr; c.height = H * dpr; }
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, W, H);
  const yOf = (us: number) => H - 6 - frac(us) * (H - 12);
  const xOf = (w: number) => W - ((now - w) / (PLOT_S * 1000)) * W;
  g.strokeStyle = "#2a313b"; g.fillStyle = "#5c6673"; g.font = "11px ui-monospace, monospace";
  for (const us of [1000, 1500, 2000]) {
    g.beginPath(); g.moveTo(0, yOf(us)); g.lineTo(W, yOf(us)); g.stroke();
    g.fillText(String(us), 4, yOf(us) - 3);
  }
  for (let s = 5; s < PLOT_S; s += 5) {
    const x = W - (s / PLOT_S) * W;
    g.beginPath(); g.moveTo(x, 0); g.lineTo(x, H); g.stroke();
    g.fillText(`-${s}s`, x + 3, H - 4);
  }
  for (let i = 0; i < 8; i++) {
    g.strokeStyle = COLORS[i]; g.lineWidth = 1.5; g.beginPath();
    hist.forEach((h, k) => (k ? g.lineTo(xOf(h.w), yOf(h.ch[i])) : g.moveTo(xOf(h.w), yOf(h.ch[i]))));
    g.stroke();
  }
}

function frame() {
  const now = performance.now();
  const age = last ? (now - lastWall) / 1000 : null;
  const ageEl = $("age");
  ageEl.textContent = age == null ? "–" : `${age.toFixed(1)} s ago`;
  ageEl.style.color = age != null && age > 1.5 ? "#ffb3b3" : "";
  bars.classList.toggle("stale", age == null || age > 1.5);
  const ch = last?.ch ?? [MID, MID, MID, MID];
  drawPad("padL", ch[3], ch[0]);
  drawPad("padR", ch[1], ch[2]);
  drawPlot(now);
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);
