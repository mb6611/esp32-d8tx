// D8Link: protocol v1 client with a paced stick sender (port of python/d8tx/link.py).
import type { Clock } from './clock.ts'
import type { SerialPort } from './port.ts'
import {
  ARM_CH, ARM_LIMIT, BIND_TIMEOUT_MS, DEFAULT_FOFS_HZ, DEFAULT_LINK_POWER, TXID, LO, MID, SLOT_S, TLM_RECIPE, ProtocolError, checkLine, fmtSticks, nextTid,
  parseTxid, payloadOk, unpack4, type KV, type TlmMeta,
} from './protocol.ts'
import { Reader, type ReaderEvent } from './reader.ts'
import { Tracker, type RadioSnapshot, type Reply } from './telemetry.ts'

export const ARM_THROTTLE_HOLD_MS = 500
export const LOST_MS = 400
export const STAT_POLL_MS = 200
export const WRITE_BACKLOG_MAX = 64
export const CAPTURE_QUEUE_MAX = 16
/** Minimum spacing between S frames as a fraction of SLOT_S. A late sender catches up at this spacing instead of in a
 * burst: the firmware keys and listens with interrupts off for up to ~11.3 ms, during which its 128-byte UART RX FIFO
 * must hold everything we send. A burst of 3 S lines plus a TID (129 bytes) overflowed it, the firmware read a torn
 * line ("ERR unknown cmd") and ended the link. Two 41-byte S lines + TID + STAT fit. */
export const SENDER_MIN_SPACING = 0.8
/** While linked the firmware silently ignores STAT while it ships a capture; resend after this long without a reply. */
export const STAT_RESEND_MS = 120

export class D8Error extends ProtocolError {}
export class D8TimeoutError extends Error {
  constructor(line: string) {
    super(`no reply to ${JSON.stringify(line)}`)
    this.name = 'TimeoutError'
  }
}

/** Decoder injected by the host (native/WASM demod). iq: int8 I,Q interleaved (Q not negated). */
export type DecodeFn = (iq: Int8Array, fs: number, hint: number | null, txid?: readonly [number, number]) => Reply | null | Promise<Reply | null>

export type LinkEvent = { name: string; [k: string]: unknown }

export interface D8LinkOptions {
  decode?: DecodeFn
  replyTimeoutMs?: number
  lostMs?: number
  statPollMs?: number
}

export interface StartOptions {
  power?: number
  timeoutMs?: number
  allowArm?: boolean
  fofsHz?: number | null
  telemetry?: boolean
}

type Reply1 = { kind: 'ok'; val: KV } | { kind: 'err'; val: [string, string] }

export class D8Link {
  private port: SerialPort
  private clock: Clock
  private decode: DecodeFn | undefined
  private replyTimeout: number
  private lostMs: number
  private statPollMs: number
  private reader = new Reader()
  private tlm: Tracker
  private cbs: ((e: LinkEvent) => void)[] = []
  private replyQ: Reply1[] = []
  private replyWake: (() => void) | null = null
  private reqChain: Promise<unknown> = Promise.resolve()
  private reqPending = 0
  private capQ: { meta: TlmMeta; payload: Uint8Array }[] = []
  private capBusy = false
  private pump: Promise<void> | null = null
  private ch: number[] = [LO, MID, MID, MID, MID, MID, LO, MID]
  private allowArm = false
  private linked = false
  private closed = false
  private tlmOn = false
  private tlmSent = false
  private tid = 0
  private shiftHint: number | null = null
  private protoOk = false
  private infoData: KV | null = null
  private pwrMaxV = 127
  private txidV: [number, number] | null = null // this ESP's identity, from INFO/ID; replies must carry it
  private bindingV = false
  private bindTimer: unknown = null
  private st = { keyed: 0, slots: 0, late_max_us: 0, last_event: null as LinkEvent | null, sender_hz: 0, sender_max_gap_ms: 0, sent: 0, skipped: 0, fofs: 0 }
  private senderTimer: unknown = null
  private watchTimer: unknown = null
  private statTimer: unknown = null
  private lastRx = 0
  private strayS = false
  private lostWhy: string | null = null
  private statWait: (() => void) | null = null // resends STAT while a linked STAT request is outstanding

