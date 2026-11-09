// Minimal read-only MSP v1 client for Betaflight (port of python/d8tx/msp.py).
import type { Clock } from './clock.ts'
import type { SerialPort } from './port.ts'

export const MSP_STATUS = 101
export const MSP_MOTOR = 104
export const MSP_RC = 105
export const MSP_ATTITUDE = 108
export const MSP_ANALOG = 110
export const ARMING_DISABLE = [
  'NO_GYRO', 'FAILSAFE', 'RX_FAILSAFE', 'BAD_RX_RECOVERY', 'BOXFAILSAFE', 'RUNAWAY_TAKEOFF', 'CRASH_DETECTED',
  'THROTTLE', 'ANGLE', 'BOOT_GRACE_TIME', 'NOPREARM', 'LOAD', 'CALIBRATING', 'CLI', 'CMS_MENU', 'BST', 'MSP',
  'PARALYZE', 'GPS', 'RESC', 'RPMFILTER', 'REBOOT_REQUIRED', 'DSHOT_BBANG', 'ACC_CALIBRATION', 'MOTOR_PROTOCOL',
  'ARM_SWITCH',
]
export const ARMED_FLAG = 1

export class MspError extends Error {
  kind: 'timeout' | 'value'
  constructor(kind: 'timeout' | 'value', message: string) {
    super(message)
    this.kind = kind
    this.name = 'MspError'
  }
}

export function frame(cmd: number, payload: Uint8Array = new Uint8Array(0)): Uint8Array {
  const out = new Uint8Array(6 + payload.length)
  out.set([0x24, 0x4d, 0x3c, payload.length, cmd])
  out.set(payload, 5)
  let c = 0
  for (let i = 3; i < 5 + payload.length; i++) c ^= out[i]
  out[5 + payload.length] = c
  return out
}

export interface MspFrame {
  cmd: number
  payload: Uint8Array
}

/** Incremental frame scanner mirroring msp.read_frame. Throws MspError('value') on checksum / error reply. */
export function scanFrame(buf: number[]): MspFrame | null {
  const i = findMs(buf)
  if (i < 0) {
    buf.splice(0, Math.max(0, buf.length - 1))
    return null
  }
  buf.splice(0, i)
  if (buf.length >= 5) {
    const n = buf[3]
    if (buf.length >= 6 + n) {
      const d = buf[2]
      let c = 0
      for (let k = 3; k < 5 + n; k++) c ^= buf[k]
      const cmd = buf[4]
      const payload = Uint8Array.from(buf.slice(5, 5 + n))
      const ok = c === buf[5 + n]
      buf.splice(0, 6 + n)
      if (!ok) throw new MspError('value', 'bad MSP checksum')
      if (d === 0x21) throw new MspError('value', `MSP error reply cmd=${cmd}`)
      return { cmd, payload }
    }
  }
  return null
}

function findMs(buf: number[]): number {
  for (let i = 0; i + 1 < buf.length; i++) if (buf[i] === 0x24 && buf[i + 1] === 0x4d) return i
  return -1
}

const dv = (p: Uint8Array): DataView => new DataView(p.buffer, p.byteOffset, p.byteLength)

export function parseRc(p: Uint8Array): number[] {
  const out: number[] = []
  for (let i = 0; i + 1 < p.length; i += 2) out.push(p[i] | (p[i + 1] << 8))
  return out
}

export function parseAttitude(p: Uint8Array): number[] {
  const v = dv(p)
  return [v.getInt16(0, true) / 10, v.getInt16(2, true) / 10, v.getInt16(4, true)]
}

export function parseAnalog(p: Uint8Array) {
  const v = dv(p)
  return { vbat_dv: v.getUint8(0), mah: v.getUint16(1, true), rssi: v.getUint16(3, true), amps_cA: v.getInt16(5, true), vbat_cv: v.getUint16(7, true) }
}

