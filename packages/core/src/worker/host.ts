// Worker host (R10): owns the ports, D8Link, FC poller and demod; the UI only sends intents and receives state.
//
// The radio link behaves like a normal radio: whenever the ESP32 is wanted (connected from the UI), the host keeps the
// link running with the current radio settings. A single reconcile loop drives the ESP side toward that goal: open the
// port, start the link, restart it when the settings change, and after a lost link or port retry with backoff. Bind and
// New identity pause the loop and it restarts the link afterwards. Arming is never touched by the loop: every (re)start
// holds ch7 low until the UI sends a disarmed frame.
import { realClock, type Clock } from '../clock.ts'
import { FcPoller, FC_DEFAULT } from '../fc.ts'
import { D8Error, D8Link, type DecodeFn } from '../link.ts'
import { BetaflightMSP, MspError } from '../msp.ts'
import { PortInUseError, type SerialPort } from '../port.ts'
import { DEFAULT_FOFS_HZ } from '../protocol.ts'
import { idleRadio } from '../telemetry.ts'
import type { BindPhase, ErrorKind, FromWorker, LinkPhase, PortRef, RadioConfig, Role, ToWorker } from './types.ts'

export const STATE_HZ = 50
/** If the UI goes silent this long while linked, the host disarms and centres the sticks (the link itself stays up). */
export const UI_SILENCE_MS = 2500
const SAFE_STICKS = [1000, 1500, 1500, 1500, 1000, 1000, 1000, 1000]
/** How long the ESP sends bind packets after the FC entered bind mode (the CC2500 tunes and binds in ~2–5 s). */
export const BIND_WINDOW_MS = 6000
/** How long the confirm link waits for a telemetry reply carrying this ESP's txid. */
export const BIND_CONFIRM_MS = 5000
/** Power of the bind packets and of the confirm link when the UI gives none. */
export const BIND_POWER = 40
/** Delay before reconnect / restart attempt n (the last value repeats). */
export const RETRY_MS = [250, 500, 1000, 2000, 3000]
/**
 * Retry period while another app or tab holds the port (open fails busy: Web Serial and our Node adapter open
 * exclusively). Steady, so the host takes the port over within this long after the other side closes it.
 */
export const IN_USE_RETRY_MS = 2000
export const DEFAULT_RADIO: Required<RadioConfig> = { power: 127, fofs_hz: DEFAULT_FOFS_HZ, timeout_ms: 300, allow_arm: true }

export interface HostDeps {
  post(msg: FromWorker): void
  /** Real port for the role: the picked granted port (`ref`), else one matching the role's USB VID/PID. Throws when none fits. */
  openPort(role: Role, ref?: PortRef): Promise<SerialPort>
  /** Simulated port for the role. */
  mockPort(role: Role): SerialPort | Promise<SerialPort>
  decode?: DecodeFn
  clock?: Clock
}

const errKind = (e: unknown): ErrorKind => {
  if (e instanceof PortInUseError) return 'port_in_use'
  if (e instanceof D8Error && e.code === 'protocol') return 'protocol'
  if ((e as Error)?.name === 'NoPortError') return 'no_port'
  return 'other'
}
const msg = (e: unknown): string => (e instanceof Error ? e.message : String(e))
export class NoPortError extends Error {
  constructor(m: string) {
    super(m)
    this.name = 'NoPortError'
  }
}

const clampInt = (v: unknown, lo: number, hi: number, dflt: number): number => {
  const n = Number(v)
  return Number.isFinite(n) ? Math.max(lo, Math.min(hi, Math.trunc(n))) : dflt
}
export function radioConfig(m: Partial<RadioConfig>): Required<RadioConfig> {
  return {
    power: clampInt(m.power, 0, 127, DEFAULT_RADIO.power),
    fofs_hz: clampInt(m.fofs_hz, -200000, 200000, DEFAULT_RADIO.fofs_hz),
    timeout_ms: clampInt(m.timeout_ms, 50, 2000, DEFAULT_RADIO.timeout_ms),
    allow_arm: m.allow_arm ?? true,
  }
}
const sameRadio = (a: RadioConfig | null, b: RadioConfig): boolean =>
  !!a && a.power === b.power && a.fofs_hz === b.fofs_hz && a.timeout_ms === b.timeout_ms && a.allow_arm === b.allow_arm