  constructor(port: SerialPort, clock: Clock, opts: D8LinkOptions = {}) {
    this.port = port
    this.clock = clock
    this.decode = opts.decode
    this.replyTimeout = opts.replyTimeoutMs ?? 1000
    this.lostMs = opts.lostMs ?? LOST_MS
    this.statPollMs = opts.statPollMs ?? STAT_POLL_MS
    this.tlm = new Tracker(() => clock.now() / 1000)
  }

  /** Opens the port and starts reading. */
  async open(): Promise<void> {
    await this.port.open()
    this.pump = this.readLoop()
  }

  on(cb: (e: LinkEvent) => void): void {
    this.cbs.push(cb)
  }

  // --- reading
  private async readLoop(): Promise<void> {
    try {
      for await (const chunk of this.port.read()) {
        for (const ev of this.reader.feed(chunk)) this.onEvent(ev)
      }
    } catch {
      /* port error: treated as close */
    }
    if (!this.closed) this.markLost('port_closed')
  }

  private onEvent(ev: ReaderEvent): void {
    this.lastRx = this.clock.now()
    // A capture or a drop/probe line ends a firmware shipment, during which STAT was dropped: ask again now.
    if (ev.type === 'capture' || (ev.parsed.kind === 'ev' && (ev.parsed.name === 'tlm_drop' || ev.parsed.name === 'probe'))) this.statWait?.()
    if (ev.type === 'capture') {
      if (this.capQ.length >= CAPTURE_QUEUE_MAX) this.tlm.noteTriggerMiss()
      else {
        this.capQ.push({ meta: ev.meta, payload: ev.payload })
        void this.drainCaptures()
      }
      return
    }
    const p = ev.parsed
    if (p.kind === 'ev') {
      const e: LinkEvent = { name: p.name, ...p.data }
      this.st.last_event = e
      if (p.name === 'link') {
        this.st.slots = Number(p.data.slots ?? 0)
        this.st.late_max_us = Number(p.data.late_max_us ?? 0)
      } else if (p.name === 'bind_end') {
        this.endBind()
      } else if (p.name === 'link_end') {
        this.st.slots = Number(p.data.slots ?? this.st.slots)
        this.st.late_max_us = Number(p.data.late_max_us ?? this.st.late_max_us)
        this.markLost('link_end', true)
      }
      if (p.name === 'tlm_drop') this.tlm.noteTriggerMiss()
      for (const cb of [...this.cbs]) {
        try { cb(e) } catch { /* listener error */ }
      }
    } else if (p.kind === 'ok') {
      this.pushReply({ kind: 'ok', val: p.data })
    } else if (p.kind === 'err') {
      this.pushReply({ kind: 'err', val: [p.code, p.text] })
    }
  }

  private pushReply(r: Reply1): void {
    this.replyQ.push(r)
    if (this.replyQ.length > 64) this.replyQ.shift()
    this.replyWake?.()
  }

  private async drainCaptures(): Promise<void> {
    if (this.capBusy) return
    this.capBusy = true
    try {
      while (this.capQ.length && !this.closed) {
        const c = this.capQ.shift()!
        try { await this.processCapture(c.meta, c.payload) } catch { /* decoder error: miss */ }
      }
    } finally {
      this.capBusy = false
    }
  }

  private async processCapture(meta: TlmMeta, payload: Uint8Array): Promise<void> {
    if (!this.tlmOn) return
    let rep: Reply | null = null
    if (payloadOk(meta, payload) && this.decode) {
      const bits = Number(meta.bits ?? 16)
      if (bits === 4 || bits === 8) {
        const iq = bits === 4 ? unpack4(payload) : new Int8Array(payload.buffer, payload.byteOffset, payload.length)
        rep = (await this.decode(iq, Number(meta.fs ?? 500000), this.shiftHint, this.txidV ?? TXID)) ?? null
      }
    }
    if (rep) {
      if (rep.shift_hz !== undefined) this.shiftHint = rep.shift_hz
      this.tlm.noteReply(rep)
    } else this.tlm.noteTriggerMiss()
    this.tid = nextTid(Number(meta.tid ?? this.tid), rep ? rep.tid : null)
    // Only while linked, checked after the async decode: no TID follows STOP or a loss.
    if (this.linked) this.writeLine(`TID ${this.tid}\n`)
  }

