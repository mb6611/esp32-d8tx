import { useEffect, useState } from 'react'
import Stick from './Stick'
import { MOCK, useController } from './useController'
import type { StartOptions } from './types'

const CH_NAMES = ['Throttle', 'Roll', 'Pitch', 'Yaw', 'Aux1', 'Aux2', 'Arm', 'Aux4']

function Bars({ cmd, rc }: { cmd: number[]; rc?: number[] }) {
  const pct = (v: number) => Math.max(0, Math.min(100, (v - 1000) / 10))
  return (
    <div className="flex flex-col gap-1.5 font-sans text-xs">
      {CH_NAMES.map((n, i) => (
        <div key={n} className="flex items-center gap-2">
          <span className="w-14 text-muted">{n}</span>
          <div className="relative h-3 flex-1 border border-line bg-paper-2">
            <div className="absolute inset-y-0 left-0 bg-ch1/70" style={{ width: `${pct(cmd[i])}%` }} />
            {rc && <div className="absolute -inset-y-px w-0.5 bg-fg" style={{ left: `${pct(rc[i] ?? 1000)}%` }} />}
          </div>
          <span className="w-10 text-right font-mono tabular-nums">{cmd[i]}</span>
          <span className="w-10 text-right font-mono tabular-nums text-muted">{rc ? Math.round(rc[i] ?? 0) : '–'}</span>
        </div>
      ))}
      <div className="flex justify-end gap-4 pt-1 text-muted">
        <span>blue bar: commanded</span>
        <span>black tick: Betaflight readback</span>
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

type Tab = 'fly' | 'sticks' | 'stats'
const tabFromHash = (): Tab => (location.hash === '#sticks' ? 'sticks' : location.hash === '#stats' ? 'stats' : 'fly')

const REASONS: Record<string, string> = {
  ANGLE: 'drone not level',
  THROTTLE: 'throttle not low',
  RXFAILSAFE: 'no radio link yet',
  RXLOSS: 'no radio link yet',
  ARMSWITCH: 'arm switch was high: release and re-arm',
  FAILSAFE: 'failsafe active',
  RUNAWAYTAKEOFF: 'runaway-takeoff protection (props off or drone stuck)',
}

export default function App() {
  const c = useController()
  const [opts, setOpts] = useState<StartOptions>({ power: 127, fofs_hz: -63000, timeout_ms: 300, allow_arm: true })
  const [tab, setTabState] = useState<Tab>(tabFromHash)
  const setTab = (t: Tab) => {
    window.history.replaceState(null, '', t === 'fly' ? location.pathname + location.search : '#' + t)
    setTabState(t)
    if (t !== 'stats') c.setMode(t)
  }
  useEffect(() => {
    if (tab !== 'stats') c.setMode(tab)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const fly = c.mode === 'fly'
  const esp = c.tel?.esp
  const fc = c.tel?.fc
  const linked = !!esp?.link
  const failsafe = !!fc?.failsafe
  const fcArmed = !!fc?.armed
  const reachable = (c.ws === 'open' || MOCK) && !!esp?.connected
  const fcOn = !!fc?.connected
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
  const num = (k: keyof StartOptions) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setOpts({ ...opts, [k]: Number(e.target.value) })

  let banner: { text: string; cls: string }
  if (!reachable) banner = { text: 'Not connected', cls: 'border-line text-muted' }
  else if (c.armed) banner = { text: 'ARMED', cls: 'border-bad bg-bad text-paper font-bold' }
  else if (!linked) banner = failsafe ? { text: 'Failsafe, start the link again', cls: 'border-warn text-warn' } : { text: 'Link off', cls: 'border-line text-muted' }
  else if (!fcOn && !noFcReady) banner = { text: 'Starting link…', cls: 'border-warn text-warn' }
  else if (fcOn && failsafe) banner = { text: 'Failsafe, waiting for Betaflight to clear it', cls: 'border-warn text-warn' }
  else if (!fcOn) banner = { text: 'Ready (no Betaflight readback), hold R to arm', cls: 'border-ok text-ok' }
  else banner = { text: 'Ready, hold R to arm', cls: 'border-ok text-ok' }

  if (!c.armed && c.disarmNote) {
    const n = c.disarmNote.replace(/^(Betaflight (?:disarmed|did not arm)|Cannot arm yet): ?/, '')
    const head = c.disarmNote.slice(0, c.disarmNote.length - n.length).replace(/: ?$/, '')
    const plain = n
      .split(', ')
      .filter(Boolean)
      .map((r) => REASONS[r.toUpperCase().replace(/_/g, '')] ?? r)
      .join(', ')
    banner = { text: plain ? `${head}: ${plain}` : head, cls: 'border-warn text-warn' }
  }
  if (fcOn && c.armed && !fcArmed && reasons) banner = { text: `Armed requested, not armed: ${reasons}`, cls: 'border-warn text-warn' }

  const thrLabel = c.armed ? 'throttle' : 'throttle (preview, not sent)'

  const primary = !linked ? (
    <button className="btn min-w-56 py-2.5 text-base" onClick={() => c.startLink(opts)} disabled={!reachable}>Start link</button>
  ) : c.armed ? (
    <button className="btn min-w-56 border-bad py-2.5 text-base font-bold text-bad" onClick={c.disarm}>Disarm (X)</button>
  ) : (
    <button
      disabled={!ready || !c.canArm}
      onPointerDown={c.armPress}
      onPointerUp={c.armRelease}
      onPointerLeave={c.armRelease}
      className="btn relative min-w-56 overflow-hidden py-2.5 text-base"
    >
      <span className="absolute inset-y-0 left-0 bg-bad/20" style={{ width: `${c.armProgress * 100}%` }} />
      <span className="relative">{ready ? 'Hold to arm (R)' : 'Waiting for failsafe to clear'}</span>
    </button>
  )

  const tabs: [Tab, string][] = [['fly', 'Fly'], ['sticks', 'Sticks'], ['stats', 'Stats for nerds']]

  return (
    <div className="mx-auto max-w-[900px] px-5 pt-10 pb-16">
      <header className="mb-4">
        <h1 className="font-serif text-[2.1rem] leading-tight font-bold">D8 TX controller</h1>
        <nav className="mt-3 flex gap-5 border-t border-line pt-2 font-sans text-sm">
          {tabs.map(([t, n]) => (
            <button key={t} onClick={() => setTab(t)} className={tab === t ? 'border-b-2 border-fg font-bold' : 'text-link'}>{n}</button>
          ))}
        </nav>
      </header>

      {c.ws !== 'open' && !MOCK && (
        <p className="mb-4 border border-line px-3 py-2 font-sans text-sm text-muted">Backend not reachable, retrying every second.</p>
      )}
      {c.error && <p className="mb-4 border border-bad px-3 py-2 font-sans text-sm text-bad">{c.error}</p>}

      {tab !== 'stats' && (
        <main className="flex flex-col items-center gap-6">
          <div className={`w-full border px-3 py-2 text-center font-sans text-base ${banner.cls}`}>{banner.text}</div>

          <div className="flex flex-wrap items-center justify-center gap-3">
            {primary}
            {linked && <button className="btn text-muted" onClick={c.stopLink}>Stop link</button>}
          </div>

          {fly && (
            <div className="text-center font-sans">
              <div className="text-xs font-semibold text-muted">Hover throttle, µs ( [ down, ] up )</div>
              <div className="font-mono text-6xl tabular-nums">{c.hover}</div>
            </div>
          )}

          <div
            className="flex flex-wrap justify-center gap-6"
            onClick={() => {
              if (fly && c.mouseYawOn && !document.pointerLockElement) void (document.body.requestPointerLock() as unknown)
            }}
          >
            <Stick label="Left, mode 2" xLabel="yaw" yLabel={thrLabel} x={c.sticks.yaw} y={c.sticks.throttle * 2 - 1}
              onDrag={(x, y) => !fly && c.setMouseL({ x, y })} onRelease={() => c.setMouseL(null)} />
            <Stick label="Right" xLabel="roll" yLabel="pitch" x={c.sticks.roll} y={c.sticks.pitch}
              onDrag={(x, y) => !fly && c.setMouseR({ x, y })} onRelease={() => c.setMouseR(null)} />
          </div>

          <p className="m-0 text-center font-sans text-xs leading-snug text-muted">
            {fly
              ? 'W/S pitch · A/D roll · Q/E yaw · Space climb · Shift descend · [ ] hover · hold R arm · X disarm'
              : 'W/S throttle · A/D yaw · arrows pitch/roll · Shift fine · hold R arm · X disarm · or drag the sticks'}
          </p>

          <details className="w-full font-sans text-sm">
            <summary className="cursor-pointer text-link">Settings</summary>
            <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3">
              <label>Power (0–127)<input type="number" min={0} max={127} value={opts.power} onChange={num('power')} disabled={linked} /></label>
              <label>FOFS, Hz<input type="number" min={-200000} max={200000} step={1000} value={opts.fofs_hz} onChange={num('fofs_hz')} disabled={linked} /></label>
              <label>Timeout, ms<input type="number" min={50} max={2000} step={50} value={opts.timeout_ms} onChange={num('timeout_ms')} disabled={linked} /></label>
              <label>Max tilt, %<input type="number" min={10} max={100} value={c.tilt} onChange={(e) => c.setTilt(Number(e.target.value))} /></label>
              <label>Climb, +µs<input type="number" min={0} max={500} step={10} value={c.climb} onChange={(e) => c.setClimb(Number(e.target.value))} /></label>
              <label>Descend, −µs<input type="number" min={0} max={500} step={10} value={c.descend} onChange={(e) => c.setDescend(Number(e.target.value))} /></label>
              <label className="flex items-center gap-2">
                <input type="checkbox" className="!w-auto" checked={c.mouseYawOn} onChange={(e) => c.setMouseYawOn(e.target.checked)} />
                Mouse X yaw (click sticks to capture, Esc releases)
              </label>
            </div>
          </details>
        </main>
      )}

      {tab === 'stats' && (
        <main className="grid gap-8 md:grid-cols-2">
          <div className="flex flex-col gap-6">
            <section>
              <h2 className="h">Link</h2>
              <Row k="backend" v={MOCK ? 'mock' : c.ws} cls={c.ws === 'open' ? '' : 'text-bad'} />
              <Row k="ESP32" v={esp?.connected ? 'connected' : 'not connected'} />
              <Row k="link" v={linked ? 'up' : 'down'} />
              <Row k="arm command" v={c.armed ? 'ARMED (ch7 high)' : 'off'} cls={c.armed ? 'font-bold text-bad' : ''} />
              <Row k="slots" v={esp?.slots ?? '–'} />
              <Row k="late max" v={esp?.late_max_us != null ? `${esp.late_max_us} µs` : '–'} cls={(esp?.late_max_us ?? 0) > 1000 ? 'text-warn' : ''} />
              <Row k="FOFS" v={esp?.fofs != null ? `${esp.fofs} Hz` : '–'} />
              <Row k="keyed" v={esp?.keyed ? 'yes' : 'no'} />
              <Row k="sender rate" v={esp?.sender_hz ? `${esp.sender_hz.toFixed(1)} Hz` : '–'} />
              <Row k="browser to backend" v={`${c.sendHz} Hz`} />
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
              <Bars cmd={c.channels} rc={fc?.connected ? fc.rc : undefined} />
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
