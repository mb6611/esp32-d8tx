import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, test } from 'vitest'
import { BetaflightMSP, D8Error, D8Link, FakeClock, FcPoller, SLOT_S, TLM_RECIPE, parseReply, type LinkEvent, type Reply } from '@d8tx/core'
import { MockDronePort, MockPort, type MockCapture } from './mock.ts'

const root = fileURLToPath(new URL('../../../protocol/', import.meta.url))
const vec = (n: string): any => JSON.parse(readFileSync(root + `vectors/${n}.json`, 'utf8'))

/** Drive the fake clock in 1 ms steps until the promise settles. */
async function settle<T>(clock: FakeClock, p: Promise<T>, maxMs = 5000): Promise<T> {
  let done = false
  let val: any, err: any, failed = false
  p.then((v) => ((val = v), (done = true)), (e) => ((err = e), (failed = true), (done = true)))
  for (let i = 0; i < maxMs && !done; i++) await clock.advance(1)
  if (!done) throw new Error('did not settle')
  if (failed) throw err
  return val
}

function mk(opts: Partial<ConstructorParameters<typeof MockPort>[0]> = {}) {
  const clock = new FakeClock()
  const port = new MockPort({ clock, ...opts })
  const link = new D8Link(port, clock)
  const events: LinkEvent[] = []
  link.on((e) => events.push(e))
  return { clock, port, link, events }
}
async function opened(opts: Parameters<typeof mk>[0] = {}) {
  const m = mk(opts)
  await m.link.open()
  return m
}
const sLines = (p: MockPort) => p.lines.filter((l) => l.startsWith('S '))