  // --- writing
  private writeLine(s: string): void {
    this.write(new TextEncoder().encode(s))
  }

  private write(b: Uint8Array): void {
    this.port.write(b).catch(() => { this.st.skipped++ })
  }

  // --- requests
  request(line: string, timeoutMs = this.replyTimeout): Promise<KV> {
    checkLine(line)
    this.reqPending++
    const run = async (): Promise<KV> => {
      try {
        if (this.strayS && !this.linked) {
          this.strayS = false
          await this.sleep(20) // let stray idle-S OK replies arrive
        }
        this.replyQ.length = 0
        this.writeLine(line + '\n')
        const want = replyKey(line)
        const isStat = want === 'keyed'
        const deadline = this.clock.now() + timeoutMs
        let resendAt = this.clock.now() + STAT_RESEND_MS
        if (isStat) {
          this.statWait = () => {
            if (!this.linked) return
            this.writeLine('STAT\n')
            resendAt = this.clock.now() + STAT_RESEND_MS
          }
        }
        for (;;) {
          const r = await this.nextReply(isStat && this.linked ? Math.min(deadline, resendAt) : deadline)
          if (!r) {
            if (this.clock.now() < deadline) {
              this.statWait?.()
              continue
            }
            throw new D8TimeoutError(line)
          }
          if (r.kind === 'err') throw new D8Error(r.val[0], r.val[1])
          // Match the reply shape: a stray `OK tid=` (async TID after the link ended), a duplicate `OK keyed=` (STAT
          // resend) or a bare `OK` (S answered after the link ended) must not answer a different request.
          if (!replyMatches(r.val, want)) continue
          return r.val
        }
      } finally {
        this.reqPending--
        this.statWait = null
      }
    }
    const p = this.reqChain.then(run, run)
    this.reqChain = p.catch(() => undefined)
    return p
  }

  /**
   * Resynchronise after open: the firmware may still be in a link from an earlier session (it answers `ERR busy` and
   * ends that link) or hold a partial line from a writer that went away mid-line. Ends any partial line, then PINGs
   * until one is answered. Returns the PING reply.
   */
  async sync(tries = 4): Promise<KV> {
    this.writeLine('\n')
    await this.sleep(30)
    let last: unknown
    for (let i = 0; i < tries; i++) {
      try {
        return await this.request('PING', 500)
      } catch (e) {
        if (!(e instanceof D8Error || e instanceof D8TimeoutError)) throw e
        last = e
        await this.sleep(50) // let a link_end / boot banner finish
      }
    }
    throw last
  }

  private nextReply(deadline: number): Promise<Reply1 | null> {
    return new Promise((resolve) => {
      let timer: unknown
      const check = (): void => {
        const r = this.replyQ.shift()
        if (r) {
          this.clock.clearTimeout(timer)
          this.replyWake = null
          resolve(r)
        }
      }
      if (this.replyQ.length) return check()
      timer = this.clock.setTimeout(() => {
        this.replyWake = null
        resolve(null)
      }, Math.max(0, deadline - this.clock.now()))
      this.replyWake = check
    })
  }

  private sleep(ms: number): Promise<void> {
    return new Promise((res) => this.clock.setTimeout(res, ms))
  }

  /** The firmware's compile-time power cap (INFO pwr_max); 127 until INFO has been read or if it is absent. */
  get pwrMax(): number {
    return this.pwrMaxV
  }

