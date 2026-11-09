// Settings and last-used ports survive a reload (localStorage). Mock mode (?mock) never reads or writes them, so a
// simulated session cannot overwrite the real setup.
import { DEFAULT_FOFS_HZ, type PortRef, type Role } from '@d8tx/core'

export const STORE_KEY = 'd8tx.settings.v1'

export interface SavedPort extends PortRef {
  /** Reconnect on load: true after a connect, false after an explicit disconnect. */
  auto: boolean
}

export interface Saved {
  power: number
  fofs_hz: number
  timeout_ms: number
  maxThr: number
  ports: Partial<Record<Role, SavedPort>>
}

export const DEFAULTS: Saved = { power: 127, fofs_hz: DEFAULT_FOFS_HZ, timeout_ms: 300, maxThr: 100, ports: {} }

type StorageLike = Pick<Storage, 'getItem' | 'setItem'>

const num = (v: unknown, lo: number, hi: number, d: number): number => {
  const n = Number(v)
  return v !== null && v !== '' && Number.isFinite(n) ? Math.max(lo, Math.min(hi, n)) : d
}

function port(v: unknown): SavedPort | undefined {
  const p = v as Partial<SavedPort> | null
  if (!p || typeof p !== 'object' || !Number.isInteger(p.index)) return undefined
  const id = (x: unknown) => (Number.isInteger(x) ? (x as number) : undefined)
  return { index: p.index!, usbVendorId: id(p.usbVendorId), usbProductId: id(p.usbProductId), auto: p.auto !== false }
}

/** Saved settings merged over the defaults; bad or missing fields fall back to the defaults. */
export function load(store: StorageLike | null): Saved {
  let raw: Record<string, unknown> = {}
  try {
    raw = JSON.parse(store?.getItem(STORE_KEY) ?? '{}') ?? {}
  } catch {
    /* corrupt: defaults */
  }
  const ports = (raw.ports ?? {}) as Record<string, unknown>
  const out: Saved = {
    power: num(raw.power, 0, 127, DEFAULTS.power),
    fofs_hz: num(raw.fofs_hz, -200000, 200000, DEFAULTS.fofs_hz),
    timeout_ms: num(raw.timeout_ms, 50, 2000, DEFAULTS.timeout_ms),
    maxThr: num(raw.maxThr, 0, 100, DEFAULTS.maxThr),
    ports: {},
  }
  for (const r of ['esp', 'fc'] as Role[]) {
    const p = port(ports[r])
    if (p) out.ports[r] = p
  }
  return out
}

/** Merges a change into the saved settings. */
export function save(store: StorageLike | null, patch: Partial<Omit<Saved, 'ports'>> & { ports?: Partial<Record<Role, SavedPort>> }): Saved {
  const cur = load(store)
  const next: Saved = { ...cur, ...patch, ports: { ...cur.ports, ...patch.ports } }
  try {
    store?.setItem(STORE_KEY, JSON.stringify(next))
  } catch {
    /* quota or disabled storage: settings just do not persist */
  }
  return next
}

/** The browser's localStorage, or null in mock mode or where storage is unavailable. */
export function storage(mock: boolean): StorageLike | null {
  if (mock) return null
  try {
    return globalThis.localStorage ?? null
  } catch {
    return null
  }
}

interface PortLike {
  index: number
  info: { usbVendorId?: number; usbProductId?: number }
}

/** The granted port a saved ref names: same index and USB IDs, else the first with the same USB IDs. */
export function findSaved<P extends PortLike>(ports: P[], ref: PortRef | undefined): P | undefined {
  if (!ref) return undefined
  const same = (p: P) => p.info.usbVendorId === ref.usbVendorId && p.info.usbProductId === ref.usbProductId
  const at = ports.find((p) => p.index === ref.index)
  return at && same(at) ? at : ports.find(same)
}
