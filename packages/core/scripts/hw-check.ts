// Hardware check: node packages/core/scripts/hw-check.ts [--esp PATH] [--fc PATH] [--power N] [--seconds N] [--fofs HZ] [--bind S] [--no-link] [--no-esp] [--no-fc]
// The reply filter uses the txid the firmware reports (INFO/ID), not the old TXID constant. With the FC enabled, MSP_RC and
// MSP_STATUS are polled during the link (RC readback vs our sticks, RX failsafe). --bind S: D8Link.bind() for S seconds
// before the link (the drone must be in bind mode). --no-link: identity/bind only.
// Props off. Arm is never allowed here. Only one process may hold each serial port.
import { readFileSync, writeSync } from 'node:fs'
import { inspect } from 'node:util'
import { fileURLToPath } from 'node:url'
import { BetaflightMSP, D8Link, realClock, type DecodeFn } from '../src/index.ts'
import { createDecoder } from '../src/worker/demod.ts'
import { NodeSerialPort } from '../../serial/src/node.ts'

const arg = (k: string, d: string): string => {
  const i = process.argv.indexOf(k)
  return i > 0 ? process.argv[i + 1] : d
}
const esp = arg('--esp', '/dev/cu.usbserial-0001')
const fcPath = arg('--fc', '/dev/cu.usbmodem0x80000001')
const power = Number(arg('--power', '30'))
const seconds = Number(arg('--seconds', '10'))
const fofs = process.argv.includes('--fofs') ? Number(arg('--fofs', '0')) : undefined
const bindS = process.argv.includes('--bind') ? Number(arg('--bind', '10')) : 0
const doLink = !process.argv.includes('--no-link')
const useFc = !process.argv.includes('--no-fc')
// Distinct values per channel so the readback checks the mapping. ch5/6/8 stay out of the 1700+ mode ranges, ch7 (arm) low.
const STICKS = [1100, 1200, 1300, 1400, 1450, 1550, 1000, 1600]
// Betaflight `map TAER1234`: MSP_RC = [roll, pitch, yaw, throttle, aux1..] = D8 ch [2, 3, 4, 1, 5, 6, 7, 8].
const RC_EXPECT = [STICKS[1], STICKS[2], STICKS[3], STICKS[0], ...STICKS.slice(4)]
// Synchronous stdout so every line is out even if a later port close stalls or the process is killed.
const log = (...a: unknown[]): void => {
  writeSync(1, a.map((x) => (typeof x === 'string' ? x : inspect(x, { breakLength: Infinity, depth: 4 }))).join(' ') + '\n')
}
const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms))

// WASM demod (demod/dist/d8demod.wasm) through the same wrapper the UI worker uses (passes the INFO txid to d8_opts),
// else captures are only counted.
async function loadDecoder(): Promise<DecodeFn | undefined> {
  try {
    const path = fileURLToPath(new URL('../../../demod/dist/d8demod.wasm', import.meta.url))
    const dec = await createDecoder(readFileSync(path))
    return (iq, fs, hint, txid) => {
      if (!txid) throw new Error('no txid passed to the decoder')
      return dec(iq, fs, hint, txid)
    }
  } catch {
    return undefined
  }
}

let ok = true

// FC side: MSP_RC + MSP_STATUS poll while the link runs (RC readback, RX failsafe).
type FcPoll = { n: number; errs: number; rcMatch: number; rcN: number; fsN: number; fsAfterLock: number; lockMs: number | null; lastRc: number[]; lastArmDis: string[]; maxDiff: number }
async function pollFc(msp: BetaflightMSP, until: () => boolean): Promise<FcPoll> {
  const t0 = realClock.now()
  const r: FcPoll = { n: 0, errs: 0, rcMatch: 0, rcN: 0, fsN: 0, fsAfterLock: 0, lockMs: null, lastRc: [], lastArmDis: [], maxDiff: 0 }
  while (!until()) {
    try {
      const rc = await msp.rc()
      const st = await msp.status()
      r.n++
      r.lastRc = rc
      r.lastArmDis = st.arming_disable
      if (st.failsafe) {
        r.fsN++
        if (r.lockMs !== null) r.fsAfterLock++
      } else {
        r.lockMs ??= realClock.now() - t0
        r.rcN++
        const d = Math.max(...RC_EXPECT.map((v, i) => Math.abs((rc[i] ?? 0) - v)))
        r.maxDiff = Math.max(r.maxDiff, d)
        if (d <= 3) r.rcMatch++
      }
      if (st.armed) log('!! FC reports ARMED')
    } catch {
      r.errs++
    }
    await sleep(200)
  }
  return r
}

let msp: BetaflightMSP | null = null
if (useFc && !process.argv.includes('--no-esp')) {
  msp = new BetaflightMSP(new NodeSerialPort(fcPath, 115200), realClock, 300)
  await msp.open()
  await sleep(300)
  const st = await msp.status()
  log(`FC before link: armed=${st.armed} failsafe=${st.failsafe} arming_disable=${st.arming_disable.join(',')}`)
}

