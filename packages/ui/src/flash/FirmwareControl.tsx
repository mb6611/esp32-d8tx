// One firmware button under the ESP32 port picker in Pairing. Its label follows what the DevKit reports:
// "Install firmware" when no d8tx firmware answers, "Update firmware" when INFO ver differs from the bundled build,
// "Reinstall firmware" when d8tx answers with the bundled version, "Flash firmware" when unknown (not connected).
// Flashing itself is useFlash (esptool-js on the UI thread).
import { useState } from 'react'
import type { PortRef } from '@d8tx/core'
import { Tip } from '../components/ui/tooltip'
import { cn } from '../lib/utils'
import { findSaved } from '../persist'
import type { EspStatus } from '../types'
import type { GrantedPort } from '../usePorts'
import { flashOffer } from './bundle'
import { useFlash, type FlashApi, type FlashPhase } from './useFlash'

const STEP: Partial<Record<FlashPhase, string>> = {
  preparing: 'Preparing',
  releasing: 'Stopping the link',
  connecting: 'Entering the bootloader',
  writing: 'Writing',
  resetting: 'Resetting',
  reconnecting: 'Reconnecting',
}

const KEEP = 'Writes bootloader, partition table and app only (no erase): this ESP32\'s identity (txid, hop table) and so the drone\'s binding are kept. The radio link stops for about 20 s.'

/** The DevKit port to flash: the one the worker uses, else the saved one, else the first granted DevKit. */
export function flashTarget(ports: GrantedPort[], esp: EspStatus | undefined, saved: PortRef | undefined): GrantedPort | undefined {
  const ref = (esp as { port?: PortRef } | undefined)?.port
  return findSaved(ports, ref) ?? findSaved(ports, saved) ?? ports.find((p) => p.role === 'esp')
}

/** INFO keeps failing on an open port: no d8tx firmware answers (blank or foreign). */
function noAnswer(esp?: EspStatus): boolean {
  if (!esp?.wanted || esp.connected || esp.in_use || esp.link_state !== 'lost') return false
  return /no reply to "(INFO|PING)|proto=1/.test(`${esp.error ?? ''} ${esp.retry_reason ?? ''}`)
}

export function FirmwareControl({ api, esp, ports, saved, armed, enabled }: {
  api?: FlashApi
  esp?: EspStatus
  ports: GrantedPort[]
  saved?: PortRef
  armed: boolean
  /** real ports with Web Serial (not mock) */
  enabled: boolean
}) {
  const f = useFlash(api, esp, enabled && !!api)
  const [confirm, setConfirm] = useState<string | null>(null)
  const info = esp?.connected ? esp.info : undefined
  if (!enabled || !api) return null

  const target = flashTarget(ports, esp, saved)
  const bundled = f.manifest?.version
  const offer = flashOffer({ bundled, connected: !!esp?.connected, info, protocolOk: esp?.protocol_ok, noAnswer: noAnswer(esp) })
  const blocked = armed ? 'Disarm first.' : !target ? 'Add the ESP32 DevKit port first.' : esp?.binding || esp?.bind_state === 'binding' || esp?.bind_state === 'confirming' ? 'Wait for the bind to finish.' : null
  const go = () => {
    setConfirm(null)
    if (target) void f.flash(target)
  }
  const ask = (label: string) => setConfirm(label)
  const s = f.state
  const running = info && String(info.fw ?? '').startsWith('d8tx')
  const actionLabel = !bundled ? null
    : offer.kind === 'install' ? 'Install firmware'
    : offer.kind === 'update' ? 'Update firmware'
    : running ? 'Reinstall firmware'
    : 'Flash firmware'
  const actionTip = offer.kind === 'install' ? `No d8tx firmware answers on this DevKit (blank or other firmware). Installs d8tx ${bundled}. ${KEEP}`
    : offer.kind === 'update' ? `Running ${offer.from}, this app ships ${offer.to}. ${KEEP}`
    : running ? `Running ${String(info?.ver ?? '?')}, the same version this app ships. ${KEEP}`
    : `Writes d8tx ${bundled}. ${KEEP}`

  return (
    <div className="flex w-56 flex-col gap-1 text-[11px] leading-snug">
      {!f.busy && !confirm && actionLabel && (
        blocked
          ? <Tip tip={blocked} className="cursor-not-allowed no-underline"><button className="btn w-full !py-0.5 text-xs" disabled>{actionLabel}</button></Tip>
          : <Tip tip={actionTip} className="no-underline"><button className={cn('btn w-full !py-0.5 text-xs', (offer.kind === 'install' || offer.kind === 'update') && 'border-warn')} onClick={() => ask(actionLabel)}>{actionLabel}</button></Tip>
      )}
      {confirm && !f.busy && (
        <div className="flex flex-col gap-1 rounded-sm border border-warn p-1.5">
          <span>{confirm}? {KEEP}</span>
          <div className="flex gap-1">
            <button className="btn !py-0 text-xs" onClick={go} disabled={!!blocked}>Flash</button>
            <button className="btn !py-0 text-xs" onClick={() => setConfirm(null)}>Cancel</button>
          </div>
        </div>
      )}
      {f.busy && (
        <div role="status" className="flex flex-col gap-0.5">
          <span className="text-warn">{STEP[s.phase] ?? s.phase}{s.phase === 'writing' ? ` ${Math.round(s.fraction * 100)}%` : '…'}{s.detail ? ` · ${s.detail}` : ''}</span>
          <div className="h-1 w-full bg-line"><div className="h-1 bg-warn" style={{ width: `${Math.round(s.fraction * 100)}%` }} /></div>
        </div>
      )}
      {s.phase === 'done' && (
        <span className={s.mismatch ? 'text-warn' : 'text-ok'}>
          {s.mismatch ? `Flashed, but the DevKit reports ver=${s.mismatch} (bundle ${bundled}).` : `Firmware ${bundled} flashed; link restarting.`}{' '}
          <button className="text-link" onClick={f.dismiss}>OK</button>
        </span>
      )}
      {s.phase === 'failed' && (
        <span className="text-bad">
          Flashing failed: {s.error}.{' '}
          <button className="text-link" onClick={f.dismiss}>OK</button>
        </span>
      )}
      {f.manifestError && offer.kind === 'none' && !info && <span className="text-muted">{f.manifestError}</span>}
    </div>
  )
}
