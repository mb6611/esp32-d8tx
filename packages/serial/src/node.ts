// Node transport for hardware-in-the-loop tests and scripts (macOS / Linux). Dev only: never imported by the UI path.
//
// Not the `serialport` npm package: on macOS its read wake-ups missed data from the Betaflight USB CDC port (a reply sat
// unread until the next write). Plain non-blocking fd reads after `stty` raw setup are reliable on both bench devices.
import { execFileSync } from 'node:child_process'
import * as fs from 'node:fs'
import { PortInUseError, type SerialPort } from '@d8tx/core'

const POLL_MS = 1
const OPEN_FLAGS = fs.constants.O_RDWR | fs.constants.O_NOCTTY | fs.constants.O_NONBLOCK

// D8TX_SERIAL_DEBUG=1: close timing; =2 also every byte chunk in/out (printable text, binary runs summarised) on stderr.
const DEBUG = Number(process.env.D8TX_SERIAL_DEBUG ?? 0) || 0
const T0 = Date.now()
function trace(dir: string, b: Uint8Array): void {
  let s = ''
  let bin = 0
  const flush = (): void => {
    if (bin) s += `<${bin}b>`
    bin = 0
  }
  for (const c of b) {
    if (c === 10) { flush(); s += '\\n' } else if (c >= 32 && c < 127) { flush(); s += String.fromCharCode(c) } else bin++
  }
  flush()
  process.stderr.write(`[serial ${((Date.now() - T0) / 1000).toFixed(3)}] ${dir} ${s}\n`)
}

export class NodeSerialPort implements SerialPort {
  private path: string
  private baud: number
  private fd = -1
  private closed = false
  private pending = 0
  private chain: Promise<void> = Promise.resolve()
  private inflight: Promise<unknown> = Promise.resolve() // the current threadpool fs.read, if any

  constructor(path: string, baudRate: number) {
    this.path = path
    this.baud = baudRate
  }

  get outWaiting(): number {
    return this.pending
  }

  async open(): Promise<void> {
    try {
      this.fd = fs.openSync(this.path, OPEN_FLAGS)
      // termios is per device and persists while any fd is open, so it is set through a second, short-lived fd: a
      // child's stdio fd shares its open file description, and libuv clears O_NONBLOCK on child stdio, which would turn
      // our reads blocking (a threadpool read then pins the fd and close waits for it, up to a minute on the CP2102).
      this.onSideFd((fd) => {
        execFileSync('stty', [String(this.baud), 'raw', '-echo', 'clocal', 'cread', '-crtscts', '-hupcl'], { stdio: [fd, 'ignore', 'ignore'], timeout: 3000 })
      })
    } catch (e) {
      if (this.fd >= 0) try { fs.closeSync(this.fd) } catch { /* ignore */ }
      this.fd = -1
      const m = (e as Error).message
      if (/EBUSY|resource busy|EACCES/i.test(m)) throw new PortInUseError(`port in use (${m})`)
      throw e
    }
  }

  private onSideFd(fn: (fd: number) => void): void {
    const fd = fs.openSync(this.path, OPEN_FLAGS)
    try { fn(fd) } finally { fs.closeSync(fd) }
  }

  read(): AsyncIterable<Uint8Array> {
    const self = this
    return {
      async *[Symbol.asyncIterator]() {
        const buf = Buffer.alloc(8192)
        while (!self.closed) {
          const p = new Promise<number>((res) =>
            fs.read(self.fd, buf, 0, buf.length, null, (err, n) => res(err ? (err.code === 'EAGAIN' ? 0 : -1) : n)),
          )
          self.inflight = p
          const n = await p
          if (n < 0) return
          if (n > 0) {
            const chunk = new Uint8Array(buf.subarray(0, n))
            if (DEBUG >= 2) trace('rx', chunk)
            yield chunk
          }
          else await new Promise<void>((r) => setTimeout(r, POLL_MS))
        }
      },
    }
  }

  write(data: Uint8Array): Promise<void> {
    if (DEBUG >= 2) trace('tx', data)
    this.pending += data.length
    const run = async (): Promise<void> => {
      try {
        let off = 0
        while (off < data.length && !this.closed) {
          const n = await new Promise<number>((res, rej) =>
            fs.write(this.fd, data, off, data.length - off, null, (err, w) => (err ? (err.code === 'EAGAIN' ? res(0) : rej(err)) : res(w))),
          )
          off += n
          if (n === 0) await new Promise<void>((r) => setTimeout(r, POLL_MS))
        }
      } finally {
        this.pending -= data.length
      }
    }
    const p = this.chain.then(run, run)
    this.chain = p.catch(() => undefined)
    return p
  }

  // Close in an order that never leaves the kernel waiting: stop issuing reads and writes, wait for the threadpool
  // read/write in flight to return, discard both tty queues, then close. Before this, closeSync could block the main
  // thread for a minute or more in __close_nocancel on the CP2102 (macOS DriverKit) after a streaming session (cause:
  // O_NONBLOCK lost to stty, see open()).
  async close(): Promise<void> {
    if (this.closed) return
    this.closed = true
    const dbg = process.env.D8TX_SERIAL_DEBUG ? (m: string) => process.stderr.write(`[serial] ${m}\n`) : () => {}
    const t0 = Date.now()
    const settle = (p: Promise<unknown>) => Promise.race([p.catch(() => undefined), new Promise((r) => setTimeout(r, 500))])
    await settle(this.inflight)
    await settle(this.chain)
    dbg(`io settled ${Date.now() - t0} ms`)
    try {
      // tcflush(TCIOFLUSH) (Node has no termios binding; best effort) so the last close has no output to drain.
      this.onSideFd((fd) => {
        execFileSync('python3', ['-c', 'import termios; termios.tcflush(0, termios.TCIOFLUSH)'], { stdio: [fd, 'ignore', 'ignore'], timeout: 2000 })
      })
    } catch { /* no python3: close anyway */ }
    dbg(`flushed ${Date.now() - t0} ms`)
    const fd = this.fd
    this.fd = -1
    await new Promise<void>((r) => fs.close(fd, () => r()))
    dbg(`closed ${Date.now() - t0} ms`)
  }
}
