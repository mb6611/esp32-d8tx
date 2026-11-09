// Copies the built firmware images into the web app (apps/web/public/firmware/) with a manifest the in-app flasher
// reads. Offsets and flash settings come from the ESP-IDF build's flasher_args.json; only bootloader, partition table
// and app are bundled, so flashing never touches the NVS partition (per-ESP identity). Run via `make -C firmware web`.
// Usage: node firmware/tools/web_bundle.mjs [build_dir] [out_dir]
import { createHash } from 'node:crypto'
import { copyFileSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs'
import { basename, join, resolve } from 'node:path'
import { FW_ROOT, fwVersion } from './fw_version.mjs'

const build = resolve(process.argv[2] ?? join(FW_ROOT, 'build'))
const out = resolve(process.argv[3] ?? join(FW_ROOT, '../apps/web/public/firmware'))
const fa = JSON.parse(readFileSync(join(build, 'flasher_args.json'), 'utf8'))
const ver = readFileSync(join(build, 'd8tx_fw_version.txt'), 'utf8').trim()
const src = fwVersion()
if (ver !== src) {
  console.error(`web_bundle: build version ${ver} != source version ${src}: rebuild (make -C firmware build), or fw_version.mjs and CMakeLists.txt disagree`)
  process.exit(1)
}
if (fa.extra_esptool_args?.chip !== 'esp32') throw new Error(`unexpected chip ${fa.extra_esptool_args?.chip}`)

const parts = [['bootloader', 'bootloader.bin'], ['partition-table', 'partition-table.bin'], ['app', 'd8tx-app.bin']]
mkdirSync(out, { recursive: true })
for (const f of readdirSync(out)) if (f.endsWith('.bin') || f === 'manifest.json') rmSync(join(out, f))
const files = parts.map(([key, name]) => {
  const e = fa[key]
  if (!e || e.encrypted !== 'false') throw new Error(`flasher_args.json: no plain ${key} entry`)
  const data = readFileSync(join(build, e.file))
  copyFileSync(join(build, e.file), join(out, name))
  return { name: key, offset: Number.parseInt(e.offset, 16), path: name, size: data.length, sha256: createHash('sha256').update(data).digest('hex') }
})
// the images must stay clear of the NVS partition (0x9000..0xF000 in the single-app table)
const NVS = [0x9000, 0xf000]
for (const f of files) if (f.offset < NVS[1] && f.offset + f.size > NVS[0]) throw new Error(`${f.name} overlaps NVS`)
const manifest = {
  chip: 'esp32',
  version: ver,
  flash: fa.flash_settings, // { flash_mode, flash_size, flash_freq }
  files,
}
writeFileSync(join(out, 'manifest.json'), JSON.stringify(manifest, null, 2) + '\n')
console.log(`web_bundle: ${ver} -> ${out}`)
for (const f of files) console.log(`  0x${f.offset.toString(16)} ${basename(f.path)} ${f.size} B`)