describe('D8Link on MockPort', () => {
  test('info / stat / fofs range error', async () => {
    const { clock, link } = await opened()
    expect((await settle(clock, link.info())).proto).toBe(1)
    expect((await settle(clock, link.stat())).keyed).toBe(0)
    await settle(clock, link.setFofs(-1000))
    await expect(settle(clock, link.setFofs(300000))).rejects.toMatchObject({ code: 'range' })
  })

  test('pacing, arm-edge hold, events, stop', async () => {
    const { clock, port, link, events } = await opened()
    await settle(clock, link.start({ power: 100, timeoutMs: 300, allowArm: true, fofsHz: 500 }))
    expect(port.lines).toEqual(expect.arrayContaining(['ARMOK', 'LINK 100 300', 'FOFS 500']))
    link.setSticks([1100, 1500, 1500, 1500, 1500, 1500, 2000, 1500])
    await clock.advance(800)
    const st = link.status()
    expect(st.link).toBe(1)
    expect(st.keyed).toBe(1)
    expect(st.sender_hz).toBeGreaterThanOrEqual(100)
    expect(st.sender_hz).toBeLessThanOrEqual(115)
    const armed = sLines(port).filter((l) => l.includes(' 2000 1500'))
    expect(armed[0].startsWith('S 1000')).toBe(true)
    const nHold = armed.findIndex((l) => l.startsWith('S 1100'))
    expect(nHold).toBeGreaterThanOrEqual(45)
    expect(nHold).toBeLessThanOrEqual(60)
    await settle(clock, link.stop())
    expect(link.status().link).toBe(0)
    expect(events.some((e) => e.name === 'link_end')).toBe(true)
    const n = port.tSticks.length
    await clock.advance(50)
    expect(port.tSticks.length).toBe(n)
  })

  test('arm forced low without allow', async () => {
    const { clock, port, link } = await opened()
    await settle(clock, link.start())
    link.setSticks(Array(8).fill(1500))
    await clock.advance(100)
    await settle(clock, link.stop())
    expect(port.lines).not.toContain('ARMOK')
    expect(sLines(port).every((l) => l.split(' ')[7] === '1000')).toBe(true)
  })

  test('firmware link_end clears link; arm state reset', async () => {
    const { clock, port, link, events } = await opened()
    await settle(clock, link.start({ allowArm: true }))
    link.setSticks([1000, 1500, 1500, 1500, 1500, 1500, 2000, 1500])
    await clock.advance(50)
    expect(link.status().allow_arm).toBe(1)
    port.linked = false
    port.emit('EV link_end why=timeout slots=9 late_max_us=1 retune_max_us=1')
    await clock.advance(50)
    const st = link.status()
    expect(st.link).toBe(0)
    expect(st.keyed).toBe(0)
    expect(st.slots).toBe(9)
    expect(st.allow_arm).toBe(0)
    expect(st.ch[6]).toBe(1000)
    expect(events.some((e) => e.name === 'link_lost')).toBe(true)
    // stray OKs from idle S must not satisfy a request
    for (let i = 0; i < 3; i++) {
      expect((await settle(clock, link.info())).proto).toBe(1)
      expect((await settle(clock, link.stat())).keyed).toBe(0)
    }
  })

  test('LINK failure sends STOP and resets', async () => {
    const { clock, port, link } = await opened()
    await settle(clock, link.start())
    await clock.advance(50)
    await settle(clock, link.stop())
    // LINK now fails: out-of-range power
    await expect(settle(clock, link.start({ power: 500, allowArm: true }))).rejects.toBeInstanceOf(D8Error)
    expect(port.lines.at(-1)).toBe('STOP')
    const st = link.status()
    expect(st.sender_hz).toBe(0)
    expect(st.last_event).toBeNull()
    expect(st.allow_arm).toBe(0)
  })

  test('stray TID OK does not satisfy a request', async () => {
    const { clock, port, link } = await opened()
    await settle(clock, link.start())
    await settle(clock, link.stop())
    const orig = (port as any).cmd.bind(port)
    ;(port as any).cmd = (ln: string) => {
      if (ln === 'STAT') port.emit('OK tid=7')
      orig(ln)
    }
    expect((await settle(clock, link.stat())).keyed).toBe(0)
  })

  test('link lost within 500 ms of the last reply; arm reset', async () => {
    const { clock, port, link, events } = await opened()
    await settle(clock, link.start({ allowArm: true }))
    link.setSticks([1000, 1500, 1500, 1500, 1500, 1500, 2000, 1500])
    await clock.advance(1000)
    expect(link.status().link).toBe(1)
    port.muted = true // device stops answering (and the port is dead)
    const tMute = clock.now()
    let tLost = -1
    link.on((e) => { if (e.name === 'link_lost') tLost = clock.now() })
    await clock.advance(1000)
    expect(events.find((e) => e.name === 'link_lost')).toMatchObject({ why: 'timeout' })
    // last reply is at most one STAT period (200 ms) older than the mute; loss follows 400 ms (+ watch tick) after it
    expect(tLost - tMute).toBeLessThanOrEqual(500)
    const st = link.status()
    expect(st.link).toBe(0)
    expect(st.allow_arm).toBe(0)
    expect(st.ch[6]).toBe(1000)
  })

  test('port close while linked is a loss', async () => {
    const { clock, port, link, events } = await opened()
    await settle(clock, link.start())
    await port.close()
    await clock.advance(20)
    expect(link.status().link).toBe(0)
    expect(events.find((e) => e.name === 'link_lost')).toMatchObject({ why: 'port_closed' })
  })

  test('write backpressure skips frames', async () => {
    const { clock, port, link } = await opened()
    await settle(clock, link.start())
    await clock.advance(100)
    port.outWaiting = 100
    const n = sLines(port).length
    await clock.advance(100)
    expect(sLines(port).length).toBe(n)
    expect(link.status().skipped).toBeGreaterThan(5)
    port.outWaiting = 0
    await clock.advance(50)
    expect(sLines(port).length).toBeGreaterThan(n)
  })

  test('refuses arm unless INFO proto=1', async () => {
    const { clock, port, link } = await opened()
    ;(port as any).cmd = (ln: string) => {
      if (ln === 'INFO') port.emit('OK proto=2 fw=x')
    }
    await expect(settle(clock, link.start({ allowArm: true }))).rejects.toMatchObject({ code: 'protocol' })
    expect(port.lines).not.toContain('ARMOK')
    expect(port.lines.some((l) => l.startsWith('LINK'))).toBe(false)
  })

  test('mock firmware ends the link 300 ms after the last S', async () => {
    const { clock, port } = await opened()
    const enc = new TextEncoder()
    await port.write(enc.encode('LINK 10 300\n'))
    await port.write(enc.encode('S 1500 1500 1500 1500 1500 1500 1000 1500\n'))
    await clock.advance(299)
    expect(port.linked).toBe(true)
    await clock.advance(5)
    expect(port.linked).toBe(false)
  })

  test('start sequences match the golden vectors', async () => {
    for (const seq of vec('commands').start_sequences) {
      const { clock, port, link } = await opened({ tlmErr: seq.tlm_err })
      for (const step of seq.steps) {
        port.lines.length = 0
        if (step.op === 'start') {
          await settle(clock, link.start({
            power: step.power, timeoutMs: step.timeout_ms, allowArm: step.allow_arm, fofsHz: step.fofs_hz, telemetry: step.telemetry,
          }))
        } else await settle(clock, link.stop())
        expect(port.lines.filter((l) => !l.startsWith('S ') && !l.startsWith('STAT') && l !== 'INFO' /* proto gate before ARMOK */), `${seq.name}/${step.op}`).toEqual(step.lines)
      }
    }
  })

  test('telemetry: captures decode, TID rule, tracker', async () => {
    const idx = JSON.parse(readFileSync(root + 'captures/index.json', 'utf8')).filter((c: any) => c.format === 'i4_d64' && c.expect)
    const captures: MockCapture[] = idx.map((c: any) => ({
      payload: new Uint8Array(readFileSync(root + 'captures/' + c.file)), fs: c.fs, bits: 4, n: c.n,
    }))
    const clock = new FakeClock()
    const port = new MockPort({ clock, captures })
    // decoder stub: the real demod arrives with U3; answer with the expected reply of the capture, echoing the tid asked
    let call = 0
    const seen: number[] = []
    const link = new D8Link(port, clock, {
      decode: (iq, fs) => {
        expect(iq.length).toBe(4000)
        expect(fs).toBe(250000)
        const hex = '1142b24b1a47' + '00' + '00' + '00005e0200005e030000'.slice(0, 20)
        const raw = Uint8Array.from(hex.match(/../g)!.map((h) => parseInt(h, 16)))
        raw[7] = port.tid
        seen.push(raw[7])
        call++
        return { ...parseReply(raw), cfo_hz: 1000, shift_hz: -50000 } as Reply
      },
    })
    await link.open()
    await settle(clock, link.start())
    await clock.advance(1500)
    expect(call).toBeGreaterThan(5)
    const tl = link.telemetry()
    expect(tl.enabled).toBe(true)
    expect(tl.replies).toBe(call)
    expect(tl.link).toBe(true)
    // every decoded reply advanced the id: the host sent TID n+1 each time
    const tids = port.lines.filter((l) => l.startsWith('TID ')).map((l) => Number(l.slice(4)))
    expect(tids.slice(0, 4)).toEqual([0, 1, 2, 3])
    expect(port.lines).toContain(TLM_RECIPE)
    await settle(clock, link.stop())
    const n = port.lines.length
    await clock.advance(1500)
    expect(port.lines.slice(n).filter((l) => l.startsWith('TID '))).toEqual([])
  })

  test('undecodable capture repeats the tid', async () => {
    const payload = new Uint8Array(2000).fill(0x11)
    const clock = new FakeClock()
    const port = new MockPort({ clock, captures: [{ payload, fs: 250000, bits: 4, n: 2000 }] })
    const link = new D8Link(port, clock, { decode: () => null })
    await link.open()
    await settle(clock, link.start())
    await clock.advance(500)
    const tids = port.lines.filter((l, i) => i > 3 && l.startsWith('TID ')).map((l) => Number(l.slice(4)))
    expect(tids.length).toBeGreaterThan(2)
    expect(new Set(tids).size).toBe(1)
    expect(link.telemetry().replies).toBe(0)
    expect(link.telemetry().triggers).toBeGreaterThan(2)
  })
})