/** Forwards to a port and reports when its read stream ends (unplugged, or closed by us). */
function watchPort(p: SerialPort, onEnd: () => void): SerialPort {
  return {
    open: () => p.open(),
    write: (d) => p.write(d),
    close: () => p.close(),
    get outWaiting() {
      return p.outWaiting
    },
    read: () => ({
      async *[Symbol.asyncIterator]() {
        try {
          yield* p.read()
        } finally {
          onEnd()
        }
      },
    }),
  }
}

/** One open ESP port. `dead` once its read stream ended without our close (unplugged, reset, I/O error). */
interface EspSession {
  link: D8Link
  dead: boolean
  closing: boolean
}

export class Host {
  private d: HostDeps
  private clock: Clock
  private sess: EspSession | null = null
  private msp: BetaflightMSP | null = null
  private poller: FcPoller | null = null
  private mock = false
  private info: Record<string, string | number> | undefined
  private espError: string | undefined
  private allowArm = false
  private lastUi = 0
  /** Set when the UI-silence guard fired; sticks are forced safe until the UI posts a disarmed frame. */
  private guardAt: number | null = null
  private lastArmed = false
  private guardWall: number | null = null
  /** Set on every link (re)start: ch7 stays low until the UI posts a disarmed frame. */
  private needLow = false
  private mockFc: { state: { rc: number[]; armed: boolean } } | null = null
  private timer: unknown = null
  private uiTimer: unknown = null
  private busy = new Set<string>()
  private bindPhase: BindPhase = 'idle'
  private bindTxid: string | undefined
  private bindReason: string | undefined
  private bindVia: 'telemetry' | 'fc' | undefined
  private bindCancel = false
  // --- firmware flashing: the port is released to the UI thread until resumeFlash is called
  private resumeFlash: (() => void) | null = null
  // --- link supervisor
  private cfg: Required<RadioConfig> = { ...DEFAULT_RADIO }
  /** Settings of the running link; null when none runs. */
  private runCfg: Required<RadioConfig> | null = null
  /** The ESP the UI wants connected; null after a disconnect. */
  private espWant: { mock: boolean; ref?: PortRef } | null = null
  private paused = 0
  private phase: LinkPhase = 'off'
  private attempt = 0
  private retryTimer: unknown = null
  private retryAt: number | null = null
  private retryReason: string | undefined
  private recon: Promise<void> = Promise.resolve()
  private reconRunning = false
  private reconAgain = false
  private streakErr = false
  // --- FC: wanted port and the retry while another app holds it
  private fcWant: { mock: boolean; ref?: PortRef } | null = null
  private fcInUse = false
  private fcTimer: unknown = null
  private fcStreakErr = false

  constructor(deps: HostDeps) {
    this.d = deps
    this.clock = deps.clock ?? realClock
  }

  private get link(): D8Link | null {
    return this.sess?.link ?? null
  }

  startState(): void {
    const tick = (): void => {
      this.d.post({ type: 'state', ...this.snapshot() })
      this.timer = this.clock.setTimeout(tick, 1000 / STATE_HZ)
    }
    tick()
  }

  stopState(): void {
    if (this.timer !== null) this.clock.clearTimeout(this.timer)
    this.timer = null
  }

