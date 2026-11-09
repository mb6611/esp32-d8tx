// Cross-check: run demod/dist/d8demod.wasm in Node over every capture and compare with test/expected.txt.
// Layouts: d8_opts {u8 txid[2]; i32 has_hint @4; f32 hint @8} = 12 B; d8_result {u8 pkt[20]; i32 crc_ok @20; f32 cfo @24; f32 shift @28; f32 t_ms @32} = 36 B.
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
const here = dirname(fileURLToPath(import.meta.url));
const repo = join(here, '..', '..');
const { instance } = await WebAssembly.instantiate(readFileSync(join(repo, 'demod/dist/d8demod.wasm')), {
  env: { atan2f: Math.atan2, sinf: Math.sin, cosf: Math.cos, floorf: Math.floor },
});
const x = instance.exports;
const unpack4 = (b) => { const o = new Int8Array(2 * b.length); for (let i = 0; i < b.length; i++) { o[2 * i] = ((b[i] & 0xf) ^ 8) - 8; o[2 * i + 1] = ((b[i] >> 4) ^ 8) - 8; } return o; };
let fails = 0, rows = 0;
for (const line of readFileSync(join(here, '..', 'test', 'expected.txt'), 'utf8').trim().split('\n')) {
  const [file, bits, fs, found, hex, cfo] = line.split(' ');
  const raw = new Uint8Array(readFileSync(join(repo, 'protocol/captures', file)));
  const iq = Number(bits) === 4 ? unpack4(raw) : new Int8Array(raw.buffer, raw.byteOffset, raw.length);
  const n = iq.length / 2;
  x.d8_reset();
  const pIq = x.d8_alloc(iq.length), pW = x.d8_alloc(x.d8_work_size(n)), pR = x.d8_alloc(36);
  new Int8Array(x.memory.buffer, pIq, iq.length).set(iq);
  const rc = x.d8_decode(pIq, n, Number(fs), 0, pW, pR);
  const dv = new DataView(x.memory.buffer, pR, 36);
  let ok = rc === Number(found), got = '-', c = 0;
  if (rc === 1) {
    got = Buffer.from(new Uint8Array(x.memory.buffer, pR, 20)).toString('hex');
    c = dv.getFloat32(24, true);
    ok = ok && got === hex && dv.getInt32(20, true) === 1 && Math.abs(c - Number(cfo)) < 500;
  }
  console.log(`${file.padEnd(22)} ${ok ? 'ok  ' : 'FAIL'} wasm_cfo=${c.toFixed(1)} py_cfo=${Number(cfo).toFixed(1)}`);
  if (!ok) { fails++; console.log(`  expected ${hex} found=${found}, got ${got} rc=${rc}`); }
  rows++;
}
console.log(`${rows} captures, ${fails} failures`);
process.exit(rows && !fails ? 0 : 1);
