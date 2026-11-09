// Instantiates demod/dist/d8demod.wasm and wraps d8_decode as the DecodeFn injected into D8Link.
// Layouts: d8_opts {u8 txid[2]; i32 has_hint @4; f32 hint @8} = 12 B; d8_result {u8 pkt[20]; i32 crc_ok @20; f32 cfo @24;
// f32 shift @28; f32 t_ms @32} = 36 B (see demod/wasm/check.mjs).
import type { DecodeFn } from '../link.ts'
import { TXID } from '../protocol.ts'
import { parseReply, REPLY_LEN } from '../telemetry.ts'

interface Exports {
  memory: WebAssembly.Memory
  d8_reset(): void
  d8_alloc(n: number): number
  d8_work_size(n: number): number
  d8_decode(iq: number, n: number, fs: number, opts: number, work: number, out: number): number
}

export async function createDecoder(wasm: BufferSource | Response | Promise<Response>): Promise<DecodeFn> {
  const env = { atan2f: Math.atan2, sinf: Math.sin, cosf: Math.cos, floorf: Math.floor }
  let inst: WebAssembly.Instance
  if (wasm instanceof Response || wasm instanceof Promise) inst = (await WebAssembly.instantiateStreaming(wasm as Response | Promise<Response>, { env })).instance
  else inst = (await WebAssembly.instantiate(wasm, { env })).instance
  const x = inst.exports as unknown as Exports
  return (iq, fs, hint, txid = TXID) => {
    const n = iq.length >> 1
    x.d8_reset()
    const pIq = x.d8_alloc(iq.length)
    const pWork = x.d8_alloc(x.d8_work_size(n))
    const pOpts = x.d8_alloc(12)
    const pOut = x.d8_alloc(36)
    new Int8Array(x.memory.buffer, pIq, iq.length).set(iq)
    const ov = new DataView(x.memory.buffer, pOpts, 12)
    ov.setUint8(0, txid[0])
    ov.setUint8(1, txid[1])
    ov.setInt32(4, hint === null ? 0 : 1, true)
    ov.setFloat32(8, hint ?? 0, true)
    if (x.d8_decode(pIq, n, fs, pOpts, pWork, pOut) !== 1) return null
    const dv = new DataView(x.memory.buffer, pOut, 36)
    const pkt = new Uint8Array(x.memory.buffer, pOut, 20).slice()
    if (dv.getInt32(20, true) !== 1 || pkt[0] !== REPLY_LEN) return null
    return { ...parseReply(pkt), cfo_hz: dv.getFloat32(24, true), shift_hz: dv.getFloat32(28, true), t_ms: dv.getFloat32(32, true) }
  }
}
