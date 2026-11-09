// Mock transports: a simulated D8 TX firmware (protocol v1) and a simulated Betaflight MSP drone.
import { crc32, frame, frameV2, MSP2_BETAFLIGHT_BIND, scanFrame, SLOT_S, type Clock, type SerialPort } from '@d8tx/core'

const enc = new TextEncoder()
const dec = new TextDecoder()

/** Chunk queue exposed as an AsyncIterable; ends on close. */
class ByteQueue {
  private q: Uint8Array[] = []
  private wake: (() => void) | null = null
  private ended = false
  push(b: Uint8Array): void {
    if (this.ended) return
    this.q.push(b)
    this.wake?.()
  }
  end(): void {
    this.ended = true
    this.wake?.()
  }
  iterable(): AsyncIterable<Uint8Array> {
    const self = this
    return {
      async *[Symbol.asyncIterator]() {
        for (;;) {
          while (self.q.length) yield self.q.shift()!
          if (self.ended) return
          await new Promise<void>((r) => (self.wake = r))
          self.wake = null
        }
      },
    }
  }
}

export interface MockCapture {
  /** payload as shipped by the firmware (int4 packed, bits=4) */
  payload: Uint8Array
  fs: number
  bits: number
  n: number
}

export interface MockPortOptions {
  clock: Clock
  /** captures replayed as `EV tlm` after each trigger (cycled); none = telemetry never answers */
  captures?: MockCapture[]
  /** answer ERR to the TLM recipe (older firmware) */
  tlmErr?: boolean
  /** INFO pwr_max (default 127); null omits the key like old firmware. */
  pwrMax?: number | null
  /** ms between telemetry triggers (12 slots) */
  triggerMs?: number
  /** Like the firmware: a capture goes out over this many ms (header first, trailing bytes last), and a STAT that
   * arrives meanwhile is dropped without a reply. 0/undefined: the capture arrives at once. */
  shipMs?: number
  /** Like the firmware's 128-byte UART RX FIFO, which is not drained while a slot is keyed/listening: while linked,
   * bytes beyond this many within one slot are lost (a torn line ends the link with an error). */
  rxFifoBytes?: number
  /** ms until a BIND ends by itself (firmware: 30 s) */
  bindTimeoutMs?: number
}

/** Simulated ESP32 firmware. Test helpers: lines, sticks timestamps, emit(). */
export class MockPort implements SerialPort {
  lines: string[] = []
  tSticks: number[] = []
  linked = false
  armok = false
  closed = false
  opened = false
  outWaiting = 0
  /** drop all writes (simulates an unplugged / stalled device) */
  muted = false
  /** keep emitting replies when true; when false the device falls silent */
  tlmOn = false
  tid = 0
  slots = 0
  fofs = 0
  binding = false
  /** persisted identity */
  txid = '42B2'
  hopStart = 2
  hopStep = 55
  private bindTimer: unknown = null
  private opts: MockPortOptions
  private q = new ByteQueue()
  private rx = ''
  private silenceTimer: unknown = null
  private trigTimer: unknown = null
  private capIdx = 0
  private waitingTid = false
  private tidTimer: unknown = null
  private shipping = false
  private fifoUsed = 0
  private fifoSlot = -1
  /** STATs dropped because a capture was going out */
  statDropped = 0

  constructor(opts: MockPortOptions) {
    this.opts = opts
  }

  async open(): Promise<void> {
    this.opened = true
  }
  read(): AsyncIterable<Uint8Array> {
    return this.q.iterable()
  }
  async close(): Promise<void> {
    this.closed = true
    this.clearTimers()
    this.q.end()
  }

  async write(data: Uint8Array): Promise<void> {
    if (this.muted || this.closed) return
    if (this.linked && this.opts.rxFifoBytes) {
      const slot = Math.floor(this.opts.clock.now() / (SLOT_S * 1000))
      if (slot !== this.fifoSlot) {
        this.fifoSlot = slot
        this.fifoUsed = 0
      }
      const room = Math.max(0, this.opts.rxFifoBytes - this.fifoUsed)
      this.fifoUsed += Math.min(room, data.length)
      if (data.length > room) data = data.subarray(0, room)
    }
    this.rx += dec.decode(data)
    let i: number
    while ((i = this.rx.indexOf('\n')) >= 0) {
      const ln = this.rx.slice(0, i).replace(/\r$/, '')
      this.rx = this.rx.slice(i + 1)
      if (ln) {
        this.lines.push(ln)
        this.cmd(ln)
      }
    }
  }

  /** Device -> host line. */
  emit(s: string): void {
    this.q.push(enc.encode(s + '\n'))
  }
  emitBytes(b: Uint8Array): void {
    this.q.push(b)
  }

  private clearTimers(): void {
    for (const t of [this.silenceTimer, this.trigTimer, this.tidTimer, this.bindTimer]) if (t !== null) this.opts.clock.clearTimeout(t)
    this.silenceTimer = this.trigTimer = this.tidTimer = this.bindTimer = null
    this.shipping = false
  }

