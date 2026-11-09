export interface EspStatus {
  connected?: boolean
  /** the UI asked for the ESP32 (the worker keeps reconnecting until a disconnect) */
  wanted?: boolean
  link_state?: 'off' | 'connecting' | 'linking' | 'up' | 'lost' | 'paused'
  retry_in_ms?: number
  retry_reason?: string
  attempt?: number
  /** power of the running link */
  power?: number
  error?: string
  info?: Record<string, string | number>
  link?: boolean
  binding?: boolean
  /** one-click bind flow progress (worker Host.bind) */
  bind_state?: 'idle' | 'binding' | 'confirming' | 'bound' | 'failed'
  bind_txid?: string
  bind_reason?: string
  bind_via?: 'telemetry' | 'fc'
  txid?: string
  keyed?: boolean
  fofs?: number
  slots?: number
  late_max_us?: number
  allow_arm?: boolean
  sender_hz?: number
  sender_max_gap_ms?: number
  lost_reason?: string | null
  /** the DevKit port is held by another app or tab; the worker retries every 2 s */
  in_use?: boolean
  protocol_ok?: boolean
  guard?: 'ui-silent'
  guard_at?: number
}
export interface FcStatus {
  connected?: boolean
  /** the UI asked for the drone USB (the worker retries while the port is in use) */
  wanted?: boolean
  /** the drone USB port is held by another app or tab; the worker retries every 2 s */
  in_use?: boolean
  error?: string
  rc?: number[]
  armed?: boolean
  failsafe?: boolean
  arming_disable?: string[]
  rssi?: number
  attitude_deg?: number[] | null
  motors?: number[] | null
}
export interface HubPatched {
  gyro_dps?: number[] | null
  attitude_deg?: (number | null)[] | null
  flight_mode?: string | null
  armed?: boolean | null
  failsafe?: boolean | null
  [k: string]: unknown
}
export interface RadioHub {
  acc_mg?: (number | null)[] | null
  heading_deg?: number | null
  rpm?: number | null
  vfas_v?: number | null
  current_a?: number | null
  fuel?: number | null
  temp1?: number | null
  temp2?: number | null
  patched?: HubPatched
  raw?: Record<string, number>
  age_ms?: number | null
}
export interface RadioFast {
  attitude_deg?: number[] | null
  gyro_dps?: number[] | null
  age_ms?: number | null
  rate_hz?: number | null
  seq?: number
}
export interface RadioStatus {
  fast?: RadioFast | null
  hub?: RadioHub
  cfo_khz?: number | null
  enabled?: boolean
  powered?: boolean
  link?: boolean
  age_ms?: number | null
  catch_rate?: number | null
  triggers?: number
  replies?: number
  rssi?: number | null
  rssi_dbm?: number | null
  vbat_v?: number | null
  battery?: 'absent' | 'present' | null
  armed?: boolean | null
  armed_source?: 'patched' | 'rpm' | null
}
export interface Telemetry {
  esp?: EspStatus
  fc?: FcStatus
  radio?: RadioStatus
}
export interface StartOptions {
  power: number
  fofs_hz: number
  timeout_ms: number
}
export type WsState = 'connecting' | 'open' | 'closed'
