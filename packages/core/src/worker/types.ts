// Message protocol between the UI thread and the worker (R10). State shapes match packages/ui/src/types.ts.
export type Role = 'esp' | 'fc'

export type ToWorker =
  /** Open the granted port for the role (matched by USB VID/PID), or the simulated one when mock. */
  | { type: 'connect'; role: Role; mock?: boolean }
  | { type: 'disconnect'; role: Role }
  | { type: 'start'; power: number; fofs_hz: number; timeout_ms: number; allow_arm: boolean }
  | { type: 'stop' }
  /** Transmit bind packets (idle only); ends on bind_stop, the firmware's 30 s timeout or a loss. */
  | { type: 'bind'; power?: number; fofs_hz?: number }
  | { type: 'bind_stop' }
  /** Generate and persist a new random identity (bound receivers must re-bind). */
  | { type: 'new_id' }
  | { type: 'sticks'; ch: number[] }

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