  snapshot() {
    const l = this.link
    const st = l?.status()
    const lost = l?.lostReason ?? null
    const connected = !!l && !this.sess?.dead
    const esp: Record<string, unknown> = {
      connected,
      wanted: !!this.espWant,
      link_state: this.phase,
      // the DevKit port is released for firmware flashing (UI thread); the ref of the wanted port
      flashing: this.resumeFlash ? true : undefined,
      port: this.espWant?.ref,
      retry_in_ms: this.retryAt === null ? undefined : Math.max(0, this.retryAt - this.clock.now()),
      retry_reason: this.retryReason,
      attempt: this.attempt,
      power: this.runCfg?.power,
      error: this.espError,
      info: this.info,
      link: !!l?.isLinked,
      binding: !!l?.binding,
      bind_state: this.bindPhase,
      bind_txid: this.bindTxid,
      bind_reason: this.bindReason,
      bind_via: this.bindVia,
      txid: this.txid(),
      keyed: !!st?.keyed,
      fofs: st?.fofs,
      slots: st?.slots,
      late_max_us: st?.late_max_us,
      allow_arm: l?.isLinked ? this.allowArm : false,
      sender_hz: st?.sender_hz,
      sender_max_gap_ms: st?.sender_max_gap_ms,
      skipped: st?.skipped,
      lost_reason: l?.isLinked ? null : (this.sess?.dead ? 'port_closed' : (lost ?? (this.phase === 'lost' ? this.retryReason : null))),
      // the DevKit port is held by another app or tab; retrying every IN_USE_RETRY_MS
      in_use: !this.sess && this.phase === 'lost' && this.retryReason === 'port_in_use' ? true : undefined,
      protocol_ok: l?.protocolOk,
      guard: this.guardAt !== null ? 'ui-silent' : undefined,
      guard_at: this.guardWall ?? undefined,
    }
    const fs = this.poller?.state ?? FC_DEFAULT
    const fc: Record<string, unknown> = {
      ...fs, error: fs.error ?? undefined, armed: fs.armed ?? undefined, failsafe: fs.failsafe ?? undefined, rssi: fs.rssi ?? undefined,
      wanted: !!this.fcWant || undefined,
      in_use: (!this.poller && this.fcInUse) || undefined,
    }
    const radio = (l ? l.telemetry() : idleRadio()) as unknown as Record<string, unknown>
    return { mock: this.mock, esp, fc, radio }
  }

  /** Identity as hex text (live from ID/INFO), or the INFO field before the link learned it. */
  private txid(): string | undefined {
    const t = this.link?.txid
    if (t) return t.map((b) => b.toString(16).padStart(2, '0')).join('').toUpperCase()
    const v = this.info?.txid
    return v === undefined ? undefined : String(v)
  }

  private err(role: Role | undefined, e: unknown): void {
    this.d.post({ type: 'error', role, kind: errKind(e), message: msg(e) })
  }

  async handle(m: ToWorker): Promise<void> {
    switch (m.type) {
      case 'sticks': {
        this.lastUi = this.clock.now()
        const high = m.ch[6] > 1500
        if (this.guardAt !== null) {
          // latched: only a disarmed UI frame (explicit re-arm needed afterwards) releases the guard
          if (high) {
            this.link?.setSticks(SAFE_STICKS)
            return
          }
          this.guardAt = null
          this.guardWall = null
        }
        if (this.needLow) {
          // a (re)started link never inherits an arm: wait for a disarmed frame
          if (high) {
            this.link?.setSticks(SAFE_STICKS)
            this.driveMockFc(SAFE_STICKS)
            return
          }
          this.needLow = false
        }
        const wasArmed = this.lastArmed
        this.lastArmed = high
        // settings that changed while armed apply once disarmed
        if (wasArmed && !high && this.runCfg && !sameRadio(this.runCfg, this.cfg)) void this.kick()
        this.link?.setSticks(m.ch)
        this.driveMockFc(m.ch)
        return
      }
      case 'connect':
        if (m.role === 'esp') return this.connectEsp(!!m.mock, m.port)
        return this.guard('cfc', () => this.connectFc(!!m.mock, m.port))
      case 'disconnect':
        if (m.role === 'esp') return this.disconnectEsp()
        this.fcWant = null
        this.fcInUse = false
        this.clearFcRetry()
        return this.guard('cfc', () => this.closeFc())
      case 'radio':
      case 'start': {
        const c = radioConfig(m)
        if (sameRadio(this.cfg, c)) return this.recon
        this.cfg = c
        return this.kick()
      }
      case 'ports_changed':
        // a device came back: retry now instead of waiting out the backoff
        if (this.fcTimer !== null && this.fcWant) {
          const want = this.fcWant
          this.clearFcRetry()
          void this.guard('cfc', () => this.connectFc(want.mock, want.ref))
        }
        if (this.retryTimer !== null) {
          this.clearRetry()
          return this.kick()
        }
        return
      case 'bind':
        return this.guard('start', () => this.paused_(() => this.bind(m)))
      case 'bind_stop':
        // not guarded: it must reach a bind flow that holds the 'start' guard
        this.bindCancel = true
        return
      case 'esp_release':
        return this.releaseEsp()
      case 'esp_resume': {
        const r = this.resumeFlash
        this.resumeFlash = null
        r?.()
        return
      }
      case 'new_id':
        return this.guard('start', () =>
          this.paused_(async () => {
            try {
              if (!this.link) throw new Error('ESP32 not connected')
              await this.link.newId()
            } catch (e) {
              this.err('esp', e)
            }
          }),
        )
    }
  }

