// The firmware version INFO reports as ver=<semver>+<hash8>. Same algorithm as firmware/main/CMakeLists.txt (keep
// them in sync; web_bundle.mjs checks that both agree): sha256 over "<path>\n<sha256(content)>\n" for main/*.c,
// main/*.h, main/CMakeLists.txt, CMakeLists.txt and sdkconfig.defaults, sorted by path relative to firmware/.
// CLI: node firmware/tools/fw_version.mjs  -> prints the version of the current sources.
import { createHash } from 'node:crypto'
import { readFileSync, readdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

export const FW_ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')

const sha = (b) => createHash('sha256').update(b).digest('hex')

export function fwSourceFiles(root = FW_ROOT) {
  const main = readdirSync(join(root, 'main')).filter((f) => /\.[ch]$/.test(f) || f === 'CMakeLists.txt').map((f) => `main/${f}`)
  // CMake's list(SORT) is a plain byte-wise string sort
  return [...main, 'CMakeLists.txt', 'sdkconfig.defaults'].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0))
}

export function fwVersion(root = FW_ROOT) {
  const semver = /set\(D8TX_FW_SEMVER "([^"]+)"\)/.exec(readFileSync(join(root, 'main/CMakeLists.txt'), 'utf8'))?.[1]
  if (!semver) throw new Error('D8TX_FW_SEMVER not found in firmware/main/CMakeLists.txt')
  const cat = fwSourceFiles(root).map((f) => `${f}\n${sha(readFileSync(join(root, f)))}\n`).join('')
  return `${semver}+${sha(cat).slice(0, 8)}`
}

if (process.argv[1] === fileURLToPath(import.meta.url)) console.log(fwVersion())
