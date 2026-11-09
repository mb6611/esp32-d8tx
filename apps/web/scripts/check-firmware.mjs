// Build guard for the bundled DevKit firmware (public/firmware/, made by `make -C firmware web`, kept in git because
// building ESP-IDF in every web build is impractical). Fails when the manifest or an image is missing or its sha256
// is off; warns when the firmware sources changed since the bundle was made.
import { createHash } from 'node:crypto'
import { existsSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { fwVersion } from '../../../firmware/tools/fw_version.mjs'

const dir = join(dirname(fileURLToPath(import.meta.url)), '../public/firmware')
const fail = (m) => {
  console.error(`check-firmware: ${m}\n  Rebuild the bundle with ESP-IDF: make -C firmware web`)
  process.exit(1)
}
const mf = join(dir, 'manifest.json')
if (!existsSync(mf)) fail(`missing ${mf}`)
const m = JSON.parse(readFileSync(mf, 'utf8'))
if (!m.version || !Array.isArray(m.files) || m.files.length !== 3) fail('manifest.json is malformed')
for (const f of m.files) {
  const p = join(dir, f.path)
  if (!existsSync(p)) fail(`missing ${p}`)
  const h = createHash('sha256').update(readFileSync(p)).digest('hex')
  if (h !== f.sha256) fail(`${f.path} sha256 ${h} != manifest ${f.sha256}`)
}
const src = fwVersion()
if (src !== m.version) console.warn(`check-firmware: WARNING bundled firmware ${m.version} is older than the sources (${src}); run make -C firmware web`)
else console.log(`check-firmware: bundled firmware ${m.version} ok`)