  /** Releases the DevKit port for flashing: link stopped, port closed, supervisor paused until 'esp_resume'. */
  private async releaseEsp(): Promise<void> {
    const reply = (ok: boolean, error?: string) => this.d.post({ type: 'esp_released', ok, error })
    if (this.resumeFlash) return reply(true) // already released
    if (this.busy.has('start')) return reply(false, 'busy: a bind or identity change is running')
    if (this.link?.isLinked && this.allowArm && this.lastArmed) return reply(false, 'disarm first')
    let replied = false
    await this.guard('start', () =>
      this.paused_(async () => {
        await this.teardownEsp()
        // a fresh start after flashing: no backoff left from the old firmware's failures
        this.attempt = 0
        this.streakErr = false
        this.espError = undefined
        const resumed = new Promise<void>((res) => (this.resumeFlash = res))
        replied = true
        reply(true)
        await resumed
      }),
    )
    if (!replied) reply(false, 'disarm first')
  }

  private async guard(key: string, fn: () => Promise<void>): Promise<void> {
    if (this.busy.has(key)) return
    this.busy.add(key)
    try {
      await fn()
    } finally {
      this.busy.delete(key)
    }
  }

  // --- link supervisor

  /** Runs the reconcile loop (single flight); resolves when it went idle. */
  private kick(): Promise<void> {
    if (this.reconRunning) {
      this.reconAgain = true
      return this.recon
    }
    this.reconRunning = true
    this.recon = (async () => {
      try {
        do {
          this.reconAgain = false
          try {
            await this.reconcile()
          } catch (e) {
            this.err('esp', e)
          }
        } while (this.reconAgain)
      } finally {
        this.reconRunning = false
      }
    })()
    return this.recon
  }

  /** Posts the first error of a failure streak only; the retry state shows the rest. */
  private reportOnce(e: unknown): void {
    if (this.streakErr) return
    this.streakErr = true
    this.err('esp', e)
  }

  private clearRetry(): void {
    if (this.retryTimer !== null) this.clock.clearTimeout(this.retryTimer)
    this.retryTimer = null
    this.retryAt = null
  }

  private scheduleRetry(reason: string, fixedMs?: number): void {
    this.clearRetry()
    const delay = fixedMs ?? RETRY_MS[Math.min(this.attempt, RETRY_MS.length - 1)]
    this.attempt++
    this.phase = 'lost'
    this.retryReason = reason
    this.retryAt = this.clock.now() + delay
    this.retryTimer = this.clock.setTimeout(() => {
      this.retryTimer = null
      this.retryAt = null
      void this.kick()
    }, delay)
  }

  /** One pass toward the goal: ESP wanted -> port open -> link running with this.cfg. */
  private async reconcile(): Promise<void> {
    if (!this.espWant) {
      this.clearRetry()
      await this.teardownEsp()
      this.phase = 'off'
      this.attempt = 0
      this.retryReason = undefined
      return
    }
    if (this.paused > 0) {
      this.phase = 'paused'
      return
    }
    if (this.retryTimer !== null) return // waiting out the backoff
    if (this.sess?.dead) await this.teardownEsp() // the backoff already ran (kickAfterLoss): reopen now
    if (!this.sess) {
      this.phase = 'connecting'
      const want = this.espWant
      try {
        await this.openEsp(want.mock, want.ref)
      } catch (e) {
        if (this.espWant !== want) return
        this.reportOnce(e)
        // held by another app or tab: retry steadily and quietly until it lets go
        if (e instanceof PortInUseError) return this.scheduleRetry('port_in_use', IN_USE_RETRY_MS)
        return this.scheduleRetry(msg(e))
      }
      if (this.espWant !== want) {
        // disconnected (or retargeted) while opening
        this.reconAgain = true
        return
      }
    }
    const l = this.sess!.link
    const cfg = this.cfg
    // never drop a link under an armed drone for a settings change: it applies on disarm
    if (l.isLinked && !sameRadio(this.runCfg, cfg) && !(this.lastArmed && this.allowArm)) {
      await l.stop()
      this.runCfg = null
    }
    if (l.isLinked) {
      this.phase = 'up'
      return
    }
    if (l.binding) await l.stopBind().catch(() => undefined)
    this.phase = 'linking'
    try {
      await this.startLink(l, cfg)
    } catch (e) {
      this.runCfg = null
      this.reportOnce(e)
      return this.scheduleRetry(msg(e))
    }
    this.phase = 'up'
    this.attempt = 0
    this.streakErr = false
    this.retryReason = undefined
    this.espError = undefined
  }

