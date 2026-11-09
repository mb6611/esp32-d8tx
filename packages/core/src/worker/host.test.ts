// Host bind flow on the mock DevKit + mock drone (fake clock).
import { describe, expect, test } from 'vitest'
import { FakeClock } from '../clock.ts'
import type { Reply } from '../telemetry.ts'
import { parseReply } from '../telemetry.ts'
import { MockDronePort, MockPort } from '../../../serial/src/mock.ts'
import { PortInUseError } from '../port.ts'
import { BIND_CONFIRM_MS, BIND_WINDOW_MS, Host, IN_USE_RETRY_MS } from './host.ts'
import type { FromWorker } from './types.ts'

const RX_FAILSAFE = 1 << 2

function mk(o: { fc?: boolean; drone?: Partial<MockDronePort> } = {}) {
  const clock = new FakeClock()
  const newEsp = () => new MockPort({ clock, captures: [{ payload: new Uint8Array(2000).fill(0x11), fs: 250000, bits: 4, n: 2000 }] })
  let esp = newEsp()
  /** opens of the ESP port; set espGone to make opening fail (unplugged) */
  let espOpens = 0
  /** espBusy / fcBusy: another app or tab holds that port (open fails as in use) */
  const ctl = { espGone: false, espBusy: false, fcBusy: false }
  let fcOpens = 0
  const drone = new MockDronePort()
  Object.assign(drone, o.drone ?? {})
  drone.state.armingDisable = RX_FAILSAFE
  /** the txid the simulated receiver is bound to: set from the ESP when the FC was told to bind while the ESP sent bind packets */
  let boundTo: string | null = null
  const wrap = drone.write.bind(drone)
  drone.write = async (d: Uint8Array) => {
    const before = drone.binds
    await wrap(d)
    if (drone.binds > before && esp.binding && !drone.bindError) boundTo = esp.txid
  }
  const errors: FromWorker[] = []
  const released: FromWorker[] = []
  const host = new Host({
    post: (m) => {
      if (m.type === 'error') errors.push(m)
      if (m.type === 'esp_released') released.push(m)
    },
    openPort: async () => {
      throw new Error('no real ports in tests')
    },
    mockPort: (role) => {
      if (role !== 'esp') {
        fcOpens++
        if (ctl.fcBusy) throw new PortInUseError('port in use (EBUSY)')
        return drone
      }
      if (ctl.espBusy) throw new PortInUseError('port in use (EBUSY)')
      if (ctl.espGone) throw new Error('no granted DevKit port')
      espOpens++
      // a closed port comes back as a fresh device (replug), with the same persisted identity
      if (esp.closed) {
        const txid = esp.txid
        esp = newEsp()
        esp.txid = txid
      }
      return esp
    },
    clock,
    // the drone answers only when bound to the txid the decoder filters on
    decode: (_iq, _fs, _hint, txid) => {
      const want = txid ? txid.map((b) => b.toString(16).padStart(2, '0')).join('').toUpperCase() : null
      if (!boundTo || boundTo !== want) return null
      const raw = Uint8Array.from('1142b24b1a4700000000005e0200005e0300'.match(/../g)!.map((h) => parseInt(h, 16)))
      raw[1] = txid![0]
      raw[2] = txid![1]
      raw[7] = esp.tid
      return { ...parseReply(raw), cfo_hz: 0, shift_hz: 0 } as Reply
    },
  })
  const run = async (p: Promise<void>, maxMs = BIND_WINDOW_MS + BIND_CONFIRM_MS + 3000): Promise<void> => {
    let done = false
    void p.finally(() => (done = true))
    for (let i = 0; i < maxMs / 10 && !done; i++) await clock.advance(10)
    expect(done).toBe(true)
  }
  const esp_ = () => host.snapshot().esp as Record<string, unknown>
  return { clock, get esp() { return esp }, ctl, opens: () => espOpens, fcOpens: () => fcOpens, drone, host, run, errors, released, snap: esp_, boundTo: () => boundTo, connect: async () => {
    await run(host.handle({ type: 'connect', role: 'esp', mock: true }), 3000)
    if (o.fc !== false) await run(host.handle({ type: 'connect', role: 'fc', mock: true }), 1000)
  } }
}

