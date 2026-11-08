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
  tt = 0
  hubAt = -10
  hubSnap = { acc: [12, -30, 1010], gyro: [3, -2, 1], att: [0, 0, 0] as number[] }
  tick(dt: number): Telemetry {
    this.tt += dt
    const T = this.tt
    const Tq = Math.floor(T * 5.7) / 5.7 // fast block updates at 5.7 Hz
    const truth = [18 * Math.sin(T * 0.8), 12 * Math.sin(T * 0.55 + 1), 40 * Math.sin(T * 0.3)]
    if (T - this.hubAt > 4) { // slow telemetry stream refreshes gyro/attitude every few seconds
      this.hubAt = T
      this.hubSnap = {
        acc: [Math.round(-Math.sin(truth[1] * Math.PI / 180) * 1000 + Math.random() * 30), Math.round(Math.sin(truth[0] * Math.PI / 180) * 1000), Math.round(1000 * Math.cos(truth[0] * Math.PI / 180) * Math.cos(truth[1] * Math.PI / 180))],
        gyro: [Math.round(18 * 0.8 * Math.cos(T * 0.8) * 57 / 57 * 10), Math.round(12 * 0.55 * Math.cos(T * 0.55 + 1) * 10), Math.round(40 * 0.3 * Math.cos(T * 0.3) * 10)],
        att: truth.map((v) => Math.round(v * 10) / 10),
      }
    }
    if (this.link && performance.now() - this.sentAt > 250) this.stop()
    if (this.link) this.slots += Math.round(dt * 111.2)
    const k = Math.min(1, dt * 12)
    this.rc = this.rc.map((v, i) => {
      const target = this.link ? (i === 6 && !this.allowArm ? 1000 : this.ch[i]) : v
      return v + (target - v) * k
    })
    const armed = this.link && this.allowArm && this.slots >= 170 && this.rc[6] > 1700 && this.rc[0] < 1900
    const q = new URLSearchParams(location.search)
    const radioOn = (this.link || q.has('demo')) && q.get('radio') !== 'off'
    const radioArmed = armed && q.get('radio') !== 'noarm'
    const radio: RadioStatus = radioOn
      ? {
          enabled: true, powered: true, link: true, age_ms: 40 + Math.round(Math.random() * 60),
          catch_rate: 0.98, rssi: 120, vbat_v: q.get('batt') === 'absent' ? 0.2 : 3.9,
          battery: q.get('batt') === 'absent' ? 'absent' : 'present',
          rssi_dbm: -62, cfo_khz: 1.4,
          fast: { attitude_deg: [18 * Math.sin(Tq * 0.8), 12 * Math.sin(Tq * 0.55 + 1), 40 * Math.sin(Tq * 0.3)].map((v) => Math.round(v * 10) / 10), gyro_dps: this.hubSnap.gyro.map((v) => v / 10), age_ms: Math.round(Math.random() * 170), rate_hz: 5.7, seq: Math.floor(T * 5.7) & 0xffff },
          hub: {
            acc_mg: this.hubSnap.acc, heading_deg: Math.round(((this.hubSnap.att[2] % 360) + 360) % 360), rpm: null, vfas_v: 3.9, current_a: 0.4, fuel: null, temp1: 31, temp2: null,
            patched: { gyro_dps: this.hubSnap.gyro, attitude_deg: [this.hubSnap.att[0], this.hubSnap.att[1], q.get('yaw') === 'null' ? null : this.hubSnap.att[2]], flight_mode: 'ANGLE', armed: radioArmed, failsafe: false },
            raw: { '0x03': 0, '0x24': this.hubSnap.acc[0], '0x25': this.hubSnap.acc[1], '0x26': this.hubSnap.acc[2], '0x14': 0 }, age_ms: 120,
          },
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
      fc: q.get('fc') === 'off' ? { connected: false, error: 'no serial' } : {
        connected: true,
        rc: this.rc.map(Math.round),
        armed,
        failsafe: this.link ? this.slots < 170 : this.slots > 0, // clears ~1.5 s after the link starts
        arming_disable: armed ? [] : this.link ? ['ARMSWITCH'] : ['RXLOSS'],
        rssi: this.link ? 90 + Math.round(Math.random() * 8) : 0,
        motors: q.get('msp') === 'off' ? null : armed ? [1300, 1350, 1400, 1450] : [1000, 1000, 1000, 1000],
        attitude_deg: q.get('msp') === 'off' ? null : truth.map((v) => Math.round(v * 10) / 10),
      },
    }
  }
}