  async info(): Promise<KV> {
    const r = await this.request('INFO')
    this.infoData = r
    this.protoOk = r.proto === 1
    // Unknown/missing keys are fine (old firmware): pwr_max falls back to 127.
    const pm = Number(r.pwr_max)
    this.pwrMaxV = r.pwr_max !== undefined && Number.isFinite(pm) ? Math.max(0, Math.min(127, Math.trunc(pm))) : 127
    this.noteTxid(r)
    return r
  }

  private noteTxid(r: KV): void {
    const t = parseTxid(r.txid)
    if (t) this.txidV = t
  }

  /** The ESP's transmitter id as [id0, id1] (from INFO/ID); null until the firmware reported one. */
  get txid(): readonly [number, number] | null {
    return this.txidV
  }

  /** Reads the identity: `ID` -> txid (hex text), start, step. Idle only. */
  async id(): Promise<KV> {
    const r = await this.request('ID')
    this.noteTxid(r)
    return r
  }

  /** Sets and persists an identity (clone/restore). txid is 4 hex digits. */
  async setId(txid: string, start: number, step: number): Promise<KV> {
    const r = await this.request(`ID ${txid.toUpperCase()} ${Math.trunc(start)} ${Math.trunc(step)}`)
    this.noteTxid(r)
    return r
  }

  /** Generates and persists a new random identity; bound receivers must re-bind. */
  async newId(): Promise<KV> {
    const r = await this.request('ID new')
    this.noteTxid(r)
    return r
  }

  get binding(): boolean {
    return this.bindingV
  }

  /**
   * Starts transmitting bind packets (idle only). Ends on stopBind(), the firmware's 30 s timeout (EV bind_end) or a host
   * fallback timer. Sets FOFS first (default DEFAULT_FOFS_HZ): the receiver tunes to the carrier it binds on, so bind at
   * the offset later links use, not whatever an earlier link left in the firmware. power is clamped to pwr_max when INFO
   * has been read (info() first).
   */
  async bind(power?: number, fofsHz: number = DEFAULT_FOFS_HZ): Promise<void> {
    if (this.linked) throw new D8Error('busy', 'link active')
    await this.setFofs(fofsHz)
    await this.request(power === undefined ? 'BIND' : `BIND ${Math.min(Math.trunc(power), this.pwrMaxV)}`)
    this.bindingV = true
    this.clearBindTimer()
    this.bindTimer = this.clock.setTimeout(() => {
      this.bindTimer = null
      if (this.bindingV) void this.stopBind().catch(() => undefined)
    }, BIND_TIMEOUT_MS + 1500)
  }

  async stopBind(): Promise<void> {
    this.endBind()
    try {
      await this.request('STOP')
    } catch (e) {
      if (!(e instanceof D8Error || e instanceof D8TimeoutError)) throw e
    }
  }

  private endBind(): void {
    this.bindingV = false
    this.clearBindTimer()
  }

  private clearBindTimer(): void {
    if (this.bindTimer !== null) this.clock.clearTimeout(this.bindTimer)
    this.bindTimer = null
  }

  get protocolOk(): boolean {
    return this.protoOk
  }

  async stat(): Promise<KV> {
    const r = await this.request('STAT')
    this.applyStat(r)
    return r
  }

  private applyStat(r: KV): void {
    if (typeof r.keyed === 'number') this.st.keyed = r.keyed
    if (typeof r.fofs === 'number') this.st.fofs = r.fofs
    if (typeof r.bind === 'number') {
      if (r.bind === 0 && this.bindingV) this.endBind()
      else if (r.bind === 1) this.bindingV = true
    }
    if (this.linked) {
      if (typeof r.slots === 'number') this.st.slots = r.slots
      if (typeof r.late_max_us === 'number') this.st.late_max_us = r.late_max_us
    }
  }

  async setFofs(hz: number): Promise<void> {
    await this.request(`FOFS ${Math.trunc(hz)}`)
    this.st.fofs = Math.trunc(hz)
  }

