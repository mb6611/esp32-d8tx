// Dedicated worker (R10): core + serial ports + WASM demod. Web Serial is reached through navigator.serial
// ('serial' in self is false in workers, but navigator.serial works in Chrome and Electron).
import { Host, NoPortError, createDecoder, type FromWorker, type PortRef, type Role, type ToWorker, type SerialPort } from '@d8tx/core'
import { DEVKIT, FC, MockDronePort, MockPort, WebSerialPort, pickGrantedPort, type MockCapture } from '@d8tx/serial'
import { realClock } from '@d8tx/core'
import wasmUrl from '../../../demod/dist/d8demod.wasm?url'
import capIndex from '../../../protocol/captures/index.json'

const capFiles = import.meta.glob('../../../protocol/captures/i4_d64/*.iq4', { query: '?url', import: 'default', eager: true }) as Record<string, string>

const post = (m: FromWorker): void => self.postMessage(m)
const nav = self.navigator as Navigator & { serial?: { getPorts(): Promise<unknown[]>; addEventListener?(t: string, f: () => void): void } }
post({ type: 'ready', serial: !!nav.serial })

async function mockCaptures(): Promise<MockCapture[]> {
  const out: MockCapture[] = []
  for (const c of capIndex as { file: string; format: string; fs: number; n: number; expect?: unknown }[]) {
    if (c.format !== 'i4_d64' || !c.expect) continue
    const url = capFiles[`../../../protocol/captures/${c.file}`]
    if (!url) continue
    out.push({ payload: new Uint8Array(await (await fetch(url)).arrayBuffer()), fs: c.fs, bits: 4, n: c.n })
  }
  return out
}

const decodePromise = createDecoder(fetch(wasmUrl))

const host = new Host({
  post,
  clock: realClock,
  decode: (iq, fs, hint, txid) => decodePromise.then((d) => d(iq, fs, hint, txid)),
  async openPort(role: Role, ref?: PortRef): Promise<SerialPort> {
    const spec = role === 'esp' ? DEVKIT : FC
    if (!nav.serial) throw new NoPortError('Web Serial is not available in this worker')
    const port = await pickGrantedPort(role, ref, nav.serial as never)
    if (!port) throw new NoPortError(ref ? 'the selected port is gone (unplugged?): pick it again' : `no granted ${role === 'esp' ? 'DevKit' : 'flight controller'} port: pick one first`)
    return new WebSerialPort(port, spec.baud)
  },
  async mockPort(role: Role): Promise<SerialPort> {
    return role === 'esp' ? new MockPort({ clock: realClock, captures: await mockCaptures() }) : new MockDronePort()
  },
})
host.startState()
// a granted device was plugged back in: retry a pending reconnect right away (the UI thread forwards this too)
nav.serial?.addEventListener?.('connect', () => void host.handle({ type: 'ports_changed' }))
self.onmessage = (ev: MessageEvent<ToWorker>) => void host.handle(ev.data)