if (!process.argv.includes('--no-esp')) {
  const decode = await loadDecoder()
  log(`== DevKit ${esp}, power ${power}, ${seconds} s, fofs ${fofs ?? 'default'}, telemetry on, arm disallowed, decoder: ${decode ? 'wasm' : 'none (captures counted only)'}`)
  const port = new NodeSerialPort(esp, 921600)
  const link = new D8Link(port, realClock, { decode })
  let captures = 0
  const events: Record<string, number> = {}
  link.on((e) => {
    events[e.name] = (events[e.name] ?? 0) + 1
    if (e.name === 'tlm') captures++
    if (e.name === 'link_lost') log('LINK LOST', e)
    if (e.name === 'link_end' || e.name === 'bind_end') log(e.name, e)
  })
  await link.open()
  await sleep(1500) // opening the port resets the ESP32 (DTR/RTS)
  log('PING (sync)', await link.sync())
  const info = await link.info()
  log('INFO', info, 'link.txid', link.txid)
  if (!link.txid) {
    log('FAIL: INFO has no txid')
    ok = false
  }
  const id = await link.id()
  log('ID', id, 'link.txid', link.txid)
  if (bindS > 0) {
    await link.bind(power, fofs) // sets FOFS first (default DEFAULT_FOFS_HZ)
    log(`bind started (power ${power}), binding=${link.binding}; STAT`, await link.request('STAT'))
    await sleep(bindS * 1000)
    await link.stopBind()
    log(`bind stopped, binding=${link.binding}; STAT`, await link.request('STAT'))
  }
  if (doLink) {
    await link.start({ power, allowArm: false, telemetry: true, fofsHz: fofs })
    link.setSticks(STICKS)
    const t0 = realClock.now()
    const fcPoll = msp ? pollFc(msp, () => !link.isLinked || realClock.now() - t0 >= seconds * 1000) : null
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
      await sleep(Math.min(5000, seconds * 1000 - (realClock.now() - t0)))
      const s = link.status()
      const tl = link.telemetry()
      log(`t=${((realClock.now() - t0) / 1000).toFixed(1)} hz=${s.sender_hz.toFixed(1)} max_gap=${s.sender_max_gap_ms.toFixed(1)} sent=${s.sent} skipped=${s.skipped} link=${s.link} catch10s=${tl.catch_rate} rssi=${tl.rssi_dbm}`)
    }
    await statLoop
    const fc = fcPoll ? await fcPoll : null
    const s = link.status()
    const tl = link.telemetry()
    const stat = await link.request('STAT').catch((e) => ({ error: String(e) }))
    await link.stop()
    log('STAT', stat, 'events', events)
    log(`RESULT sender_hz=${s.sender_hz.toFixed(2)} max_gap_ms=${s.sender_max_gap_ms.toFixed(1)} sent=${s.sent} skipped=${s.skipped} slots=${s.slots} late_max_us=${s.late_max_us}`)
    log(`RESULT stat_ok=${statN} stat_timeouts=${statTimeouts} stat_max_ms=${statMs.toFixed(0)}`)
    log(`RESULT telemetry triggers=${tl.triggers} decoded_replies=${tl.replies} tlm_events=${events.tlm ?? 0} catch_rate_10s=${tl.catch_rate} total_catch=${tl.triggers ? (tl.replies / tl.triggers).toFixed(3) : 'n/a'} rssi_dbm=${tl.rssi_dbm} vbat=${tl.vbat_v}`)
    const espOk = s.sender_hz >= 108 && s.sender_hz <= 113 && s.sender_max_gap_ms <= 50 && s.link === 1 && statTimeouts === 0
    if (!espOk) ok = false
    log(`DevKit ${espOk ? 'PASS' : 'FAIL'}`)
    if (fc) {
      log(`RESULT fc polls=${fc.n} errors=${fc.errs} failsafe_polls=${fc.fsN} (after lock ${fc.fsAfterLock}) rx_lock_ms=${fc.lockMs?.toFixed(0)} rc_match=${fc.rcMatch}/${fc.rcN} rc_max_diff=${fc.maxDiff} last_rc=${JSON.stringify(fc.lastRc.slice(0, 8))} expect=${JSON.stringify(RC_EXPECT)} arming_disable=${fc.lastArmDis.join(',')}`)
      const fcOk = fc.n > 0 && fc.lockMs !== null && fc.fsAfterLock === 0 && fc.rcN > 0 && fc.rcMatch === fc.rcN
      if (!fcOk) ok = false
      log(`FC link ${fcOk ? 'PASS' : 'FAIL'}`)
    }
  }
  log('closing DevKit port')
  const tc = realClock.now()
  await link.close()
  log(`port closed in ${(realClock.now() - tc).toFixed(0)} ms`)
  if (msp) {
    await sleep(1500)
    const st = await msp.status().catch(() => null)
    log(`FC after link stop: failsafe=${st?.failsafe} arming_disable=${st?.arming_disable.join(',')}`)
  }
}

if (useFc) {
  if (!msp) {
    msp = new BetaflightMSP(new NodeSerialPort(fcPath, 115200), realClock, 300)
    await msp.open()
    await sleep(300)
  }
  log(`== FC ${fcPath}, attitude for 5 s`)
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
