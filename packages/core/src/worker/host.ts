// Worker host (R10): owns the ports, D8Link, FC poller and demod; the UI only sends intents and receives state.
import { realClock, type Clock } from '../clock.ts'
import { FcPoller, FC_DEFAULT } from '../fc.ts'
import { D8Error, D8Link, type DecodeFn } from '../link.ts'
import { BetaflightMSP } from '../msp.ts'
import { PortInUseError, type SerialPort } from '../port.ts'
import { idleRadio } from '../telemetry.ts'
import type { ErrorKind, FromWorker, Role, ToWorker } from './types.ts'

export const STATE_HZ = 50
/** If the UI goes silent this long while linked, the host disarms and centres the sticks (the link itself stays up). */
export const UI_SILENCE_MS = 2500
const SAFE_STICKS = [1000, 1500, 1500, 1500, 1000, 1000, 1000, 1000]

export interface HostDeps {
  post(msg: FromWorker): void
  /** Real port for the role: the granted port matching its USB VID/PID. Throws when none was granted. */
  openPort(role: Role): Promise<SerialPort>
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
export class NoPortError extends Error {
  constructor(m: string) {
    super(m)
    this.name = 'NoPortError'
  }
}

export class Host {
  private d: HostDeps
  private clock: Clock
  private link: D8Link | null = null
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
  private mockFc: { state: { rc: number[]; armed: boolean } } | null = null
  private timer: unknown = null
  private busy = new Set<string>()

  constructor(deps: HostDeps) {
    this.d = deps
    this.clock = deps.clock ?? realClock
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
    const connected = !!l && lost !== 'port_closed'
    const esp: Record<string, unknown> = {
      connected,
      error: this.espError,
      info: this.info,
      link: !!l?.isLinked,
      keyed: !!st?.keyed,
      fofs: st?.fofs,
      slots: st?.slots,
      late_max_us: st?.late_max_us,
      allow_arm: l?.isLinked ? this.allowArm : false,
      sender_hz: st?.sender_hz,
      sender_max_gap_ms: st?.sender_max_gap_ms,
      skipped: st?.skipped,
      lost_reason: l?.isLinked ? null : lost,
      protocol_ok: l?.protocolOk,
      guard: this.guardAt !== null ? 'ui-silent' : undefined,
      guard_at: this.guardWall ?? undefined,
    }
    const fs = this.poller?.state ?? FC_DEFAULT
    const fc: Record<string, unknown> = { ...fs, error: fs.error ?? undefined, armed: fs.armed ?? undefined, failsafe: fs.failsafe ?? undefined, rssi: fs.rssi ?? undefined }
    const radio = (l ? l.telemetry() : idleRadio()) as unknown as Record<string, unknown>
    return { mock: this.mock, esp, fc, radio }
  }

  private err(role: Role | undefined, e: unknown): void {
    this.d.post({ type: 'error', role, kind: errKind(e), message: e instanceof Error ? e.message : String(e) })
  }

  async handle(m: ToWorker): Promise<void> {
    switch (m.type) {
      case 'sticks':
        this.lastUi = this.clock.now()
        if (this.guardAt !== null) {
          // latched: only a disarmed UI frame (explicit re-arm needed afterwards) releases the guard
          if (m.ch[6] > 1500) {
            this.link?.setSticks(SAFE_STICKS)
            return
          }
          this.guardAt = null
          this.guardWall = null
        }
        this.lastArmed = m.ch[6] > 1500
        this.link?.setSticks(m.ch)
        this.driveMockFc(m.ch)
        return
      case 'connect':
        return this.guard(`c${m.role}`, () => this.connect(m.role, !!m.mock))
      case 'disconnect':
        return this.guard(`c${m.role}`, () => this.disconnect(m.role))
      case 'start':
        return this.guard('start', () => this.start(m))
      case 'stop':
        return this.guard('start', async () => {
          await this.link?.stop()
        })
    }
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

  private async connect(role: Role, mock: boolean): Promise<void> {
    if (this.mock && !mock) return this.err(role, new Error('mock mode: real ports are never opened'))
    if (mock) this.mock = true
    try {
      if (role === 'esp') {
        if (this.link) await this.disconnect('esp')
        const port = await (mock ? this.d.mockPort('esp') : this.d.openPort('esp'))
        const link = new D8Link(port, this.clock, { decode: this.d.decode })
        this.espError = undefined
        await link.open()
        this.link = link
        this.info = undefined
        // End a link or partial line left by an earlier session before asking for INFO.
        try {
          await link.sync()
        } catch {
          /* INFO retries below report the error */
        }
        // Opening the port resets the ESP32; the first INFO may land before it boots.
        let last: unknown
        for (let i = 0; i < 3 && !this.info; i++) {
          try {
            this.info = (await link.info()) as Record<string, string | number>
          } catch (e) {
            last = e
          }
        }
        if (!this.info) throw last
        if (!link.protocolOk) this.err('esp', new D8Error('protocol', `firmware does not report proto=1 (${JSON.stringify(this.info)}); arming refused`))
      } else {
        if (this.poller) await this.disconnect('fc')
        const port = await (mock ? this.d.mockPort('fc') : this.d.openPort('fc'))
        const msp = new BetaflightMSP(port, this.clock)
        await msp.open()
        this.msp = msp
        this.poller = new FcPoller(msp, this.clock)
        // mock only: the simulated FC has no RC input, so feed it the sticks (arm state follows ch7)
        this.mockFc = mock ? (port as unknown as { state: { rc: number[]; armed: boolean } }) : null
        this.poller.start()
      }
    } catch (e) {
      if (role === 'esp') {
        this.espError = e instanceof Error ? e.message : String(e)
        await this.link?.close().catch(() => undefined)
        this.link = null
      }
      this.err(role, e)
    }
  }

  private async disconnect(role: Role): Promise<void> {
    if (role === 'esp') {
      const l = this.link
      this.link = null
      this.info = undefined
      this.espError = undefined
      await l?.close().catch(() => undefined)
    } else {
      this.poller?.stop()
      const m = this.msp
      this.poller = null
      this.mockFc = null
      this.msp = null
      await m?.close().catch(() => undefined)
    }
  }

  private async start(m: Extract<ToWorker, { type: 'start' }>): Promise<void> {
    const l = this.link
    if (!l) return this.err('esp', new Error('ESP32 not connected'))
    try {
      this.allowArm = m.allow_arm
      this.guardAt = null
      this.guardWall = null
      this.lastUi = this.clock.now()
      await l.start({ power: m.power, fofsHz: m.fofs_hz, timeoutMs: m.timeout_ms, allowArm: m.allow_arm, telemetry: true })
      this.watchUi()
    } catch (e) {
      this.allowArm = false
      this.err('esp', e)
    }
  }

  private driveMockFc(ch: number[]): void {
    const f = this.mockFc
    if (!f?.state || !this.link?.isLinked) return
    f.state.rc = ch.slice(0, 8)
    f.state.armed = this.allowArm && ch[6] > 1500
  }

  private watchUi(): void {
    const check = (): void => {
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
      this.clock.setTimeout(check, 250)
    }
    this.clock.setTimeout(check, 250)
  }

  async close(): Promise<void> {
    this.stopState()
    await this.disconnect('esp')
    await this.disconnect('fc')
  }
}
