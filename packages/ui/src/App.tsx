import { useEffect, useRef, useState } from 'react'
import { Settings as Gear } from 'lucide-react'
import type { PortRef, Role } from '@d8tx/core'
import Stick from './Stick'
import DronePanel, { DroneView, useDrone } from './DronePanel'
import { MOCK, useController } from './useController'
import type { StartOptions } from './types'
import { Tip, TooltipProvider } from './components/ui/tooltip'
import Pairing from './PairingPanel'
import SettingsDialog from './SettingsDialog'
import { refOf, usePorts } from './usePorts'
import { findSaved, load, save, storage, type SavedPort } from './persist'
import { ESP_IN_USE, FC_IN_USE, espPwrMax, linkText, lostWhy } from './linkState'

/** Radio settings reach the worker this long after the last edit (each change restarts the link). */
const RADIO_DEBOUNCE_MS = 600
const store = storage(MOCK)

const CH = ['THR', 'AIL', 'ELE', 'RUD', 'AUX1', 'AUX2', 'ARM', 'AUX4']
const CH_COL = ['ch1', 'ch2', 'ch3', 'ch4', 'ch5', 'ch6', 'ch7', 'ch8']
const CH_VAR = CH_COL.map((c) => `var(--color-${c})`)

/** EdgeTX-style channel monitor: bars centred at 1500, readback tick, µs values. */
function Monitor({ cmd, rc, armed, compact }: { cmd: number[]; rc?: number[]; armed: boolean; compact?: boolean }) {
  const pos = (v: number) => Math.max(0, Math.min(100, (v - 1000) / 10))
  return (
    <div className="font-sans text-xs">
      <div className="grid grid-cols-[3rem_1fr_3rem_3rem] items-end gap-x-2 pb-1 text-[10px] font-semibold tracking-wide text-muted uppercase">
        <span>Ch</span>
        <span className="relative h-3"><span className="absolute left-0">1000</span><span className="absolute left-1/2 -translate-x-1/2">1500</span><span className="absolute right-0">2000</span></span>
        <span className="text-right">cmd</span>
        <span className="text-right">fc</span>
      </div>
      {CH.map((n, i) => {
        const p = pos(cmd[i])
        const isArm = i === 6
        const on = isArm && armed
        return (
          <div key={n} className={`grid grid-cols-[3rem_1fr_3rem_3rem] items-center gap-x-2 border-t border-line ${compact ? 'py-px' : 'py-[5px]'} ${isArm ? 'bg-paper-2' : ''}`}>
            <span className={`font-mono text-[11px] ${isArm ? 'font-bold text-fg' : 'text-muted'}`}>
              <i className="mr-1 inline-block h-2 w-2 align-baseline" style={{ background: CH_VAR[i] }} />{n}
            </span>
            <div className={`relative bg-paper ${compact ? 'h-3' : 'h-3.5'}`}>
              {[0, 25, 50, 75, 100].map((t) => (
                <span key={t} className={`absolute inset-y-0 w-px ${t === 50 ? 'bg-muted' : 'bg-line'}`} style={{ left: `${t}%` }} />
              ))}
              <div className="absolute top-[3px] bottom-[3px]" style={{ left: `${Math.min(p, 50)}%`, width: `${Math.abs(p - 50)}%`, background: on ? 'var(--color-bad)' : CH_VAR[i], opacity: on ? 1 : 0.85 }} />
              {rc && <div className="absolute -inset-y-px w-0.5 -translate-x-1/2 bg-fg" style={{ left: `${pos(rc[i] ?? 1000)}%` }} />}
            </div>
            <span className="text-right font-mono tabular-nums">{Math.round(cmd[i])}</span>
            <span className="text-right font-mono tabular-nums text-muted">{rc ? Math.round(rc[i] ?? 0) : '–'}</span>
          </div>
        )
      })}
      <div className={`${compact ? 'hidden' : 'flex'} justify-end gap-4 border-t border-line pt-1.5 text-[11px] text-muted`}>
        <span>bar: commanded</span><span><i className="mr-1 inline-block h-2.5 w-0.5 bg-fg align-middle" />Betaflight readback</span>
      </div>
    </div>
  )
}

