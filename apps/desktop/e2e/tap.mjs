// Code evaluated inside the app's dedicated worker (via Playwright worker.evaluate) before any port is opened.
// It observes, without changing behaviour:
//  - DevKit RX text lines (EV/OK/ERR), DevKit TX lines (S frame write times -> host-side S gaps),
//  - FC RX MSP v1 replies (per-command counts, attitude reply times),
//  - every state message the worker posts to the UI (latest kept, 1 Hz series).
// It also keeps the real SerialPort objects so the harness can close (forget) the DevKit port.
export function installTap() {
  if (self.__e2e) return 'already'
  const T = (self.__e2e = {
    t0: Date.now(),
    esp: { lines: [], sTimes: 0, sCount: 0, sLast: null, sMaxGap: 0, sGaps50: 0, sGapsList: [], lastS: null, linked: false, txOther: [] },
    fc: { counts: {}, attTimes: [], motors: [] },
    state: null,
    series: [],
    lastSeriesAt: 0,
    ports: {},
    marks: [],
    kill: {},
  })
  const lost = () => new DOMException('The device has been lost.', 'NetworkError')
  const killers = {}
  const killP = (role) => new Promise((_, rej) => { killers[role] = () => rej(lost()) })
  // Simulated unplug: pending and later reads/writes on the role's port reject like Chrome on device loss.
  T.unplug = (role) => { T.kill[role] = Date.now(); if (killers[role]) killers[role]() }
  const now = () => Date.now()
  const VID = { 0x10c4: 'esp', 0x0483: 'fc' }

  // --- state messages
  const origPost = self.postMessage.bind(self)
  self.postMessage = (m, ...rest) => {
    if (m && m.type === 'error') T.marks.push({ t: now(), ev: 'worker_error', role: m.role, kind: m.kind, message: m.message })
    if (m && m.type === 'state') {
      T.state = m
      const t = now()
      if (t - T.lastSeriesAt >= 1000) {
        T.lastSeriesAt = t
        const e = m.esp || {}, f = m.fc || {}, r = m.radio || {}
        T.series.push({
          t, link: e.link, connected: e.connected, lost: e.lost_reason, slots: e.slots, hz: e.sender_hz, gap: e.sender_max_gap_ms,
          skipped: e.skipped, allow: e.allow_arm, guard: e.guard,
          trig: r.triggers, rep: r.replies, age: r.age_ms, rlink: r.link, vbat: r.vbat_v, rssi: r.rssi,
          fcc: f.connected, att: f.attitude_deg, mot: f.motors, rc: f.rc, armed: f.armed, fs: f.failsafe, dis: f.arming_disable,
        })
      }
      // link-lost transitions
      const linked = !!(m.esp && m.esp.link)
      if (T._prevLink && !linked) T.marks.push({ t, ev: 'state_link_false', lost: m.esp.lost_reason, connected: m.esp.connected })
      T._prevLink = linked
    }
    return origPost(m, ...rest)
  }

  const td = new TextDecoder('latin1')
  // --- DevKit RX: printable text lines only (capture payloads are binary)
  let espBuf = ''
  const espRx = (u8) => {
    const s = td.decode(u8)
    for (const ch of s) {
      if (ch === '\n') {
        const line = espBuf.replace(/\r$/, '')
        espBuf = ''
        if (/^(EV|OK|ERR)( [ -~]*)?$/.test(line)) {
          const t = now()
          if (line.startsWith('EV link ') || line.startsWith('OK keyed=')) {
            // keep the high-rate lines compactly
            T.esp.lines.push([t, line])
            if (T.esp.lines.length > 20000) T.esp.lines.splice(0, 5000)
          } else T.esp.lines.push([t, line])
        }
      } else if (espBuf.length < 200) espBuf += ch
      else espBuf = ''
    }
  }
  // --- DevKit TX
  const espTx = (u8) => {
    const s = td.decode(u8)
    const t = performance.now()
    for (const line of s.split('\n')) {
      if (!line) continue
      if (line.startsWith('S ')) {
        const E = T.esp
        if (E.linked) {
          if (E.sLast !== null) {
            const g = t - E.sLast
            if (g > E.sMaxGap) E.sMaxGap = g
            if (g > 50) { E.sGaps50++; if (E.sGapsList.length < 50) E.sGapsList.push([now(), Math.round(g)]) }
          }
          E.sLast = t
          E.sCount++
        }
        E.lastS = [now(), line]
      } else {
        T.esp.txOther.push([now(), line])
        if (line.startsWith('LINK')) { T.esp.linked = true; T.esp.sLast = null }
        if (line.startsWith('STOP') || line === 'U') T.esp.linked = false
      }
    }
  }
  // --- FC RX: MSP v1 replies "$M>" len cmd payload crc
  const fcState = { st: 0, len: 0, cmd: 0, n: 0 }
  const fcRx = (u8) => {
    for (const b of u8) {
      const F = fcState
      switch (F.st) {
        case 0: F.st = b === 0x24 ? 1 : 0; break
        case 1: F.st = b === 0x4d ? 2 : 0; break
        case 2: F.st = b === 0x3e ? 3 : 0; break
        case 3: F.len = b; F.st = 4; break
        case 4: F.cmd = b; F.n = 0; F.pl = []; F.st = F.len ? 5 : 6; break
        case 5: F.pl.push(b); if (++F.n >= F.len) F.st = 6; break
        case 6: {
          T.fc.counts[F.cmd] = (T.fc.counts[F.cmd] || 0) + 1
          if (F.cmd === 108) { T.fc.attTimes.push(now()); if (T.fc.attTimes.length > 100000) T.fc.attTimes.splice(0, 20000) }
          if (F.cmd === 104 && F.pl.length >= 8) {
            const m = []
            for (let i = 0; i < 8; i += 2) m.push(F.pl[i] | (F.pl[i + 1] << 8))
            T.fc.motors.push([now(), m])
            if (T.fc.motors.length > 5000) T.fc.motors.splice(0, 1000)
          }
          F.st = 0
          break
        }
      }
    }
  }

  const wrapPort = (port) => {
    if (port.__tapped) return port
    port.__tapped = true
    const info = port.getInfo ? port.getInfo() : {}
    const role = VID[info.usbVendorId]
    if (!role) return port
    T.ports[role] = port
    const proto = Object.getPrototypeOf(port)
    const rd = Object.getOwnPropertyDescriptor(proto, 'readable')
    const wd = Object.getOwnPropertyDescriptor(proto, 'writable')
    Object.defineProperty(port, 'readable', {
      configurable: true,
      get() {
        const s = rd.get.call(port)
        if (s && !s.__tapped) {
          s.__tapped = true
          const gr = s.getReader.bind(s)
          s.getReader = (...a) => {
            const r = gr(...a)
            const read = r.read.bind(r)
            const kp = killP(role)
            kp.catch(() => undefined)
            r.read = async () => {
              if (T.kill[role]) throw lost()
              const res = await Promise.race([read(), kp])
              if (res.value) { try { (role === 'esp' ? espRx : fcRx)(res.value) } catch (e) { T.marks.push({ t: now(), ev: 'tap_err', e: String(e) }) } }
              if (res.done) T.marks.push({ t: now(), ev: `${role}_read_done` })
              return res
            }
            return r
          }
        }
        return s
      },
    })
    Object.defineProperty(port, 'writable', {
      configurable: true,
      get() {
        const s = wd.get.call(port)
        if (s && !s.__tapped && role === 'esp') {
          s.__tapped = true
          const gw = s.getWriter.bind(s)
          s.getWriter = (...a) => {
            const w = gw(...a)
            const write = w.write.bind(w)
            w.write = (chunk) => { if (T.kill[role]) return Promise.reject(lost()); try { espTx(chunk) } catch { /* ignore */ } return write(chunk) }
            return w
          }
        }
        return s
      },
    })
    return port
  }
  const serial = navigator.serial
  const gp = serial.getPorts.bind(serial)
  serial.getPorts = async () => (await gp()).map(wrapPort)
  return 'installed'
}
