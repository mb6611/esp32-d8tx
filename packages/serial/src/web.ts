// Web Serial transport (Chrome, Electron). Used on the UI thread or in a worker with navigator.serial.
import { PortInUseError, type SerialPort as D8Port } from '@d8tx/core'

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

/** Granted ports matching a role by USB VID/PID (never by order). */
export async function findGrantedPorts(role: UsbFilter, serial: { getPorts(): Promise<any[]> } = (globalThis as any).navigator.serial): Promise<any[]> {
  const ports = await serial.getPorts()
  return ports.filter((p) => {
    const i = p.getInfo?.() ?? {}
    return i.usbVendorId === role.usbVendorId && i.usbProductId === role.usbProductId
  })
}
