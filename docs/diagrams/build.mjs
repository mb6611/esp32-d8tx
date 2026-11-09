// Generates the .excalidraw scenes (hand-drawn style). Run via `pnpm diagrams` (render.mjs calls this, then renders SVG + PNG).
//
// Visual language, the same in every diagram (each one draws the legend):
//   fill colour = layer: app/JS (blue), OS/driver/USB (grey), firmware on an MCU (green), digital data/signal (yellow),
//                 analog RF/physics (red), mechanical (purple)
//   shape       = kind: rounded box = processing step, sharp box = data unit on the wire, ellipse = physical phenomenon
//   arrows      = solid: control path, dashed: telemetry return, dotted violet: optional drone USB (MSP)
//   containers  = one per physical device (neutral outline), dotted sub-groups inside
// Every label was checked against the code (packages/core, packages/ui, firmware/main, demod, protocol/PROTOCOL.md,
// Betaflight rx/cc2500_frsky_*.c); keep it that way when editing.
import { writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const dir = fileURLToPath(new URL('./', import.meta.url))

// ---------- excalidraw primitives ----------
let n = 0
const seed = () => 1000 + 7 * ++n
const base = (type, x, y, w, h, extra = {}) => ({
  id: `e${n + 1}`, type, x, y, width: w, height: h, angle: 0,
  strokeColor: '#1e1e1e', backgroundColor: 'transparent', fillStyle: 'solid', strokeWidth: 2, strokeStyle: 'solid',
  roughness: 1, opacity: 100, groupIds: [], frameId: null, roundness: null, seed: seed(), version: 1, versionNonce: seed(),
  isDeleted: false, boundElements: null, updated: 1, link: null, locked: false, ...extra,
})

export const INK = '#1e1e1e', MUTED = '#495057', USB = '#6741d9'
export const FILL = { app: '#a5d8ff', os: '#e9ecef', fw: '#b2f2bb', dig: '#ffec99', rf: '#ffc9c9', mech: '#d0bfff' }
const ARROW = {
  ctl: { color: INK, style: 'solid' },
  tlm: { color: INK, style: 'dashed' },
  usb: { color: USB, style: 'dotted' },
}

export function scene() {
  const els = []
  const s = {
    els,
    shape(kind, x, y, w, h, { fill = 'transparent', stroke = INK, style = 'solid', width = 2 } = {}) {
      const type = kind === 'phys' ? 'ellipse' : 'rectangle'
      els.push(base(type, x, y, w, h, {
        backgroundColor: fill, strokeColor: stroke, strokeStyle: style, strokeWidth: width,
        roundness: kind === 'step' || kind === 'box' ? { type: 3 } : null,
      }))
    },
    text(x, y, w, str, { fs = 20, color = INK, align = 'center' } = {}) {
      const lines = str.split('\n').length
      els.push(base('text', x, y, w, Math.ceil(lines * fs * 1.25), {
        text: str, originalText: str, fontSize: fs, fontFamily: 1, textAlign: align, verticalAlign: 'top',
        strokeColor: color, containerId: null, autoResize: false, lineHeight: 1.25, strokeWidth: 1,
      }))
    },
    arrow(pts, { kind = 'ctl', head = true, width = 2 } = {}) {
      const a = ARROW[kind]
      const [x, y] = pts[0], rel = pts.map(([p, q]) => [p - x, q - y])
      const xs = rel.map((p) => p[0]), ys = rel.map((p) => p[1])
      els.push(base('arrow', x, y, Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys), {
        points: rel, strokeColor: a.color, strokeStyle: a.style, strokeWidth: width, startBinding: null, endBinding: null,
        startArrowhead: null, endArrowhead: head ? 'arrow' : null, roundness: null, lastCommittedPoint: null,
      }))
    },
    save(file) {
      writeFileSync(file, JSON.stringify({ type: 'excalidraw', version: 2, source: 'd8tx docs/diagrams/build.mjs', elements: els, appState: { viewBackgroundColor: '#ffffff', gridSize: null, exportBackground: true }, files: {} }, null, 2) + '\n')
    },
  }
  return s
}

// ---------- grid layout ----------
// A diagram is a 4-column grid of nodes. Rows are placed top to bottom; device containers and sub-groups add header bands
// above their first row and padding below their last, and every gap between rows keeps a free band for vertical arrow labels.
const BW = 176, BH = 64, GAP = 108, X0 = 48
const HEAD = 58, GHEAD = 42, CPAD = 18, GPAD = 10, FREE = 56, CM = 26, GM = 12
const colX = (c) => X0 + CM + c * (BW + GAP)
const WIDTH = colX(3) + BW + CM + X0

/**
 * spec: { title, sub, nodes: { id: [row, col, text, layer, kind?, opts?] }, boxes: [{ label, ids, level, side }],
 *         arrows: [[from, to, label?, kind?, opts?]], notes: [[row, col, text, opts]], timeline?: fn(s, y) -> height }
 * kind: 'step' (default) | 'data' | 'phys'
 */