export function parseStatus(p: Uint8Array) {
  const v = dv(p)
  const cycle = v.getUint16(0, true)
  const flags = v.getUint32(6, true)
  const load = v.getUint16(11, true)
  const n = p[15]
  const o = 16 + n
  const cnt = p[o]
  const arm = v.getUint32(o + 1, true)
  const names: string[] = []
  for (let i = 0; i < Math.min(cnt, ARMING_DISABLE.length); i++) if ((arm >>> i) & 1) names.push(ARMING_DISABLE[i])
  return {
    cycle_us: cycle,
    mode_flags: flags,
    load,
    arming_disable: names,
    arming_disable_mask: arm,
    armed: (flags & ARMED_FLAG) !== 0,
    failsafe: names.includes('RX_FAILSAFE') || names.includes('FAILSAFE'),
  }
}

export function parseMotors(p: Uint8Array): number[] {
  return parseRc(p).slice(0, 4)
}

/** MSP client over a SerialPort. Requests are serialized. */
export class BetaflightMSP {
  private port: SerialPort
  private clock: Clock
  private timeoutMs: number
  private minGapMs: number
  private tLast = -Infinity
  private buf: number[] = []
  private waiter: (() => void) | null = null
  private chain: Promise<unknown> = Promise.resolve()
  private closed = false
  private pump: Promise<void> | null = null

  /** minGapMs: pause between requests; the MATEKF411RX drops requests that arrive within ~15 ms of the previous one. */
  constructor(port: SerialPort, clock: Clock, timeoutMs = 200, minGapMs = 20) {
    this.minGapMs = minGapMs
    this.port = port
    this.clock = clock
    this.timeoutMs = timeoutMs
  }

  /** Opens the port and starts the read pump. */
  async open(): Promise<void> {
    await this.port.open()
    this.pump = (async () => {
      try {
        for await (const chunk of this.port.read()) {
          for (const b of chunk) this.buf.push(b)
          if (this.buf.length > 4096) this.buf.splice(0, this.buf.length - 4096)
          this.waiter?.()
        }
      } catch {
        /* port closed */
      }
      this.closed = true
      this.waiter?.()
    })()
  }

  private async readFrame(): Promise<MspFrame> {
    const end = this.clock.now() + this.timeoutMs
    for (;;) {
      const f = scanFrame(this.buf)
      if (f) return f
      if (this.closed) throw new MspError('timeout', 'MSP port closed')
      const left = end - this.clock.now()
      if (left <= 0) throw new MspError('timeout', 'MSP timeout')
      await new Promise<void>((res) => {
        const h = this.clock.setTimeout(() => {
          this.waiter = null
          res()
        }, left)
        this.waiter = () => {
          this.clock.clearTimeout(h)
          this.waiter = null
          res()
        }
      })
    }
  }

  request(cmd: number): Promise<Uint8Array> {
    const run = async (): Promise<Uint8Array> => {
      const wait = this.tLast + this.minGapMs - this.clock.now()
      if (wait > 0) await new Promise<void>((r) => this.clock.setTimeout(r, wait))
      this.buf.length = 0
      try {
        await this.port.write(frame(cmd))
        for (;;) {
          const f = await this.readFrame()
          if (f.cmd === cmd) return f.payload
        }
      } finally {
        this.tLast = this.clock.now()
      }
    }
    const p = this.chain.then(run, run)
    this.chain = p.catch(() => undefined)
    return p
  }

  async rc() { return parseRc(await this.request(MSP_RC)) }
  async attitude() { return parseAttitude(await this.request(MSP_ATTITUDE)) }
  async status() { return parseStatus(await this.request(MSP_STATUS)) }
  async motors() { return parseMotors(await this.request(MSP_MOTOR)) }
  async rssi() { return parseAnalog(await this.request(MSP_ANALOG)).rssi }

  async close(): Promise<void> {
    this.closed = true
    try {
      await this.port.close()
    } catch {
      /* ignore */
    }
    await this.pump
  }
}
