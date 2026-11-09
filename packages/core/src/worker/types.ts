// Message protocol between the UI thread and the worker (R10). State shapes match packages/ui/src/types.ts.
export type Role = 'esp' | 'fc'

/** A granted Web Serial port picked on the UI thread (index into getPorts(), plus its USB IDs). */
export interface PortRef {
  index: number
  usbVendorId?: number
  usbProductId?: number
}

export type ToWorker =
  /**
   * Open a granted port for the role, or the simulated one when mock. `port` names the port the user picked: its index
   * in the UI thread's navigator.serial.getPorts() order plus its USB IDs, which the worker checks against its own
   * list. Without `port`, the first granted port whose USB VID/PID fits the role.
   */
  | { type: 'connect'; role: Role; mock?: boolean; port?: PortRef }
  /** For the ESP: stops transmitting, closes the port and ends auto-reconnect. */
  | { type: 'disconnect'; role: Role }
  /**
   * Radio link settings. The link runs whenever the ESP32 is connected (like a normal radio); new settings restart it.
   * allow_arm (default true) lets ch7 through to the firmware (ARMOK); arming itself stays the UI's hold-R gate.
   */
  | ({ type: 'radio' } & RadioConfig)
  /** Deprecated alias of 'radio' (older scripts). */
  | ({ type: 'start' } & RadioConfig)
  /** Granted serial ports changed (a device was plugged in): retry a pending reconnect now. */
  | { type: 'ports_changed' }
  /**
   * One-click bind (like Betaflight Configurator's 'Bind receiver'): needs the DevKit and the drone's USB, disarmed.
   * Pauses the link, ESP bind packets on, MSP2_BETAFLIGHT_BIND to the FC, wait, bind off, then a short no-arm link
   * confirms through telemetry replies carrying this ESP's txid; the normal link restarts afterwards. Progress is
   * esp.bind_state in the state messages.
   */
  | { type: 'bind'; power?: number; fofs_hz?: number }
  /** Cancels a running bind flow. */
  | { type: 'bind_stop' }
  /** Generate and persist a new random identity (bound receivers must re-bind). */
  | { type: 'new_id' }
  | { type: 'sticks'; ch: number[] }
  /**
   * Firmware flashing (runs on the UI thread with esptool-js): stop the link, close the DevKit port and keep it closed
   * (supervisor paused, esp.flashing in state) until 'esp_resume'. Answered by 'esp_released'; refused while armed
   * or while a bind runs.
   */
  | { type: 'esp_release' }
  /** Flashing finished (or failed): reopen the DevKit port if it is wanted; the link auto-starts. */
  | { type: 'esp_resume' }

export interface RadioConfig {
  power: number
  fofs_hz: number
  timeout_ms: number
  allow_arm?: boolean
}

/**
 * esp.link_state: off (no ESP wanted), connecting (opening the port), linking (starting the link), up (transmitting),
 * lost (port or link lost, retrying after esp.retry_in_ms), paused (bind or new identity running).
 */
export type LinkPhase = 'off' | 'connecting' | 'linking' | 'up' | 'lost' | 'paused'

/** Bind flow progress (esp.bind_state / bind_txid / bind_reason / bind_via in state messages). */
export type BindPhase = 'idle' | 'binding' | 'confirming' | 'bound' | 'failed'

export type ErrorKind = 'port_in_use' | 'protocol' | 'no_port' | 'other'

export interface WorkerState {
  mock: boolean
  esp: Record<string, unknown>
  fc: Record<string, unknown>
  radio: Record<string, unknown>
}

export type FromWorker =
  | { type: 'ready'; serial: boolean }
  | ({ type: 'state' } & WorkerState)
  | { type: 'error'; role?: Role; kind: ErrorKind; message: string }
  /** Reply to 'esp_release': ok = the worker closed the DevKit port and holds off until 'esp_resume'. */
  | { type: 'esp_released'; ok: boolean; error?: string }
