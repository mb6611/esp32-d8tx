// Granted Web Serial ports, listed on the UI thread. Web Serial only lists ports this origin was granted, so the
// device dropdowns show those plus an "Add device…" entry that calls requestPort() with the role's USB filters.
import { useCallback, useEffect, useState } from 'react'
import { deviceOf, portLabel, roleFilters, type PortInfoLike } from '@d8tx/serial'
import type { PortRef, Role } from '@d8tx/core'

interface SerialPortLike {
  getInfo(): PortInfoLike
}
interface SerialLike extends EventTarget {
  getPorts(): Promise<SerialPortLike[]>
  requestPort(o: { filters: PortInfoLike[] }): Promise<SerialPortLike>
}

export interface GrantedPort {
  port: SerialPortLike
  /** Index in navigator.serial.getPorts() order: what the worker matches on. */
  index: number
  info: PortInfoLike
  label: string
  role: Role | null
  /** "1A86:7523" */
  ids: string
}

const serialApi = (): SerialLike | undefined => (navigator as Navigator & { serial?: SerialLike }).serial
const hex4 = (v?: number) => (v ?? 0).toString(16).padStart(4, '0').toUpperCase()

export const refOf = (p: GrantedPort): PortRef => ({ index: p.index, usbVendorId: p.info.usbVendorId, usbProductId: p.info.usbProductId })

export function usePorts() {
  const [ports, setPorts] = useState<GrantedPort[]>([])
  const supported = !!serialApi()
  /** The first getPorts() listing arrived (always true without Web Serial). */
  const [loaded, setLoaded] = useState(!supported)

  const refresh = useCallback(async (): Promise<GrantedPort[]> => {
    const serial = serialApi()
    if (!serial) return []
    const list = await serial.getPorts().catch(() => [] as SerialPortLike[])
    const out = list.map((port, index) => {
      const info = port.getInfo?.() ?? {}
      return { port, index, info, label: portLabel(info), role: deviceOf(info)?.role ?? null, ids: `${hex4(info.usbVendorId)}:${hex4(info.usbProductId)}` }
    })
    // number identical devices so two DevKits stay distinguishable
    for (const p of out) {
      const same = out.filter((q) => q.label === p.label)
      if (same.length > 1) p.label = `${p.label} #${same.indexOf(p) + 1}`
    }
    setPorts(out)
    setLoaded(true)
    return out
  }, [])

  useEffect(() => {
    const serial = serialApi()
    if (!serial) return
    const on = () => void refresh()
    // initial listing; setPorts lands asynchronously after getPorts resolves
    on()
    serial.addEventListener('connect', on)
    serial.addEventListener('disconnect', on)
    return () => {
      serial.removeEventListener('connect', on)
      serial.removeEventListener('disconnect', on)
    }
  }, [refresh])

  /** Opens the browser's port chooser for the role; resolves to the granted port, or null when cancelled. */
  const add = useCallback(
    async (role: Role): Promise<GrantedPort | null> => {
      const serial = serialApi()
      if (!serial) throw new Error('Web Serial is not available in this browser')
      let picked: SerialPortLike
      try {
        picked = await serial.requestPort({ filters: roleFilters(role) })
      } catch (e) {
        if ((e as Error).name === 'NotFoundError') return null
        throw e
      }
      const list = await refresh()
      return list.find((p) => p.port === picked) ?? null
    },
    [refresh],
  )

  return { ports, supported, loaded, add, refresh }
}
