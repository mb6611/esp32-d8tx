export interface EspStatus {
  connected?: boolean
  error?: string
  info?: Record<string, string | number>
  link?: boolean
  keyed?: boolean
  fofs?: number
  slots?: number
  late_max_us?: number
  allow_arm?: boolean
  sender_hz?: number
}
export interface FcStatus {
  connected?: boolean
  error?: string
  rc?: number[]
  armed?: boolean
  failsafe?: boolean
  arming_disable?: string[]
  rssi?: number
}
export interface Telemetry {
  esp?: EspStatus
  fc?: FcStatus
}
export interface StartOptions {
  power: number
  fofs_hz: number
  timeout_ms: number
  allow_arm: boolean
}
export type WsState = 'connecting' | 'open' | 'closed'