function SignalBars({ level }: { level: number }) {
  return (
    <svg width="22" height="16" viewBox="0 0 22 16" className="block">
      {[0, 1, 2, 3, 4].map((i) => (
        <rect key={i} x={i * 4.5} y={14 - (i + 1) * 2.8} width="3" height={(i + 1) * 2.8 + 2} fill={i < level ? 'var(--color-fg)' : 'var(--color-line)'} />
      ))}
    </svg>
  )
}

function Cell({ k, tip, children, cls = '' }: { k: string; tip?: string; children: React.ReactNode; cls?: string }) {
  return (
    <div className={`flex min-w-0 flex-col justify-center border-r border-line px-3 py-1 ${cls}`}>
      <div className="font-sans text-[10px] font-semibold tracking-wider text-muted uppercase">
        {tip ? <Tip tip={tip}>{k}</Tip> : k}
      </div>
      <div className="flex items-center gap-2 font-mono text-sm leading-tight tabular-nums">{children}</div>
    </div>
  )
}

function Key({ k, wide }: { k: string; wide?: boolean }) {
  return (
    <kbd className={`inline-flex h-5 items-center justify-center border border-muted border-b-2 bg-paper px-1 font-mono text-[10px] text-fg ${wide ? 'min-w-9' : 'min-w-5'}`}>{k}</kbd>
  )
}

/** Physical toggle: lever flips up when armed; hold-fill shows the 1 s press. */
function ArmSwitch({ armed, progress, enabled, onDown, onUp, onDisarm }: {
  armed: boolean; progress: number; enabled: boolean; onDown: () => void; onUp: () => void; onDisarm: () => void
}) {
  const lever = armed ? 22 : 62 - progress * 40
  return (
    <div className="flex items-center gap-2">
      <svg
        width="34" height="49" viewBox="0 0 92 132"
        className={`touch-none select-none ${armed || enabled ? 'cursor-pointer' : 'cursor-not-allowed opacity-50'}`}
        onPointerDown={() => (armed ? onDisarm() : enabled && onDown())}
        onPointerUp={onUp}
        onPointerLeave={onUp}
      >
        <rect x="14" y="4" width="64" height="124" fill="var(--color-paper-2)" stroke="var(--color-fg)" />
        <text x="46" y="20" textAnchor="middle" fontSize="9" fontFamily="var(--font-sans)" fill="var(--color-bad)" fontWeight="700">ARM</text>
        <text x="46" y="123" textAnchor="middle" fontSize="9" fontFamily="var(--font-sans)" fill="var(--color-muted)">SAFE</text>
        <rect x="35" y="28" width="22" height="76" fill="var(--color-paper)" stroke="var(--color-muted)" />
        {[0, 1, 2, 3, 4, 5, 6].map((i) => <line key={i} x1="29" x2="35" y1={34 + i * 11} y2={34 + i * 11} stroke="var(--color-muted)" />)}
        <line x1="46" x2="46" y1="66" y2={lever + 22} stroke="var(--color-fg)" strokeWidth="8" strokeLinecap="butt" />
        <rect x="38" y={lever + 6} width="16" height="16" fill={armed ? 'var(--color-bad)' : progress > 0 ? 'var(--color-warn)' : 'var(--color-fg)'} />
      </svg>
      <div className="font-sans text-[11px] leading-tight text-muted">
        <div className="text-[10px] font-semibold tracking-wider uppercase">Arm switch · CH7</div>
        {armed ? <>click or <Key k="X" /> to disarm</> : enabled ? <>hold click or <Key k="R" /> 1 s</> : 'locked until link is ready'}
      </div>
    </div>
  )
}

function Row({ k, v, cls = '' }: { k: string; v: React.ReactNode; cls?: string }) {
  return (
    <div className="row">
      <span className="text-muted">{k}</span>
      <span className={cls}>{v}</span>
    </div>
  )
}