  private async startLink(l: D8Link, cfg: Required<RadioConfig>): Promise<void> {
    // firmware without proto=1 links with arming refused (no ARMOK, ch7 forced low)
    this.allowArm = cfg.allow_arm && l.protocolOk
    this.guardAt = null
    this.guardWall = null
    this.needLow = true
    this.lastUi = this.clock.now()
    try {
      await l.start({ power: cfg.power, fofsHz: cfg.fofs_hz, timeoutMs: cfg.timeout_ms, allowArm: this.allowArm, telemetry: true })
    } catch (e) {
      this.allowArm = false
      throw e
    }
    this.runCfg = { ...cfg }
    this.watchUi()
  }

  private onLinkEvent(s: EspSession, e: { name: string; why?: unknown }): void {
    if (e.name !== 'link_lost' || this.sess !== s) return
    this.runCfg = null
    if (this.paused > 0) return // the bind flow handles its own confirm link; the loop restarts afterwards
    void this.kickAfterLoss(String(e.why ?? 'lost'))
  }

  private async kickAfterLoss(why: string): Promise<void> {
    await this.recon
    if (!this.espWant || this.paused > 0 || this.retryTimer !== null) return
    if (this.link?.isLinked) return
    this.scheduleRetry(why)
  }

  private async openEsp(mock: boolean, ref?: PortRef): Promise<void> {
    if (this.mock && !mock) throw new Error('mock mode: real ports are never opened')
    if (mock) this.mock = true
    const raw = await (mock ? this.d.mockPort('esp') : this.d.openPort('esp', ref))
    let s: EspSession | null = null
    const port = watchPort(raw, () => {
      if (s && !s.closing && !s.dead) {
        s.dead = true
        if (this.sess === s) void this.kickAfterLoss('port_closed')
      }
    })
    const link = new D8Link(port, this.clock, { decode: this.d.decode })
    s = { link, dead: false, closing: false }
    const sess = s
    link.on((e) => this.onLinkEvent(sess, e))
    this.espError = undefined
    try {
      await link.open()
      this.info = undefined
      // End a link or partial line left by an earlier session before asking for INFO.
      try {
        await link.sync()
      } catch {
        /* INFO retries below report the error */
      }
      // Opening the port resets the ESP32; the first INFO may land before it boots.
      let last: unknown
      let info: Record<string, string | number> | undefined
      for (let i = 0; i < 3 && !info && !sess.dead; i++) {
        try {
          info = (await link.info()) as Record<string, string | number>
        } catch (e) {
          last = e
        }
      }
      if (!info) throw last ?? new Error('ESP32 port closed')
      this.info = info
    } catch (e) {
      this.espError = msg(e)
      sess.closing = true
      await link.close().catch(() => undefined)
      throw e
    }
    this.sess = sess
    if (!link.protocolOk) this.err('esp', new D8Error('protocol', `firmware does not report proto=1 (${JSON.stringify(this.info)}); arming refused`))
  }

  private async teardownEsp(): Promise<void> {
    const s = this.sess
    this.sess = null
    this.runCfg = null
    this.allowArm = false
    this.info = undefined
    if (!s) return
    s.closing = true
    await s.link.close().catch(() => undefined)
  }

  private async connectEsp(mock: boolean, ref?: PortRef): Promise<void> {
    if (this.mock && !mock) return this.err('esp', new Error('mock mode: real ports are never opened'))
    const same = this.espWant && this.espWant.mock === mock && JSON.stringify(this.espWant.ref) === JSON.stringify(ref)
    if (same && (this.sess || this.retryTimer !== null)) {
      // already connected or retrying this port: retry now
      if (this.retryTimer !== null) this.clearRetry()
      return this.kick()
    }
    this.espWant = { mock, ref }
    this.clearRetry()
    this.attempt = 0
    this.streakErr = false
    this.espError = undefined
    this.bindCancel = true
    await this.recon
    await this.teardownEsp()
    return this.kick()
  }

