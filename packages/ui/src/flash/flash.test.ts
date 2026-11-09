import { describe, expect, test } from 'vitest'
import { md5 } from './md5'
import { checkManifest, flashOffer, type Manifest } from './bundle'

describe('md5', () => {
  // expected digests from node:crypto
  const REF: Record<number, string> = {
    55: 'c9e512626618c9980ef21a96597af94c',
    56: 'ecde7caa08e9f5657c863df107cac60a',
    63: '2f0301069e1c40af7f6c8f843b1b13f2',
    64: 'b6bf87c24b1bc334e2541387a92b981b',
    65: 'f168246f08b6134d66bd2a10343fa9f1',
    1000: '2b1e78d5765de9e10495a01412a1cf22',
    70001: 'e9f4118a13dce52b1ce13e95f2844615',
  }
  test('matches reference digests', () => {
    expect(md5(new Uint8Array())).toBe('d41d8cd98f00b204e9800998ecf8427e')
    expect(md5(new TextEncoder().encode('abc'))).toBe('900150983cd24fb0d6963f7d28e17f72')
    for (const n of [55, 56, 63, 64, 65, 1000, 70001]) {
      const d = Uint8Array.from({ length: n }, (_, i) => (i * 31 + 7) & 0xff)
      expect(md5(d)).toBe(REF[n])
    }
  })
})

const mf = (files: Manifest['files']): Manifest => ({ chip: 'esp32', version: '1.0.0+aa', flash: { flash_mode: 'dio', flash_size: '2MB', flash_freq: '40m' }, files })

describe('bundle', () => {
  test('manifest images must stay clear of NVS', () => {
    const ok = [
      { name: 'bootloader', offset: 0x1000, path: 'b', size: 23808, sha256: '' },
      { name: 'partition-table', offset: 0x8000, path: 'p', size: 3072, sha256: '' },
      { name: 'app', offset: 0x10000, path: 'a', size: 600000, sha256: '' },
    ]
    expect(() => checkManifest(mf(ok))).not.toThrow()
    expect(() => checkManifest(mf([{ ...ok[0], size: 0x9000 }]))).toThrow(/NVS/)
    expect(() => checkManifest(mf([{ ...ok[1], offset: 0x9000 }]))).toThrow(/NVS/)
    expect(() => checkManifest({ ...mf(ok), chip: 'esp32s3' })).toThrow()
  })

  test('offers install, update or nothing', () => {
    const b = '1.0.0+aa'
    expect(flashOffer({ bundled: b, connected: false, noAnswer: true })).toEqual({ kind: 'install' })
    expect(flashOffer({ bundled: b, connected: false, noAnswer: false })).toEqual({ kind: 'none' })
    expect(flashOffer({ bundled: b, connected: true, info: { proto: 1, ver: b }, protocolOk: true, noAnswer: false })).toEqual({ kind: 'current' })
    expect(flashOffer({ bundled: b, connected: true, info: { proto: 1, ver: '1.0.0+bb' }, protocolOk: true, noAnswer: false })).toEqual({ kind: 'update', from: '1.0.0+bb', to: b })
    expect(flashOffer({ bundled: b, connected: true, info: { proto: 1 }, protocolOk: true, noAnswer: false })).toEqual({ kind: 'update', from: 'unversioned', to: b })
    expect(flashOffer({ bundled: b, connected: true, info: { proto: 2 }, protocolOk: false, noAnswer: false })).toEqual({ kind: 'install' })
    expect(flashOffer({ connected: true, info: {}, noAnswer: true })).toEqual({ kind: 'none' })
  })
})
