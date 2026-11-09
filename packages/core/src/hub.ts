// FrSky hub byte-stream parser and field decoding (port of python/d8tx/hub.py).
export class HubParser {
  private id: number | null = null // null: no header yet, -1: header seen, id next
  private val: number[] = []
  private esc = false

  reset(): void {
    this.id = null
    this.val = []
    this.esc = false
  }

  /** Feed hub bytes in arrival order; returns the [id, int16 value] frames completed by this call. */
  feed(data: ArrayLike<number>): [number, number][] {
    const out: [number, number][] = []
    for (let i = 0; i < data.length; i++) {
      let b = data[i]
      if (b === 0x5e) {
        this.id = -1
        this.val = []
        this.esc = false
        continue
      }
      if (this.id === null) continue
      if (this.id === -1) {
        this.id = b
        continue
      }
      if (this.esc) {
        b ^= 0x60
        this.esc = false
      } else if (b === 0x5d) {
        this.esc = true
        continue
      }
      this.val.push(b)
      if (this.val.length === 2) {
        let v = this.val[0] | (this.val[1] << 8)
        if (v & 0x8000) v -= 0x10000
        out.push([this.id, v])
        this.id = null
        this.val = []
      }
    }
    return out
  }
}

export interface PatchedField {
  hubId: number
  key: string
  index?: number
  size?: number
  scale?: number
  kind?: 'int' | 'float' | 'bool'
  bit?: number
}

const vec = (base: number, key: string, scale: number): PatchedField[] =>
  [0, 1, 2].map((i) => ({ hubId: base + i, key, index: i, size: 3, scale, kind: 'float' as const }))

export const PATCHED_FIELDS: PatchedField[] = [
  { hubId: 0x46, key: 'armed', kind: 'bool', bit: 0 },
  { hubId: 0x46, key: 'angle', kind: 'bool', bit: 1 },
  { hubId: 0x46, key: 'horizon', kind: 'bool', bit: 2 },
  { hubId: 0x46, key: 'failsafe', kind: 'bool', bit: 3 },
  { hubId: 0x46, key: 'arming_disabled', kind: 'bool', bit: 4 },
  { hubId: 0x46, key: 'acro', kind: 'bool', bit: 5 },
  { hubId: 0x47, key: 'arming_disable_flags' },
  ...vec(0x40, 'gyro_dps', 0.1),
  ...vec(0x43, 'attitude_deg', 0.1),
]

export const RPM_ARMED_MIN = 200
export const RPM_ARMED_MAX = 400

/** Radio-confirmed armed state from the stock RPM hub field, or null when ambiguous (see hub.py). */
export function armedFromRpm(rpm: number | null | undefined, baseline: number | null = null): boolean | null {
  if (rpm === null || rpm === undefined) return null
  const inRange = rpm === 0 || (rpm >= RPM_ARMED_MIN && rpm <= RPM_ARMED_MAX)
  if (!inRange) return false
  if (baseline !== null) {
    if (rpm !== baseline) return true
    return baseline === 0 || (baseline >= RPM_ARMED_MIN && baseline <= RPM_ARMED_MAX) ? null : false
  }
  return null
}

export interface HubSnapshot {
  acc_mg: (number | null)[] | null
  heading_deg: number | null
  rpm: number | null
  vfas_v: number | null
  current_a: number | null
  fuel: number | null
  temp1: number | null
  temp2: number | null
  patched: Record<string, unknown>
  raw: Record<string, number>
  age_ms: number | null
}

export function pyRound(x: number, nd: number): number {
  const m = 10 ** nd
  return Math.round(x * m + (x < 0 ? -1e-9 : 1e-9)) / m
}

export class HubState {
  patchedFields = new Map<number, PatchedField[]>()
  raw = new Map<number, number>()
  tId = new Map<number, number>()
  patched: Record<string, any> = {}
  tLast: number | null = null

  constructor(patched: PatchedField[] = PATCHED_FIELDS) {
    for (const f of patched) {
      const l = this.patchedFields.get(f.hubId)
      if (l) l.push(f)
      else this.patchedFields.set(f.hubId, [f])
    }
  }

  update(hubId: number, value: number, now: number): void {
    this.raw.set(hubId, value)
    this.tId.set(hubId, now)
    this.tLast = now
    for (const pf of this.patchedFields.get(hubId) ?? []) {
      let v: any
      if (pf.kind === 'bool') v = pf.bit !== undefined ? ((value >> pf.bit) & 1) === 1 : value !== 0
      else if (pf.kind === 'float') v = value * (pf.scale ?? 1)
      else v = value
      if (pf.index === undefined) this.patched[pf.key] = v
      else {
        const vec = (this.patched[pf.key] ??= new Array(pf.size ?? 1).fill(null))
        vec[pf.index] = v
      }
    }
    const p = this.patched
    if ('angle' in p) p.flight_mode = p.angle ? 'angle' : p.horizon ? 'horizon' : 'acro'
  }

  get(hubId: number): number | undefined {
    return this.raw.get(hubId)
  }

  ageS(hubId: number, now: number): number | null {
    const t = this.tId.get(hubId)
    return t === undefined ? null : now - t
  }

  vfasV(): number | null {
    const v = this.raw.get(0x39)
    if (v !== undefined) return v / 10
    const bp = this.raw.get(0x3a)
    const ap = this.raw.get(0x3b)
    if (bp !== undefined && ap !== undefined) return pyRound((bp + ap / 10) * 2, 2)
    return null
  }

  snapshot(now: number): HubSnapshot {
    const r = this.raw
    const g = (k: number): number | null => r.get(k) ?? null
    const acc = [g(0x24), g(0x25), g(0x26)]
    const cur = g(0x28)
    const rawObj: Record<string, number> = {}
    for (const k of [...r.keys()].sort((a, b) => a - b)) rawObj['0x' + k.toString(16).toUpperCase().padStart(2, '0')] = r.get(k)!
    return {
      acc_mg: acc.some((a) => a !== null) ? acc : null,
      heading_deg: r.has(0x14) ? r.get(0x14)! : null,
      rpm: g(0x03),
      vfas_v: this.vfasV(),
      current_a: cur === null ? null : cur / 10,
      fuel: g(0x04),
      temp1: g(0x02),
      temp2: g(0x05),
      patched: JSON.parse(JSON.stringify(this.patched)),
      raw: rawObj,
      age_ms: this.tLast === null ? null : Math.trunc((now - this.tLast) * 1000),
    }
  }
}
