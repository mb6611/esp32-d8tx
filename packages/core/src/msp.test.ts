import { describe, expect, test } from 'vitest'
import { FakeClock } from './clock.ts'
import { BetaflightMSP, MSP2_BETAFLIGHT_BIND, MspError, crc8DvbS2, frame, frameV2, scanFrame } from './msp.ts'
import type { SerialPort } from './port.ts'

const hex = (b: ArrayLike<number>): string => Array.from(b, (x) => x.toString(16).padStart(2, '0')).join(' ')

describe('MSP v2 framing', () => {
  test('crc8_dvb_s2 and frames match known vectors', () => {
    // MSP_IDENT (100) as v2: the frame commonly quoted in MSP v2 docs
    expect(hex(frameV2(100))).toBe('24 58 3c 00 64 00 00 00 8f')
    // Configurator's 'Bind receiver': MSP2_BETAFLIGHT_BIND = 0x3000, no payload
    expect(hex(frameV2(MSP2_BETAFLIGHT_BIND))).toBe('24 58 3c 00 00 30 00 00 2b')
    expect(crc8DvbS2([0, 0x64, 0, 1, 0, 0xab])).toBe(0xd9)
    expect(hex(frameV2(100, Uint8Array.of(0xab)))).toBe('24 58 3c 00 64 00 01 00 ab d9')
  })

  test('scanFrame parses v1 and v2 replies, partial input, junk and errors', () => {
    const v2 = frameV2(0x3000, Uint8Array.of(1, 2))
    v2[2] = 0x3e
    const v1 = frame(105, Uint8Array.of(9))
    v1[2] = 0x3e
    const buf = [0x00, 0x11, ...v2.slice(0, 5)]
    expect(scanFrame(buf)).toBeNull()
    buf.push(...v2.slice(5), ...v1)
    expect(scanFrame(buf)).toEqual({ cmd: 0x3000, payload: Uint8Array.of(1, 2), v2: true })
    expect(scanFrame(buf)).toEqual({ cmd: 105, payload: Uint8Array.of(9) })
    expect(buf.length).toBe(0)

    const bad = Array.from(v2)
    bad[bad.length - 1] ^= 1
    expect(() => scanFrame(bad)).toThrow(/checksum/)
    expect(bad.length).toBe(0)

    const err = frameV2(0x3000)
    err[2] = 0x21
    expect(() => scanFrame(Array.from(err))).toThrow(MspError)
  })
})

/** FC stub: answers each request with `answer(frame)` bytes. */
class StubPort implements SerialPort {
  written: Uint8Array[] = []
  private chunks: Uint8Array[] = []
  private wake: (() => void) | null = null
  private done = false
  private answer: (req: Uint8Array) => Uint8Array
  constructor(answer: (req: Uint8Array) => Uint8Array) {
    this.answer = answer
  }
  async open(): Promise<void> {}
  async write(d: Uint8Array): Promise<void> {
    this.written.push(d)
    this.chunks.push(this.answer(d))
    this.wake?.()
  }
  async *read(): AsyncIterable<Uint8Array> {
    for (;;) {
      while (this.chunks.length) yield this.chunks.shift()!
      if (this.done) return
      await new Promise<void>((r) => (this.wake = r))
    }
  }
  async close(): Promise<void> {
    this.done = true
    this.wake?.()
  }
}

describe('BetaflightMSP.bind', () => {
  test('sends MSP2_BETAFLIGHT_BIND as v2 and resolves on the ack', async () => {
    const port = new StubPort((req) => {
      const r = frameV2(req[4] | (req[5] << 8))
      r[2] = 0x3e
      return r
    })
    const msp = new BetaflightMSP(port, new FakeClock(), 200, 0)
    await msp.open()
    await msp.bind()
    expect(hex(port.written[0])).toBe('24 58 3c 00 00 30 00 00 2b')
    await msp.close()
  })

  test('rejects when the FC answers with an error frame', async () => {
    const port = new StubPort(() => {
      const r = frameV2(MSP2_BETAFLIGHT_BIND)
      r[2] = 0x21
      return r
    })
    const msp = new BetaflightMSP(port, new FakeClock(), 200, 0)
    await msp.open()
    await expect(msp.bind()).rejects.toMatchObject({ kind: 'value' })
    await msp.close()
  })
})
