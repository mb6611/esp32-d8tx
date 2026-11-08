import type { RadioStatus, Telemetry } from './types'

/** Simulated backend state for ?mock=1 */
export class MockBackend {
  link = false
  allowArm = false
  fofs = 0
  slots = 0
  sentAt = 0
  ch: number[] = [1000, 1500, 1500, 1500, 1000, 1000, 1000, 1000]
  rc: number[] = [1000, 1500, 1500, 1500, 1000, 1000, 1000, 1000]

  setSticks(ch: number[]) {
    this.ch = ch
    this.sentAt = performance.now()
  }
  start(allowArm: boolean, fofs: number) {
    this.link = true
    this.allowArm = allowArm
    this.fofs = fofs
    this.slots = 0
  }
  stop() {
    this.link = false
    this.allowArm = false
  }
  tick(dt: number): Telemetry {
    if (this.link && performance.now() - this.sentAt > 250) this.stop()
    if (this.link) this.slots += Math.round(dt * 111.2)
    const k = Math.min(1, dt * 12)
    this.rc = this.rc.map((v, i) => {
      const target = this.link ? (i === 6 && !this.allowArm ? 1000 : this.ch[i]) : v
      return v + (target - v) * k
    })
    const armed = this.link && this.allowArm && this.slots >= 170 && this.rc[6] > 1700 && this.rc[0] < 1900
    const q = new URLSearchParams(location.search)
    const radioOn = this.link && q.get('radio') !== 'off'
    const radioArmed = armed && q.get('radio') !== 'noarm'
    const radio: RadioStatus = radioOn
      ? {
          enabled: true, powered: true, link: true, age_ms: 40 + Math.round(Math.random() * 60),
          catch_rate: 0.98, rssi: 120, vbat_v: q.get('batt') === 'absent' ? 0.2 : 3.9,
          battery: q.get('batt') === 'absent' ? 'absent' : 'present',
          armed: radioArmed ? true : this.slots >= 170 ? false : null, armed_source: 'rpm',
        }
      : { enabled: this.link, powered: false, link: false, age_ms: null, catch_rate: null, vbat_v: null, battery: null, armed: null, armed_source: null }
    return {
      radio,
      esp: {
        connected: true,
        link: this.link,
        keyed: this.link,
        fofs: this.fofs,
        slots: this.slots,
        late_max_us: this.link ? 40 + Math.round(Math.random() * 60) : 0,
        allow_arm: this.allowArm,
        sender_hz: this.link ? 111.2 : 0,
        info: { proto: 1, fw: 'mock' },
      },
      fc: new URLSearchParams(location.search).get('fc') === 'off' ? { connected: false, error: 'no serial' } : {
        connected: true,
        rc: this.rc.map(Math.round),
        armed,
        failsafe: this.link ? this.slots < 170 : this.slots > 0, // clears ~1.5 s after the link starts
        arming_disable: armed ? [] : this.link ? ['ARMSWITCH'] : ['RXLOSS'],
        rssi: this.link ? 90 + Math.round(Math.random() * 8) : 0,
      },
    }
  }
}