describe('Host bind flow', () => {
  test('binds over MSP v2, confirms through a reply with the ESP txid, twice across ID new', async () => {
    const m = mk()
    await m.connect()
    await m.run(m.host.handle({ type: 'bind', fofs_hz: 0 }))
    expect(m.drone.binds).toBe(1)
    expect(m.boundTo()).toBe(m.esp.txid)
    // the bind paused the normal link and restarted it afterwards
    expect(m.snap()).toMatchObject({ bind_state: 'bound', bind_txid: m.esp.txid, bind_via: 'telemetry', link: true, link_state: 'up', binding: false })
    const ls = m.esp.lines
    const during = ls.slice(ls.findIndex((l) => l.startsWith('BIND')), ls.indexOf('LINK 40 300') + 1)
    expect(during).toContain('LINK 40 300')
    expect(during).not.toContain('ARMOK')
    expect(ls.slice(ls.indexOf('LINK 40 300'))).toContain('LINK 127 300')

    const old = m.esp.txid
    await m.run(m.host.handle({ type: 'new_id' }), 1000)
    expect(m.esp.txid).not.toBe(old)
    await m.run(m.host.handle({ type: 'bind', fofs_hz: 0 }))
    expect(m.snap()).toMatchObject({ bind_state: 'bound', bind_txid: m.esp.txid })
    expect(m.boundTo()).toBe(m.esp.txid)
    await m.run(m.host.close(), 3000)
  })

  test('needs the drone USB', async () => {
    const m = mk({ fc: false })
    await m.connect()
    await m.run(m.host.handle({ type: 'bind' }), 1000)
    expect(m.snap().bind_state).toBe('failed')
    expect(String(m.snap().bind_reason)).toMatch(/drone USB/)
    expect(m.esp.lines.filter((l) => l.startsWith('BIND'))).toEqual([])
  })

  test('FC refusing the bind fails and stops the bind packets', async () => {
    const m = mk({ drone: { bindError: true } })
    await m.connect()
    await m.run(m.host.handle({ type: 'bind' }))
    expect(m.snap()).toMatchObject({ bind_state: 'failed', binding: false })
    expect(String(m.snap().bind_reason)).toMatch(/refused/)
    expect(m.esp.binding).toBe(false)
  })

  test('no reply with this txid fails; cancel ends the bind window', async () => {
    const m = mk()
    await m.connect()
    // drone answers bind but never binds to us (e.g. out of range)
    m.drone.write = (async (d: Uint8Array) => MockDronePort.prototype.write.call(m.drone, d)) as never
    await m.run(m.host.handle({ type: 'bind' }))
    expect(m.snap().bind_state).toBe('failed')
    expect(String(m.snap().bind_reason)).toMatch(/no reply/)
    expect(m.snap().link).toBe(true) // normal link back

    const p = m.host.handle({ type: 'bind' })
    await m.clock.advance(1000)
    expect(m.snap().bind_state).toBe('binding')
    void m.host.handle({ type: 'bind_stop' })
    await m.run(p, 1000)
    expect(m.snap()).toMatchObject({ bind_state: 'failed', bind_reason: 'cancelled', binding: false })
    expect(m.esp.binding).toBe(false)
  })
})

