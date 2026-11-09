// In-app flashing of the bundled d8tx firmware. Runs on the UI thread: esptool-js drives Web Serial (and its DTR/RTS
// reset lines) directly and reports progress to React, while the worker only has to let go of the port. Flow: download
// and check the images, worker releases the DevKit port (link stopped), esptool writes bootloader + partition table +
// app (no erase, identity in NVS kept) and hard-resets, worker resumes and reconnects, the link auto-starts.
import { useCallback, useEffect, useRef, useState } from 'react'
import type { PortRef } from '@d8tx/core'
import type { EspStatus } from '../types'
import { refOf, type GrantedPort } from '../usePorts'
import { loadImages, loadManifest, type Image, type Manifest } from './bundle'
import { flashDevKit, type FlashPort } from './flasher'

export interface FlashApi {
  /** worker: stop the link and close the DevKit port; rejects when refused (armed, bind running) */
  release(): Promise<void>
  /** worker: reopen the DevKit port (when wanted); the link auto-starts */
  resume(): void
  /** connect the ESP32 (used when it was not connected before flashing) */
  connect(ref: PortRef): void
}

export type FlashPhase = 'idle' | 'preparing' | 'releasing' | 'connecting' | 'writing' | 'resetting' | 'reconnecting' | 'done' | 'failed'
export interface FlashState {
  phase: FlashPhase
  fraction: number
  detail?: string
  error?: string
  /** version the ESP32 reported after flashing (done), when it differs from the bundle */
  mismatch?: string
}

/** How long the app waits for the reflashed DevKit to answer INFO with the bundled version. */
const RECONNECT_MS = 20000

export function useFlash(api: FlashApi | undefined, esp: EspStatus | undefined, enabled: boolean) {
  const [manifest, setManifest] = useState<Manifest | null>(null)
  const [manifestError, setManifestError] = useState<string | null>(null)
  const [st, setSt] = useState<FlashState>({ phase: 'idle', fraction: 0 })
  const since = useRef(0)

  useEffect(() => {
    if (!enabled || manifest) return
    let live = true
    loadManifest().then(
      (m) => live && setManifest(m),
      (e: unknown) => live && setManifestError(e instanceof Error ? e.message : String(e)),
    )
    return () => {
      live = false
    }
  }, [enabled, manifest])

  // after the reset: done once the DevKit answers INFO again (with the bundled version, normally)
  const ver = esp?.connected ? esp.info?.ver : undefined
  // (adjusting state while rendering, React's documented alternative to an effect)
  if (st.phase === 'reconnecting' && esp?.connected && esp.info) {
    const v = ver === undefined ? 'unversioned' : String(ver)
    setSt({ phase: 'done', fraction: 1, mismatch: manifest && v !== manifest.version ? v : undefined })
  }
  useEffect(() => {
    if (st.phase !== 'reconnecting') return
    const t = setTimeout(() => setSt((s) => (s.phase === 'reconnecting' ? { phase: 'failed', fraction: 1, error: 'written, but the DevKit did not answer after the reset' } : s)), Math.max(0, since.current + RECONNECT_MS - Date.now()))
    return () => clearTimeout(t)
  }, [st.phase])

  const flash = useCallback(
    async (target: GrantedPort) => {
      if (!api || !manifest) return
      const wasWanted = !!esp?.wanted
      let images: Image[]
      try {
        setSt({ phase: 'preparing', fraction: 0, detail: 'downloading the bundled images' })
        images = await loadImages(manifest)
        setSt({ phase: 'releasing', fraction: 0, detail: 'stopping the radio link' })
        await api.release()
      } catch (e) {
        setSt({ phase: 'failed', fraction: 0, error: e instanceof Error ? e.message : String(e) })
        return
      }
      let err: unknown = null
      try {
        await flashDevKit(target.port as unknown as FlashPort, manifest, images, (p) => setSt({ phase: p.step, fraction: p.fraction, detail: p.detail }))
      } catch (e) {
        err = e
      } finally {
        api.resume()
        if (!wasWanted) api.connect(refOf(target))
      }
      if (err) {
        setSt({ phase: 'failed', fraction: 0, error: err instanceof Error ? err.message : String(err) })
        return
      }
      since.current = Date.now()
      setSt({ phase: 'reconnecting', fraction: 1, detail: 'waiting for the DevKit to boot' })
    },
    [api, manifest, esp?.wanted],
  )

  const dismiss = useCallback(() => setSt({ phase: 'idle', fraction: 0 }), [])
  const busy = !['idle', 'done', 'failed'].includes(st.phase)
  return { manifest, manifestError, state: st, busy, flash, dismiss }
}
