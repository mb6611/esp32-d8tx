// Flight-controller poller on the schedule of the retired python/d8tx/server.py: RC + attitude every poll, motors every 2nd,
// status + RSSI every 5th (starting with the first).
import type { Clock } from './clock.ts'
import type { BetaflightMSP } from './msp.ts'

export interface FcState {
  connected: boolean
  rc: number[]
  attitude_deg: number[] | null
  motors: number[] | null
  armed: boolean | null
  failsafe: boolean | null
  arming_disable: string[]
  rssi: number | null
  error: string | null
}

export const FC_DEFAULT: FcState = {
  connected: false, rc: [], attitude_deg: null, motors: null, armed: null, failsafe: null, arming_disable: [], rssi: null, error: null,
}

export class FcPoller {
  state: FcState = { ...FC_DEFAULT }
  polls = 0
  private msp: BetaflightMSP
  private clock: Clock
  private gapMs: number
  private running = false
  private timer: unknown = null
  private listeners: ((s: FcState) => void)[] = []

  constructor(msp: BetaflightMSP, clock: Clock, gapMs = 5) {
    this.msp = msp
    this.clock = clock
    this.gapMs = gapMs
  }

  onState(cb: (s: FcState) => void): void {
    this.listeners.push(cb)
  }

  /** One poll cycle; never throws (errors land in state.error with connected=false). */
  async poll(): Promise<FcState> {
    const out: FcState = { ...FC_DEFAULT, ...this.state }
    try {
      this.polls++
      const rc = await this.msp.rc()
      out.connected = true
      out.rc = rc.slice(0, 8)
      out.error = null
      out.attitude_deg = await this.msp.attitude()
      if (this.polls % 2 === 0) out.motors = await this.msp.motors()
      if (this.polls % 5 === 1) {
        const s = await this.msp.status()
        out.rssi = await this.msp.rssi()
        out.armed = s.armed
        out.failsafe = s.failsafe
        out.arming_disable = s.arming_disable
      }
    } catch (e) {
      out.connected = false
      out.error = e instanceof Error ? e.message : String(e)
    }
    this.state = out
    for (const cb of this.listeners) cb(out)
    return out
  }

  start(): void {
    if (this.running) return
    this.running = true
    const loop = async (): Promise<void> => {
      if (!this.running) return
      await this.poll()
      if (this.running) this.timer = this.clock.setTimeout(() => void loop(), this.gapMs)
    }
    void loop()
  }

  stop(): void {
    this.running = false
    if (this.timer !== null) this.clock.clearTimeout(this.timer)
    this.timer = null
  }
}