describe('Host link supervisor', () => {
  const ARMED = [1000, 1500, 1500, 1500, 1000, 1000, 2000, 1000]
  const LOW = [1000, 1500, 1500, 1500, 1000, 1000, 1000, 1000]
  const ch7 = (m: ReturnType<typeof mk>) => (m.host as unknown as { link: { status(): { ch: number[] } } }).link.status().ch[6]

  test('connecting the ESP starts the link with the radio settings; new settings restart it', async () => {
    const m = mk({ fc: false })
    await m.run(m.host.handle({ type: 'radio', power: 60, fofs_hz: -75000, timeout_ms: 400 }), 100)
    await m.connect()
    expect(m.snap()).toMatchObject({ connected: true, wanted: true, link: true, link_state: 'up', allow_arm: true })
    expect(m.esp.lines).toContain('FOFS -75000')
    expect(m.esp.lines).toContain('ARMOK')
    expect(m.esp.lines).toContain('LINK 60 400')
    expect(m.esp.linked).toBe(true)

    // same settings: no restart
    const n = m.esp.lines.length
    await m.run(m.host.handle({ type: 'radio', power: 60, fofs_hz: -75000, timeout_ms: 400 }), 100)
    expect(m.esp.lines.slice(n).filter((l) => l !== 'STAT' && !l.startsWith('S '))).toEqual([])

    await m.run(m.host.handle({ type: 'radio', power: 90, fofs_hz: -75000, timeout_ms: 400 }), 2000)
    const after = m.esp.lines.slice(n)
    expect(after).toContain('STOP')
    expect(after).toContain('LINK 90 400')
    expect(m.snap()).toMatchObject({ link: true, link_state: 'up', power: 90 })
  })

  test('a (re)started link holds ch7 low until the UI sends a disarmed frame', async () => {
    const m = mk({ fc: false })
    await m.connect()
    await m.host.handle({ type: 'sticks', ch: ARMED })
    expect(ch7(m)).toBe(1000)
    await m.host.handle({ type: 'sticks', ch: LOW })
    await m.host.handle({ type: 'sticks', ch: ARMED })
    expect(ch7(m)).toBe(2000)
    // a settings change restarts the link: the arm is not carried over
    await m.host.handle({ type: 'sticks', ch: LOW })
    await m.run(m.host.handle({ type: 'radio', power: 50, fofs_hz: 0, timeout_ms: 300 }), 2000)
    await m.host.handle({ type: 'sticks', ch: ARMED })
    expect(ch7(m)).toBe(1000)
  })

  test('bind and new identity refuse while armed, else pause the link and restart it', async () => {
    const m = mk({ fc: false })
    await m.connect()
    await m.host.handle({ type: 'sticks', ch: LOW })
    await m.host.handle({ type: 'sticks', ch: ARMED })
    await m.run(m.host.handle({ type: 'new_id' }), 1000)
    expect(m.errors.at(-1)).toMatchObject({ message: 'disarm first' })
    expect(m.esp.lines).not.toContain('ID new')

    await m.host.handle({ type: 'sticks', ch: LOW })
    const old = m.esp.txid
    const n = m.esp.lines.length
    await m.run(m.host.handle({ type: 'new_id' }), 2000)
    expect(m.esp.txid).not.toBe(old)
    const ls = m.esp.lines.slice(n).filter((l) => l !== 'STAT' && !l.startsWith('S '))
    expect(ls.indexOf('STOP')).toBeLessThan(ls.indexOf('ID new'))
    expect(ls.slice(ls.indexOf('ID new'))).toContain('LINK 127 300')
    expect(m.snap()).toMatchObject({ link: true, link_state: 'up', txid: m.esp.txid })
  })

  test('port loss: retries with backoff until the device is back, then relinks', async () => {
    const m = mk({ fc: false })
    await m.connect()
    expect(m.opens()).toBe(1)
    m.ctl.espGone = true
    await m.esp.close() // unplugged
    await m.clock.advance(50)
    expect(m.snap()).toMatchObject({ connected: false, link: false, link_state: 'lost', wanted: true })
    await m.clock.advance(5000)
    expect(m.snap().link_state).toBe('lost')
    expect(Number(m.snap().attempt)).toBeGreaterThanOrEqual(3)
    expect(m.errors.filter((e) => e.type === 'error' && /no granted/.test(e.message)).length).toBe(1) // reported once
    m.ctl.espGone = false
    await m.run(m.host.handle({ type: 'ports_changed' }), 3000)
    for (let i = 0; i < 300 && m.snap().link_state !== 'up'; i++) await m.clock.advance(10)
    expect(m.opens()).toBe(2)
    expect(m.snap()).toMatchObject({ connected: true, link: true, link_state: 'up', attempt: 0 })
    expect(m.esp.linked).toBe(true)
  })

  test('a link lost while the port stays open restarts on the same port', async () => {
    const m = mk({ fc: false })
    await m.connect()
    m.esp.muted = true // device stops answering
    for (let i = 0; i < 300 && m.snap().link; i++) await m.clock.advance(10)
    expect(m.snap()).toMatchObject({ link: false, link_state: 'lost', connected: true })
    m.esp.muted = false
    for (let i = 0; i < 1000 && m.snap().link_state !== 'up'; i++) await m.clock.advance(10)
    expect(m.snap()).toMatchObject({ link: true, link_state: 'up' })
    expect(m.opens()).toBe(1)
  })

  test('disconnect stops transmitting and ends auto-reconnect', async () => {
    const m = mk({ fc: false })
    await m.connect()
    const esp = m.esp
    await m.run(m.host.handle({ type: 'disconnect', role: 'esp' }), 2000)
    expect(esp.lines).toContain('STOP')
    expect(esp.linked).toBe(false)
    expect(esp.closed).toBe(true)
    await m.clock.advance(10000)
    expect(m.opens()).toBe(1)
    expect(m.snap()).toMatchObject({ connected: false, wanted: false, link: false, link_state: 'off' })
  })
})

test('settings changed while armed apply only after disarm', async () => {
  const m = mk({ fc: false })
  await m.connect()
  const LOW = [1000, 1500, 1500, 1500, 1000, 1000, 1000, 1000]
  await m.host.handle({ type: 'sticks', ch: LOW })
  await m.host.handle({ type: 'sticks', ch: [...LOW.slice(0, 6), 2000, 1000] })
  await m.run(m.host.handle({ type: 'radio', power: 33, fofs_hz: 0, timeout_ms: 300 }), 500)
  expect(m.esp.lines).not.toContain('LINK 33 300')
  expect(m.snap()).toMatchObject({ link: true, power: 127 })
  await m.host.handle({ type: 'sticks', ch: LOW })
  for (let i = 0; i < 200 && m.snap().power !== 33; i++) await m.clock.advance(10)
  expect(m.esp.lines).toContain('LINK 33 300')
  expect(m.snap()).toMatchObject({ link: true, power: 33 })
})

