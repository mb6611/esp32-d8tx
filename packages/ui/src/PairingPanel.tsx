// Pairing: a header entry that opens a panel with a line diagram of the setup (ESP32 DevKit, laptop, drone), each
// device's USB port picker with Connect/Disconnect under it, and the radio link between ESP32 and drone with the
// txid and the one-click Bind flow. Web Serial lists only granted ports, hence the "+ Add device…" entry. The radio link
// itself runs whenever the ESP32 is connected (the worker starts and restarts it); there is no start/stop here.
import { useEffect, useState } from 'react'
import { CircuitBoard, Drone, Laptop } from 'lucide-react'
import type { PortRef, Role } from '@d8tx/core'
import { Popover, PopoverContent, PopoverTrigger } from './components/ui/popover'
import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectSeparator, SelectTrigger, SelectValue } from './components/ui/select'
import { Tip } from './components/ui/tooltip'
import { cn } from './lib/utils'
import type { EspStatus, RadioStatus } from './types'
import { refOf, type GrantedPort } from './usePorts'
import { findSaved } from './persist'
import { ESP_IN_USE, FC_IN_USE, linkText, lostWhy } from './linkState'
import { FirmwareControl } from './flash/FirmwareControl'
import type { FlashApi } from './flash/useFlash'

const ADD = '__add'
const MOCK_PORT = '__mock'
const CONNECT_TIMEOUT_MS = 10000

interface PortsApi {
  mock: boolean
  supported: boolean
  ports: GrantedPort[]
  /** last used port per role (persisted): preselected in the dropdowns */
  saved?: Partial<Record<Role, PortRef>>
  error: string | null
  onAdd(role: Role): Promise<GrantedPort | null>
  onConnect(role: Role, port?: PortRef): void
  onConnectMock(roles?: Role[]): void
  onDisconnect(role: Role): void
  onFail(e: unknown): void
}

