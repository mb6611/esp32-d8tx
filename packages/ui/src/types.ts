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
  sender_max_gap_ms?: number
  lost_reason?: string | null
  protocol_ok?: boolean
  guard?: 'ui-silent'
  guard_at?: number
}
export interface FcStatus {
  connected?: boolean
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
  allow_arm: boolean
}
export type WsState = 'connecting' | 'open' | 'closed'
