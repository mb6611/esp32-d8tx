// The d8tx firmware bundled with the web app (apps/web/public/firmware/, made by `make -C firmware web`): manifest,
// image download with sha256 check, and the version comparison the Pairing panel offers updates from.

export interface BundleFile {
  name: string
  offset: number
  path: string
  size: number
  sha256: string
}
export interface Manifest {
  chip: string
  version: string
  flash: { flash_mode: string; flash_size: string; flash_freq: string }
  files: BundleFile[]
}
export interface Image {
  name: string
  address: number
  data: Uint8Array
}

/** The NVS partition (per-ESP identity: txid + hop table) of the single-app table; images must never touch it. */
export const NVS_RANGE: readonly [number, number] = [0x9000, 0xf000]

const baseUrl = (): string => new URL('firmware/', document.baseURI).href

export async function loadManifest(base = baseUrl()): Promise<Manifest> {
  const r = await fetch(new URL('manifest.json', base))
  if (!r.ok) throw new Error(`no bundled firmware (manifest.json: HTTP ${r.status})`)
  const m = (await r.json()) as Manifest
  checkManifest(m)
  return m
}

/** Throws unless the manifest is a classic-ESP32 bundle whose images all stay clear of NVS. */
export function checkManifest(m: Manifest): void {
  if (m.chip !== 'esp32') throw new Error(`bundled firmware is for ${m.chip}, not the ESP32 DevKit`)
  if (!m.version || !m.files?.length) throw new Error('bundled firmware manifest is malformed')
  for (const f of m.files) {
    if (!(f.offset >= 0x1000) || !(f.size > 0)) throw new Error(`bad image ${f.name}`)
    if (f.offset < NVS_RANGE[1] && f.offset + f.size > NVS_RANGE[0]) throw new Error(`image ${f.name} would overwrite the identity (NVS)`)
  }
}

const hex = (b: ArrayBuffer): string => [...new Uint8Array(b)].map((x) => x.toString(16).padStart(2, '0')).join('')

/** Downloads the images and checks size and sha256 against the manifest. */
export async function loadImages(m: Manifest, base = baseUrl()): Promise<Image[]> {
  return Promise.all(
    m.files.map(async (f) => {
      const r = await fetch(new URL(f.path, base))
      if (!r.ok) throw new Error(`${f.path}: HTTP ${r.status}`)
      const buf = await r.arrayBuffer()
      const h = hex(await crypto.subtle.digest('SHA-256', buf))
      if (buf.byteLength !== f.size || h !== f.sha256) throw new Error(`${f.path} is corrupt (sha256 ${h})`)
      return { name: f.name, address: f.offset, data: new Uint8Array(buf) }
    }),
  )
}

/** What the Pairing panel offers for the ESP32's firmware. */
export type FlashOffer =
  | { kind: 'install' } // no d8tx firmware answered (blank or foreign)
  | { kind: 'update'; from: string; to: string } // d8tx firmware of another version
  | { kind: 'current' } // the bundled version runs (reflash from the menu only)
  | { kind: 'none' } // nothing to judge yet

export function flashOffer(o: {
  bundled?: string
  connected: boolean
  /** INFO of the running firmware */
  info?: Record<string, unknown>
  protocolOk?: boolean
  /** the ESP32 is wanted but INFO keeps failing (no d8tx firmware answers) */
  noAnswer: boolean
}): FlashOffer {
  if (!o.bundled) return { kind: 'none' }
  if (o.connected && o.info) {
    if (o.protocolOk === false) return { kind: 'install' }
    const ver = o.info.ver === undefined ? undefined : String(o.info.ver)
    return ver === o.bundled ? { kind: 'current' } : { kind: 'update', from: ver ?? 'unversioned', to: o.bundled }
  }
  return o.noAnswer ? { kind: 'install' } : { kind: 'none' }
}
