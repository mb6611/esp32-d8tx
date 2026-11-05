// d8live page: wires the /ws feed to the readouts and canvases.
// Packets (~108/s with --follow) only update state; everything is drawn once
// per animation frame.
import "./style.css";
import { Bars } from "./bars";
import { renderHitmap } from "./hitmap";
import { drawPad } from "./pads";
import { drawPlot, History } from "./plot";
import { setConnected, showAge, showPacket, showStats } from "./stats";
import type { PacketMsg, StatsMsg } from "./types";

const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
const padL = $<HTMLCanvasElement>("padL"), padR = $<HTMLCanvasElement>("padR"), plot = $<HTMLCanvasElement>("plot");
const bars = new Bars($("bars"));
const hist = new History();
const main = document.querySelector("main")!;

let last: PacketMsg | null = null;
let lastWall = 0; // performance.now() of the last CRC-ok packet
let fresh = false; // a packet arrived since the last frame

function onPacket(p: PacketMsg) {
  if (!p.crc_ok) return;
  last = p;
  lastWall = performance.now();
  hist.push(lastWall, p.ch);
  fresh = true;
}

function onStats(s: StatsMsg) {
  showStats(s);
  renderHitmap(s.follow);
}

function connect() {
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  ws.onopen = () => setConnected(true);
  ws.onclose = () => {
    setConnected(false);
    setTimeout(connect, 1000);
  };
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.type === "packet") onPacket(m);
    else if (m.type === "stats") onStats(m);
  };
}
connect();

function frame() {
  const now = performance.now();
  const age = last ? (now - lastWall) / 1000 : null;
  showAge(age);
  if (fresh && last) { showPacket(last); fresh = false; }
  if (!main.hidden) { // the waterfall tab hides <main>; skip drawing what is not shown
    const ch = last?.ch;
    bars.update(ch ?? null, age == null || age > 1.5);
    // left = yaw ch4 (X) / throttle ch1 (Y), right = roll ch2 (X) / pitch ch3 (Y)
    drawPad(padL, ch ? ch[3] : null, ch ? ch[0] : null);
    drawPad(padR, ch ? ch[1] : null, ch ? ch[2] : null);
    drawPlot(plot, hist, now);
  }
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);