function draw(spec) {
  const s = scene()
  s.text(X0, 0, WIDTH - 2 * X0, spec.title, { fs: 32, align: 'left' })
  let top = 50
  if (spec.sub) { s.text(X0, top, WIDTH - 2 * X0, spec.sub, { fs: 18, color: MUTED, align: 'left' }); top += 34 }
  if (spec.timeline) top += spec.timeline(s, top + 16) + 16
  const nodes = Object.entries(spec.nodes).map(([id, [row, col, text, layer, kind = 'step', o = {}]]) => ({ id, row, col, text, layer, kind, o }))
  const byId = Object.fromEntries(nodes.map((d) => [d.id, d]))
  const nRows = Math.max(...nodes.map((d) => d.row), ...(spec.notes ?? []).map((t) => t[0])) + 1
  const boxes = (spec.boxes ?? []).map((b) => {
    const cells = b.ids.map((i) => byId[i] ?? (() => { throw new Error(`box ${b.label}: no node ${i}`) })())
    return { ...b, level: b.level ?? 0, r0: Math.min(...cells.map((d) => d.row)), r1: Math.max(...cells.map((d) => d.row)),
      c0: b.c0 ?? Math.min(...cells.map((d) => d.col)), c1: b.c1 ?? Math.max(...cells.map((d) => d.col)) }
  })
  // vertical placement
  const rowTop = [], bandTop = []
  let y = top + 20
  for (let r = 0; r < nRows; r++) {
    const starts = boxes.filter((b) => b.r0 === r)
    y += starts.some((b) => b.level === 0) ? HEAD : 0
    y += starts.some((b) => b.level === 1) ? GHEAD : 0
    rowTop[r] = y
    y += BH
    const ends = boxes.filter((b) => b.r1 === r)
    y += ends.some((b) => b.level === 1) ? GPAD : 0
    y += ends.some((b) => b.level === 0) ? CPAD : 0
    bandTop[r] = y
    y += FREE
  }
  // containers first (drawn underneath)
  for (const b of boxes) {
    const pad = b.level === 0 ? CM : GM
    const x0 = colX(b.c0) - pad, x1 = colX(b.c1) + BW + pad
    const nested = b.level === 0 && boxes.some((g) => g.level === 1 && g.r0 === b.r0)
    const yt = rowTop[b.r0] - (b.level === 0 ? HEAD + (nested ? GHEAD : 0) : GHEAD)
    const nestedEnd = b.level === 0 && boxes.some((g) => g.level === 1 && g.r1 === b.r1)
    const yb = rowTop[b.r1] + BH + (b.level === 0 ? CPAD + (nestedEnd ? GPAD : 0) : GPAD)
    s.shape('box', x0, yt, x1 - x0, yb - yt, b.level === 0 ? { stroke: '#868e96', width: 2 } : { stroke: '#adb5bd', style: 'dotted', width: 1 })
    const fs = b.level === 0 ? 22 : 16, w = x1 - x0 - 24
    s.text(x0 + 12, yt + (b.level === 0 ? 10 : 5), w, b.label, { fs, color: b.level === 0 ? INK : MUTED, align: b.side === 'r' ? 'right' : 'left' })
  }
  // nodes
  const geo = {}
  for (const d of nodes) {
    const w = d.o.w ?? BW, x = colX(d.col) + (BW - w) / 2 + (d.o.dx ?? 0), yy = rowTop[d.row]
    geo[d.id] = { x, y: yy, w, h: BH, cx: x + w / 2, cy: yy + BH / 2 }
    s.shape(d.kind, x, yy, w, BH, { fill: FILL[d.layer] })
    const fs = d.o.fs ?? 20, lines = d.text.split('\n').length
    s.text(x + 4, yy + (BH - lines * fs * 1.25) / 2, w - 8, d.text, { fs })
  }
  // arrows
  for (const [from, to, label = '', kind = spec.kind ?? 'ctl', o = {}] of spec.arrows) {
    const a = geo[from], b = geo[to]
    if (!a || !b) throw new Error(`arrow ${from} -> ${to}`)
    const A = byId[from], B = byId[to]
    let pts, lab
    if (A.row === B.row && !o.via) {
      const dir = B.col > A.col ? 1 : -1
      const x1 = dir > 0 ? a.x + a.w + 4 : a.x - 4, x2 = dir > 0 ? b.x - 4 : b.x + b.w + 4
      pts = [[x1, a.cy], [x2, b.cy]]
      const lines = label.split('\n').length
      const lw = o.lw ?? GAP - 4, lx = (x1 + x2) / 2 - lw / 2
      lab = label && [lx, a.cy - 8 - lines * 20, lw, 'center']
    } else if (A.col === B.col && !o.via) {
      const down = B.row > A.row
      const x = a.cx + (o.dx ?? 0)
      pts = down ? [[x, a.y + BH + 4], [x, b.y - 4]] : [[x, a.y - 4], [x, b.y + BH + 4]]
      const band = bandTop[down ? A.row : B.row]
      const lines = label.split('\n').length
      const side = o.side ?? (A.col === 3 ? 'l' : 'r')
      const lw = o.lw ?? 460
      lab = label && [side === 'r' ? x + 12 : x - 12 - lw, band + (FREE - lines * 20) / 2 - 4 + (o.ly ?? 0), lw, side === 'r' ? 'left' : 'right']
    } else {
      // explicit route: o.via = list of [x|'a'|'b', y|'band:N'] corner points
      const P = (p) => [p[0] === 'a' ? a.cx : p[0] === 'b' ? b.cx : p[0], typeof p[1] === 'string' ? bandTop[+p[1].slice(5)] + FREE / 2 : p[1]]
      const via = o.via.map(P)
      const start = o.from === 'r' ? [a.x + a.w + 4, a.cy] : o.from === 'l' ? [a.x - 4, a.cy] : o.from === 't' ? [a.cx, a.y - 4] : [a.cx, a.y + BH + 4]
      const end = o.to === 'l' ? [b.x - 4, b.cy] : o.to === 'r' ? [b.x + b.w + 4, b.cy] : o.to === 'b' ? [b.cx, b.y + BH + 4] : [b.cx, b.y - 4]
      pts = [start, ...via, end]
      const lw = o.lw ?? 300
      lab = label && [o.lx, typeof o.ly === 'string' ? bandTop[+o.ly.slice(5)] + FREE / 2 - 10 : o.ly, lw, o.la ?? 'left']
    }
    s.arrow(pts, { kind })
    if (lab) s.text(lab[0], lab[1], lab[2], label, { fs: o.fs ?? 16, color: kind === 'usb' ? USB : MUTED, align: lab[3] })
  }
  for (const [row, col, text, o = {}] of spec.notes ?? []) {
    const lines = text.split('\n').length
    s.text(colX(col) + (o.dx ?? 0), rowTop[row] + (BH - lines * 20) / 2 + (o.dy ?? 0), o.w ?? BW, text, { fs: o.fs ?? 16, color: o.color ?? MUTED, align: o.align ?? 'center' })
  }
  legend(s, bandTop[nRows - 1] + 10)
  s.save(dir + spec.file)
}