describe('Host: port held by another app or tab', () => {
  test('ESP: shows in use, retries every IN_USE_RETRY_MS reporting once, and takes over when released', async () => {
    const m = mk({ fc: false })
    m.ctl.espBusy = true
    await m.run(m.host.handle({ type: 'connect', role: 'esp', mock: true }), 100)
    expect(m.snap()).toMatchObject({ connected: false, wanted: true, link_state: 'lost', retry_reason: 'port_in_use', in_use: true })
    expect(Number(m.snap().retry_in_ms)).toBeGreaterThan(IN_USE_RETRY_MS - 100)
    await m.clock.advance(IN_USE_RETRY_MS * 5 + 50)
    expect(m.snap()).toMatchObject({ in_use: true, retry_reason: 'port_in_use' })
    expect(Number(m.snap().retry_in_ms)).toBeLessThanOrEqual(IN_USE_RETRY_MS)
    const busy = m.errors.filter((e) => e.type === 'error' && e.kind === 'port_in_use')
    expect(busy).toHaveLength(1)
    expect(busy[0]).toMatchObject({ role: 'esp' })
    m.ctl.espBusy = false
    for (let i = 0; i < (IN_USE_RETRY_MS + 2000) / 10 && m.snap().link_state !== 'up'; i++) await m.clock.advance(10)
    expect(m.snap()).toMatchObject({ connected: true, link: true, link_state: 'up', attempt: 0 })
    expect(m.snap().in_use).toBeUndefined()
  })

  test('FC: shows in use, retries quietly, connects when released; disconnect ends the retry', async () => {
    const m = mk({ fc: false })
    m.ctl.fcBusy = true
    await m.run(m.host.handle({ type: 'connect', role: 'fc', mock: true }), 100)
    const fc = () => m.host.snapshot().fc as Record<string, unknown>
    expect(fc()).toMatchObject({ connected: false, wanted: true, in_use: true })
    await m.clock.advance(IN_USE_RETRY_MS * 3 + 50)
    expect(m.fcOpens()).toBe(4)
    expect(m.errors.filter((e) => e.type === 'error' && e.kind === 'port_in_use')).toHaveLength(1)
    m.ctl.fcBusy = false
    for (let i = 0; i < (IN_USE_RETRY_MS + 1000) / 10 && !fc().connected; i++) await m.clock.advance(10)
    expect(fc()).toMatchObject({ connected: true, wanted: true })
    expect(fc().in_use).toBeUndefined()

    // released while waiting: a disconnect stops the retries
    await m.run(m.host.handle({ type: 'disconnect', role: 'fc' }), 500)
    m.ctl.fcBusy = true
    await m.run(m.host.handle({ type: 'connect', role: 'fc', mock: true }), 100)
    await m.run(m.host.handle({ type: 'disconnect', role: 'fc' }), 100)
    const n = m.fcOpens()
    await m.clock.advance(IN_USE_RETRY_MS * 3)
    expect(m.fcOpens()).toBe(n)
    expect(fc().in_use).toBeUndefined()
  })
})

describe('Host firmware flashing hand-off', () => {
  test('esp_release stops the link and closes the port until esp_resume; then it reopens and links', async () => {
    const m = mk({ fc: false })
    await m.connect()
    expect(m.snap().link_state).toBe('up')
    const port = m.esp
    const rel = m.host.handle({ type: 'esp_release' })
    for (let i = 0; i < 300 && !m.released.length; i++) await m.clock.advance(10)
    expect(m.released).toEqual([{ type: 'esp_released', ok: true, error: undefined }])
    expect(port.closed).toBe(true)
    expect(m.snap()).toMatchObject({ flashing: true, connected: false, link_state: 'paused', wanted: true })
    const opens = m.opens()
    // nothing reopens the port while it is released (the flasher owns it)
    await m.clock.advance(20000)
    expect(m.opens()).toBe(opens)
    // a second release while released answers ok at once
    await m.host.handle({ type: 'esp_release' })
    expect(m.released.length).toBe(2)
    await m.host.handle({ type: 'esp_resume' })
    await m.run(rel, 1000)
    for (let i = 0; i < 300 && m.snap().link_state !== 'up'; i++) await m.clock.advance(10)
    expect(m.opens()).toBe(opens + 1)
    expect(m.snap()).toMatchObject({ flashing: undefined, connected: true, link_state: 'up' })
  })

  test('esp_release is refused while a bind runs', async () => {
    const m = mk()
    await m.connect()
    const bind = m.host.handle({ type: 'bind', fofs_hz: 0 })
    await m.clock.advance(50)
    await m.host.handle({ type: 'esp_release' })
    expect(m.released[0]).toMatchObject({ ok: false })
    await m.run(bind)
  })
})
