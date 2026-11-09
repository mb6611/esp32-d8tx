// Minimal MSP client for Betaflight (port of python/d8tx/msp.py): v1 reads plus the v2 MSP2_BETAFLIGHT_BIND command.
import type { Clock } from './clock.ts'
import type { SerialPort } from './port.ts'

export const MSP_STATUS = 101
export const MSP_MOTOR = 104
export const MSP_RC = 105
export const MSP_ATTITUDE = 108
export const MSP_ANALOG = 110
/** MSP v2: put the receiver in bind mode (what Configurator's 'Bind receiver' sends). BF 4.2: RX_SPI (FrSky D/X) and SRXL2;
 * replies with an empty ack, or an error frame when the receiver cannot bind. */
export const MSP2_BETAFLIGHT_BIND = 0x3000
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

/** CRC-8/DVB-S2 (poly 0xD5), the MSP v2 checksum. */
export function crc8DvbS2(data: ArrayLike<number>, from = 0, to = data.length, crc = 0): number {
  for (let i = from; i < to; i++) {
    crc ^= data[i]
    for (let k = 0; k < 8; k++) crc = crc & 0x80 ? ((crc << 1) ^ 0xd5) & 0xff : (crc << 1) & 0xff
  }
  return crc
}

/** MSP v2 request: `$X<` flag cmd(u16 LE) len(u16 LE) payload crc8_dvb_s2(flag..payload). */
export function frameV2(cmd: number, payload: Uint8Array = new Uint8Array(0)): Uint8Array {
  const n = payload.length
  const out = new Uint8Array(9 + n)
  out.set([0x24, 0x58, 0x3c, 0, cmd & 255, (cmd >> 8) & 255, n & 255, (n >> 8) & 255])
  out.set(payload, 8)
  out[8 + n] = crc8DvbS2(out, 3, 8 + n)
  return out
}

export interface MspFrame {
  cmd: number
  payload: Uint8Array
  /** true for an MSP v2 (`$X`) frame */
  v2?: boolean
}

/** Incremental frame scanner (v1 `$M` and v2 `$X`) mirroring msp.read_frame. Throws MspError('value') on checksum / error reply. */
export function scanFrame(buf: number[]): MspFrame | null {
  const i = findMs(buf)
  if (i < 0) {
    buf.splice(0, Math.max(0, buf.length - 1))
    return null
  }
  buf.splice(0, i)
  if (buf[1] === 0x58) return scanV2(buf)
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

function scanV2(buf: number[]): MspFrame | null {
  if (buf.length < 8) return null
  const n = buf[6] | (buf[7] << 8)
  if (n > 4096) {
    buf.splice(0, 2) // not a sane frame: resync
    throw new MspError('value', 'bad MSP v2 length')
  }
  if (buf.length < 9 + n) return null
  const d = buf[2]
  const cmd = buf[4] | (buf[5] << 8)
  const ok = crc8DvbS2(buf, 3, 8 + n) === buf[8 + n]
  const payload = Uint8Array.from(buf.slice(8, 8 + n))
  buf.splice(0, 9 + n)
  if (!ok) throw new MspError('value', 'bad MSP v2 checksum')
  if (d === 0x21) throw new MspError('value', `MSP error reply cmd=0x${cmd.toString(16)}`)
  return { cmd, payload, v2: true }
}

function findMs(buf: number[]): number {
  for (let i = 0; i + 1 < buf.length; i++) if (buf[i] === 0x24 && (buf[i + 1] === 0x4d || buf[i + 1] === 0x58)) return i
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

  /** One request/reply. v2: send as an MSP v2 frame (commands above 255 need it). */
  request(cmd: number, opts: { v2?: boolean; payload?: Uint8Array } = {}): Promise<Uint8Array> {
    const v2 = opts.v2 ?? cmd > 255
    const run = async (): Promise<Uint8Array> => {
      const wait = this.tLast + this.minGapMs - this.clock.now()
      if (wait > 0) await new Promise<void>((r) => this.clock.setTimeout(r, wait))
      this.buf.length = 0
      try {
        await this.port.write(v2 ? frameV2(cmd, opts.payload) : frame(cmd, opts.payload))
        for (;;) {
          const f = await this.readFrame()
          if (f.cmd === cmd && !!f.v2 === v2) return f.payload
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
  /** Puts the receiver in bind mode (MSP2_BETAFLIGHT_BIND). Throws MspError('value') when the FC refuses. */
  async bind(): Promise<void> { await this.request(MSP2_BETAFLIGHT_BIND, { v2: true }) }

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
