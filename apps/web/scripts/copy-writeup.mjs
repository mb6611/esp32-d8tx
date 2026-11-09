// Copies the writeup (docs/devkitv1/writeup, the only source) into dist/writeup so the app serves it at ./writeup/.
import { cpSync, rmSync, existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const src = fileURLToPath(new URL('../../../docs/devkitv1/writeup/', import.meta.url))
const dest = fileURLToPath(new URL('../dist/writeup/', import.meta.url))
if (!existsSync(src)) throw new Error('missing ' + src)
rmSync(dest, { recursive: true, force: true })
cpSync(src, dest, { recursive: true, filter: (p) => !/\.(py|md)$/.test(p) })
console.log('copied writeup ->', dest)
