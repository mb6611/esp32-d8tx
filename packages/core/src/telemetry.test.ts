import { describe, expect, test } from 'vitest'
import { HubParser, HubState, armedFromRpm } from './hub.ts'
import { Tracker, parseReply, rssiDbm, vbatFromA1 } from './telemetry.ts'
import { ARMING_DISABLE, BetaflightMSP, frame, parseAnalog, parseAttitude, parseMotors, parseRc, parseStatus, scanFrame, MspError } from './msp.ts'
import { FakeClock } from './clock.ts'
import { each, hex, toHex, vec } from './vectors.ts'

/** deep equality with float tolerance (python round() vs JS). */
function close(a: any, b: any, path = ''): void {
  if (typeof b === 'number' && typeof a === 'number') return void expect(a, path).toBeCloseTo(b, 6)
  if (Array.isArray(b)) {
    expect(Array.isArray(a), path).toBe(true)
    expect(a.length, path).toBe(b.length)
    return b.forEach((x, i) => close(a[i], x, `${path}[${i}]`))
  }
  if (b && typeof b === 'object') {
    expect(Object.keys(a).sort(), path).toEqual(Object.keys(b).sort())
    return Object.keys(b).forEach((k) => close(a[k], b[k], `${path}.${k}`))
  }
  expect(a, path).toEqual(b)
}

describe('hub vectors', () => {
  const h = vec('hub')
  each(h.parser, (v) => {
    const p = new HubParser()
    const frames: [number, number][] = []
    for (const c of v.chunks) frames.push(...p.feed(hex(c)))
    expect(frames).toEqual(v.frames)
  })
  each(h.state, (v) => {
    const s = new HubState()
    for (const [id, val, t] of v.updates) s.update(id, val, t)
    close(s.snapshot(v.now), v.snapshot)
    expect(s.vfasV()).toEqual(v.vfas_v)
  })
  test('armedFromRpm', () => {
    for (const v of h.armed_from_rpm) expect(armedFromRpm(v.rpm, v.baseline), JSON.stringify(v)).toBe(v.armed)
  })
})

describe('reply parse vectors', () => {
  const r = vec('reply_parse')
  each(r.parse_reply, (v) => {
    const { hub, fast, ...rest } = parseReply(hex(v.raw))
    const { hub: eh, fast: ef, ...erest } = v.reply
    expect(rest).toEqual(erest)
    expect(toHex(hub)).toBe(eh)
    if (ef) close(fast, ef)
  })
  test('vbat/rssi', () => {
    for (const v of r.vbat_from_a1) expect(vbatFromA1(v.a1)).toBeCloseTo(v.vbat_v, 9)
    for (const v of r.rssi_dbm) expect(rssiDbm(v.byte), `byte ${v.byte}`).toBe(v.dbm)
  })
})

describe('tracker vectors', () => {
  each(vec('tracker'), (v) => {
    let t = 100.0 // python Clk starts at 100
    const tr = new Tracker(() => t)
    const snaps: unknown[] = []
    for (const op of v.ops) {
      if (op.op === 'reset') tr.reset(op.enabled)
      else if (op.op === 'reply') {
        const rep = parseReply(hex(op.raw))
        if ('cfo_hz' in op) rep.cfo_hz = op.cfo_hz
        tr.noteReply(rep)
      } else if (op.op === 'miss') tr.noteTriggerMiss()
      else if (op.op === 'arm') tr.noteArmOnAir(op.high)
      else if (op.op === 'advance') t += op.s
      else if (op.op === 'snapshot') snaps.push(tr.snapshot())
    }
    close(snaps, v.snapshots)
  })
})

describe('msp vectors', () => {
  const m = vec('msp')
  each(m.frames, (v) => expect(toHex(frame(v.cmd, hex(v.payload)))).toBe(v.frame), (v) => 'frame ' + v.cmd)
  each(m.responses, (v) => {
    const buf = Array.from(hex(v.raw))
    let res: any
    try {
      const f = scanFrame(buf)
      res = f ? { cmd: f.cmd, payload: toHex(f.payload) } : { error: 'timeout', message: 'MSP timeout' }
    } catch (e) {
      res = { error: (e as MspError).kind, message: (e as Error).message }
    }
    expect(res).toEqual(v.result)
  })
  test('parsers', () => {
    for (const v of m.parse.rc) expect(parseRc(hex(v.payload))).toEqual(v.result)
    for (const v of m.parse.attitude) close(parseAttitude(hex(v.payload)), v.result)
    for (const v of m.parse.analog) expect(parseAnalog(hex(v.payload))).toEqual(v.result)
    for (const v of m.parse.status) expect(parseStatus(hex(v.payload))).toEqual(v.result)
    for (const v of m.parse.motors) expect(parseMotors(hex(v.payload))).toEqual(v.result)
    expect(m.constants.ARMING_DISABLE).toEqual(ARMING_DISABLE)
  })
  test('client timeout with fake clock', async () => {
    const clock = new FakeClock()
    const port = { open: async () => {}, close: async () => {}, write: async () => {}, read: () => (async function* () { await new Promise(() => {}) })() }
    const msp = new BetaflightMSP(port, clock)
    await msp.open()
    const p = msp.attitude().then(() => 'ok', (e) => e.message)
    await clock.advance(300)
    expect(await p).toBe('MSP timeout')
  })
})