  private async disconnectEsp(): Promise<void> {
    this.espWant = null
    this.bindCancel = true
    this.clearRetry()
    await this.kick()
    this.espError = undefined
  }

  /** Runs fn with the link supervisor paused and the link stopped; restarts the link afterwards. */
  private async paused_(fn: () => Promise<void>): Promise<void> {
    if (this.link?.isLinked && this.allowArm && this.lastArmed) return this.err('esp', new Error('disarm first'))
    this.paused++
    this.bindCancel = false
    try {
      await this.recon
      this.phase = this.espWant ? 'paused' : 'off'
      const l = this.link
      if (l?.isLinked) {
        await l.stop()
        this.runCfg = null
      }
      await fn()
    } finally {
      this.paused--
      if (this.paused === 0) {
        this.clearRetry()
        void this.kick()
      }
    }
  }

  // --- FC

  private clearFcRetry(): void {
    if (this.fcTimer !== null) this.clock.clearTimeout(this.fcTimer)
    this.fcTimer = null
  }

  private async connectFc(mock: boolean, ref?: PortRef): Promise<void> {
    if (this.mock && !mock) return this.err('fc', new Error('mock mode: real ports are never opened'))
    if (mock) this.mock = true
    const want = { mock, ref }
    // a new connect (not our own retry of the same port) starts a fresh error streak
    if (JSON.stringify(this.fcWant) !== JSON.stringify(want)) {
      this.fcStreakErr = false
      this.fcInUse = false
    }
    this.fcWant = want
    this.clearFcRetry()
    try {
      if (this.poller) await this.closeFc()
      const port = await (mock ? this.d.mockPort('fc') : this.d.openPort('fc', ref))
      const msp = new BetaflightMSP(port, this.clock)
      await msp.open()
      this.msp = msp
      this.poller = new FcPoller(msp, this.clock)
      // mock only: the simulated FC has no RC input, so feed it the sticks (arm state follows ch7)
      this.mockFc = mock ? (port as unknown as { state: { rc: number[]; armed: boolean } }) : null
      this.poller.start()
      this.fcInUse = false
      this.fcStreakErr = false
    } catch (e) {
      if (e instanceof PortInUseError && this.fcWant === want) {
        // held by another app or tab: report once, then retry quietly until it lets go
        if (!this.fcStreakErr) this.err('fc', e)
        this.fcStreakErr = true
        this.fcInUse = true
        this.fcTimer = this.clock.setTimeout(() => {
          this.fcTimer = null
          if (this.fcWant === want) void this.guard('cfc', () => this.connectFc(want.mock, want.ref))
        }, IN_USE_RETRY_MS)
        return
      }
      this.fcInUse = false
      this.err('fc', e)
    }
  }

  private async closeFc(): Promise<void> {
    this.poller?.stop()
    const m = this.msp
    this.poller = null
    this.mockFc = null
    this.msp = null
    await m?.close().catch(() => undefined)
  }

  // --- bind

  private setBind(phase: BindPhase, o: { txid?: string; reason?: string; via?: 'telemetry' | 'fc' } = {}): void {
    this.bindPhase = phase
    this.bindTxid = o.txid ?? this.bindTxid
    this.bindReason = o.reason
    this.bindVia = o.via
  }

  /** Sleeps ms in small steps; false when the bind was cancelled meanwhile. */
  private async bindWait(ms: number, done?: () => boolean): Promise<boolean> {
    const end = this.clock.now() + ms
    while (this.clock.now() < end) {
      if (this.bindCancel) return false
      if (done?.()) return true
      await new Promise<void>((r) => this.clock.setTimeout(r, Math.min(100, end - this.clock.now())))
    }
    return !this.bindCancel
  }

