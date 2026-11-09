import { describe, expect, test } from 'vitest'
import { DEFAULTS, STORE_KEY, findSaved, load, save, storage } from './persist'

function mem(init?: string) {
  const m = new Map<string, string>()
  if (init !== undefined) m.set(STORE_KEY, init)
  return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v), m }
}

describe('persisted settings', () => {
  test('defaults when empty, corrupt or absent', () => {
    expect(load(mem())).toEqual(DEFAULTS)
    expect(load(mem('{not json'))).toEqual(DEFAULTS)
    expect(load(null)).toEqual(DEFAULTS)
  })

  test('round trip of settings and ports; patches merge', () => {
    const s = mem()
    save(s, { power: 60, fofs_hz: -75000, timeout_ms: 400, maxThr: 40 })
    save(s, { ports: { esp: { index: 1, usbVendorId: 0x10c4, usbProductId: 0xea60, auto: true } } })
    save(s, { ports: { fc: { index: 0, usbVendorId: 0x0483, usbProductId: 0x5740, auto: false } } })
    expect(load(s)).toEqual({
      power: 60, fofs_hz: -75000, timeout_ms: 400, maxThr: 40,
      ports: {
        esp: { index: 1, usbVendorId: 0x10c4, usbProductId: 0xea60, auto: true },
        fc: { index: 0, usbVendorId: 0x0483, usbProductId: 0x5740, auto: false },
      },
    })
  })

  test('out-of-range or wrong-typed fields fall back or clamp', () => {
    const s = mem(JSON.stringify({ power: 500, fofs_hz: 'x', timeout_ms: null, maxThr: -5, ports: { esp: { index: 'a' }, fc: { index: 2 } } }))
    expect(load(s)).toEqual({ ...DEFAULTS, power: 127, maxThr: 0, ports: { fc: { index: 2, usbVendorId: undefined, usbProductId: undefined, auto: true } } })
  })

  test('mock mode has no storage', () => {
    expect(storage(true)).toBeNull()
  })

  test('findSaved matches index and USB IDs, else USB IDs only', () => {
    const ports = [
      { index: 0, info: { usbVendorId: 0x0483, usbProductId: 0x5740 } },
      { index: 1, info: { usbVendorId: 0x10c4, usbProductId: 0xea60 } },
    ]
    expect(findSaved(ports, { index: 1, usbVendorId: 0x10c4, usbProductId: 0xea60 })).toBe(ports[1])
    // the order changed after a replug
    expect(findSaved(ports, { index: 0, usbVendorId: 0x10c4, usbProductId: 0xea60 })).toBe(ports[1])
    expect(findSaved(ports, { index: 0, usbVendorId: 0x1a86, usbProductId: 0x7523 })).toBeUndefined()
    expect(findSaved(ports, undefined)).toBeUndefined()
  })
})