/** Port dropdown with the Connect/Disconnect button under it, for one role. */
function DeviceConnect({ api, role, title, tip, connected, lock, inUse }: {
  api: PortsApi; role: Role; title: React.ReactNode; tip: string; connected: boolean; lock?: string | null
  /** the port is held by another app or tab; the worker retries until it is free */
  inUse?: boolean
}) {
  const { mock } = api
  const [sel, setSel] = useState<GrantedPort['port'] | null>(null)
  const [waiting, setWaiting] = useState(false)
  // a finished attempt (connected, or an error came back) ends the waiting state; adjusting state while rendering
  // is React's documented alternative to an effect here
  if (waiting && (connected || api.error)) setWaiting(false)

  const mine = api.ports.filter((x) => x.role === role)
  const other = api.ports.filter((x) => x.role !== role)
  // the picked port while it is still granted and present, else the last used one, else the first port of this role
  const current = api.ports.find((x) => x.port === sel) ?? findSaved(api.ports, api.saved?.[role]) ?? mine[0] ?? null
  const pending = waiting && !connected && !api.error
  const unsupported = !mock && !api.supported

  const begin = (ref?: PortRef) => {
    setWaiting(true)
    setTimeout(() => setWaiting(false), CONNECT_TIMEOUT_MS)
    if (mock) api.onConnectMock([role])
    else api.onConnect(role, ref)
  }
  const add = async (): Promise<GrantedPort | null> => {
    try {
      const g = await api.onAdd(role)
      if (g) setSel(g.port)
      return g
    } catch (e) {
      api.onFail(e)
      return null
    }
  }
  const onButton = async () => {
    if (connected) {
      setWaiting(false)
      api.onDisconnect(role)
      return
    }
    if (mock) return begin()
    const target = current ?? (await add())
    if (target) begin(refOf(target))
  }
  const onPick = (v: string) => {
    if (v === ADD) void add()
    else if (v !== MOCK_PORT) setSel(api.ports.find((x) => String(x.index) === v)?.port ?? null)
  }
  const item = (x: GrantedPort) => <SelectItem key={x.index} value={String(x.index)} hint={x.ids}>{x.label}</SelectItem>
  const locked = connected && !!lock

  const button = (
    <button
      onClick={() => void onButton()}
      disabled={pending || locked || unsupported}
      className={cn(
        'h-8 w-full rounded-sm border font-sans text-sm font-semibold whitespace-nowrap',
        connected ? 'border-bad bg-paper text-bad hover:bg-bad/10' : 'border-ok bg-ok text-paper hover:bg-ok/90',
      )}
    >
      {pending ? 'Connecting…' : connected ? 'Disconnect' : 'Connect'}
    </button>
  )

  return (
    <div className="flex w-56 flex-col gap-1.5">
      <div className="text-[10px] font-semibold tracking-wider text-muted uppercase"><Tip tip={tip}>{title}</Tip></div>
      <Select value={mock ? MOCK_PORT : current ? String(current.index) : ''} onValueChange={onPick} disabled={connected || pending || unsupported}>
        <SelectTrigger aria-label={`${role === 'esp' ? 'ESP32' : 'Drone'} port`} className="h-8 w-full">
          <SelectValue placeholder={api.supported ? 'No device yet: add one' : 'Web Serial unavailable'} />
        </SelectTrigger>
        <SelectContent>
          {mock ? (
            <SelectItem value={MOCK_PORT} hint="mock">{role === 'esp' ? 'Simulated DevKit' : 'Simulated drone'}</SelectItem>
          ) : (<>
            {mine.length > 0 && (
              <SelectGroup>
                <SelectLabel>{role === 'esp' ? 'ESP32 DevKits' : 'Flight controllers'}</SelectLabel>
                {mine.map(item)}
              </SelectGroup>
            )}
            {other.length > 0 && (
              <SelectGroup>
                <SelectLabel>Other granted ports</SelectLabel>
                {other.map(item)}
              </SelectGroup>
            )}
            {api.ports.length > 0 && <SelectSeparator />}
            <SelectItem value={ADD} className="text-link">+ Add device…</SelectItem>
          </>)}
        </SelectContent>
      </Select>
      {locked ? <Tip tip={lock} className="cursor-not-allowed no-underline">{button}</Tip> : button}
      {inUse && (
        <span role="status" className="text-[11px] leading-snug text-bad">
          {role === 'esp' ? ESP_IN_USE : FC_IN_USE}. Close it there; retrying every 2 s.
        </span>
      )}
    </div>
  )
}

/** Mounted only while a bind runs, so the timer restarts on every bind. */
function Elapsed() {
  const [s, setS] = useState(0)
  useEffect(() => {
    const id = setInterval(() => setS((v) => v + 1), 1000)
    return () => clearInterval(id)
  }, [])
  return <>{s} s</>
}

const BIND_STEP: Record<string, string> = {
  binding: 'Binding: drone in bind mode, sending bind packets…',
  confirming: 'Checking: short link (arming off), waiting for a reply…',
}

/** The one-click Bind flow, drawn as the label on the radio link. */
function LinkLabel({ esp, fcConnected, armed, onBind, onStop }: {
  esp?: EspStatus; fcConnected: boolean; armed: boolean; onBind: () => void; onStop: () => void
}) {
  const connected = !!esp?.connected
  const phase = esp?.bind_state ?? 'idle'
  const running = phase === 'binding' || phase === 'confirming'
  const idle = connected && !armed && !running && !esp?.binding
  const why = !connected ? 'Connect the ESP32 first.'
    : !fcConnected ? "Connect the drone's USB first: Bind tells Betaflight to enter bind mode through its USB port, like Betaflight Configurator's Bind receiver button."
      : armed ? 'Disarm first.'
        : null
  const bindTip = 'Props off, drone on USB. Pauses the radio link, tells Betaflight to bind over USB (MSP, as Configurator does), sends bind packets for about 6 s at the FOFS from Settings, then runs a short link with arming off and waits for a telemetry reply carrying this txid; the link restarts afterwards. About 10 s.'
  return (
    <div className="flex flex-col items-center gap-1 bg-paper px-3 text-center text-xs">
      <div className="flex items-center gap-2.5">
        {running
          ? <button className="btn !py-0 text-xs" onClick={onStop}>Cancel</button>
          : why
            ? <Tip tip={why} className="cursor-not-allowed no-underline"><button className="btn !py-0 text-xs" disabled>Bind</button></Tip>
            : <Tip tip={bindTip} className="no-underline"><button className="btn !py-0 text-xs" onClick={onBind} disabled={!idle}>Bind</button></Tip>}
      </div>
      {running && <span className="max-w-64 text-warn">{BIND_STEP[phase]} <Elapsed /></span>}
      {phase === 'bound' && <span className="max-w-64 text-ok">Bound to {esp?.bind_txid ?? esp?.txid}{esp?.bind_via === 'fc' ? ' (confirmed over USB, no telemetry reply)' : ': the drone replied'}.</span>}
      {phase === 'failed' && <span className="max-w-64 text-bad">Bind failed: {esp?.bind_reason ?? 'unknown'}.</span>}
    </div>
  )
}

