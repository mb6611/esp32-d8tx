// Web Serial transport (Chrome, Electron). Used on the UI thread or in a worker with navigator.serial.
import { PortInUseError, type PortRef, type Role, type SerialPort as D8Port } from '@d8tx/core'

export const DEVKIT = { usbVendorId: 0x10c4, usbProductId: 0xea60, baud: 921600 } as const
export const FC = { usbVendorId: 0x0483, usbProductId: 0x5740, baud: 115200 } as const

interface WebSerialLike {
  open(o: { baudRate: number; bufferSize?: number }): Promise<void>
  close(): Promise<void>
  readable: ReadableStream<Uint8Array> | null
  writable: WritableStream<Uint8Array> | null
}

export class WebSerialPort implements D8Port {
  private port: WebSerialLike
  private baud: number
  private writer: WritableStreamDefaultWriter<Uint8Array> | null = null
  private reader: ReadableStreamDefaultReader<Uint8Array> | null = null
  private pending = 0

  constructor(port: unknown, baud: number) {
    this.port = port as WebSerialLike
    this.baud = baud
  }

  get outWaiting(): number {
    return this.pending
  }

  async open(): Promise<void> {
    try {
      await this.port.open({ baudRate: this.baud, bufferSize: 65536 })
    } catch (e) {
      const err = e as Error
      // Chrome: InvalidStateError "The port is already open", NetworkError "Failed to open serial port" when another
      // process or tab holds the device.
      if (err.name === 'InvalidStateError' || err.name === 'NetworkError') throw new PortInUseError(`port in use (${err.name}: ${err.message})`)
      throw e
    }
    this.writer = this.port.writable!.getWriter()
    this.reader = this.port.readable!.getReader()
  }

  read(): AsyncIterable<Uint8Array> {
    const self = this
    return {
      async *[Symbol.asyncIterator]() {
        const r = self.reader!
        for (;;) {
          const { value, done } = await r.read()
          if (done) return
          if (value) yield value
        }
      },
    }
  }

  async write(data: Uint8Array): Promise<void> {
    this.pending += data.length
    try {
      await this.writer!.write(data)
    } finally {
      this.pending -= data.length
    }
  }

  async close(): Promise<void> {
    try { await this.reader?.cancel() } catch { /* ignore */ }
    try { this.reader?.releaseLock() } catch { /* ignore */ }
    try { await this.writer?.close() } catch { /* ignore */ }
    try { this.writer?.releaseLock() } catch { /* ignore */ }
    this.reader = this.writer = null
    await this.port.close()
  }
}

export interface UsbFilter {
  usbVendorId: number
  usbProductId: number
}

export type PortRole = Role

/** Known USB serial devices, by VID/PID. A DevKit V1 ships with one of several USB-UART bridges. */
export const USB_DEVICES: readonly (UsbFilter & { role: PortRole; name: string; chip: string })[] = [
  { usbVendorId: 0x10c4, usbProductId: 0xea60, role: 'esp', name: 'ESP32 DevKit', chip: 'CP2102' },
  { usbVendorId: 0x1a86, usbProductId: 0x7523, role: 'esp', name: 'ESP32 DevKit', chip: 'CH340' },
  { usbVendorId: 0x1a86, usbProductId: 0x55d4, role: 'esp', name: 'ESP32 DevKit', chip: 'CH9102' },
  { usbVendorId: 0x0483, usbProductId: 0x5740, role: 'fc', name: 'Betaflight FC', chip: 'STM32 VCP' },
]

/** requestPort() filters for a role: every known VID/PID of that role. */
export function roleFilters(role: PortRole): UsbFilter[] {
  return USB_DEVICES.filter((d) => d.role === role).map(({ usbVendorId, usbProductId }) => ({ usbVendorId, usbProductId }))
}

export interface PortInfoLike {
  usbVendorId?: number
  usbProductId?: number
}

/** The known device for a port's USB IDs, if any. */
export function deviceOf(info: PortInfoLike) {
  return USB_DEVICES.find((d) => d.usbVendorId === info.usbVendorId && d.usbProductId === info.usbProductId)
}

const hex4 = (v: number) => v.toString(16).padStart(4, '0').toUpperCase()

/** Human label for a granted port, e.g. "ESP32 DevKit (CP2102)" or "USB serial 1234:5678". */
export function portLabel(info: PortInfoLike): string {
  const d = deviceOf(info)
  if (d) return `${d.name} (${d.chip})`
  if (info.usbVendorId !== undefined) return `USB serial ${hex4(info.usbVendorId)}:${hex4(info.usbProductId ?? 0)}`
  return 'Serial port'
}

const infoOf = (p: any): PortInfoLike => p?.getInfo?.() ?? {}

/** Granted ports matching a role by USB VID/PID (never by order). */
export async function findGrantedPorts(role: UsbFilter | PortRole, serial: { getPorts(): Promise<any[]> } = (globalThis as any).navigator.serial): Promise<any[]> {
  const ids = typeof role === 'string' ? roleFilters(role) : [role]
  const ports = await serial.getPorts()
  return ports.filter((p) => {
    const i = infoOf(p)
    return ids.some((f) => i.usbVendorId === f.usbVendorId && i.usbProductId === f.usbProductId)
  })
}

/**
 * The granted port to open: the one at ref.index when its USB IDs agree with ref, else the first granted port with
 * ref's USB IDs (the two threads' getPorts() orders can differ). Without a ref, the first granted port of the role.
 * Null when none fits.
 */
export async function pickGrantedPort(role: PortRole, ref: PortRef | undefined, serial: { getPorts(): Promise<any[]> } = (globalThis as any).navigator.serial): Promise<any | null> {
  const ports = await serial.getPorts()
  if (ref) {
    const same = (p: any) => {
      const i = infoOf(p)
      return i.usbVendorId === ref.usbVendorId && i.usbProductId === ref.usbProductId
    }
    const at = ports[ref.index]
    if (at && same(at)) return at
    return ports.find(same) ?? null
  }
  const ids = roleFilters(role)
  return ports.find((p) => {
    const i = infoOf(p)
    return ids.some((f) => i.usbVendorId === f.usbVendorId && i.usbProductId === f.usbProductId)
  }) ?? null
}
