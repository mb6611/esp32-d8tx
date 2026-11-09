import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import type { FcStatus, RadioStatus } from './types'

const Quad3D = lazy(() => import('./Quad3D'))

const STALE_MS = 3000

/** Wall-clock time (ms) the value last changed; null while there is no value. The backend sends no per-field age. */
function useStamp(value: unknown): number | null {
  const key = value == null ? '' : JSON.stringify(value)
  const [t, setT] = useState<number | null>(null)
  const last = useRef('')
  useEffect(() => {
    if (key === last.current) return
    last.current = key
    setT(key === '' ? null : Date.now())
  }, [key])
  return t
}

function useNow(): number {
  const [n, setN] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setN(Date.now()), 500)
    return () => clearInterval(id)
  }, [])
  return n
}

const fmtAge = (ms: number) => (ms < 10000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms / 1000)}s`)

function Bar({ v, max }: { v: number | null; max: number }) {
  const p = v == null ? 50 : 50 + Math.max(-1, Math.min(1, v / max)) * 50
  return (
    <div className="relative h-2.5 bg-paper-2">
      <span className="absolute inset-y-0 left-1/2 w-px bg-muted" />
      {v != null && <div className="absolute top-[2px] bottom-[2px] bg-fg" style={{ left: `${Math.min(p, 50)}%`, width: `${Math.abs(p - 50)}%` }} />}
    </div>
  )
}

function Triple({ title, unit, vals, max, digits, age, stale }: {
  title: string; unit: string; vals: (number | null)[] | null; max: number; digits: number; age: number | null; stale: boolean
}) {
  return (
    <div className={stale ? 'text-muted opacity-50' : ''}>
      <div className="flex justify-between font-sans text-[10px] font-semibold tracking-wider text-muted uppercase">
        <span>{title} <span className="font-normal normal-case">{unit} · ±{max}</span></span>
        <span className="font-mono font-normal normal-case">{age == null ? 'no data' : fmtAge(age)}</span>
      </div>
      {['X', 'Y', 'Z'].map((a, i) => {
        const v = vals?.[i] ?? null
        return (
          <div key={a} className="grid grid-cols-[1rem_3.6rem_1fr] items-center gap-x-1.5 font-mono text-[11px] leading-[14px] tabular-nums">
            <span className="text-muted">{a}</span>
            <span className="text-right">{v == null ? '–' : v.toFixed(digits)}</span>
            <Bar v={v} max={max} />
          </div>
        )
      })}
    </div>
  )
}

export function useDrone(radio?: RadioStatus, fc?: FcStatus) {
  const hub = radio?.hub
  const p = hub?.patched
  const acc = hub?.acc_mg ?? null
  const fast = radio?.fast ?? null
  const fastOk = fast != null && fast.age_ms != null && fast.age_ms < STALE_MS
  const hubGyro = p?.gyro_dps ?? null
  const att = p?.attitude_deg ?? null
  const now = useNow()
  const tAcc = useStamp(acc)
  const tGyro = useStamp(hubGyro)
  const fastGyro = fastOk ? fast?.gyro_dps ?? null : null
  const fastAtt = fastOk ? fast?.attitude_deg ?? null : null
  const gyro = fastGyro ?? hubGyro
  const tAtt = useStamp(att)
  const tMode = useStamp(p?.flight_mode)
  const ageOf = (t: number | null) => (t == null ? null : Math.max(0, now - t))
  const aAcc = ageOf(tAcc), aGyro = fastGyro ? fast!.age_ms! : ageOf(tGyro), aAtt = ageOf(tAtt), aMode = ageOf(tMode)
  const st = (a: number | null) => a == null || a > STALE_MS
  const fcAtt = fc?.connected ? fc.attitude_deg ?? null : null
  // MSP is polled continuously and fc.connected drops on poll errors, so a still drone (unchanged value) is not stale
  const useFc = fcAtt != null
  const useFast = !useFc && fastAtt != null
  const shown = useFc ? fcAtt : useFast ? fastAtt : att
  const attStale = useFc || useFast ? false : st(aAtt)
  const live = !!radio?.enabled && radio.powered
  return { hub, p, acc, gyro, aAcc, aGyro, aAtt, aMode, st, useFc, useFast, fast, shown, attStale, live }
}
export type Drone = ReturnType<typeof useDrone>

/** Centrepiece: square 3D view with attitude numbers and source label. */
export function DroneView({ d, fc, radioArmed, throttle }: { d: Drone; fc?: FcStatus; radioArmed?: boolean | null; throttle?: number }) {
  const { shown, attStale, useFc, useFast, fast, hub, aAtt } = d
  const m = fc?.connected ? fc.motors : null
  const mot = m && m.length >= 4 ? m.slice(0, 4) : null
  const est = !mot && radioArmed === true && throttle != null
  const spin = mot ? mot.map((v) => Math.max(0, Math.min(1, (v - 1000) / 1000))) : est ? [1, 1, 1, 1].map(() => Math.max(0, Math.min(1, throttle!))) : null
  const motLabel = mot ? 'motors: MSP' : est ? 'motors: throttle (est.)' : 'stopped'
  return (
    <div className={`flex w-full flex-col items-center ${attStale ? 'text-muted' : ''}`}>
      <Suspense fallback={<div className="aspect-square w-full" />}>
        <Quad3D att={{ roll: shown?.[0] ?? 0, pitch: shown?.[1] ?? 0, yaw: shown?.[2] ?? null }} dim={attStale || shown == null} tau={useFast ? 150 : 100} spin={spin} src={attStale ? 'stale' : useFc ? 'fc' : useFast ? 'fast' : 'hub'} />
      </Suspense>
      <div className="font-mono text-[11px] leading-tight tabular-nums">
        R {shown?.[0] != null ? shown[0].toFixed(0) : '–'}° P {shown?.[1] != null ? shown[1].toFixed(0) : '–'}° Y {shown?.[2] != null ? shown[2].toFixed(0) : hub?.heading_deg != null ? `${hub.heading_deg.toFixed(0)}h` : '–'}°
      </div>
      <div className="font-mono text-[10px] leading-tight text-muted">{motLabel}</div>
      <div className="font-mono text-[10px] leading-tight">
        {useFc ? 'MSP, ~50 Hz' : useFast ? `radio, ~6 Hz · ${fast?.rate_hz != null ? fast.rate_hz.toFixed(1) : '–'} Hz · ${fast?.age_ms != null ? fmtAge(fast.age_ms) : '–'}` : <>radio, slow · {aAtt == null ? 'no data' : fmtAge(aAtt)}</>}
      </div>
    </div>
  )
}

export default function DronePanel({ d, radio }: { d: Drone; radio?: RadioStatus }) {
  const { p, acc, gyro, aAcc, aGyro, aMode, st, useFc, live } = d
  return (
    <div className="min-w-0 font-sans">
      <div className="flex items-baseline justify-between">
        <h2 className="h !mb-1 flex-1">Drone (radio)</h2>
      </div>
      {!live && !useFc ? <div className="font-sans text-xs text-muted">no telemetry</div> : (
        <div className="grid grid-cols-2 gap-x-3">
          <Triple title="Accel" unit="g" vals={acc ? acc.map((v) => (v == null ? null : v / 1000)) : null} max={2} digits={2} age={aAcc} stale={st(aAcc)} />
          <Triple title="Gyro" unit="°/s" vals={gyro} max={500} digits={0} age={aGyro} stale={st(aGyro)} />
          <div className="col-span-2 mt-0.5 flex flex-wrap gap-x-3 border-t border-line pt-0.5 font-mono text-[10px] text-muted">
            <span className={st(aMode) ? 'opacity-50' : ''}>mode <span className="text-fg">{p?.flight_mode ?? '–'}</span></span>
            <span>armed <span className={p?.armed ? 'font-bold text-bad' : 'text-fg'}>{p?.armed == null ? '?' : p.armed ? 'yes' : 'no'}</span></span>
            <span>failsafe <span className={p?.failsafe ? 'font-bold text-warn' : 'text-fg'}>{p?.failsafe == null ? '?' : p.failsafe ? 'yes' : 'no'}</span></span>
            <span>rssi <span className="text-fg">{radio?.rssi_dbm ?? '–'}</span></span>
            <span>cfo <span className="text-fg">{radio?.cfo_khz ?? '–'}k</span></span>
          </div>
        </div>
      )}
    </div>
  )
}
