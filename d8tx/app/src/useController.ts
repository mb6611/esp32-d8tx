import { useCallback, useEffect, useRef, useState } from 'react'
import { MockBackend } from './mock'
import type { StartOptions, Telemetry, WsState } from './types'

export const MOCK = new URLSearchParams(location.search).has('mock')
const SEND_HZ = 120
const ARM_HOLD_MS = 1000
const ARM_THROTTLE_HOLD_MS = 500

export interface Sticks {
  throttle: number // 0..1
  yaw: number
  pitch: number
  roll: number // -1..1
}

const startedAllow = { current: false }

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v))
const us = (v: number) => Math.round(clamp(v, 1000, 2000))

export function useController() {
  const [tel, setTel] = useState<Telemetry | null>(null)
  const [ws, setWs] = useState<WsState>(MOCK ? 'open' : 'connecting')
  const [sticks, setSticks] = useState<Sticks>({ throttle: 0, yaw: 0, pitch: 0, roll: 0 })
  const [channels, setChannels] = useState<number[]>([1000, 1500, 1500, 1500, 1000, 1000, 1000, 1000])
  const [armed, setArmed] = useState(false)
  const [armProgress, setArmProgress] = useState(0)
  const [sendHz, setSendHz] = useState(0)
  const [telHz, setTelHz] = useState(0)
  const [error, setError] = useState<string | null>(null)

  const st = useRef({ throttle: 0, yaw: 0, pitch: 0, roll: 0 })
  const [maxThr, setMaxThr] = useState(100)
  const settings = useRef({ maxThr: maxThr / 100 })
  useEffect(() => {
    settings.current = { maxThr: maxThr / 100 }
  })
  const keys = useRef(new Set<string>())
  const mouseL = useRef<{ x: number; y: number } | null>(null)
  const mouseR = useRef<{ x: number; y: number } | null>(null)
  const armedRef = useRef(false)
  const telRef = useRef<Telemetry | null>(null)
  const armTrack = useRef({ at: 0, seen: false, bad: null as number | null })
  const [disarmNote, setDisarmNote] = useState<string | null>(null)
  useEffect(() => {
    telRef.current = tel
  }, [tel])
  const armStart = useRef<number | null>(null)
  const allowArm = useRef(false)
  const sock = useRef<WebSocket | null>(null)
  const mock = useRef<MockBackend | null>(null)
  const counts = useRef({ sent: 0, tel: 0 })

  const canArm = !!tel?.esp?.link && (tel.esp.allow_arm ?? startedAllow.current)
  useEffect(() => {
    allowArm.current = canArm
  }, [canArm])

  const disarm = useCallback(() => {
    armedRef.current = false
    armStart.current = null
    setDisarmNote(null)
    setArmed(false)
    setArmProgress(0)
  }, [])

  // telemetry transport
  useEffect(() => {
    if (MOCK) {
      const m = new MockBackend()
      mock.current = m
      let last = performance.now()
      const id = setInterval(() => {
        const now = performance.now()
        setTel(m.tick((now - last) / 1000))
        last = now
        counts.current.tel++
      }, 50)
      return () => clearInterval(id)
    }
    let closed = false
    let timer: ReturnType<typeof setTimeout>
    const connect = () => {
      setWs('connecting')
      const proto = location.protocol === 'https:' ? 'wss' : 'ws'
      const s = new WebSocket(`${proto}://${location.host}/api/ws`)
      sock.current = s
      s.onopen = () => setWs('open')
      s.onmessage = (ev) => {
        try {
          const m = JSON.parse(ev.data)
          if (m.type === 'telemetry') {
            counts.current.tel++
            setTel({ esp: m.esp ?? undefined, fc: m.fc ?? undefined })
          }
        } catch {
          /* ignore malformed frame */
        }
      }
      s.onclose = () => {
        setWs('closed')
        sock.current = null
        if (!closed) timer = setTimeout(connect, 1000)
      }
      s.onerror = () => s.close()
    }
    connect()
    return () => {
      closed = true
      clearTimeout(timer)
      sock.current?.close()
    }
  }, [])

  // keyboard
  useEffect(() => {
    const WATCH = ['w', 's', 'a', 'd', 'arrowup', 'arrowdown', 'arrowleft', 'arrowright']
    const kd = (e: KeyboardEvent) => {
      const t = e.target as HTMLInputElement | null
      const typing = t?.tagName === 'TEXTAREA' || (t?.tagName === 'INPUT' && !['checkbox', 'radio', 'button'].includes(t.type))
      const k = e.code === 'Space' ? ' ' : e.key.toLowerCase()
      if (k === 'x') {
        // disarm works regardless of focus
        e.preventDefault()
        st.current.throttle = 0
        disarm()
        return
      }
      if (typing) return
      if (k === 'r') {
        if (!e.repeat && allowArm.current && !armedRef.current) armStart.current = performance.now()
        return
      }
      if (WATCH.includes(k)) {
        e.preventDefault()
        keys.current.add(k)
      }
    }
    const ku = (e: KeyboardEvent) => {
      const k = e.code === 'Space' ? ' ' : e.key.toLowerCase()
      keys.current.delete(k)
      if (k === 'r') armStart.current = null
    }
    const blur = () => {
      keys.current.clear()
    }
    window.addEventListener('keydown', kd)
    window.addEventListener('keyup', ku)
    window.addEventListener('blur', blur)
    return () => {
      window.removeEventListener('keydown', kd)
      window.removeEventListener('keyup', ku)
      window.removeEventListener('blur', blur)
    }
  }, [disarm])

  // main loop: integrate inputs, send channels
  useEffect(() => {
    let last = performance.now()
    let lastUi = 0
    let lastRate = last
    const id = setInterval(() => {
      const now = performance.now()
      const dt = Math.min(0.1, (now - last) / 1000)
      last = now
      const k = keys.current
      const s = st.current
      const cfg = settings.current
      const axis = (pos: string, neg: string) => (k.has(pos) ? 1 : 0) - (k.has(neg) ? 1 : 0)
      // keys move a spring axis toward its target at a limited rate, so holding a key ramps the stick
      // and releasing eases it back to centre, like a thumb on a gimbal
      const ramp = (cur: number, target: number) => {
        const rate = target === 0 ? 3.3 : 2.2
        const step = rate * dt
        return Math.abs(target - cur) <= step ? target : cur + Math.sign(target - cur) * step
      }
      const cap = cfg.maxThr
      // non-centering throttle: 0 unless armed; W raises (ease-in, ~2 s to 100%), S lowers (~1.5 s), stays where left
      const dir = axis('w', 's')
      if (!armedRef.current) s.throttle = 0
      else if (mouseL.current) s.throttle = clamp((mouseL.current.y + 1) / 2, 0, cap)
      else if (dir > 0) s.throttle = Math.min(cap, (Math.sqrt(s.throttle) + dt / 2) ** 2)
      else if (dir < 0) s.throttle = Math.max(0, s.throttle - dt / 1.5)
      else s.throttle = Math.min(s.throttle, cap)
      s.yaw = mouseL.current ? mouseL.current.x : ramp(s.yaw, axis('d', 'a'))
      if (mouseR.current) {
        s.roll = mouseR.current.x
        s.pitch = mouseR.current.y
      } else {
        s.roll = ramp(s.roll, axis('arrowright', 'arrowleft'))
        s.pitch = ramp(s.pitch, axis('arrowup', 'arrowdown'))
      }
      let thrUs = 1000 + s.throttle * 1000

      // arm hold
      if (armStart.current !== null) {
        if (!allowArm.current) {
          armStart.current = null
        } else if (now - armStart.current >= ARM_HOLD_MS) {
          const f0 = telRef.current?.fc
          const blk = (f0?.connected ? (f0.arming_disable ?? []) : []).filter((r) =>
            ['ARMSWITCH', 'THROTTLE'].includes(r.toUpperCase().replace(/_/g, '')),
          )
          armStart.current = null
          if (blk.length) {
            setDisarmNote(`Cannot arm yet: ${blk.join(', ')}`)
          } else {
            armedRef.current = true
            armTrack.current = { at: now, seen: false, bad: null }
            setDisarmNote(null)
          }
        }
      }
      // Betaflight disarmed itself (or never armed): drop our arm state
      if (armedRef.current) {
        const fc = telRef.current?.fc
        const tr = armTrack.current
        if (fc?.connected && fc.armed) {
          tr.seen = true
          tr.bad = null
        } else if (fc?.connected && fc.armed === false) {
          if (tr.bad === null) tr.bad = now
          const limit = tr.seen ? 500 : 1000
          if (now - Math.max(tr.bad, tr.seen ? 0 : tr.at) >= limit) {
            const why = (fc.arming_disable ?? []).join(', ')
            armedRef.current = false
            st.current.throttle = 0
            s.throttle = 0
            thrUs = 1000
            setDisarmNote(
              tr.seen ? `Betaflight disarmed${why ? ': ' + why : ''}` : `Betaflight did not arm${why ? ': ' + why : ''}`,
            )
          }
        } else tr.bad = null
      }
      if (armedRef.current && !allowArm.current) armedRef.current = false

      // disarmed: the stick shows a preview, but 1000 is what is sent
      // Betaflight arms only if throttle is at minimum when the arm switch goes high: hold 1000 for
      // ARM_THROTTLE_HOLD_MS after arming, then the normal (eased) throttle takes over
      const inArmHold = armedRef.current && now - armTrack.current.at < ARM_THROTTLE_HOLD_MS
      if (inArmHold) {
        st.current.throttle = 0
        s.throttle = 0
      }
      const sendThr = armedRef.current && !inArmHold ? thrUs : 1000
      const ch = [
        us(sendThr),
        us(1500 + s.roll * 500),
        us(1500 + s.pitch * 500),
        us(1500 + s.yaw * 500),
        1000,
        1000,
        armedRef.current ? 2000 : 1000,
        1000,
      ]
      if (MOCK) mock.current?.setSticks(ch)
      else if (sock.current?.readyState === WebSocket.OPEN) sock.current.send(JSON.stringify({ type: 'sticks', ch }))
      counts.current.sent++

      if (now - lastUi > 8) {
        lastUi = now
        setSticks({ ...s })
        setChannels(ch)
        setArmed(armedRef.current)
        setArmProgress(armStart.current === null ? 0 : Math.min(1, (now - armStart.current) / ARM_HOLD_MS))
      }
      if (now - lastRate > 1000) {
        const sec = (now - lastRate) / 1000
        setSendHz(Math.round(counts.current.sent / sec))
        setTelHz(Math.round(counts.current.tel / sec))
        counts.current = { sent: 0, tel: 0 }
        lastRate = now
      }
    }, 1000 / SEND_HZ)
    return () => clearInterval(id)
  }, [])

  const post = useCallback(async (path: string, body?: unknown) => {
    setError(null)
    try {
      const r = await fetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body ?? {}),
      })
      if (!r.ok) setError(`${path}: ${r.status} ${(await r.text()).slice(0, 120)}`)
    } catch (e) {
      setError(`${path}: ${String(e)}`)
    }
  }, [])

  const startLink = useCallback(
    (o: StartOptions) => {
      // starting a link always allows arming; the 1 s hold is the deliberate gate
      startedAllow.current = true
      if (MOCK) mock.current?.start(true, o.fofs_hz)
      else void post('/api/link/start', { ...o, allow_arm: true })
    },
    [post],
  )
  const stopLink = useCallback(() => {
    disarm()
    startedAllow.current = false
    if (MOCK) mock.current?.stop()
    else void post('/api/link/stop')
  }, [post, disarm])

  return {
    tel,
    ws,
    sticks,
    channels,
    armed,
    disarmNote,
    armProgress,
    sendHz,
    telHz,
    error,
    canArm,
    startLink,
    stopLink,
    maxThr, setMaxThr,
    disarm: () => {
      st.current.throttle = 0
      disarm()
    },
    armPress: () => {
      if (allowArm.current && !armedRef.current) armStart.current = performance.now()
    },
    armRelease: () => {
      armStart.current = null
    },
    setMouseL: (v: { x: number; y: number } | null) => (mouseL.current = v),
    setMouseR: (v: { x: number; y: number } | null) => (mouseR.current = v),
  }
}
