/** Byte transport used by D8Link and the MSP client. Adapters live in @d8tx/serial. */
export interface SerialPort {
  open(): Promise<void>
  /** Chunks as they arrive; ends when the port closes. */
  read(): AsyncIterable<Uint8Array>
  write(data: Uint8Array): Promise<void>
  close(): Promise<void>
  /** Bytes accepted by write() but not yet sent (write backpressure); optional. */
  readonly outWaiting?: number
}

export class PortInUseError extends Error {
  constructor(message = 'port in use') {
    super(message)
    this.name = 'PortInUseError'
  }
}