  /**
   * One-click bind, like Betaflight Configurator's 'Bind receiver': ESP bind packets on, MSP2_BETAFLIGHT_BIND, wait
   * BIND_WINDOW_MS, bind off, then a short link with arming disallowed; bound once a telemetry reply with this ESP's txid
   * arrives (or, failing a decode, the FC's own MSP status shows its receiver out of failsafe). Runs paused (paused_).
   */
  private async bind(m: Extract<ToWorker, { type: 'bind' }>): Promise<void> {
    const l = this.link
    const msp = this.msp
    this.bindTxid = undefined
    const fail = (reason: string): void => this.setBind('failed', { reason })
    if (!l) return fail('DevKit not connected')
    if (!msp) return fail("drone USB not connected: Betaflight is told to bind over its USB port")
    if (l.isLinked) return fail('the link did not stop')
    const power = m.power ?? BIND_POWER
    const fofs = m.fofs_hz ?? this.cfg.fofs_hz
    this.setBind('binding')
    try {
      try {
        await l.id() // fresh txid, and the ESP is answering
        this.bindTxid = this.txid()
        await l.bind(power, fofs)
      } catch (e) {
        return fail(`DevKit: ${msg(e)}`)
      }
      try {
        try {
          await msp.bind()
        } catch {
          await msp.bind() // one retry: a poll may have collided with the request
        }
      } catch (e) {
        return fail(e instanceof MspError && e.kind === 'value'
          ? 'Betaflight refused to bind (receiver is not an SPI/SRXL2 receiver?)'
          : `drone did not answer the bind request: ${msg(e)}`)
      }
      if (!(await this.bindWait(BIND_WINDOW_MS))) return fail('cancelled')
    } finally {
      if (l.binding) await l.stopBind().catch(() => undefined)
    }

    this.setBind('confirming')
    const polls0 = this.poller?.polls ?? 0
    try {
      this.allowArm = false
      await l.start({ power, fofsHz: fofs, timeoutMs: 300, allowArm: false, telemetry: true })
    } catch (e) {
      return fail(`confirm link did not start: ${msg(e)}`)
    }
    let via: 'telemetry' | 'fc' | undefined
    let fcOkSince: number | null = null
    try {
      const ok = await this.bindWait(BIND_CONFIRM_MS, () => {
        if (!l.isLinked) return true
        if (l.telemetry().replies > 0) {
          via = 'telemetry'
          return true
        }
        // fallback: the FC itself reports its receiver out of failsafe (fresh polls only, held 2.5 s; 1 s at the deadline)
        const fs = this.poller?.state
        const fresh = (this.poller?.polls ?? 0) - polls0 >= 10
        if (fresh && fs?.connected && fs.failsafe === false) fcOkSince ??= this.clock.now()
        else fcOkSince = null
        if (fcOkSince !== null && this.clock.now() - fcOkSince >= 2500) {
          via = 'fc'
          return true
        }
        return false
      })
      if (!via && fcOkSince !== null && this.clock.now() - fcOkSince >= 1000) via = 'fc'
      const lost = !l.isLinked ? (l.lostReason ?? 'ended') : null
      if (l.isLinked) await l.stop()
      if (!ok) return fail('cancelled')
      if (lost) return fail(`confirm link ended (${lost})`)
      if (!via) return fail('no reply from the drone with this txid: bind did not take (drone powered? within range?)')
      this.setBind('bound', { txid: this.txid(), via })
    } finally {
      if (l.isLinked) await l.stop().catch(() => undefined)
    }
  }

  private driveMockFc(ch: number[]): void {
    const f = this.mockFc
    if (!f?.state || !this.link?.isLinked) return
    f.state.rc = ch.slice(0, 8)
    f.state.armed = this.allowArm && ch[6] > 1500
  }

  private watchUi(): void {
    if (this.uiTimer !== null) this.clock.clearTimeout(this.uiTimer)
    const check = (): void => {
      this.uiTimer = null
      const l = this.link
      if (!l?.isLinked) return
      if (this.clock.now() - this.lastUi > UI_SILENCE_MS) {
        if (this.guardAt === null && this.lastArmed) {
          this.guardAt = this.clock.now()
          this.guardWall = Date.now()
        }
        l.setSticks(SAFE_STICKS)
        this.driveMockFc(SAFE_STICKS)
      }
      this.uiTimer = this.clock.setTimeout(check, 250)
    }
    this.uiTimer = this.clock.setTimeout(check, 250)
  }

  async close(): Promise<void> {
    this.stopState()
    this.espWant = null
    this.bindCancel = true
    this.clearRetry()
    this.fcWant = null
    this.clearFcRetry()
    await this.kick()
    if (this.uiTimer !== null) this.clock.clearTimeout(this.uiTimer)
    this.uiTimer = null
    await this.closeFc()
  }
}
