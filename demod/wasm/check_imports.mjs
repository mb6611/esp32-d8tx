import { readFileSync } from 'node:fs';
const mod = new WebAssembly.Module(readFileSync(process.argv[2]));
const imps = WebAssembly.Module.imports(mod).map((i) => `${i.module}.${i.name}`).sort();
const want = ['atan2f', 'cosf', 'floorf', 'sinf'].map((n) => `env.${n}`);
if (JSON.stringify(imps) !== JSON.stringify(want)) {
  console.error('FAIL wasm imports:', imps, 'expected', want);
  process.exit(1);
}
const exps = WebAssembly.Module.exports(mod).map((e) => e.name);
for (const n of ['d8_decode', 'd8_work_size', 'd8_alloc', 'd8_reset', 'memory'])
  if (!exps.includes(n)) { console.error('FAIL missing export', n); process.exit(1); }
console.log('wasm imports ok:', imps.join(', '));