const OK = 'var(--color-ok)'
const WARN = 'var(--color-warn)'
const MUTED = 'var(--color-muted)'
const LINE = 'var(--color-line)'
const FG = 'var(--color-fg)'

/** ESP32 DevKit, laptop and drone (lucide icons) joined by USB cables and the radio link. viewBox 720 × 230. */
function Diagram({ esp, fc, radio }: { esp: boolean; fc: boolean; radio: 'up' | 'starting' | 'off' }) {
  const icon = (on: boolean) => ({ absoluteStrokeWidth: true, strokeWidth: 1.5, color: on ? FG : MUTED, opacity: on ? 1 : 0.45 })
  const cable = (on: boolean) => ({ stroke: on ? OK : MUTED, strokeWidth: on ? 2 : 1.5, strokeDasharray: on ? undefined : '5 4', fill: 'none' })
  const rc = radio === 'up' ? OK : radio === 'starting' ? WARN : LINE
  const arc = 'M 130 122 C 220 20, 520 20, 610 114'
  return (
    <svg viewBox="0 0 720 230" className="block w-full" aria-hidden>
      <style>{'@keyframes d8flow{to{stroke-dashoffset:-20}} .d8flow{animation:d8flow .8s linear infinite}'}</style>
      {/* radio link: ESP32 to drone */}
      <path d={arc} fill="none" stroke={rc} strokeWidth={radio === 'off' ? 1.5 : 2}
        strokeDasharray={radio === 'up' ? '8 12' : '4 5'} className={radio === 'off' ? '' : 'd8flow'} />
      {radio !== 'off' && <path d={arc} fill="none" stroke={rc} strokeWidth="1" opacity="0.35" />}
      {/* USB cables to the laptop */}
      <path d="M 158 150 C 232 150, 250 177, 320 177" {...cable(esp)} />
      <path d="M 578 146 C 508 146, 470 177, 400 177" {...cable(fc)} />
      <CircuitBoard x={94} y={114} width={72} height={72} {...icon(esp)} />
      <Laptop x={312} y={98} width={96} height={96} {...icon(true)} />
      <Drone x={570} y={106} width={80} height={80} {...icon(fc)} />
    </svg>
  )
}

export interface PairingProps extends PortsApi {
  /** Controlled: the app opens it on load when no ESP32 could be reconnected. */
  open: boolean
  onOpenChange(v: boolean): void
  esp?: EspStatus
  fcConnected: boolean
  /** the drone USB port is held by another app or tab */
  fcInUse?: boolean
  linked: boolean
  armed: boolean
  radio?: RadioStatus
  onBind(): void
  onStopBind(): void
  /** in-app firmware flashing of the ESP32 (worker port hand-off); absent = not offered */
  flash?: FlashApi
}

