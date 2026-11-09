// Human text for the worker's link supervisor state (esp.link_state, see LinkPhase in @d8tx/core).
import type { EspStatus } from './types'

export const ESP_IN_USE = 'DevKit in use by another app or tab'
export const FC_IN_USE = 'Drone USB in use by another app or tab'

const WHY: Record<string, string> = {
  port_closed: 'DevKit port closed',
  timeout: 'DevKit stopped answering',
  link_end: 'firmware ended the link',
  port_in_use: ESP_IN_USE,
}

/** Why the last attempt failed, short. */
export function lostWhy(esp?: EspStatus): string {
  const r = esp?.retry_reason ?? esp?.lost_reason ?? ''
  return WHY[r] ?? r
}

/** Short state for the status strip: off, connecting…, linking…, up, lost · retry 2 s, paused. */
export function linkText(esp?: EspStatus): { text: string; tone: 'ok' | 'warn' | 'bad' | 'muted' } {
  const st = esp?.link_state ?? 'off'
  if (st === 'up') return { text: 'up', tone: 'ok' }
  if (st === 'connecting') return { text: 'connecting…', tone: 'warn' }
  if (st === 'linking') return { text: 'linking…', tone: 'warn' }
  if (st === 'paused') return { text: 'paused', tone: 'warn' }
  if (st === 'lost' && esp?.in_use) return { text: 'DevKit in use', tone: 'bad' }
  if (st === 'lost') {
    const s = esp?.retry_in_ms != null ? Math.ceil(esp.retry_in_ms / 1000) : null
    return { text: s ? `lost · retry ${s} s` : 'lost · retrying', tone: 'bad' }
  }
  return { text: 'off', tone: 'muted' }
}