function legend(s, y) {
  const x = X0, w = WIDTH - 2 * X0
  s.shape('box', x, y, w, 170, { stroke: '#ced4da', width: 1 })
  s.text(x + 14, y + 8, 200, 'Legend', { fs: 18, align: 'left', color: MUTED })
  const sw = 148, g = (w - 28 - 6 * sw) / 5
  const items = [['app / JS', 'app'], ['OS, driver, USB', 'os'], ['MCU firmware', 'fw'], ['digital data', 'dig'], ['analog RF', 'rf'], ['mechanical', 'mech']]
  items.forEach(([t, k], i) => {
    const xx = x + 14 + i * (sw + g)
    s.shape('step', xx, y + 40, sw, 44, { fill: FILL[k] })
    s.text(xx + 4, y + 52, sw - 8, t, { fs: 16 })
  })
  const y2 = y + 104, sw2 = 116
  const shapes = [['step', 'processing\nstep'], ['data', 'data unit'], ['phys', 'physical\neffect']]
  shapes.forEach(([k, t], i) => {
    const xx = x + 14 + i * (sw2 + 16)
    s.shape(k, xx, y2, sw2, 50, {})
    s.text(xx + 4, y2 + 25 - t.split('\n').length * 10, sw2 - 8, t, { fs: 16 })
  })
  const ax = x + 14 + 3 * (sw2 + 16) + 20
  const arrows = [['ctl', 'control'], ['tlm', 'telemetry'], ['usb', 'drone USB (MSP)']]
  const aw = (x + w - 14 - ax) / 3
  arrows.forEach(([k, t], i) => {
    const xx = ax + i * aw
    s.arrow([[xx, y2 + 25], [xx + 60, y2 + 25]], { kind: k })
    s.text(xx + 68, y2 + 15, aw - 70, t, { fs: 16, align: 'left', color: k === 'usb' ? USB : INK })
  })
}