export default function Pairing(p: PairingProps) {
  const { open, onOpenChange: setOpen } = p
  const espOn = !!p.esp?.connected
  // while the ESP32 is wanted (connected or reconnecting) its button disconnects
  const espWanted = espOn || !!p.esp?.wanted
  const radioState = !p.linked ? (espWanted ? 'starting' : 'off') : p.radio?.link ? 'up' : 'starting'
  const lt = linkText(p.esp)
  const dot = (on: boolean, optional?: boolean) => (
    <i className={cn('inline-block h-2 w-2 rounded-full', on ? 'bg-ok' : optional ? 'border border-muted' : 'bg-bad')} />
  )
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button className={cn('flex items-center gap-2 rounded-sm border px-2 py-px', open ? 'border-fg bg-paper-2' : 'border-line hover:border-muted')}>
          Pairing
          <span className="flex items-center gap-1" aria-label={`ESP32 ${espOn ? 'connected' : 'not connected'}, drone USB ${p.fcConnected ? 'connected' : 'not connected'}`}>
            {dot(espOn)}{dot(p.fcConnected, true)}
          </span>
          <svg width="9" height="6" viewBox="0 0 10 6" aria-hidden className={cn('text-muted transition-transform', open && 'rotate-180')}><path d="M1 1l4 4 4-4" fill="none" stroke="currentColor" strokeWidth="1.5" /></svg>
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        className="w-[736px] p-4 pt-3"
        // the browser's port chooser takes focus; keep the panel open through it (Esc or a click outside still close it)
        onFocusOutside={(e) => e.preventDefault()}
        // focus the panel itself on open: the first focusable is a tooltip label, whose tip would cover the diagram
        onOpenAutoFocus={(e) => { e.preventDefault(); (e.currentTarget as HTMLElement | null)?.focus() }}
      >
        <div className="mb-1 flex items-baseline justify-between gap-4 border-b border-fg pb-1.5">
          <h2 className="m-0 font-serif text-lg leading-tight font-bold">Pairing</h2>
          {p.mock && <span className="text-xs text-warn">Simulated link and drone, no real port is opened.</span>}
        </div>
        <div className="relative">
          <Diagram esp={espOn} fc={p.fcConnected} radio={radioState} />
          <div className="absolute top-[10%] left-1/2 -translate-x-1/2">
            <LinkLabel esp={p.esp} fcConnected={p.fcConnected} armed={p.armed} onBind={p.onBind} onStop={p.onStopBind} />
          </div>
          <div className="absolute top-[86%] left-1/2 -translate-x-1/2 font-mono text-[10px] whitespace-nowrap text-muted">
            {p.linked
              ? (p.radio?.link ? <span className="text-ok">link up · telemetry</span> : <span className="text-warn">link up · no telemetry yet</span>)
              : p.esp?.in_use
                ? <span className="text-bad">link off: {ESP_IN_USE}</span>
              : p.esp?.link_state === 'lost'
                ? <span className="text-bad">link {lt.text}{lostWhy(p.esp) ? ` (${lostWhy(p.esp)})` : ''}</span>
                : espWanted ? <span className="text-warn">link {lt.text}</span> : 'radio link off: connect the ESP32'}
          </div>
        </div>
        <div className="flex items-start justify-between">
          <div className="flex flex-col gap-1">
            <DeviceConnect api={p} role="esp" connected={espWanted} lock={p.armed ? 'Disarm first: disconnecting the ESP32 stops the radio link.' : null}
              title={<>ESP32 DevKit · required</>}
              tip="The ESP32 DevKit over USB serial: it transmits the D8 packets to the drone." inUse={!!p.esp?.in_use} />
            <FirmwareControl api={p.flash} esp={p.esp} ports={p.ports} saved={p.saved?.esp} armed={p.armed} enabled={!p.mock && p.supported} />
          </div>
          <DeviceConnect api={p} role="fc" connected={p.fcConnected || !!p.fcInUse} inUse={!!p.fcInUse}
            title={<>Drone USB · optional</>}
            tip="The drone's flight controller over USB (Betaflight MSP). Optional: needed for Bind, and for reading back attitude, motors, RC and failsafe." />
        </div>
        {!p.mock && (
          <p className="m-0 mt-3 border-t border-line pt-2 text-[11px] leading-snug text-muted">
            The browser lists only ports this page may use: pick <span className="text-link">+ Add device…</span> to grant one.
          </p>
        )}
      </PopoverContent>
    </Popover>
  )
}
