// Radio telemetry: reply parsing, TID rule helpers and the rolling Tracker (port of python/d8tx/telemetry.py).
import { HubParser, HubState, armedFromRpm, pyRound, type HubSnapshot, type PatchedField } from './hub.ts'

export const REPLY_LEN = 0x11
export const POWERED_S = 3.0
export const LINK_S = 1.0
export const CATCH_WINDOW_S = 10.0
export const RPM_FRESH_S = 5.0
export const FAST_FLAG = 0x80
export const FAST_WINDOW_S = 5.0

export interface FastBlock {
  attitude_deg: number[]
  gyro_dps: number[]
  seq: number
}

export interface Reply {
  a1: number
  a2: number
  rssi: number
  hub_count: number
  tid: number
  hub: Uint8Array
  fast?: FastBlock
  cfo_hz?: number
  shift_hz?: number
  t_ms?: number
}

const sx = (v: number, bits: number): number => {
  v &= (1 << bits) - 1
  return v >> (bits - 1) ? v - (1 << bits) : v
}

/** 10-byte FAST block = little-endian 80-bit integer (see PROTOCOL.md). */
export function parseFast(block: ArrayLike<number>): FastBlock {
  let v = 0n
  for (let i = 9; i >= 0; i--) v = (v << 8n) | BigInt(block[i] ?? 0)
  const f = (shift: number, bits: number): number => sx(Number((v >> BigInt(shift)) & ((1n << BigInt(bits)) - 1n)), bits)
  const yaw = Number((v >> 24n) & 0xfffn)
  return {
    attitude_deg: [f(0, 12) / 10, f(12, 12) / 10, yaw / 10],
    gyro_dps: [f(36, 14) * 0.25, f(50, 14) * 0.25, f(64, 14) * 0.25],
    seq: Number((v >> 78n) & 3n),
  }
}

/** 18-byte D8 telemetry frame -> fields. */
export function parseReply(raw: ArrayLike<number>): Reply {
  const out: Reply = { a1: raw[3], a2: raw[4], rssi: raw[5], hub_count: raw[6], tid: raw[7], hub: new Uint8Array(0) }
  const slice = (a: number, b: number): Uint8Array => Uint8Array.from(Array.prototype.slice.call(raw, a, b))
  if (raw[6] & FAST_FLAG) out.fast = parseFast(slice(8, 18))
  else out.hub = slice(8, 8 + Math.min(raw[6], 10))
  return out
}

export function rssiDbm(byte: number): number | null {
  const s = byte >= 246 ? byte - 256 : byte
  if (s >= 65 && s <= 136) return pyRound(((s - 65) * 32) / 18 / 2 - 72, 1)
  if (s >= -10 && s <= 61) return pyRound((((s + 82) * 32) / 18 - 256) / 2 - 72, 1)
  return null
}

export function vbatFromA1(a1: number): number {
  return pyRound(a1 * 0.05, 2)
}

const same = (a: Uint8Array | null, b: Uint8Array): boolean => a !== null && a.length === b.length && a.every((x, i) => x === b[i])

export interface RadioSnapshot {
  fast: (FastBlock & { age_ms: number; rate_hz: number }) | null
  enabled: boolean
  powered: boolean
  link: boolean
  age_ms: number | null
  catch_rate: number | null
  triggers: number
  replies: number
  rssi: number | null
  rssi_dbm: number | null
  a1_raw: number | null
  a2_raw: number | null
  vbat_v: number | null
  battery: 'absent' | 'present' | null
  cfo_khz: number | null
  hub: HubSnapshot
  armed: boolean | null
  armed_source: 'patched' | 'rpm' | null
}

export class Tracker {
  private now: () => number // seconds
  private patchedTable?: PatchedField[]
  enabled = false
  triggers = 0
  replies = 0
  private window: [number, boolean][] = []
  private tReply: number | null = null
  private last: Reply | null = null
  private hub!: HubState
  private parser!: HubParser
  private prevChunk: Uint8Array | null = null
  private prevTid: number | null = null
  private fastLast: FastBlock | null = null
  private tFast: number | null = null
  private fastTimes: number[] = []
  private armedLowSince: number | null = null
  private rpmBase: number | null = null
  private rpmBaseN = 0

  constructor(now: () => number, patched?: PatchedField[]) {
    this.now = now
    this.patchedTable = patched
    this.reset(false)
  }

  reset(enabled: boolean): void {
    this.enabled = enabled
    this.triggers = this.replies = 0
    this.window = []
    this.tReply = null
    this.last = null
    this.hub = new HubState(this.patchedTable)
    this.parser = new HubParser()
    this.prevChunk = null
    this.prevTid = null
    this.fastLast = null
    this.tFast = null
    this.fastTimes = []
    this.armedLowSince = null
    this.rpmBase = null
    this.rpmBaseN = 0
  }