// =====================================================================================================================
// 1a. Control path: key press to motor
// =====================================================================================================================
draw({
  file: 'overview-control.excalidraw',
  title: 'Control path: key press to motor',
  sub: 'one D8 packet every 8.994 ms (111 Hz), over 47 hop channels',
  kind: 'ctl',
  nodes: {
    keys: [0, 0, 'keyboard,\ntouch sticks', 'os'],
    react: [0, 1, 'React UI', 'app'],
    ctrl: [0, 2, 'useController', 'app'],
    chans: [0, 3, '8 channels\n(µs)', 'dig', 'data'],
    link: [1, 3, 'D8Link\nsender', 'app'],
    sline: [1, 2, '"S 1500 1500 …"\ntext line', 'dig', 'data'],
    wsp: [1, 1, 'WebSerialPort', 'app', 'step', { fs: 19 }],
    wsa: [1, 0, 'Web Serial API', 'app'],
    chrome: [2, 0, 'Chromium\nserial', 'os'],
    tty: [2, 1, 'tty layer', 'os'],
    usbdrv: [2, 2, 'USB serial\ndriver', 'os'],
    hc: [2, 3, 'USB host\ncontroller', 'os'],
    bulk: [3, 3, 'USB bulk\npacket', 'dig', 'data'],
    cp: [4, 3, 'CP2102', 'os'],
    fifo: [4, 2, 'UART\nRX FIFO', 'fw'],
    parse: [4, 1, 'line parser', 'fw'],
    sticks: [4, 0, 'stick values', 'dig', 'data'],
    frame: [5, 0, 'D8 frame\n18 bytes', 'dig', 'data'],
    crc: [5, 1, 'CRC-16', 'fw'],
    air: [5, 2, 'air frame\n26 bytes', 'dig', 'data'],
    bits: [5, 3, '208 bits', 'dig', 'data'],
    step: [6, 3, 'tone step\n±1', 'fw'],
    nco: [6, 2, 'tone generator\n(NCO)', 'dig'],
    dac: [6, 1, 'digital→analog\n(DAC)', 'rf'],
    mix: [7, 1, 'mixer', 'rf'],
    hop: [6, 0, 'hop table\n47 channels', 'dig', 'data'],
    lo: [7, 0, 'carrier oscillator\n(LO)', 'rf'],
    pa: [7, 2, 'power amplifier\n(PA)', 'rf'],
    cur: [7, 3, 'antenna\ncurrent', 'rf', 'phys'],
    wave: [8, 3, 'EM wave\n2.4 GHz', 'rf', 'phys'],
    ant: [9, 3, 'antenna', 'rf'],
    lna: [9, 2, 'low-noise amp\n(LNA)', 'rf'],
    demod: [9, 1, '2-FSK\ndemod', 'dig'],
    sync: [9, 0, 'sync detect', 'dig'],
    addr: [10, 0, 'address\ncheck', 'dig'],
    crcok: [10, 1, 'CRC check', 'dig'],
    rxf: [10, 2, 'RX FIFO', 'dig'],
    spi: [10, 3, 'SPI read', 'os'],
    frsky: [11, 3, 'FrSky D\nreceiver', 'fw'],
    rc: [11, 2, 'RC channels', 'dig', 'data'],
    pid: [11, 1, 'PID loop', 'fw'],
    mmix: [11, 0, 'motor mixer', 'fw'],
    dshot: [12, 0, 'DShot600\nframes', 'dig', 'data'],
    esc: [12, 1, 'motor drivers\n(ESCs)', 'mech'],
    mot: [12, 2, 'motors', 'mech'],
    thrust: [12, 3, 'thrust', 'mech', 'phys'],
  },
  boxes: [
    { label: 'Laptop (macOS, Chrome or Electron)', ids: ['keys', 'hc'], c0: 0, c1: 3 },
    { label: 'browser main thread', ids: ['react', 'chans'], level: 1, c0: 0, c1: 3, side: 'r' },
    { label: 'Web Worker', ids: ['link', 'wsa'], level: 1, c0: 0, c1: 3 },
    { label: 'browser process, macOS kernel', ids: ['chrome', 'hc'], level: 1, c0: 0, c1: 3, side: 'r' },
    { label: 'ESP32 DevKit V1', ids: ['cp', 'cur'], c0: 0, c1: 3 },
    { label: 'UART and firmware (d8tone.c, packet.c)', ids: ['cp', 'bits'], level: 1, c0: 0, c1: 3 },
    { label: 'Wi-Fi PHY used as a 2-FSK transmitter', ids: ['step', 'cur'], level: 1, c0: 0, c1: 3 },
    { label: 'Drone (Tinyhawk, MATEKF411RX)', ids: ['ant', 'thrust'], c0: 0, c1: 3 },
    { label: 'CC2500 radio chip', ids: ['ant', 'spi'], level: 1, c0: 0, c1: 3 },
    { label: 'Betaflight on the STM32F411, ESCs, motors', ids: ['frsky', 'thrust'], level: 1, c0: 0, c1: 3 },
  ],
  arrows: [
    ['keys', 'react', 'keys,\ndrags'],
    ['react', 'ctrl', 'stick\ninput'],
    ['ctrl', 'chans', '120 Hz'],
    ['chans', 'link', 'postMessage'],
    ['link', 'sline', 'every\n8.994 ms'],
    ['sline', 'wsp', 'bytes'],
    ['wsp', 'wsa', 'write()'],
    ['wsa', 'chrome', 'IPC to the browser process'],
    ['chrome', 'tty', 'write()'],
    ['tty', 'usbdrv'],
    ['usbdrv', 'hc'],
    ['hc', 'bulk', 'USB 2.0, 12 Mbit/s'],
    ['bulk', 'cp', 'USB cable'],
    ['cp', 'fifo', '921600\nbaud'],
    ['fifo', 'parse', 'bytes'],
    ['parse', 'sticks', 'ch7 gate'],
    ['sticks', 'frame', 'µs × 1.5 → 12-bit values, + txid, hop counter'],
    ['frame', 'crc'],
    ['crc', 'air', '+ preamble,\nsync D3 91'],
    ['air', 'bits', 'MSB first'],
    ['bits', 'step', '7731 CPU cycles per bit (31 kbaud)'],
    ['step', 'nco', '±39 kHz'],
    ['nco', 'dac', 'digital\nI/Q'],
    ['dac', 'mix', 'baseband'],
    ['hop', 'lo', 'next channel\n+ FOFS, each slot', 'ctl', { side: 'r', lw: 160 }],
    ['lo', 'mix', 'LO'],
    ['mix', 'pa', '2404–2478\nMHz'],
    ['pa', 'cur', 'power\ncode'],
    ['cur', 'wave', 'radiates'],
    ['wave', 'ant', 'through the air'],
    ['ant', 'lna'],
    ['lna', 'demod'],
    ['demod', 'sync', 'bits'],
    ['sync', 'addr', 'bytes after sync word D3 91', 'ctl', { side: 'r' }],
    ['addr', 'crcok', 'byte 1\n= txid'],
    ['crcok', 'rxf', 'CRC OK'],
    ['rxf', 'spi', '20 bytes'],
    ['spi', 'frsky', 'txid match, then hop to the next channel'],
    ['frsky', 'rc', '× 2/3 → µs'],
    ['rc', 'pid', 'setpoint'],
    ['pid', 'mmix'],
    ['mmix', 'dshot', '4 motor outputs', 'ctl', { side: 'r' }],
    ['dshot', 'esc'],
    ['esc', 'mot', '3-phase'],
    ['mot', 'thrust', 'props'],
  ],
})