type Tab = 'sticks' | 'stats'
const tabFromHash = (): Tab => (location.hash === '#stats' ? 'stats' : 'sticks')

const REASONS: Record<string, string> = {
  ANGLE: 'drone not level',
  THROTTLE: 'throttle not low',
  RXFAILSAFE: 'no radio link yet',
  RXLOSS: 'no radio link yet',
  ARMSWITCH: 'arm switch was high: release and re-arm',
  FAILSAFE: 'failsafe active',
  RUNAWAYTAKEOFF: 'runaway-takeoff protection (props off or drone stuck)',
}

function AppInner({ createWorker }: { createWorker: () => Worker }) {
  const c = useController(createWorker)
  const [saved, setSaved] = useState(() => load(store))
  const [opts, setOpts] = useState<StartOptions>(() => ({ power: saved.power, fofs_hz: saved.fofs_hz, timeout_ms: saved.timeout_ms }))
  const [settings, setSettings] = useState(false)
  const [pairOpen, setPairOpen] = useState(false)
  const serial = usePorts()
  const { setRadio, connect } = c

  // radio settings: saved, and sent to the worker (first right away, before any connect; then debounced)
  const radioSent = useRef(false)
  useEffect(() => {
    save(store, opts)
    if (c.ws !== 'open') return
    if (!radioSent.current) {
      radioSent.current = true
      setRadio(opts)
      return
    }
    const t = setTimeout(() => setRadio(opts), RADIO_DEBOUNCE_MS)
    return () => clearTimeout(t)
  }, [opts, c.ws, setRadio])

  const { portsChanged } = c
  useEffect(() => {
    portsChanged()
  }, [serial.ports, portsChanged])

  const remember = (role: Role, p: SavedPort) => setSaved(save(store, { ports: { [role]: p } }))
  const onConnect = (role: Role, ref?: PortRef) => {
    if (ref) remember(role, { ...ref, auto: true })
    connect(role, ref)
  }
  const onDisconnect = (role: Role) => {
    const sp = saved.ports[role]
    if (sp) remember(role, { ...sp, auto: false })
    c.disconnect(role)
  }

  // on load: reconnect the ports used last time when they are still granted (getPorts needs no user gesture); open
  // Pairing only when no ESP32 could be reconnected
  const autoDone = useRef(false)
  useEffect(() => {
    if (autoDone.current || c.ws !== 'open' || !serial.loaded) return
    autoDone.current = true
    if (MOCK) return
    let esp = false
    for (const role of ['esp', 'fc'] as Role[]) {
      const sp = saved.ports[role]
      const g = sp?.auto ? findSaved(serial.ports, sp) : undefined
      if (!g) continue
      connect(role, refOf(g))
      if (role === 'esp') esp = true
    }
    // after this commit: the popover opens once the header has laid out
    if (!esp) queueMicrotask(() => setPairOpen(true))
  }, [c.ws, serial.loaded, serial.ports, saved.ports, connect])

  const [tab, setTabState] = useState<Tab>(tabFromHash)
  const setTab = (t: Tab) => {
    window.history.replaceState(null, '', t === 'sticks' ? location.pathname + location.search : '#' + t)
    setTabState(t)
  }
  const esp = c.tel?.esp
  const fc = c.tel?.fc
  const linked = !!esp?.link
  const failsafe = !!fc?.failsafe
  const fcArmed = !!fc?.armed
  const fcOn = !!fc?.connected
  const radio = c.tel?.radio
  const drone = useDrone(radio, fc)
  const [noFcReady, setNoFcReady] = useState(false)
  useEffect(() => {
    if (!linked) return
    const t = setTimeout(() => setNoFcReady(true), 3000)
    return () => {
      clearTimeout(t)
      setNoFcReady(false)
    }
  }, [linked])
  const ready = linked && (fcOn ? !failsafe : noFcReady)
  const reasons = (fc?.arming_disable ?? []).map((r) => REASONS[r.toUpperCase().replace(/_/g, '')] ?? r).join(', ')

  // banners only when there is something to say; link state itself is in the status strip
  let notice: { text: string; cls: string } | null = null
  if (esp?.wanted && esp.link_state === 'lost' && esp.in_use) {
    notice = { text: `${ESP_IN_USE}: close it there and this app takes the DevKit over (retrying every 2 s).`, cls: 'border-bad text-bad' }
  } else if (esp?.wanted && esp.link_state === 'lost') {
    const why = lostWhy(esp)
    notice = { text: `Radio link lost${why ? ` (${why})` : ''}, ${c.armed ? '' : 'disarmed, '}reconnecting… ${linkText(esp).text.replace(/^lost · /, '')}`, cls: 'border-bad text-bad' }
  }
  if (!c.armed && c.disarmNote) {
    const n = c.disarmNote.replace(/^(Betaflight (?:disarmed|did not arm)|Cannot arm yet): ?/, '')
    const head = c.disarmNote.slice(0, c.disarmNote.length - n.length).replace(/: ?$/, '')
    const plain = n
      .split(', ')
      .filter(Boolean)
      .map((r) => REASONS[r.toUpperCase().replace(/_/g, '')] ?? r)
      .join(', ')
    notice = { text: plain ? `${head}: ${plain}` : head, cls: 'border-warn text-warn' }
  }
  if (!c.armed && c.guardNote) notice = { text: c.guardNote, cls: 'border-bad text-bad font-bold' }
  if (fcOn && c.armed && !fcArmed && reasons) notice = { text: `Armed requested, not armed: ${reasons}`, cls: 'border-warn text-warn' }
  else if (c.armed && fcOn && failsafe) notice = { text: 'Failsafe: Betaflight lost the radio link', cls: 'border-bad text-bad font-bold' }

  const redArmed = c.armed && (fcOn ? fcArmed : radio?.armed === true)
  const armSent = c.armed && !redArmed
  const tabs: [Tab, string][] = [['sticks', 'Sticks'], ['stats', 'Stats for nerds']]
  const armEnabled = linked && ready && c.canArm
  const rssi = fc?.connected ? (fc.rssi ?? 0) : undefined
  const lt = linkText(esp)
  const sig = !linked ? 0 : rssi !== undefined ? Math.round(rssi / 20) : (esp?.sender_hz ?? 0) > 100 ? 4 : 2
  const dot = (cls: string) => <i className={`inline-block h-2 w-2 rounded-full ${cls}`} />

  return (
    <div className="mx-auto flex h-dvh max-w-[1360px] flex-col overflow-y-auto px-6 pt-2 pb-2">
      <header className="mb-1.5 flex shrink-0 items-baseline justify-between border-b border-fg pb-1">
        <h1 className="m-0 font-serif text-xl leading-tight font-bold">D8 TX controller{c.mock && <span className="ml-3 border border-warn bg-warn/20 px-2 py-0.5 align-middle font-sans text-xs font-bold tracking-wider text-warn">MOCK</span>}</h1>
        <nav className="flex items-baseline gap-5 font-sans text-sm">
          <Pairing
            open={pairOpen}
            onOpenChange={setPairOpen}
            mock={c.mock}
            supported={serial.supported}
            ports={serial.ports}
            saved={saved.ports}
            error={c.error}
            onAdd={serial.add}
            onConnect={onConnect}
            onConnectMock={c.connectMock}
            onDisconnect={onDisconnect}
            onFail={c.fail}
            esp={esp}
            fcConnected={fcOn}
            fcInUse={!!fc?.in_use}
            linked={linked}
            armed={c.armed}
            radio={radio}
            onBind={() => c.startBind(opts.fofs_hz)}
            onStopBind={c.stopBind}
            flash={{ release: c.releaseEsp, resume: c.resumeEsp, connect: (ref) => onConnect('esp', ref) }}
          />
          <Tip tip="Settings: radio power, FOFS, timeout, max throttle, identity" className="no-underline">
            <button aria-label="Settings" onClick={() => setSettings(true)} className="flex items-center self-center rounded-sm border border-line p-0.5 text-muted hover:border-muted hover:text-fg">
              <Gear size={15} strokeWidth={1.75} />
            </button>
          </Tip>
          {tabs.map(([t, n]) => (
            <button key={t} onClick={() => setTab(t)} className={tab === t ? 'border-b-2 border-fg font-bold' : 'text-link'}>{n}</button>
          ))}
        </nav>
      </header>

      {/* ground-station status strip */}
      <div className="mb-1.5 grid shrink-0 grid-cols-[1.2fr_.8fr_1fr_1fr_.9fr_.9fr_.8fr_1.4fr] border border-fg">
        <Cell k="Link" tip="The radio link runs whenever the ESP32 is connected and reconnects by itself. Up: stick frames per second sent from this computer to the ESP32 over USB (about 111 = one per 9 ms radio slot). Bars: drone RSSI from Betaflight when the drone USB is connected, else how steady the rate is.">
          <SignalBars level={sig} />
          <span className={lt.tone === 'bad' ? 'font-sans text-sm font-bold text-bad' : lt.tone === 'warn' ? 'font-sans text-sm text-warn' : lt.tone === 'muted' ? 'font-sans text-sm text-muted' : ''}>
            {linked ? `${(esp?.sender_hz ?? 0).toFixed(0)} pkt/s` : lt.text}
          </span>
        </Cell>
        <Cell k="RF power" tip="ESP32 transmit power as a raw PBUS code (not dBm; uncalibrated), used for the D8 packets to the drone (Settings). The cap is the firmware build's pwr_max.">{Math.min(linked && esp?.power != null ? esp.power : opts.power, espPwrMax(esp))}<span className="font-sans text-xs text-muted">/{espPwrMax(esp)}</span></Cell>
        <Cell k="ESP32" tip="ESP32 DevKit over USB serial. transmitting = a link is running and it is sending D8 packets; idle = connected, not sending; offline = not connected.">{dot(esp?.connected ? 'bg-ok' : 'bg-bad')}<span className="font-sans text-sm">{esp?.connected ? (esp.keyed ? 'transmitting' : 'idle') : esp?.in_use ? <span className="text-bad" title={`${ESP_IN_USE}. Retrying every 2 s.`}>in use by another app</span> : 'offline'}</span></Cell>
        <Cell k="Drone USB" tip="Optional USB connection to the drone flight controller (Betaflight MSP), used to read back attitude, motors and RC. rssi = the link quality Betaflight reports.">{dot(fcOn ? 'bg-ok' : fc?.in_use ? 'bg-bad' : 'bg-muted')}<span className="font-sans text-sm">{fcOn ? `MSP${rssi !== undefined ? ` · rssi ${rssi}` : ''}` : fc?.in_use ? <span className="text-bad" title={`${FC_IN_USE}. Retrying every 2 s.`}>in use by another app</span> : 'no readback'}</span></Cell>
        <Cell k="Failsafe" tip="Betaflight failsafe state, read over the drone USB. ACTIVE means the drone stopped receiving valid packets.">{dot(failsafe ? 'bg-warn' : 'bg-ok')}<span className={`font-sans text-sm ${failsafe ? 'font-bold text-warn' : ''}`}>{failsafe ? 'ACTIVE' : 'clear'}</span></Cell>
        <Cell k="Telemetry" tip="Share of telemetry requests the drone answered over the last 10 s, received over the radio. lost = no reply for over 1 s.">
          {radio?.enabled ? (<>
            {dot(radio.link ? 'bg-ok' : radio.powered ? 'bg-warn' : 'bg-muted')}
            <span className="font-sans text-sm">
              {radio.link ? <span className="font-mono">{radio.catch_rate != null ? `${Math.round(radio.catch_rate * 100)}%` : '–'}</span> : <span className="font-bold text-warn">lost</span>}
            </span>
          </>) : <span className="font-sans text-sm text-muted">off</span>}
        </Cell>
        <Cell k="Battery" tip="Drone battery voltage from radio telemetry (A1). absent = no flight battery connected.">
          <span className="font-sans text-sm">{!radio?.enabled ? '–' : radio.battery === 'absent' ? 'absent' : radio.vbat_v != null ? <span className="font-mono">{radio.vbat_v.toFixed(1)} V</span> : '–'}</span>
        </Cell>
        <div className={`flex items-center justify-between gap-3 px-3 py-1 ${redArmed ? 'bg-bad text-paper' : armSent ? 'bg-warn/20 text-warn' : ''}`}>
          <div>
            <div className={`font-sans text-[10px] font-semibold tracking-wider uppercase ${redArmed ? 'text-paper/80' : 'text-muted'}`}><Tip tip="Arm switch (hold R to arm when arming is allowed, X to disarm). ARMED = confirmed by Betaflight (drone USB) or radio telemetry; ARM SENT = arm requested, not yet confirmed.">Motors</Tip></div>
            <div className="font-sans text-base leading-tight font-bold tracking-wide">{redArmed ? 'ARMED' : armSent ? 'ARM SENT' : 'DISARMED'}</div>
            {armSent && <div className="font-sans text-[10px] leading-tight">{fcOn ? 'waiting for Betaflight' : 'radio does not confirm armed'}</div>}
          </div>
          <svg width="46" height="24" viewBox="0 0 46 24">
            <rect x=".5" y=".5" width="45" height="23" fill={redArmed ? 'var(--color-paper)' : 'var(--color-paper-2)'} stroke={redArmed ? 'var(--color-paper)' : 'var(--color-fg)'} />
            <rect x={c.armed ? 24 : 3} y="3" width="19" height="18" fill={redArmed ? 'var(--color-bad)' : armSent ? 'var(--color-warn)' : 'var(--color-muted)'} />
          </svg>
        </div>
      </div>

      {c.ws === 'closed' && (
        <p className="mb-2 border border-bad px-3 py-1.5 font-sans text-sm text-bad">The worker stopped. Reload the page.</p>
      )}
      {notice && <p className={`mb-2 border px-3 py-1.5 font-sans text-sm ${notice.cls}`}>{notice.text}</p>}
      {c.error && c.errorKind !== 'port_in_use' && <p className="mb-2 border border-bad px-3 py-1.5 font-sans text-sm text-bad">{c.errorKind === 'port_in_use' ? `Port in use: close other tabs or programs using it. (${c.error})` : c.errorKind === 'protocol' ? `Protocol mismatch, arming refused: ${c.error}` : c.error}</p>}

      {tab !== 'stats' && (
        <main className="flex min-h-0 flex-1 flex-col">
          <SettingsDialog
            open={settings} onOpenChange={setSettings}
            opts={opts} setOpts={setOpts} maxThr={c.maxThr} setMaxThr={c.setMaxThr}
            esp={esp} armed={c.armed} onNewId={c.newId}
          />

          <div className="grid min-h-0 flex-1 grid-cols-[1fr_auto_1fr] items-stretch gap-4 min-[1100px]:gap-8">
            <div className="flex min-h-0 items-stretch justify-end gap-3">
              <div className="flex flex-col items-center font-sans">
                <div className="mb-1 text-[11px] font-semibold tracking-wide text-muted uppercase">Thr</div>
                <div className="relative mt-[22px] mb-6 w-9 flex-1 border border-fg bg-paper">
                  {[0, 25, 50, 75, 100].map((t) => (
                    <span key={t} className="absolute right-full mr-1 font-mono text-[9px] leading-none text-muted" style={{ bottom: `calc(${t}% - 4px)` }}>{t}</span>
                  ))}
                  {Array.from({ length: 21 }, (_, i) => (
                    <span key={i} className={`absolute left-0 h-px bg-line ${i % 5 === 0 ? 'w-3 bg-muted' : 'w-1.5'}`} style={{ bottom: `${i * 5}%` }} />
                  ))}
                  <div className="absolute inset-x-0 bottom-0 bg-ch1/80" style={{ height: `${c.sticks.throttle * 100}%` }} />
                  <div className="absolute inset-x-[-4px] h-0.5 bg-fg" style={{ bottom: `${c.sticks.throttle * 100}%` }} />
                </div>
                <div className="mt-1 font-mono text-lg leading-none tabular-nums">{Math.round(c.sticks.throttle * 100)}<span className="text-xs text-muted">%</span></div>
                <div className="font-mono text-[10px] text-muted">{Math.round(c.channels[0])}µs</div>
              </div>
              <div className="min-h-0 min-w-0 flex-1 max-w-[400px]">
                <Stick label={c.armed ? 'Left · mode 2' : 'Left · mode 2 · preview'} xLabel="yaw" yLabel="thr" x={c.sticks.yaw} y={c.sticks.throttle * 2 - 1} yPct={c.sticks.throttle * 100}
                  xUs={c.channels[3]} yUs={c.channels[0]} accent="var(--color-ch1)"
                  onDrag={(x, y) => c.setMouseL({ x, y })} onRelease={() => c.setMouseL(null)} />
              </div>
            </div>

            <div className="flex w-[clamp(180px,36vh,360px)] flex-col items-center justify-center gap-1">
              <DroneView d={drone} fc={fc} radioArmed={radio?.armed} throttle={c.sticks.throttle} />
              <ArmSwitch armed={c.armed} progress={c.armProgress} enabled={armEnabled}
                onDown={c.armPress} onUp={c.armRelease} onDisarm={c.disarm} />
              <div className="font-mono text-[10px] text-muted">hold {Math.round(c.armProgress * 100)}%</div>
            </div>

            <div className="min-h-0 min-w-0 flex-1 max-w-[400px]">
              <Stick label="Right" xLabel="roll" yLabel="pitch" x={c.sticks.roll} y={c.sticks.pitch}
                xUs={c.channels[1]} yUs={c.channels[2]} accent="var(--color-ch2)"
                onDrag={(x, y) => c.setMouseR({ x, y })} onRelease={() => c.setMouseR(null)} />
            </div>
          </div>

          <div className="mt-1.5 grid shrink-0 gap-6 border-t border-line pt-1.5 md:grid-cols-[1.3fr_1.5fr_0.7fr]">
            <section>
              <Monitor cmd={c.channels} rc={fc?.connected ? fc.rc : undefined} armed={c.armed} compact />
            </section>
            <DronePanel d={drone} radio={radio} />
            <section>
              <h2 className="h !mb-1">Keys</h2>
              <dl className="m-0 flex flex-col gap-1 font-sans text-[11px] text-muted">
                <div className="flex items-center gap-1"><Key k="W" /><Key k="S" /> throttle <Key k="A" /><Key k="D" /> yaw</div>
                <div className="flex items-center gap-1"><Key k="↑" /><Key k="↓" /><Key k="←" /><Key k="→" /> pitch/roll</div>
                <div className="flex items-center gap-1"><Key k="R" /> hold 1 s arm <Key k="X" /> disarm</div>
                <div className="flex items-center gap-1"><Key k="drag" wide /> either gimbal</div>
              </dl>
            </section>
          </div>
        </main>
      )}

      {tab === 'stats' && (
        <main className="grid gap-8 md:grid-cols-2">
          <div className="flex flex-col gap-6">
            <section>
              <h2 className="h">Link</h2>
              <Row k="backend" v={c.mock ? 'mock' : 'worker ' + c.ws} cls={c.ws === 'open' ? '' : 'text-bad'} />
              <Row k="ESP32" v={esp?.connected ? 'connected' : 'not connected'} />
              <Row k="link" v={linked ? 'up' : 'down'} />
              <Row k="arm command" v={c.armed ? 'ARMED (ch7 high)' : 'off'} cls={c.armed ? 'font-bold text-bad' : ''} />
              <Row k="slots" v={esp?.slots ?? '–'} />
              <Row k="late max" v={esp?.late_max_us != null ? `${esp.late_max_us} µs` : '–'} cls={(esp?.late_max_us ?? 0) > 1000 ? 'text-warn' : ''} />
              <Row k="FOFS" v={esp?.fofs != null ? `${esp.fofs} Hz` : '–'} />
              <Row k="keyed" v={esp?.keyed ? 'yes' : 'no'} />
              <Row k="sender rate" v={esp?.sender_hz ? `${esp.sender_hz.toFixed(1)} Hz` : '–'} />
              <Row k="browser to backend" v={`${c.sendHz} Hz`} />
              <Row k="radio replies" v={radio?.enabled ? `${radio.replies ?? 0} / ${radio.triggers ?? 0}` : 'off'} />
              <Row k="radio armed" v={radio?.armed == null ? 'unknown' : radio.armed ? `yes (${radio.armed_source})` : 'no'} />
              <Row k="radio rssi / cfo" v={`${radio?.rssi_dbm ?? '–'} dBm / ${radio?.cfo_khz ?? '–'} kHz`} />
              <Row k="radio hub age" v={radio?.hub?.age_ms != null ? `${radio.hub.age_ms} ms` : '–'} />
              {radio?.hub && Object.entries(radio.hub).filter(([k]) => k !== 'raw' && k !== 'patched' && k !== 'age_ms').map(([k, v]) => <Row key={`hub-${k}`} k={`hub ${k}`} v={v == null ? '–' : JSON.stringify(v)} />)}
              {radio?.hub?.patched && Object.entries(radio.hub.patched).map(([k, v]) => <Row key={`hp-${k}`} k={`hub patched ${k}`} v={v == null ? '–' : JSON.stringify(v)} />)}
              {radio?.hub?.raw && Object.entries(radio.hub.raw).map(([k, v]) => <Row key={`hr-${k}`} k={`hub raw ${k}`} v={String(v)} />)}
              <Row k="fc attitude" v={fc?.attitude_deg ? JSON.stringify(fc.attitude_deg) : '–'} />
              <Row k="telemetry" v={`${c.telHz} Hz`} cls={c.telHz < 10 ? 'text-warn' : ''} />
            </section>
            <section>
              <h2 className="h">ESP info</h2>
              {esp?.info ? Object.entries(esp.info).map(([k, v]) => <Row key={k} k={k} v={String(v)} />) : <Row k="info" v="–" />}
              {esp?.error && <Row k="error" v={esp.error} cls="text-bad" />}
            </section>
          </div>
          <div className="flex flex-col gap-6">
            <section>
              <h2 className="h">Channels, µs (commanded / readback)</h2>
              <Monitor cmd={c.channels} rc={fc?.connected ? fc.rc : undefined} armed={c.armed} />
            </section>
            <section>
              <h2 className="h">Betaflight</h2>
              <Row k="connected" v={fc?.connected ? 'yes' : 'no'} />
              <Row k="RSSI" v={fc?.connected ? (fc.rssi ?? '–') : '–'} />
              <Row k="armed" v={fcArmed ? 'ARMED' : 'no'} cls={fcArmed ? 'font-bold text-bad' : ''} />
              <Row k="failsafe" v={failsafe ? 'ACTIVE' : 'no'} cls={failsafe ? 'font-bold text-warn' : ''} />
              <Row k="arming disabled by" v={fc?.arming_disable?.length ? fc.arming_disable.join(', ') : 'none'} />
              {fc?.error && <Row k="error" v={fc.error} cls="text-bad" />}
            </section>
          </div>
        </main>
      )}
    </div>
  )
}

export default function App({ createWorker }: { createWorker: () => Worker }) {
  return (
    <TooltipProvider>
      <AppInner createWorker={createWorker} />
    </TooltipProvider>
  )
}