  // --- link
  async start(o: StartOptions = {}): Promise<void> {
    const { power = DEFAULT_LINK_POWER, timeoutMs = 300, allowArm = false, fofsHz = null, telemetry = true } = o
    if (this.linked) throw new D8Error('busy', 'already linked')
    // INFO tells us the firmware's pwr_max (and proto); missing on old firmware, then 127.
    if (allowArm && !this.protoOk) {
      await this.info()
      if (!this.protoOk) throw new D8Error('protocol', `firmware does not report proto=1 (${JSON.stringify(this.infoData)})`)
    }
    // Opening the port resets the ESP32; the first request gets a few tries.
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        await this.setFofs(fofsHz ?? DEFAULT_FOFS_HZ)
        break
      } catch (e) {
        // Timeout: the ESP32 may still be booting. ERR busy: a link from an earlier session was still running; the
        // FOFS ended it, so the retry lands on an idle firmware.
        const retry = e instanceof D8TimeoutError || (e instanceof D8Error && e.code === 'busy')
        if (!retry || attempt === 2) throw e
        if (e instanceof D8Error) await this.sleep(50)
      }
    }
    // Learn pwr_max (after FOFS, which also ends a link left by an earlier session) so LINK is clamped to it.
    if (this.infoData === null) await this.info()
    await this.setupTelemetry(telemetry)
    if (allowArm) await this.request('ARMOK')
    this.allowArm = allowArm
    this.ch[ARM_CH] = LO
    this.lostWhy = null
    Object.assign(this.st, { slots: 0, late_max_us: 0, last_event: null, sender_hz: 0, sender_max_gap_ms: 0, sent: 0, skipped: 0 })
    try {
      await this.request(`LINK ${Math.min(Math.trunc(power), this.pwrMax)} ${Math.trunc(timeoutMs)}`)
    } catch (e) {
      this.allowArm = false
      if (allowArm) await this.request('STOP').catch(() => undefined)
      throw e
    }
    this.linked = true
    this.st.keyed = 1
    this.lastRx = this.clock.now()
    this.startSender()
    this.startWatch()
  }

  private async setupTelemetry(want: boolean): Promise<void> {
    let ok = false
    if (want) {
      try {
        await this.request(`TID ${this.tid}`)
        await this.request(TLM_RECIPE)
        ok = true
        this.tlmSent = true
      } catch (e) {
        if (!(e instanceof D8Error || e instanceof D8TimeoutError)) throw e
        ok = false
      }
    } else if (this.tlmSent) {
      try {
        await this.request('TLM 0')
        this.tlmSent = false
      } catch (e) {
        if (!(e instanceof D8Error || e instanceof D8TimeoutError)) throw e
      }
    }
    this.tlmOn = ok
    this.tlm.reset(ok)
    this.tlm.noteArmOnAir(false)
    this.shiftHint = null
  }

  telemetry(): RadioSnapshot {
    return this.tlm.snapshot()
  }

  setSticks(ch: readonly number[]): void {
    this.ch = fmtSticks(ch, this.allowArm).channels
    this.tlm.noteArmOnAir(this.ch[ARM_CH] > ARM_LIMIT)
  }

  get isLinked(): boolean {
    return this.linked
  }

  async stop(): Promise<void> {
    this.linked = false
    this.st.keyed = 0
    this.cancelTimers()
    try {
      await this.request('STOP')
    } catch (e) {
      if (!(e instanceof D8Error || e instanceof D8TimeoutError)) throw e
    }
    this.allowArm = false
  }

  /** Link ended without our STOP (firmware link_end, silence, port closed): disarm host-side and tell listeners. */
  private markLost(why: string, fromFirmware = false): void {
    if (!this.linked) return
    this.linked = false
    this.st.keyed = 0
    this.cancelTimers()
    this.ch[ARM_CH] = LO
    this.allowArm = false
    this.tlm.noteArmOnAir(false)
    this.lostWhy = why
    if (!fromFirmware && why !== 'port_closed') this.writeLine('STOP\n')
    const e: LinkEvent = { name: 'link_lost', why }
    for (const cb of [...this.cbs]) {
      try { cb(e) } catch { /* listener error */ }
    }
  }

  get lostReason(): string | null {
    return this.lostWhy
  }

  private cancelTimers(): void {
    for (const t of [this.senderTimer, this.watchTimer, this.statTimer]) if (t !== null) this.clock.clearTimeout(t)
    this.senderTimer = this.watchTimer = this.statTimer = null
  }

  private startWatch(): void {
    const watch = (): void => {
      if (!this.linked) return
      if (this.clock.now() - this.lastRx > this.lostMs) return this.markLost('timeout')
      this.watchTimer = this.clock.setTimeout(watch, 50)
    }
    const poll = (): void => {
      if (!this.linked) return
      if (this.reqPending === 0) this.request('STAT', 250).then((r) => this.applyStat(r), () => undefined)
      this.statTimer = this.clock.setTimeout(poll, this.statPollMs)
    }
    this.watchTimer = this.clock.setTimeout(watch, 50)
    this.statTimer = this.clock.setTimeout(poll, this.statPollMs)
  }

  private startSender(): void {
    const period = SLOT_S * 1000
    const minGap = period * SENDER_MIN_SPACING
    const clock = this.clock
    const t0 = clock.now()
    let nxt = t0
    let last: number | null = null
    let armPrev = false
    let armEdge: number | null = null
    let sent = 0
    let skipped = 0
    let maxGap = 0
    const tick = (): void => {
      if (!this.linked) return
      let now = clock.now()
      const due = Math.max(nxt, last === null ? nxt : last + minGap)
      if (now < due) {
        this.senderTimer = clock.setTimeout(tick, due - now)
        return
      }
      if ((this.port.outWaiting ?? 0) > WRITE_BACKLOG_MAX) {
        skipped++
        this.st.skipped = skipped
      } else {
        const ch = [...this.ch]
        const allow = this.allowArm
        // Arm-edge guard: on ARM low->high send throttle 1000 for ARM_THROTTLE_HOLD_MS regardless of the caller.
        const armHi = allow && ch[ARM_CH] > 1300
        if (armHi && !armPrev) armEdge = now
        armPrev = armHi
        if (armHi && armEdge !== null && now - armEdge < ARM_THROTTLE_HOLD_MS) ch[0] = LO
        const { line } = fmtSticks(ch, allow)
        this.strayS = true
        this.writeLine(line)
        if (last !== null) maxGap = Math.max(maxGap, now - last)
        last = now
        sent++
        this.st.sent = sent
        this.st.skipped = skipped
        this.st.sender_max_gap_ms = maxGap
        if (sent > 1 && now > t0) this.st.sender_hz = ((sent - 1) / (now - t0)) * 1000
      }
      nxt += period
      now = clock.now()
      if (now - nxt > period) nxt = now
      this.senderTimer = clock.setTimeout(tick, Math.max(0, nxt - now))
    }
    this.senderTimer = clock.setTimeout(tick, 0)
  }

  status() {
    return {
      link: this.linked ? 1 : 0,
      allow_arm: this.allowArm ? 1 : 0,
      ch: fmtSticks([...this.ch], this.allowArm).channels,
      tlm_enabled: this.tlmOn ? 1 : 0,
      ...this.st,
    }
  }

  async close(): Promise<void> {
    if (this.linked) await this.stop()
    else if (this.bindingV) await this.stopBind()
    this.closed = true
    this.cancelTimers()
    this.clearBindTimer()
    try { await this.port.close() } catch { /* ignore */ }
    await this.pump
  }
}

/** Which key identifies the reply to a request line (null: any OK without tid/keyed/proto). */
function replyKey(line: string): 'tid' | 'keyed' | 'proto' | 'txid' | null {
  const c = line.split(' ', 1)[0]
  return c === 'TID' ? 'tid' : c === 'STAT' ? 'keyed' : c === 'PING' || c === 'INFO' ? 'proto' : c === 'ID' ? 'txid' : null
}

function replyMatches(val: KV, want: 'tid' | 'keyed' | 'proto' | 'txid' | null): boolean {
  if (want) return want in val
  return !('tid' in val) && !('keyed' in val) && !('proto' in val) && !('txid' in val)
}
