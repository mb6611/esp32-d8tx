// Bind check on the bench: node packages/core/scripts/bind-check.ts [--esp PATH] [--fc PATH] [--fofs HZ] [--power N] [--new-id] [--no-verify]
// Drives the worker Host's one-click bind (the app's Bind button) over real ports: ESP bind packets, MSP2_BETAFLIGHT_BIND
// to the FC, short no-arm confirm link. Then (unless --no-verify) reads `get frsky_spi_tx_id` in the Betaflight CLI and
// checks it equals the ESP txid; leaving the CLI with `exit` reboots the FC (no save; the bind already wrote it).
// --new-id: `ID new` on the ESP first. Props off; arming is never allowed. Only one process may hold each serial port.
import { readFileSync, writeSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { Host, createDecoder, realClock, type DecodeFn, type FromWorker, type Role } from '../src/index.ts'
import { NodeSerialPort } from '../../serial/src/node.ts'

const arg = (k: string, d: string): string => {
  const i = process.argv.indexOf(k)
  return i > 0 ? process.argv[i + 1] : d
}
const espPath = arg('--esp', '/dev/cu.usbserial-0001')
const fcPath = arg('--fc', '/dev/cu.usbmodem0x80000001')
const fofs = Number(arg('--fofs', '0'))
const power = process.argv.includes('--power') ? Number(arg('--power', '40')) : undefined
const log = (...a: unknown[]): void => void writeSync(1, a.map((x) => (typeof x === 'string' ? x : JSON.stringify(x))).join(' ') + '\n')
const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms))

async function loadDecoder(): Promise<DecodeFn | undefined> {
  try {
    return await createDecoder(readFileSync(fileURLToPath(new URL('../../../demod/dist/d8demod.wasm', import.meta.url))))
  } catch {
    return undefined
  }
}

/** Betaflight CLI: `get frsky_spi_tx_id`, then `exit` (reboots the FC, no save). Returns the txid as 4 hex digits. */
async function cliTxid(): Promise<string | null> {
  const port = new NodeSerialPort(fcPath, 115200)
  await port.open()
  let text = ''
  const pump = (async () => {
    for await (const c of port.read()) text += new TextDecoder().decode(c)
  })()
  const send = async (s: string, waitMs = 400) => {
    await port.write(new TextEncoder().encode(s))
    await sleep(waitMs)
  }
  await send('#', 800)
  await send('\r\n') // the first line after '#' can be swallowed
  await send('get frsky_spi_tx_id\r\n', 800)
  const m = /frsky_spi_tx_id\s*=\s*(\d+)\s*,\s*(\d+)/.exec(text)
  await send('exit\r\n', 300)
  await port.close().catch(() => undefined)
  await Promise.race([pump, sleep(1000)])
  if (!m) {
    log('CLI said:', text.slice(-400))
    return null
  }
  return [m[1], m[2]].map((v) => Number(v).toString(16).padStart(2, '0')).join('').toUpperCase()
}

async function main(): Promise<number> {
  const decode = await loadDecoder()
  if (!decode) log('WARN no WASM demod (demod/dist/d8demod.wasm): confirm can only use the FC fallback')
  let last: Record<string, unknown> = {}
  const host = new Host({
    post: (m: FromWorker) => {
      if (m.type === 'error') log('worker error:', m)
      if (m.type === 'state') {
        const e = m.esp
        const cur = { bind_state: e.bind_state, bind_reason: e.bind_reason, bind_via: e.bind_via, binding: e.binding, link: e.link, replies: m.radio.replies, fc_failsafe: m.fc.failsafe }
        if (cur.bind_state !== last.bind_state || cur.binding !== last.binding || cur.link !== last.link) log(`[${(realClock.now() / 1000).toFixed(1)}s]`, cur)
        last = cur
      }
    },
    openPort: async (role: Role) => new NodeSerialPort(role === 'esp' ? espPath : fcPath, role === 'esp' ? 921600 : 115200),
    mockPort: () => {
      throw new Error('no mock here')
    },
    decode,
    clock: realClock,
  })
  host.startState()
  await host.handle({ type: 'connect', role: 'esp' })
  await host.handle({ type: 'connect', role: 'fc' })
  await sleep(500)
  let snap = host.snapshot()
  log('ESP', { connected: snap.esp.connected, txid: snap.esp.txid }, 'FC', { connected: snap.fc.connected, error: snap.fc.error })
  if (process.argv.includes('--new-id')) {
    await host.handle({ type: 'new_id' })
    log('ID new ->', host.snapshot().esp.txid)
  }
  const t0 = realClock.now()
  await host.handle({ type: 'bind', fofs_hz: fofs, power })
  snap = host.snapshot()
  const txid = String(snap.esp.txid)
  log(`bind flow ${((realClock.now() - t0) / 1000).toFixed(1)} s:`, { state: snap.esp.bind_state, txid: snap.esp.bind_txid, via: snap.esp.bind_via, reason: snap.esp.bind_reason, replies: snap.radio.replies, armed: snap.fc.armed })
  await host.close()
  let ok = snap.esp.bind_state === 'bound'
  if (!process.argv.includes('--no-verify')) {
    await sleep(500)
    const fcTx = await cliTxid()
    log('Betaflight frsky_spi_tx_id =', fcTx, 'ESP txid =', txid, fcTx === txid ? 'MATCH' : 'MISMATCH')
    ok &&= fcTx === txid
    log('FC rebooting (CLI exit); waiting for USB to come back')
    await sleep(2000)
    for (let i = 0; i < 30; i++) {
      await sleep(500)
      try {
        const p = new NodeSerialPort(fcPath, 115200)
        await p.open()
        await p.close()
        log('FC USB back after', ((i + 1) * 0.5).toFixed(1), 's')
        break
      } catch {
        /* not yet */
      }
    }
  }
  log(ok ? 'RESULT OK' : 'RESULT FAIL')
  return ok ? 0 : 1
}

main().then((c) => process.exit(c), (e) => {
  log('fatal', String(e?.stack ?? e))
  process.exit(2)
})
