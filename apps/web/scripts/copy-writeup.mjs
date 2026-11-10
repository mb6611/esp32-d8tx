// Copies the writeup (docs/devkitv1/writeup, the only source) into dist/writeup so the app serves it at ./writeup/.
// The hosted copy only has docs/devkitv1/writeup and docs/diagrams, so the copied index.html is rewritten:
// diagram images point at ../diagrams/ (copied too), and links to other repo files go to GitHub.
import { cpSync, rmSync, existsSync, readFileSync, writeFileSync, statSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const REPO = 'https://github.com/mb6611/esp32-d8tx/'
const root = fileURLToPath(new URL('../../../', import.meta.url))
const src = path.join(root, 'docs/devkitv1/writeup')
const dist = fileURLToPath(new URL('../dist/', import.meta.url))
const dest = path.join(dist, 'writeup')
if (!existsSync(src)) throw new Error('missing ' + src)
rmSync(dest, { recursive: true, force: true })
cpSync(src, dest, { recursive: true, filter: (p) => !/\.(py|md)$/.test(p) })
const diagrams = path.join(root, 'docs/diagrams')
rmSync(path.join(dist, 'diagrams'), { recursive: true, force: true })
cpSync(diagrams, path.join(dist, 'diagrams'), { recursive: true, filter: (p) => statSync(p).isDirectory() || p.endsWith('.svg') })

const page = path.join(dest, 'index.html')
const html = readFileSync(page, 'utf8').replace(/(src|href)="([^"]+)"/g, (whole, attr, url) => {
  if (/^([a-z]+:|#|\/)/i.test(url)) return whole
  const [file, frag] = url.split('#')
  const target = path.resolve(src, file)
  const rel = path.relative(root, target).split(path.sep).join('/')
  if (rel.startsWith('..')) return whole
  if (rel.startsWith('docs/diagrams/') && rel.endsWith('.svg')) return `${attr}="../diagrams/${rel.slice('docs/diagrams/'.length)}${frag ? '#' + frag : ''}"`
  const inside = !path.relative(src, target).startsWith('..') && !file.endsWith('.md')
  if (inside) return whole
  const kind = file.endsWith('/') || (existsSync(target) && statSync(target).isDirectory()) ? 'tree' : 'blob'
  return `${attr}="${REPO}${kind}/main/${rel}${frag ? '#' + frag : ''}"`
})
writeFileSync(page, html)
console.log('copied writeup ->', dest)
