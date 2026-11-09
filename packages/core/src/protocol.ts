// Protocol v1 helpers (see protocol/PROTOCOL.md). Port of python/d8tx/protocol.py + telemetry.py parsing.
export const LO = 1000
export const MID = 1500
export const HI = 2000
export const ARM_CH = 6 // index of ch7
export const ARM_LIMIT = 1300
export const SLOT_S = 0.008994
// 0 once the receiver is bound to this ESP over the air (it tunes its own offset to our carrier). -75000 was only for the cloned E8 binding.
export const DEFAULT_FOFS_HZ = 0
export const TXID: readonly [number, number] = [66, 178]
/** Hex txid text ("42B2") -> [id0, id1], or null when malformed. */
export function parseTxid(v: unknown): [number, number] | null {
  const m = /^([0-9a-fA-F]{2})([0-9a-fA-F]{2})$/.exec(String(v ?? ''))
  return m ? [parseInt(m[1], 16), parseInt(m[2], 16)] : null
}
export const BIND_TIMEOUT_MS = 30000
export const TLM_RECIPE = 'TLM 12 9000 40 64 0 1 1 0 1 1000 4'
export const MAX_LINE = 95

export class ProtocolError extends Error {
  code: string
  text: string
  constructor(code: string, text = '') {
    super(`${code} ${text}`.trim())
    this.name = 'ProtocolError'
    this.code = code
    this.text = text
  }
}

/** Throws if the line (without newline) is longer than the firmware line buffer. */
export function checkLine(line: string): string {
  if (line.replace(/[\r\n]+$/, '').length > MAX_LINE) throw new Error(`line longer than ${MAX_LINE}`)
  return line
}

/** Python round() semantics (half to even), then clamp to 1000..2000. */
function pyRound(v: number): number {
  const f = Math.floor(v)
  const d = v - f
  if (d < 0.5) return f
  if (d > 0.5) return f + 1
  return f % 2 === 0 ? f : f + 1
}

export function clamp(v: number): number {
  return Math.max(LO, Math.min(HI, pyRound(v)))
}

/** Returns the S line and the clamped channels. ch7 forced to 1000 unless allowArm. */
export function fmtSticks(ch: readonly number[], allowArm = false): { line: string; channels: number[] } {
  const c = ch.map(clamp)
  if (c.length !== 8) throw new Error('need 8 channels')
  if (!allowArm) c[ARM_CH] = LO
  const line = 'S ' + c.join(' ') + '\n'
  checkLine(line)
  return { line, channels: c }
}

export type KV = Record<string, number | string | boolean>

function kv(tokens: string[]): KV {
  const d: KV = {}
  for (const t of tokens) {
    const i = t.indexOf('=')
    if (i >= 0) {
      const k = t.slice(0, i)
      const v = t.slice(i + 1)
      d[k] = k !== 'txid' && /^-?\d+$/.test(v) ? Number(v) : v // txid is hex text ("0042" must not become 42)
    } else d[t] = true
  }
  return d
}

export type Parsed =
  | { kind: 'ok'; data: KV }
  | { kind: 'err'; code: string; text: string }
  | { kind: 'ev'; name: string; data: KV }
  | { kind: 'other'; text: string }

const split = (s: string): string[] => s.split(/\s+/).filter(Boolean)

export function parseLine(raw: string): Parsed {
  const line = raw.trim()
  if (line === 'OK' || line.startsWith('OK ')) return { kind: 'ok', data: kv(split(line.slice(3))) }
  if (line.startsWith('ERR')) {
    const m = /^(\S+)(?:\s+(\S+)(?:\s+([\s\S]*))?)?$/.exec(line)!
    return { kind: 'err', code: m[2] ?? 'unknown', text: m[3] ?? '' }
  }
  if (line.startsWith('EV ')) {
    const parts = split(line.slice(3))
    if (parts.length) return { kind: 'ev', name: parts[0], data: kv(parts.slice(1)) }
  }
  return { kind: 'other', text: line }
}

/** `EV tlm k=.. tid=.. bytes=..` -> ints (crc stays a string). */
export function parseTlmHeader(line: string): Record<string, number | string> {
  const out: Record<string, number | string> = {}
  for (const m of line.matchAll(/(\w+)=(-?[0-9a-fA-F]+)/g)) out[m[1]] = m[1] === 'crc' ? m[2] : parseInt(m[2], 10)
  return out
}

/** TLM bits=4 payload (I low nibble, Q high nibble, signed) -> int8 I,Q interleaved. */
export function unpack4(payload: Uint8Array): Int8Array {
  const out = new Int8Array(payload.length * 2)
  for (let i = 0; i < payload.length; i++) {
    const b = payload[i]
    out[2 * i] = ((b & 0xf) ^ 8) - 8
    out[2 * i + 1] = ((b >> 4) ^ 8) - 8
  }
  return out
}

let crcTable: Uint32Array | null = null
export function crc32(data: Uint8Array): number {
  if (!crcTable) {
    crcTable = new Uint32Array(256)
    for (let n = 0; n < 256; n++) {
      let c = n
      for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1
      crcTable[n] = c >>> 0
    }
  }
  let c = 0xffffffff
  for (let i = 0; i < data.length; i++) c = crcTable[(c ^ data[i]) & 0xff] ^ (c >>> 8)
  return (c ^ 0xffffffff) >>> 0
}

export type TlmMeta = Record<string, number | string>

export function payloadOk(meta: TlmMeta, payload: Uint8Array): boolean {
  const bytes = typeof meta.bytes === 'number' ? meta.bytes : -1
  const crc = parseInt(String(meta.crc ?? '0'), 16)
  return payload.length === bytes && crc32(payload) === crc
}

/** Betaflight re-request rule: advance the id only after a reply echoed it. */
export function nextTid(sent: number, replyTid: number | null | undefined): number {
  return replyTid === sent ? (sent + 1) & 0x1f : sent & 0x1f
}