  private endBind(why: string): void {
    if (!this.binding) return
    this.binding = false
    if (this.bindTimer !== null) this.opts.clock.clearTimeout(this.bindTimer)
    this.bindTimer = null
    if (!this.muted) this.emit(`EV bind_end why=${why}`)
  }

  private idReply(): string {
    return `OK txid=${this.txid} start=${this.hopStart} step=${this.hopStep}`
  }

  private endLink(why: string): void {
    if (!this.linked) return
    this.linked = false
    this.clearTimers()
    if (this.muted) return // a dead device says nothing
    this.emit(`EV link_end why=${why} slots=${this.slots} late_max_us=7 retune_max_us=3`)
  }

  private armSilence(): void {
    if (this.silenceTimer !== null) this.opts.clock.clearTimeout(this.silenceTimer)
    this.silenceTimer = this.opts.clock.setTimeout(() => this.endLink('timeout'), this.timeoutMs)
  }
  private timeoutMs = 300

  private cmd(ln: string): void {
    const w = ln.split(/\s+/)
    const c = w[0]
    if (c === 'S') {
      if (!this.linked) this.emit('OK')
      else {
        this.tSticks.push(this.opts.clock.now())
        this.slots++
        this.armSilence()
      }
      return
    }
    if (c === 'TID' && this.linked) {
      this.tid = Number(w[1]) & 31
      if (this.waitingTid) {
        this.waitingTid = false
        this.scheduleTrigger()
      }
      return
    }
    if (this.linked && c === 'STAT' && this.shipping) {
      this.statDropped++
      return
    }
    if (this.linked && c !== 'STOP' && c !== 'U' && c !== 'STAT') {
      this.endLink('err')
      this.emit(['PING', 'INFO', 'FOFS', 'TLM', 'ARMOK', 'LINK', 'ID', 'BIND'].includes(c) ? 'ERR busy link active' : 'ERR unknown cmd')
      return
    }
    if (this.binding && !['STOP', 'U', 'STAT', 'PING', 'INFO', 'S'].includes(c)) {
      return this.emit(['ID', 'BIND', 'FOFS', 'LINK', 'TLM', 'ARMOK', 'TID'].includes(c) ? 'ERR busy binding' : 'ERR unknown cmd')
    }
    switch (c) {
      case 'ID': {
        if (w.length === 1) return this.emit(this.idReply())
        if (w[1] === 'new') {
          const r = () => Math.floor(Math.random() * 256)
          this.txid = (r() << 8 | r()).toString(16).padStart(4, '0').toUpperCase()
          this.hopStart = 1 + Math.floor(Math.random() * 255)
          this.hopStep = 1 + Math.floor(Math.random() * 255)
          return this.emit(this.idReply())
        }
        const st = Number(w[2])
        const sp = Number(w[3])
        if (w.length !== 4 || !/^[0-9a-fA-F]{4}$/.test(w[1]) || !Number.isInteger(st) || !Number.isInteger(sp) || st < 0 || st > 255 || sp < 1 || sp > 255) {
          return this.emit('ERR range id')
        }
        this.txid = w[1].toUpperCase()
        this.hopStart = st
        this.hopStep = sp
        return this.emit(this.idReply())
      }
      case 'BIND': {
        if (w[1] !== undefined && !(Number(w[1]) >= 0 && Number(w[1]) <= 127)) return this.emit('ERR range power')
        this.binding = true
        this.bindTimer = this.opts.clock.setTimeout(() => this.endBind('timeout'), this.opts.bindTimeoutMs ?? 30000)
        return this.emit('OK')
      }
      case 'PING':
        return this.emit('OK proto=1')
      case 'INFO':
        return this.emit(`OK proto=1 fw=d8tx-v1 slot_us=8994 channels=47 ${this.opts.pwrMax === null ? '' : `pwr_max=${this.opts.pwrMax ?? 127} `}fofs_max_hz=200000 timeout_max_ms=1000 txid=${this.txid} bench=0`)
      case 'STAT':
        return this.emit(`OK keyed=${+this.linked} link=${+this.linked} fofs=${this.fofs} armok=${+this.armok} slots=${this.slots} bind=${+this.binding}`)
      case 'FOFS': {
        const v = Number(w[1])
        if (!Number.isFinite(v) || Math.abs(v) > 200000) return this.emit('ERR range fofs')
        this.fofs = v
        return this.emit('OK')
      }
      case 'TID':
        this.tid = Number(w[1]) & 31
        return this.emit(`OK tid=${this.tid}`)
      case 'TLM':
        if (this.opts.tlmErr) return this.emit('ERR unknown cmd')
        this.tlmOn = w[1] !== '0'
        return this.emit('OK')
      case 'ARMOK':
        this.armok = true
        return this.emit('OK')
      case 'LINK': {
        const p = Number(w[1])
        if (!(p >= 0 && p <= 127)) return this.emit('ERR range power')
        this.timeoutMs = Number(w[2] ?? 300)
        this.linked = true
        this.slots = 0
        this.armSilence()
        if (this.tlmOn) this.scheduleTrigger()
        return this.emit('OK')
      }
      case 'STOP':
      case 'U':
        this.endLink('stop')
        this.endBind('stop')
        this.armok = false
        return this.emit('OK')
      default:
        return this.emit('ERR unknown cmd')
    }
  }

