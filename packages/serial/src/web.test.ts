import { describe, expect, it } from 'vitest'
import { findGrantedPorts, pickGrantedPort, portLabel, roleFilters } from './web.ts'

const port = (usbVendorId?: number, usbProductId?: number, name = '') => ({ name, getInfo: () => ({ usbVendorId, usbProductId }) })
const serial = (ports: unknown[]) => ({ getPorts: async () => ports })

const fc = port(0x0483, 0x5740, 'fc')
const cp = port(0x10c4, 0xea60, 'cp')
const ch = port(0x1a86, 0x7523, 'ch')
const cp2 = port(0x10c4, 0xea60, 'cp2')

describe('granted port selection', () => {
  it('opens the port at the picked index when its USB IDs agree', async () => {
    expect(await pickGrantedPort('esp', { index: 3, usbVendorId: 0x10c4, usbProductId: 0xea60 }, serial([fc, cp, ch, cp2]))).toBe(cp2)
  })
  it('falls back to the first port with the picked USB IDs when the orders differ', async () => {
    expect(await pickGrantedPort('esp', { index: 0, usbVendorId: 0x1a86, usbProductId: 0x7523 }, serial([fc, cp, ch]))).toBe(ch)
  })
  it('returns null when the picked port is gone, rather than opening another device', async () => {
    expect(await pickGrantedPort('esp', { index: 2, usbVendorId: 0x1a86, usbProductId: 0x55d4 }, serial([fc, cp, ch]))).toBeNull()
  })
  it('without a pick, uses the first granted port of the role by VID/PID', async () => {
    expect(await pickGrantedPort('esp', undefined, serial([fc, ch, cp]))).toBe(ch)
    expect(await pickGrantedPort('fc', undefined, serial([cp, fc]))).toBe(fc)
    expect(await pickGrantedPort('fc', undefined, serial([cp]))).toBeNull()
  })
  it('lists every DevKit bridge for the esp role', async () => {
    expect(await findGrantedPorts('esp', serial([fc, cp, ch]))).toEqual([cp, ch])
    expect(roleFilters('esp')).toHaveLength(3)
    expect(roleFilters('fc')).toEqual([{ usbVendorId: 0x0483, usbProductId: 0x5740 }])
  })
  it('labels ports by USB IDs', () => {
    expect(portLabel({ usbVendorId: 0x10c4, usbProductId: 0xea60 })).toBe('ESP32 DevKit (CP2102)')
    expect(portLabel({ usbVendorId: 0x1a86, usbProductId: 0x55d4 })).toBe('ESP32 DevKit (CH9102)')
    expect(portLabel({ usbVendorId: 0x0483, usbProductId: 0x5740 })).toBe('Betaflight FC (STM32 VCP)')
    expect(portLabel({ usbVendorId: 0x1234, usbProductId: 0xab })).toBe('USB serial 1234:00AB')
    expect(portLabel({})).toBe('Serial port')
  })
})
