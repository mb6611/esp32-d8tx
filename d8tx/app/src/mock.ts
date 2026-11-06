import type { Telemetry } from './types'

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
    const armed = this.link && this.allowArm && this.rc[6] > 1700 && this.rc[0] < 1900
    return {
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
        failsafe: !this.link && this.slots > 0,
        arming_disable: armed ? [] : this.link ? ['ARMSWITCH'] : ['RXLOSS'],
        rssi: this.link ? 90 + Math.round(Math.random() * 8) : 0,
      },
    }
  }
}