  private scheduleTrigger(): void {
    const caps = this.opts.captures
    if (!caps || !caps.length) return
    if (this.trigTimer !== null) this.opts.clock.clearTimeout(this.trigTimer)
    this.trigTimer = this.opts.clock.setTimeout(() => {
      this.trigTimer = null
      if (!this.linked || !this.tlmOn) return
      const cap = caps[this.capIdx++ % caps.length]
      const hdr =
        `EV tlm k=${this.slots} ch=100 tid=${this.tid} fs=${cap.fs} n=${cap.n} dec=64 bits=${cap.bits} ` +
        `bytes=${cap.payload.length} crc=${crc32(cap.payload).toString(16).padStart(8, '0')}`
      const out = new Uint8Array(hdr.length + 1 + cap.payload.length + 1)
      out.set(enc.encode(hdr + '\n'))
      out.set(cap.payload, hdr.length + 1)
      out[out.length - 1] = 10
      const ship = this.opts.shipMs ?? 0
      if (ship > 0) {
        const cut = hdr.length + 1 + (cap.payload.length >> 1)
        this.q.push(out.subarray(0, cut))
        this.shipping = true
        this.opts.clock.setTimeout(() => {
          this.shipping = false
          if (this.linked) this.q.push(out.subarray(cut))
        }, ship)
      } else this.q.push(out)
      // ack=1: the next trigger waits for the host's TID (at most 1 s, then repeats the same tid)
      this.waitingTid = true
      this.tidTimer = this.opts.clock.setTimeout(() => {
        if (this.waitingTid) {
          this.waitingTid = false
          this.scheduleTrigger()
        }
      }, 1000)
    }, this.opts.triggerMs ?? SLOT_S * 1000 * 12)
  }
}

export interface MockDroneState {
  rc: number[]
  attitude: [number, number, number]
  armed: boolean
  motors: number[]
  rssi: number
  /** MSP_STATUS arming-disable mask (bit 2 = RX_FAILSAFE); 0 when absent */
  armingDisable?: number
}

/** Simulated Betaflight MSP FC (RC, ATTITUDE, STATUS, MOTOR, ANALOG; v2 MSP2_BETAFLIGHT_BIND). */
export class MockDronePort implements SerialPort {
  /** MSP2_BETAFLIGHT_BIND requests received */
  binds = 0
  /** answer MSP2_BETAFLIGHT_BIND with an error frame (receiver cannot bind) */
  bindError = false
  state: MockDroneState = { rc: [1500, 1500, 1000, 1500, 1000, 1000, 1000, 1000], attitude: [1.5, -2.0, 90], armed: false, motors: [0, 0, 0, 0], rssi: 800 }
  requests: number[] = []
  closed = false
  outWaiting = 0
  private q = new ByteQueue()
  private buf: number[] = []

  async open(): Promise<void> {}
  read(): AsyncIterable<Uint8Array> {
    return this.q.iterable()
  }
  async close(): Promise<void> {
    this.closed = true
    this.q.end()
  }

  async write(data: Uint8Array): Promise<void> {
    for (const b of data) this.buf.push(b)
    for (;;) {
      let f
      try {
        f = scanFrame(this.buf)
      } catch {
        continue
      }
      if (!f) break
      this.requests.push(f.cmd)
      this.q.push(f.v2 ? this.respondV2(f.cmd) : this.respond(f.cmd))
    }
  }

  private respondV2(cmd: number): Uint8Array {
    const ok = cmd === MSP2_BETAFLIGHT_BIND && !this.bindError
    if (cmd === MSP2_BETAFLIGHT_BIND) this.binds++
    const out = frameV2(cmd)
    out[2] = ok ? 0x3e : 0x21 // '>' or '!'; the crc starts after the direction byte
    return out
  }

  private respond(cmd: number): Uint8Array {
    const s = this.state
    let p: number[] = []
    const u16 = (v: number): number[] => [v & 255, (v >> 8) & 255]
    const i16 = (v: number): number[] => u16(v & 0xffff)
    if (cmd === 105) p = s.rc.flatMap(u16)
    else if (cmd === 108) p = [...i16(Math.round(s.attitude[0] * 10)), ...i16(Math.round(s.attitude[1] * 10)), ...i16(Math.round(s.attitude[2]))]
    else if (cmd === 104) p = [...s.motors, 0, 0, 0, 0].slice(0, 8).flatMap(u16)
    else if (cmd === 110) p = [126, ...u16(0), ...u16(s.rssi), ...i16(0), ...u16(1260)]
    else if (cmd === 101) {
      const flags = s.armed ? 1 : 0
      p = [...u16(125), ...u16(0), ...u16(0), flags, 0, 0, 0, 0, ...u16(10), ...u16(0), 0, 26, ...[0, 8, 16, 24].map((k) => ((s.armingDisable ?? 0) >>> k) & 255)]
    }
    const body = frame(cmd, Uint8Array.from(p))
    body[2] = 0x3e // '>'
    // checksum covers len,cmd,payload only, so the direction byte change needs no fix
    return body
  }
}
