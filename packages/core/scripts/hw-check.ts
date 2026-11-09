// Hardware check: node packages/core/scripts/hw-check.ts [--esp PATH] [--fc PATH] [--power N] [--seconds N] [--fofs HZ] [--no-esp] [--no-fc]
// Props off. Arm is never allowed here. Only one process may hold each serial port.
import { readFileSync, writeSync } from 'node:fs'
import { inspect } from 'node:util'
import { fileURLToPath } from 'node:url'
import { BetaflightMSP, D8Link, TXID, parseReply, realClock, type Reply } from '../src/index.ts'
import { NodeSerialPort } from '../../serial/src/node.ts'

const arg = (k: string, d: string): string => {
  const i = process.argv.indexOf(k)
  return i > 0 ? process.argv[i + 1] : d
}
const esp = arg('--esp', '/dev/cu.usbserial-0001')
const fcPath = arg('--fc', '/dev/cu.usbmodem0x80000001')
const power = Number(arg('--power', '30'))
const seconds = Number(arg('--seconds', '10'))
const fofs = process.argv.includes('--fofs') ? Number(arg('--fofs', '-75000')) : undefined
// Synchronous stdout so every line is out even if a later port close stalls or the process is killed.
const log = (...a: unknown[]): void => {
  writeSync(1, a.map((x) => (typeof x === 'string' ? x : inspect(x, { breakLength: Infinity, depth: 4 }))).join(' ') + '\n')
}
const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms))

// WASM demod (demod/dist/d8demod.wasm) when built, else captures are only counted.
async function loadDecoder() {
  try {
    const path = fileURLToPath(new URL('../../../demod/dist/d8demod.wasm', import.meta.url))
    const { instance } = await WebAssembly.instantiate(readFileSync(path), {
      env: { atan2f: Math.atan2, sinf: Math.sin, cosf: Math.cos, floorf: Math.floor },
    })
    const x = instance.exports as any
    return (iq: Int8Array, fs: number): Reply | null => {
      const n = iq.length / 2
      x.d8_reset()
      const pIq = x.d8_alloc(iq.length), pW = x.d8_alloc(x.d8_work_size(n)), pR = x.d8_alloc(36)
      new Int8Array(x.memory.buffer, pIq, iq.length).set(iq)
      if (x.d8_decode(pIq, n, fs, 0, pW, pR) !== 1) return null
      const dv = new DataView(x.memory.buffer, pR, 36)
      const pkt = new Uint8Array(x.memory.buffer, pR, 20).slice()
      if (!dv.getInt32(20, true) || pkt[0] !== 0x11 || pkt[1] !== TXID[0] || pkt[2] !== TXID[1]) return null
      return { ...parseReply(pkt), cfo_hz: dv.getFloat32(24, true), shift_hz: dv.getFloat32(28, true), t_ms: dv.getFloat32(32, true) }
    }
  } catch {
    return undefined
  }
}

let ok = true
if (!process.argv.includes('--no-esp')) {
  const decode = await loadDecoder()
  log(`== DevKit ${esp}, power ${power}, ${seconds} s, telemetry on, arm disallowed, decoder: ${decode ? 'wasm' : 'none (captures counted only)'}`)
  const port = new NodeSerialPort(esp, 921600)
  const link = new D8Link(port, realClock, { decode })
  let captures = 0
  const events: Record<string, number> = {}
  link.on((e) => {
    events[e.name] = (events[e.name] ?? 0) + 1
    if (e.name === 'tlm') captures++
    if (e.name === 'link_lost') log('LINK LOST', e)
    if (e.name === 'link_end') log('link_end', e)
  })
  await link.open()
  await sleep(1500) // opening the port resets the ESP32 (DTR/RTS)
  log('PING (sync)', await link.sync())
  log('INFO', await link.info())
  await link.start({ power, allowArm: false, telemetry: true, fofsHz: fofs })
  link.setSticks([1000, 1500, 1500, 1500, 1500, 1500, 1000, 1500])
  const t0 = realClock.now()
  // STAT the way the host link-lost rule uses it (every 200 ms, like the library's own poll): count timeouts.
  let statN = 0, statTimeouts = 0, statMs = 0
  const statLoop = (async () => {
    while (link.isLinked && realClock.now() - t0 < seconds * 1000) {
      const ts = realClock.now()
      try {
        await link.request('STAT', 250) // the library poll's timeout
        statN++
        statMs = Math.max(statMs, realClock.now() - ts)
      } catch {
        statTimeouts++
      }
      await sleep(200)
    }
  })()
  while (realClock.now() - t0 < seconds * 1000) {
    await sleep(Math.min(2000, seconds * 1000 - (realClock.now() - t0)))
    const s = link.status()
    log(`t=${((realClock.now() - t0) / 1000).toFixed(1)} hz=${s.sender_hz.toFixed(1)} max_gap=${s.sender_max_gap_ms.toFixed(1)} sent=${s.sent} skipped=${s.skipped} link=${s.link}`)
  }
  await statLoop
  const s = link.status()
  const tl = link.telemetry()
  const stat = await link.request('STAT').catch((e) => ({ error: String(e) }))
  await link.stop()
  log('STAT', stat, 'events', events)
  log(`RESULT sender_hz=${s.sender_hz.toFixed(2)} max_gap_ms=${s.sender_max_gap_ms.toFixed(1)} sent=${s.sent} skipped=${s.skipped} slots=${s.slots} late_max_us=${s.late_max_us}`)
  log(`RESULT stat_ok=${statN} stat_timeouts=${statTimeouts} stat_max_ms=${statMs.toFixed(0)}`)
  log(`RESULT telemetry triggers=${tl.triggers} decoded_replies=${tl.replies} tlm_events=${events.tlm ?? 0} catch_rate=${tl.catch_rate} rssi_dbm=${tl.rssi_dbm} vbat=${tl.vbat_v}`)
  const espOk = s.sender_hz >= 108 && s.sender_hz <= 113 && s.sender_max_gap_ms <= 50 && s.link === 1 && statTimeouts === 0
  if (!espOk) ok = false
  log(`DevKit ${espOk ? 'PASS' : 'FAIL'}; closing port`)
  const tc = realClock.now()
  await link.close()
  log(`port closed in ${(realClock.now() - tc).toFixed(0)} ms`)
}

if (!process.argv.includes('--no-fc')) {
  log(`== FC ${fcPath}, attitude for 5 s`)
  const msp = new BetaflightMSP(new NodeSerialPort(fcPath, 115200), realClock, 300)
  await msp.open()
  await sleep(300)
  let n = 0, errs = 0, last: number[] = []
  const t0 = realClock.now()
  while (realClock.now() - t0 < 5000) {
    try {
      last = await msp.attitude()
      n++
    } catch {
      errs++
    }
  }
  const hz = (n * 1000) / (realClock.now() - t0)
  log(`RESULT fc_attitude_hz=${hz.toFixed(1)} n=${n} errors=${errs} last=${JSON.stringify(last)}`)
  if (hz < 10) ok = false
  log(`FC ${hz < 10 ? 'FAIL' : 'PASS'}; closing port`)
  await msp.close()
}
log(ok ? 'HW CHECK PASS' : 'HW CHECK FAIL')
process.exit(ok ? 0 : 1)