  noteTriggerMiss(): void {
    this.triggers++
    this.window.push([this.now(), false])
  }

  noteReply(rep: Reply): void {
    const now = this.now()
    this.triggers++
    this.replies++
    this.window.push([now, true])
    this.tReply = now
    this.last = rep
    if (rep.fast) {
      this.fastLast = rep.fast
      this.tFast = now
      this.fastTimes.push(now)
      return
    }
    const chunk = rep.hub
    if (chunk.length && !(rep.tid === this.prevTid && same(this.prevChunk, chunk))) {
      for (const [hid, val] of this.parser.feed(chunk)) {
        this.hub.update(hid, val, now)
        if (hid === 0x03) this.learnRpm(val, now)
      }
    }
    if (chunk.length) {
      this.prevChunk = chunk
      this.prevTid = rep.tid
    }
  }

  noteArmOnAir(high: boolean): void {
    if (high) this.armedLowSince = null
    else if (this.armedLowSince === null) this.armedLowSince = this.now()
  }

  private learnRpm(val: number, now: number): void {
    if (this.armedLowSince !== null && now - this.armedLowSince >= 2.0) {
      if (this.rpmBaseN >= 2) return
      if (this.rpmBase === val) this.rpmBaseN++
      else {
        this.rpmBase = val
        this.rpmBaseN = 1
      }
    }
  }

  private armedId(): number {
    for (const fs of this.hub.patchedFields.values()) for (const f of fs) if (f.key === 'armed') return f.hubId
    return -1
  }

  snapshot(): RadioSnapshot {
    const now = this.now()
    while (this.window.length && now - this.window[0][0] > CATCH_WINDOW_S) this.window.shift()
    const n = this.window.length
    const catchRate = n ? this.window.filter((w) => w[1]).length / n : null
    const age = this.tReply === null ? null : now - this.tReply
    const last: Partial<Reply> = this.last ?? {}
    const hub = this.hub.snapshot(now)
    const a1 = last.a1 ?? null
    let vbat = a1 === null ? null : vbatFromA1(a1)
    const vfasAge = this.hub.ageS(0x39, now)
    if (hub.vfas_v !== null && vfasAge !== null && vfasAge <= POWERED_S) vbat = hub.vfas_v
    let armed: boolean | null = null
    let src: 'patched' | 'rpm' | null = null
    const pa = hub.patched.armed
    if (pa !== undefined && pa !== null && (this.hub.ageS(this.armedId(), now) ?? 0) <= RPM_FRESH_S) {
      armed = Boolean(pa)
      src = 'patched'
    } else {
      const rage = this.hub.ageS(0x03, now)
      if (rage !== null && rage <= RPM_FRESH_S) {
        const base = this.rpmBaseN >= 2 ? this.rpmBase : null
        const a = armedFromRpm(hub.rpm, base)
        if (a !== null) {
          armed = a
          src = 'rpm'
        }
      }
    }
    while (this.fastTimes.length && now - this.fastTimes[0] > FAST_WINDOW_S) this.fastTimes.shift()
    let fast: RadioSnapshot['fast'] = null
    if (this.fastLast) {
      const k = this.fastTimes.length
      const t0 = k ? this.fastTimes[0] : now
      const rate = k > 1 && now > t0 ? (k - 1) / (now - t0) : 0
      fast = { ...this.fastLast, age_ms: Math.trunc((now - this.tFast!) * 1000), rate_hz: pyRound(rate, 2) }
    }
    return {
      fast,
      enabled: this.enabled,
      powered: age !== null && age <= POWERED_S,
      link: age !== null && age <= LINK_S,
      age_ms: age === null ? null : Math.trunc(age * 1000),
      catch_rate: catchRate === null ? null : pyRound(catchRate, 3),
      triggers: this.triggers,
      replies: this.replies,
      rssi: last.rssi ?? null,
      rssi_dbm: last.rssi === undefined ? null : rssiDbm(last.rssi),
      a1_raw: a1,
      a2_raw: last.a2 ?? null,
      vbat_v: vbat,
      battery: vbat === null ? null : vbat < 2.0 ? 'absent' : 'present',
      cfo_khz: last.cfo_hz === undefined ? null : pyRound(last.cfo_hz / 1000, 2),
      hub,
      armed,
      armed_source: src,
    }
  }
}

export function idleRadio(enabled = false): RadioSnapshot {
  return { ...new Tracker(() => 0).snapshot(), enabled }
}
