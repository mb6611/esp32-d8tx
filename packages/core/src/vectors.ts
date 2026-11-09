// Test helper: load golden vectors written by python/tools/gen_vectors.py.
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('../../../protocol/', import.meta.url))
export const vec = <T = any>(name: string): T => JSON.parse(readFileSync(root + 'vectors/' + name + '.json', 'utf8'))
export const captureDir = root + 'captures/'
export const captureIndex = (): any[] => JSON.parse(readFileSync(captureDir + 'index.json', 'utf8'))
export const hex = (s: string): Uint8Array => Uint8Array.from(s.match(/../g) ?? [], (h) => parseInt(h, 16))
export const toHex = (b: Uint8Array): string => Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('')

import { test } from 'vitest'
/** Register one vitest test per vector. */
export function each(list: any[], fn: (v: any) => void, label = (v: any, i: number): string => v.name ?? String(i)): void {
  list.forEach((v, i) => test(label(v, i), () => fn(v)))
}