// =====================================================================================================================
// 3. Telemetry path: the reply in the air to the screen (beat 3; starts where timeline.excalidraw ends)
// =====================================================================================================================
draw({
  file: 'overview-telemetry.excalidraw',
  title: 'Telemetry path: reply in the air to screen',
  sub: 'one reply per trigger (about 8.5 per second), decoded in the browser',
  kind: 'tlm',
  nodes: {
    wave: [0, 0, 'EM wave\n2.4 GHz', 'rf', 'phys'],
    ant: [1, 0, 'antenna', 'rf'],
    lna: [1, 1, 'low-noise amp\n(LNA)', 'rf'],
    mix: [1, 2, 'mixer', 'rf'],
    adc: [1, 3, 'analog→digital\n(ADC)', 'rf'],
    dump: [2, 3, 'RF dump\nto RAM', 'fw'],
    box: [2, 2, 'boxcar ÷64', 'fw'],
    energy: [2, 1, 'energy\ncheck', 'fw'],
    pack: [2, 0, 'int4 pack', 'fw'],
    ev: [3, 0, '"EV tlm" line\n+ 2000 bytes', 'dig', 'data', { fs: 18 }],
    utx: [3, 1, 'UART\nTX FIFO', 'fw'],
    cp: [3, 2, 'CP2102', 'os'],
    bulk: [3, 3, 'USB bulk\npacket', 'dig', 'data'],
    hc: [4, 3, 'USB host\ncontroller', 'os'],
    usbdrv: [4, 2, 'USB serial\ndriver', 'os'],
    tty: [4, 1, 'tty layer', 'os'],
    chrome: [4, 0, 'Chromium\nserial', 'os'],
    wsa: [5, 0, 'Web Serial API', 'app'],
    reader: [5, 1, 'D8Link\nreader', 'app'],
    crc32: [5, 2, 'CRC-32 check', 'app'],
    unpack: [5, 3, 'int4 → int8', 'app'],
    dc: [6, 3, 'remove DC', 'app'],
    shift: [6, 2, 'frequency\nshift', 'app'],
    fir: [6, 1, 'FIR low-pass', 'app'],
    fm: [6, 0, 'FM\ndiscriminator', 'app'],
    clock: [7, 0, 'clock\nrecovery', 'app'],
    slice: [7, 1, 'bit slicer', 'app'],
    sync: [7, 2, 'sync search', 'app'],
    crc16: [7, 3, 'CRC-16,\ntxid check', 'app'],
    fields: [8, 3, 'reply fields', 'dig', 'data'],
    state: [8, 2, 'telemetry\nstate', 'app'],
    ui: [8, 1, 'React UI', 'app'],
    show: [8, 0, '3D drone,\ngauges', 'app'],
    tid: [9, 3, '"TID n" line', 'dig', 'data'],
  },
  boxes: [
    { label: 'ESP32 DevKit V1', ids: ['ant', 'bulk'], c0: 0, c1: 3, side: 'r' },
    { label: 'Wi-Fi PHY receive chain', ids: ['ant', 'adc'], level: 1, c0: 0, c1: 3, side: 'r' },
    { label: 'firmware (tlm_cap.c, d8tone.c)', ids: ['dump', 'bulk'], level: 1, c0: 0, c1: 3 },
    { label: 'Laptop (macOS, Chrome or Electron)', ids: ['hc', 'tid'], c0: 0, c1: 3 },
    { label: 'macOS kernel, browser process', ids: ['hc', 'chrome'], level: 1, c0: 0, c1: 3 },
    { label: 'Web Worker', ids: ['wsa', 'unpack'], level: 1, c0: 0, c1: 3, side: 'r' },
    { label: 'WASM demodulator (demod/src/d8demod.c)', ids: ['dc', 'crc16'], level: 1, c0: 0, c1: 3 },
    { label: 'Web Worker → main thread', ids: ['fields', 'tid'], level: 1, c0: 0, c1: 3, side: 'l' },
  ],
  arrows: [
    ['wave', 'ant', 'through the air', 'tlm', { side: 'r' }],
    ['ant', 'lna'],
    ['lna', 'mix'],
    ['mix', 'adc', 'LO on\nch k+1'],
    ['adc', 'dump', '10-bit I/Q, 16 MS/s, 9 ms'],
    ['dump', 'box', 'ring\nbuffer'],
    ['box', 'energy', '250 kS/s'],
    ['energy', 'pack', 'reply\nseen'],
    ['pack', 'ev', 'skip the first 1 ms: 2000 samples, 1 byte each', 'tlm', { side: 'r' }],
    ['ev', 'utx', 'idle\ngaps'],
    ['utx', 'cp', '921600\nbaud'],
    ['cp', 'bulk'],
    ['bulk', 'hc', 'USB cable'],
    ['hc', 'usbdrv'],
    ['usbdrv', 'tty'],
    ['tty', 'chrome', 'read()'],
    ['chrome', 'wsa', 'IPC to the worker'],
    ['wsa', 'reader', 'bytes'],
    ['reader', 'crc32', 'header\n+ payload'],
    ['crc32', 'unpack'],
    ['unpack', 'dc', 'I/Q samples, 250 kS/s'],
    ['dc', 'shift'],
    ['shift', 'fir', '−150…+150\nkHz sweep'],
    ['fir', 'fm', '35–75 kHz'],
    ['fm', 'clock', 'minus carrier offset, ÷ deviation', 'tlm', { side: 'r' }],
    ['clock', 'slice', 'symbols'],
    ['slice', 'sync', 'bits'],
    ['sync', 'crc16', 'D3 91'],
    ['crc16', 'fields', '18 bytes'],
    ['fields', 'state', 'A1, RSSI,\nhub, FAST'],
    ['state', 'ui', 'postMessage\n50 Hz'],
    ['ui', 'show'],
    ['fields', 'tid', 'ack to the\nESP32', 'tlm', { lw: 150 }],
  ],
  notes: [[0, 1, 'the drone\'s reply on ch k+1,\n1.38 ms after the trigger ends', { w: 2 * BW + GAP, align: 'left', dx: 0 }]],
})
// =====================================================================================================================
// 2. Timeline (beat 2): three slots to scale around a telemetry trigger. slot-detail.excalidraw has the firmware loop.
// =====================================================================================================================
const SLOT = 8.994
function slotTimeline(s, y0) {
  // to scale: three slots (k = trigger, k+1 = listen, k+2 = normal)
  const x0 = X0 + 150, W = WIDTH - X0 - x0, ms = W / (3 * SLOT), X = (t) => x0 + t * ms
  const lanes = [['ESP32 sends', 0], ['ESP32 listens', 1], ['drone sends', 2]]
  const LH = 40, LG = 14, top = y0 + 30
  for (const [name, i] of lanes) s.text(X0, top + i * (LH + LG) + 8, 140, name, { fs: 18, align: 'left' })
  for (let k = 0; k <= 3; k++) {
    const x = X(k * SLOT)
    s.arrow([[x, top - 14], [x, top + 3 * (LH + LG)]], { kind: 'ctl', head: false, width: 1 })
    s.text(k === 3 ? x - 120 : x - 60, top + 3 * (LH + LG) + 4, 120, k === 0 ? '0' : `${(k * SLOT).toFixed(3)} ms`, { fs: 16, color: MUTED, align: k === 3 ? 'right' : 'center' })
  }
  const slotName = ['slot k: trigger', 'slot k+1: not sent', 'slot k+2: normal']
  slotName.forEach((t, k) => s.text(X(k * SLOT), y0, SLOT * ms, t, { fs: 18 }))
  const bar = (lane, t0, t1, fill, label, kind = 'data', fs = 16) => {
    const yy = top + lane * (LH + LG)
    s.shape(kind, X(t0), yy, (t1 - t0) * ms, LH, { fill })
    if (label) s.text(X(t0), yy + (LH - 20) / 2, (t1 - t0) * ms, label, { fs })
  }
  const RT = 0.39, PK = 6.7
  bar(0, 0, RT, FILL.rf, '', 'step')
  bar(0, RT, RT + PK, FILL.dig, 'trigger packet, 6.70 ms')
  bar(0, 2 * SLOT, 2 * SLOT + RT, FILL.rf, '', 'step')
  bar(0, 2 * SLOT + RT, 2 * SLOT + RT + PK, FILL.dig, 'packet, ch k+2')
  const c0 = RT + PK + 0.3
  bar(1, c0, c0 + 1, FILL.os, 'skip', 'step', 14)
  bar(1, c0 + 1, c0 + 9, FILL.fw, 'capture on ch k+1, 9 ms', 'step')
  const r0 = RT + PK + 1.38
  bar(2, r0, r0 + PK, FILL.dig, 'reply, ch k+1')
  s.text(X(2 * SLOT) + 8, top + 2 * (LH + LG) + 1, X(3 * SLOT) - X(2 * SLOT) - 12, 'the reply starts 1.38 ms\nafter the trigger ends', { fs: 15, color: MUTED, align: 'left' })
  s.text(X(2 * SLOT + RT + PK) + 4, top + 10, X(3 * SLOT) - X(2 * SLOT + RT + PK) - 4, 'idle', { fs: 16, color: MUTED })
  s.text(X0, top + 3 * (LH + LG) + 30, WIDTH - 2 * X0, 'to scale; red = LO retune (at most 0.39 ms measured). Slots sit on a fixed 8.994 ms grid (absolute deadlines).', { fs: 16, color: MUTED, align: 'left' })
  return 30 + 3 * (LH + LG) + 60
}