describe('FC poller on MockDronePort', () => {
  test('polls attitude/rc/motors/status', async () => {
    const clock = new FakeClock()
    const drone = new MockDronePort()
    drone.state.armed = true
    drone.state.motors = [1000, 1100, 1200, 1300]
    const msp = new BetaflightMSP(drone, clock, 200, 0)
    await msp.open()
    const fc = new FcPoller(msp, clock)
    let s = await settle(clock, fc.poll())
    expect(s.connected).toBe(true)
    expect(s.attitude_deg).toEqual([1.5, -2, 90])
    expect(s.rc).toHaveLength(8)
    expect(s.armed).toBe(true) // poll 1 includes status
    expect(s.rssi).toBe(800)
    s = await settle(clock, fc.poll())
    expect(s.motors).toEqual([1000, 1100, 1200, 1300])
    // schedule: poll1 rc att status analog; poll2 rc att motor
    expect(drone.requests.slice(0, 7)).toEqual([105, 108, 101, 110, 105, 108, 104])
    const p0 = fc.polls
    fc.start()
    await clock.advance(200)
    fc.stop()
    expect(fc.polls - p0).toBeGreaterThan(10)
  })
})

// Causes found on the DevKit (2026-11, hw-check at power 30): each test fails without its fix.
describe('D8Link bench reliability', () => {
  const blob = (): MockCapture => ({ payload: new Uint8Array(2000).fill(0x11), fs: 250000, bits: 4, n: 2000 })

  test('STAT during a capture shipment is resent, not timed out', async () => {
    // firmware: hop_drain drops STAT while shp.busy (a capture is going out), which with TLM every 12 is most of the time
    const clock = new FakeClock()
    const port = new MockPort({ clock, captures: [blob()], shipMs: 60, triggerMs: 108 })
    const link = new D8Link(port, clock, { decode: () => null, statPollMs: 1e9 })
    await link.open()
    await settle(clock, link.start())
    let timeouts = 0
    for (let i = 0; i < 40; i++) {
      await settle(clock, link.request('STAT', 250).catch(() => timeouts++))
      await clock.advance(23) // walk the request time across the shipment window
    }
    expect(port.statDropped).toBeGreaterThan(0)
    expect(timeouts).toBe(0)
    expect(link.isLinked).toBe(true)
    await settle(clock, link.stop())
  })

  test('a duplicate STAT reply or a bare OK never answers another request', async () => {
    const { clock, port, link } = await opened()
    await settle(clock, link.start())
    await settle(clock, link.stop())
    port.emit('OK keyed=1 link=1 fofs=0 armok=0') // late duplicate from a STAT resend
    await clock.advance(1)
    const orig = (port as any).cmd.bind(port)
    ;(port as any).cmd = (ln: string) => {
      if (ln.startsWith('FOFS')) port.emit('OK keyed=1 link=1 fofs=0 armok=0') // stray, arrives first
      if (ln === 'STAT') port.emit('OK') // stray idle-S OK, arrives first
      orig(ln)
    }
    await settle(clock, link.setFofs(-70000))
    expect(port.fofs).toBe(-70000)
    expect((await settle(clock, link.stat())).fofs).toBe(-70000)
  })

  test('a stalled sender catches up without overflowing the firmware RX FIFO', async () => {
    // host blocked ~25 ms (WASM decode on the main thread), then the sender caught up with 3 S lines + TID in ~3 ms
    // = 129 bytes into the 128-byte FIFO; the torn line ended the link (`ERR unknown cmd`, why=err).
    const clock = new FakeClock()
    const port = new MockPort({ clock, rxFifoBytes: 128 })
    const link = new D8Link(port, clock) // STAT poll keeps the host link-lost rule fed
    const events: LinkEvent[] = []
    link.on((e) => events.push(e))
    await link.open()
    await settle(clock, link.start())
    for (let i = 0; i < 20; i++) {
      await clock.advance(30)
      clock.stall(25)
      port.write(new TextEncoder().encode('TID 3\n'))
      await clock.advance(1)
    }
    await clock.advance(100)
    expect(events.filter((e) => e.name === 'link_end')).toEqual([])
    expect(link.isLinked).toBe(true)
    const t = port.tSticks
    const minGap = Math.min(...t.slice(1).map((x, i) => x - t[i]))
    expect(minGap).toBeGreaterThanOrEqual(SLOT_S * 1000 * 0.79)
    await settle(clock, link.stop())
  })

  test('start/sync after an earlier session left the firmware linked', async () => {
    // the previous owner of the port closed it mid-link and mid-line: the next command gets `ERR busy` and ends that link
    const clock = new FakeClock()
    const port = new MockPort({ clock })
    const w = (t: string) => port.write(new TextEncoder().encode(t))
    w('LINK 30 300\nS 1000 15')
    const link = new D8Link(port, clock)
    await link.open()
    expect((await settle(clock, link.sync())).proto).toBe(1)
    expect(port.linked).toBe(false)
    w('LINK 30 300\n') // linked again, as if sync had never run
    await clock.advance(5)
    await settle(clock, link.start())
    expect(link.isLinked).toBe(true)
    await settle(clock, link.stop())
  })
})
