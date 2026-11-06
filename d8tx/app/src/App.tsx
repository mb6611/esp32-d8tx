import { useState } from 'react'
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

export default function App() {
  const c = useController()
  const [opts, setOpts] = useState<StartOptions>({ power: 127, fofs_hz: -63000, timeout_ms: 300, allow_arm: false })

  const fly = c.mode === 'fly'
  const esp = c.tel?.esp
  const fc = c.tel?.fc
  const linked = !!esp?.link
  const failsafe = !!fc?.failsafe
  const fcArmed = !!fc?.armed
  const num = (k: keyof StartOptions) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setOpts({ ...opts, [k]: Number(e.target.value) })

  return (
    <div className="mx-auto max-w-[1400px] px-5 pt-10 pb-16">
      <header className="mb-5">
        <h1 className="font-serif text-[2.1rem] leading-tight font-bold">D8 TX controller</h1>
        <dl className="stats mt-3">
          <div><dt>Backend</dt><dd className={c.ws === 'open' ? '' : 'text-bad'}>{MOCK ? 'mock' : c.ws}</dd></div>
          <div><dt>ESP32</dt><dd>{esp?.connected ? 'connected' : 'not connected'}</dd></div>
          <div><dt>Link</dt><dd>{linked ? 'up' : 'down'}</dd></div>
          <div><dt>Flight controller</dt><dd className={fcArmed ? 'font-bold text-bad' : ''}>{fc?.connected ? (fcArmed ? 'ARMED' : 'disarmed') : 'not connected'}</dd></div>
          <div><dt>Arm command</dt><dd className={c.armed ? 'font-bold text-bad' : ''}>{c.armed ? 'ARMED (ch7 high)' : 'off'}</dd></div>
          <div><dt>Failsafe</dt><dd className={failsafe ? 'font-bold text-warn' : ''}>{failsafe ? 'ACTIVE' : 'no'}</dd></div>
        </dl>
      </header>

      {failsafe && (
        <p className="mb-4 border border-warn px-3 py-2 font-sans text-sm text-warn">
          <b>Failsafe.</b> Betaflight lost the link and has disarmed. Start the link again to recover.
        </p>
      )}
      {c.ws !== 'open' && !MOCK && (
        <p className="mb-4 border border-line px-3 py-2 font-sans text-sm text-muted">Backend not reachable, retrying every second.</p>
      )}
      {c.error && <p className="mb-4 border border-bad px-3 py-2 font-sans text-sm text-bad">{c.error}</p>}

      <main className="grid items-start gap-8 xl:grid-cols-[260px_1fr_360px]">
        <div className="flex flex-col gap-6">
          <section>
            <h2 className="h">Link</h2>
            <div className="flex flex-col gap-3 font-sans text-sm">
              <label>Power (0–127)<input type="number" min={0} max={127} value={opts.power} onChange={num('power')} disabled={linked} /></label>
              <label>FOFS, Hz (±200000)<input type="number" min={-200000} max={200000} step={1000} value={opts.fofs_hz} onChange={num('fofs_hz')} disabled={linked} /></label>
              <label className="flex items-center gap-2">
                <input type="checkbox" className="!w-auto" checked={opts.allow_arm} disabled={linked} onChange={(e) => setOpts({ ...opts, allow_arm: e.target.checked })} />
                Allow arming for this link
              </label>
              {linked ? (
                <button className="btn" onClick={c.stopLink}>Stop link</button>
              ) : (
                <button className="btn" onClick={() => c.startLink(opts)} disabled={c.ws !== 'open' || !esp?.connected}>Start link</button>
              )}
            </div>
          </section>
          <section>
            <h2 className="h">Link stats</h2>
            <Row k="slots" v={esp?.slots ?? '–'} />
            <Row k="late max" v={esp?.late_max_us != null ? `${esp.late_max_us} µs` : '–'} cls={(esp?.late_max_us ?? 0) > 1000 ? 'text-warn' : ''} />
            <Row k="FOFS" v={esp?.fofs != null ? `${esp.fofs} Hz` : '–'} />
            <Row k="keyed" v={esp?.keyed ? 'yes' : 'no'} />
            <Row k="sender rate" v={esp?.sender_hz ? `${esp.sender_hz.toFixed(1)} Hz` : '–'} />
            <Row k="browser to backend" v={`${c.sendHz} Hz`} />
            <Row k="telemetry" v={`${c.telHz} Hz`} cls={c.telHz < 10 ? 'text-warn' : ''} />
          </section>
        </div>

        <div className="flex flex-col items-center gap-6">
          <div className="flex items-center gap-4 font-sans text-sm">
            <span className="text-muted">Control mode</span>
            {(['fly', 'sticks'] as const).map((m) => (
              <button key={m} onClick={() => c.setMode(m)} className={`btn ${c.mode === m ? 'font-bold' : 'border-line text-muted'}`}>
                {m === 'fly' ? 'Fly' : 'Sticks'}
              </button>
            ))}
          </div>
          {fly && (
            <div className="flex flex-wrap items-end justify-center gap-6 font-sans">
              <div className="text-center">
                <div className="text-xs font-semibold text-muted">Hover throttle, µs ( [ down, ] up )</div>
                <div className="font-mono text-4xl tabular-nums">{c.hover}</div>
              </div>
              <label className="w-24 text-xs text-muted">Max tilt, %<input type="number" min={10} max={100} value={c.tilt} onChange={(e) => c.setTilt(Number(e.target.value))} /></label>
              <label className="w-24 text-xs text-muted">Climb, +µs<input type="number" min={0} max={500} step={10} value={c.climb} onChange={(e) => c.setClimb(Number(e.target.value))} /></label>
              <label className="w-24 text-xs text-muted">Descend, −µs<input type="number" min={0} max={500} step={10} value={c.descend} onChange={(e) => c.setDescend(Number(e.target.value))} /></label>
              <label className="flex items-center gap-2 text-xs text-muted">
                <input type="checkbox" className="!w-auto" checked={c.mouseYawOn} onChange={(e) => c.setMouseYawOn(e.target.checked)} />
                Mouse X yaw
              </label>
            </div>
          )}
          <div
            className="flex flex-wrap justify-center gap-6"
            onClick={() => {
              if (fly && c.mouseYawOn && !document.pointerLockElement) void (document.body.requestPointerLock() as unknown)
            }}
          >
            <Stick label="Left, mode 2" xLabel="yaw" yLabel="throttle" x={c.sticks.yaw} y={c.sticks.throttle * 2 - 1}
              onDrag={(x, y) => !fly && c.setMouseL({ x, y })} onRelease={() => c.setMouseL(null)} />
            <Stick label="Right" xLabel="roll" yLabel="pitch" x={c.sticks.roll} y={c.sticks.pitch}
              onDrag={(x, y) => !fly && c.setMouseR({ x, y })} onRelease={() => c.setMouseR(null)} />
          </div>

          <div className="flex flex-wrap items-center justify-center gap-3">
            <button
              disabled={!c.canArm}
              onPointerDown={c.armPress}
              onPointerUp={c.armRelease}
              onPointerLeave={c.armRelease}
              className={`btn relative min-w-48 overflow-hidden ${c.armed ? 'border-bad font-bold text-bad' : ''}`}
            >
              <span className="absolute inset-y-0 left-0 bg-bad/20" style={{ width: `${c.armProgress * 100}%` }} />
              <span className="relative">{c.armed ? 'ARMED' : 'Hold 1 s to arm (or R)'}</span>
            </button>
            <button className="btn" onClick={c.disarm}>Disarm, throttle 0 (X)</button>
          </div>

          <p className="m-0 max-w-xl text-center font-sans text-xs leading-snug text-muted">
            {fly
              ? 'Fly (Angle mode): W/S pitch, A/D roll, Q/E yaw, Space climb, Shift descend, [ ] hover throttle, X disarm, hold R arm. Tick “Mouse X yaw” then click the sticks to capture the mouse; Esc releases. '
              : 'Sticks: W/S throttle (holds), A/D yaw, arrows pitch/roll, Shift fine, X disarm. Drag the sticks with the mouse. '}
            Arming needs a link started with “Allow arming”. Disarmed sends throttle 1000.
          </p>
        </div>

        <div className="flex flex-col gap-6">
          <section>
            <h2 className="h">Channels, µs (commanded / readback)</h2>
            <Bars cmd={c.channels} rc={fc?.connected ? fc.rc : undefined} />
          </section>
          <section>
            <h2 className="h">Betaflight</h2>
            <Row k="RSSI" v={fc?.connected ? (fc.rssi ?? '–') : '–'} />
            <Row k="armed" v={fcArmed ? 'ARMED' : 'no'} cls={fcArmed ? 'font-bold text-bad' : ''} />
            <Row k="failsafe" v={failsafe ? 'ACTIVE' : 'no'} cls={failsafe ? 'font-bold text-warn' : ''} />
            <Row k="arming disabled by" v={fc?.arming_disable?.length ? fc.arming_disable.join(', ') : 'none'} />
          </section>
        </div>
      </main>
    </div>
  )
}