{
  const s = scene()
  s.text(X0, 0, WIDTH - 2 * X0, 'Telemetry trigger: three slots, to scale', { fs: 32, align: 'left' })
  s.text(X0, 50, WIDTH - 2 * X0, 'every 12 slots or more, slot k is a trigger; the ESP32 skips slot k+1 and listens on its channel', { fs: 18, color: MUTED, align: 'left' })
  const h = slotTimeline(s, 100)
  legend(s, 100 + h + 10)
  s.save(dir + 'timeline.excalidraw')
}

// =====================================================================================================================
// 4. Slot detail (ARCHITECTURE.md): the firmware per-slot loop and the trigger branch
// =====================================================================================================================
draw({
  file: 'slot-detail.excalidraw',
  title: 'Firmware slot loop and the telemetry trigger',
  sub: 'every 8.994 ms; a trigger every 12 slots or more (after the last capture is out and acked)',
  kind: 'ctl',
  nodes: {
    drain: [0, 0, 'UART drain', 'fw'],
    sticks: [0, 1, 'stick values', 'dig', 'data'],
    build: [0, 2, 'build frame', 'fw'],
    due: [0, 3, 'trigger due?', 'fw'],
    crc: [1, 3, 'CRC-16', 'fw'],
    wait: [1, 2, 'wait for\nslot start', 'fw'],
    retune: [1, 1, 'LO retune', 'rf'],
    key: [1, 0, 'key 208 bits', 'fw'],
    unkey: [2, 0, 'unkey', 'fw'],
    ship: [2, 1, 'ship capture\nbytes', 'fw'],
    next: [2, 2, 'next slot', 'fw'],
    tk: [3, 0, 'trigger\npacket sent', 'dig', 'data'],
    tun: [3, 1, 'unkey', 'fw'],
    tre: [3, 2, 'retune to\nch k+1', 'rf'],
    gain: [3, 3, 'RX gain 40', 'fw'],
    cap: [4, 3, 'capture 9 ms', 'fw'],
    box: [4, 2, 'boxcar ÷64', 'fw'],
    energy: [4, 1, 'energy\ncheck', 'fw'],
    resume: [4, 0, 'resume at\nslot k+2', 'fw'],
    ev: [5, 0, '"EV tlm" line\n+ 2000 bytes', 'dig', 'data', { fs: 18 }],
    host: [5, 1, 'WASM decode', 'app'],
    tid: [5, 2, '"TID n" line', 'dig', 'data'],
    ntrig: [5, 3, 'next trigger\nat ≥ k+12', 'fw'],
    drx: [6, 0, 'trigger\nreceived', 'fw'],
    dhop: [6, 1, 'hop to\nch k+1', 'fw'],
    dbuild: [6, 2, 'build reply', 'fw'],
    dtx: [6, 3, 'reply on\nch k+1', 'dig', 'data'],
  },
  boxes: [
    { label: 'ESP32 firmware, every slot (run_hop in d8tone.c)', ids: ['drain', 'next'], c0: 0, c1: 3 },
    { label: 'trigger slot k: listen instead of sending k+1', ids: ['tk', 'ntrig'], c0: 0, c1: 3 },
    { label: 'ESP32 firmware', ids: ['tk', 'resume'], level: 1, c0: 0, c1: 3, side: 'r' },
    { label: 'shipping, host, ack', ids: ['ev', 'ntrig'], level: 1, c0: 0, c1: 3, side: 'r' },
    { label: 'Drone, meanwhile (Betaflight cc2500_frsky_d.c)', ids: ['drx', 'dtx'], c0: 0, c1: 3 },
  ],
  arrows: [
    ['drain', 'sticks', '"S" lines'],
    ['sticks', 'build', 'txid,\ncounter k'],
    ['build', 'due'],
    ['due', 'crc', 'no: byte 3 = 0, byte 4 = k;  yes: byte 3 = 2, byte 4 = tid', 'ctl', { lw: 560 }],
    ['crc', 'wait', '26 bytes'],
    ['wait', 'retune', 'ch k\n+ FOFS'],
    ['retune', 'key', '≤ 0.39 ms'],
    ['key', 'unkey', '6.70 ms of 2-FSK; on a trigger slot, go to the trigger row below', 'ctl', { side: 'r', lw: 620 }],
    ['unkey', 'ship', 'idle\n~1.9 ms'],
    ['ship', 'next'],
    ['tk', 'tun', 'last bit'],
    ['tun', 'tre'],
    ['tre', 'gain'],
    ['gain', 'cap', '16 MS/s ring capture, starts ~0.2–0.4 ms after the last bit'],
    ['cap', 'box'],
    ['box', 'energy', '250 kS/s'],
    ['energy', 'resume', 'reply\nseen'],
    ['resume', 'ev', 'skip 1 ms, int4; no reply energy: "EV tlm_drop" and one retry, same tid', 'ctl', { side: 'r', lw: 700 }],
    ['ev', 'host', 'idle gaps'],
    ['host', 'tid', 'next tid'],
    ['tid', 'ntrig', 'UART'],
    ['drx', 'dhop', 'txid OK'],
    ['dhop', 'dbuild', 'byte 3\n% 4 = 2'],
    ['dbuild', 'dtx', 'wait\n1380 µs'],
  ].map((a) => (['ev', 'host', 'tid', 'dtx', 'dbuild'].includes(a[0]) || a[1] === 'ev' ? [a[0], a[1], a[2] ?? '', 'tlm', a[4]] : a)),
  notes: [],
})

// =====================================================================================================================
// 5. Bind (also shows the optional drone USB / MSP readback)
// =====================================================================================================================
draw({
  file: 'bind.excalidraw',
  title: 'Bind: the drone learns this ESP32\'s identity',
  sub: 'one click in the Pairing panel; about 6 s of bind packets, then a confirm link (at most 5 s)',
  kind: 'ctl',
  nodes: {
    btn: [0, 1, 'Bind button', 'app'],
    flow: [1, 1, 'bind flow\n(worker)', 'app'],
    bindl: [1, 0, '"FOFS 0",\n"BIND 40"', 'dig', 'data'],
    mspb: [1, 2, 'MSP2_BETAFLIGHT\n_BIND', 'dig', 'data', { fs: 15 }],
    nvs: [2, 0, 'NVS identity', 'fw'],
    tab: [2, 1, 'hop table\n47 channels', 'dig', 'data'],
    pkt: [3, 1, 'bind packet', 'dig', 'data'],
    crc: [3, 0, 'CRC-16', 'fw'],
    key: [4, 0, 'key on ch 0', 'fw'],
    wave: [4, 1, 'EM wave\n2.4 GHz', 'rf', 'phys'],
    cdc: [2, 2, 'USB CDC', 'os'],
    msp: [2, 3, 'Betaflight\nMSP', 'fw'],
    mode: [3, 3, 'bind mode', 'fw'],
    ch0: [3, 2, 'CC2500\non ch 0', 'rf'],
    sweep: [4, 2, 'offset sweep', 'fw'],
    lock: [4, 3, 'lock offset', 'fw'],
    b1: [5, 3, 'Bind1', 'fw'],
    b2: [5, 2, 'Bind2', 'fw'],
    list: [6, 2, 'hop list\n47 channels', 'dig', 'data'],
    save: [6, 3, 'save EEPROM', 'fw'],
    stop: [7, 0, 'STOP\nafter 6 s', 'app'],
    linkl: [7, 1, '"LINK",\n"TLM …"', 'dig', 'data'],
    d8: [7, 2, 'D8 link\n(ESP32)', 'fw'],
    rep: [7, 3, 'telemetry\nreply', 'dig', 'data'],
    dec: [8, 3, 'WASM decode', 'app'],
    match: [8, 2, 'txid match', 'app'],
    bound: [8, 1, 'bound', 'app'],
    fmsp: [9, 3, 'Betaflight\nMSP', 'fw'],
    fcdc: [9, 2, 'USB CDC', 'os'],
    fwsa: [9, 1, 'Web Serial API', 'app'],
    poll: [9, 0, 'MSP poller\n(worker)', 'app'],
  },
  boxes: [
    { label: 'Laptop (UI and Web Worker)', ids: ['btn', 'mspb'], c0: 0, c1: 3 },
    { label: 'ESP32 DevKit V1', ids: ['nvs', 'wave'], c0: 0, c1: 1, side: 'r' },
    { label: 'Drone', ids: ['cdc', 'save'], c0: 2, c1: 3, side: 'r' },
    { label: 'Confirm: worker, ESP32 and drone', ids: ['stop', 'bound'], c0: 0, c1: 3 },
    { label: 'Drone USB, also outside bind: RC, attitude, motors, status', ids: ['fmsp', 'poll'], c0: 0, c1: 3, side: 'r' },
  ],
  arrows: [
    ['btn', 'flow', 'postMessage', 'ctl', { side: 'r', lw: 200 }],
    ['flow', 'bindl', '①'],
    ['flow', 'mspb', '② after OK'],
    ['bindl', 'nvs', 'USB serial', 'ctl', { side: 'r', lw: 160 }],
    ['nvs', 'tab', 'start,\nstep'],
    ['tab', 'pkt', 'idx 0, 5 … 45', 'ctl', { side: 'r', lw: 140 }],
    ['pkt', 'crc', 'txid +\n5 entries'],
    ['crc', 'key', 'every 8.994 ms, ch 0 + FOFS', 'ctl', { side: 'r', lw: 240 }],
    ['key', 'wave'],
    ['wave', 'sweep'],
    ['mspb', 'cdc', 'drone USB', 'usb', { side: 'r', lw: 120 }],
    ['cdc', 'msp'],
    ['msp', 'mode', 'bind request', 'usb', { side: 'l', lw: 120 }],
    ['mode', 'ch0', 'ADDR\n0x03'],
    ['ch0', 'sweep', '−126 … +126, step 5 per 50 ms', 'ctl', { side: 'r', lw: 400 }],
    ['sweep', 'lock', 'CRC OK,\nLQI > 50'],
    ['lock', 'b1', 'idx 0: txid, entries 0–4', 'ctl', { side: 'l', lw: 300 }],
    ['b1', 'b2', 'idx 5 …\n45 in order'],
    ['b2', 'list', 'after idx 45', 'ctl', { side: 'r', lw: 300 }],
    ['list', 'save'],
    ['stop', 'linkl', 'confirm'],
    ['linkl', 'd8', 'arming\noff'],
    ['d8', 'rep', 'drone\nanswers'],
    ['rep', 'dec', 'capture', 'tlm', { side: 'l', lw: 200 }],
    ['dec', 'match', 'reply\nbytes 1–2'],
    ['match', 'bound'],
    ['fmsp', 'fcdc', '', 'usb'],
    ['fcdc', 'fwsa', 'MSP\nframes', 'usb'],
    ['fwsa', 'poll', '', 'usb'],
    ['poll', 'bound', 'or: status shows failsafe off', 'usb', { from: 't', to: 'b', via: [['a', 'band:8'], ['b', 'band:8']], lx: colX(1) + BW / 2 + 16, ly: 'band:8', lw: 360 }],
  ].map((a) => (['d8', 'rep', 'dec', 'match'].includes(a[0]) ? [a[0], a[1], a[2] ?? '', 'tlm', a[4]] : a)),
  notes: [],
})
