// U7 hardware end-to-end run of the real Electron app (test mode) against the DevKit and the drone FC.
//   node e2e/run.mjs soak [minutes]   U7.1: link with arm disallowed, window minimized
//   node e2e/run.mjs arm              U7.2: arm via the gate, throttle 1150 for 3 s, disarm, then close the DevKit port
// Props off, no battery (checked by the caller). Results: e2e/results/<phase>-<time>.json
import { _electron as electron } from 'playwright'
import { createRequire } from 'node:module'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { installTap } from './tap.mjs'

const here = path.dirname(fileURLToPath(import.meta.url))
const appDir = path.join(here, '..')
const require = createRequire(path.join(appDir, 'package.json'))
const ESP = process.env.D8TX_ESP_PORT || '/dev/cu.usbserial-0001'
const FCP = process.env.D8TX_FC_PORT || '/dev/cu.usbmodem0x80000001'
const SLOT_MS = 8.994
const phase = process.argv[2] || 'soak'
const minutes = Number(process.argv[3] || 10)
const outDir = path.join(here, 'results')
fs.mkdirSync(outDir, { recursive: true })
const stamp = new Date().toISOString().replace(/[:.]/g, '-')
const outFile = path.join(outDir, `${phase}-${stamp}.json`)
const log = (...a) => console.log(new Date().toISOString().slice(11, 23), ...a)
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function waitFor(fn, ms, what) {
  const t0 = Date.now()
  for (;;) {
    const v = await fn()
    if (v) return v
    if (Date.now() - t0 > ms) throw new Error(`timeout waiting for ${what}`)
    await sleep(100)
  }
}

const app = await electron.launch({
  executablePath: require('electron'),
  args: [appDir],
  cwd: appDir,
  env: { ...process.env, D8TX_ESP_PORT: ESP, D8TX_FC_PORT: FCP },
})
app.process().stdout.on('data', (d) => { for (const l of String(d).split('\n')) if (l.trim()) log('[main]', l) })
app.process().stderr.on('data', (d) => { for (const l of String(d).split('\n')) if (/d8tx|rror/.test(l)) log('[main!]', l) })
const result = { phase, started: new Date().toISOString(), esp_port: ESP, fc_port: FCP }
let page, worker
const W = (fn, arg) => worker.evaluate(fn, arg)
const state = () => W(() => self.__e2e.state)
const save = () => fs.writeFileSync(outFile, JSON.stringify(result, null, 1))

try {
  page = await app.firstWindow()
  page.on('console', (m) => { if (m.type() === 'error') log('[page error]', m.text()) })
  await page.waitForLoadState('domcontentloaded')
  worker = page.workers()[0] || (await page.waitForEvent('worker', { timeout: 10000 }))
  log('worker', worker.url(), await worker.evaluate(installTap))
  await waitFor(() => state(), 5000, 'first state message')

  // page-side observer: first time a text marker appears after arm() is called
  await page.evaluate(() => {
    window.__obs = { armedAt: null, hits: {} }
    const check = () => {
      const o = window.__obs
      if (o.armedAt === null) return
      const txt = document.body.innerText
      for (const [k, re] of [['link_lost', /Link lost/], ['disarmed', /\bDISARMED\b/]]) if (!o.hits[k] && re.test(txt)) o.hits[k] = Date.now()
    }
    new MutationObserver(check).observe(document.body, { subtree: true, childList: true, characterData: true })
  })

  // --- connect both ports through the UI buttons (requestPort -> test-mode auto-select by VID/PID)
  // Workaround for the main.cjs role race (filters IPC lands after select-serial-port): announce the role first.
  const preFilters = async (f) => { if (process.env.E2E_NO_PREFILTER) return; await page.evaluate((f) => window.postMessage({ __d8txFilters: [f] }, '*'), f); await sleep(200) }
  await preFilters({ usbVendorId: 0x10c4, usbProductId: 0xea60 })
  let t = Date.now()
  await page.getByRole('button', { name: 'Connect DevKit' }).click()
  const info = await waitFor(async () => { const s = await state(); return s?.esp?.connected && s.esp.info ? s.esp.info : null }, 10000, 'DevKit INFO')
  result.connect_esp_ms = Date.now() - t
  result.prefilter_workaround = !process.env.E2E_NO_PREFILTER
  result.info = info
  log('DevKit INFO in', result.connect_esp_ms, 'ms', JSON.stringify(info))
  await preFilters({ usbVendorId: 0x0483, usbProductId: 0x5740 })
  await page.getByRole('button', { name: 'Connect drone (optional)' }).click()
  await waitFor(async () => (await state())?.fc?.connected, 10000, 'FC connected')
  log('FC connected')
  await sleep(1500)

  if (phase === 'soak') await soak()
  else if (phase === 'arm') await arm()
  else throw new Error(`unknown phase ${phase}`)
} catch (e) {
  result.error = String(e && e.stack || e)
  log('ERROR', result.error)
} finally {
  try { result.tap = await W(() => { const T = self.__e2e; return { esp: { ...T.esp, lines: T.esp.lines.filter((l) => !l[1].startsWith('OK keyed=')).slice(-400) }, fc: { counts: T.fc.counts, motors: T.fc.motors.slice(-200) }, marks: T.marks, series: T.series } }) } catch (e) { result.tap_error = String(e) }
  result.ended = new Date().toISOString()
  save()
  log('saved', outFile)
  await app.close().catch(() => undefined)
}

// ---------------------------------------------------------------------------
async function snapshot() {
  return W(() => {
    const T = self.__e2e
    const s = T.state
    return {
      t: Date.now(), sCount: T.esp.sCount, sMaxGap: T.esp.sMaxGap, sGaps50: T.esp.sGaps50,
      att: T.fc.counts[108] || 0, rep: s.radio.replies, trig: s.radio.triggers, slots: s.esp.slots, link: s.esp.link,
    }
  })
}

function linkEndStats(lines) {
  const le = lines.filter((l) => l[1].startsWith('EV link_end')).map(([t, l]) => ({ t, ...Object.fromEntries(l.split(' ').slice(2).map((kv) => kv.split('=')).map(([k, v]) => [k, isNaN(+v) ? v : +v])) }))
  return le
}

async function soak() {
  // start the link with arming disallowed (allow_arm false), same options the UI uses otherwise
  await W(() => self.onmessage(new MessageEvent('message', { data: { type: 'start', power: 127, fofs_hz: -75000, timeout_ms: 300, allow_arm: false } })))
  await waitFor(async () => (await state())?.esp?.link, 10000, 'link up')
  const linkUpAt = Date.now()
  log('link up (arm disallowed)')
  await sleep(3000)
  await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].minimize())
  await sleep(500)
  result.minimized = await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].isMinimized())
  result.visibility_when_minimized = await page.evaluate(() => document.visibilityState)
  log('minimized', result.minimized, result.visibility_when_minimized)
  const a = await snapshot()
  const per = []
  const endAt = a.t + minutes * 60000
  let prev = a
  while (Date.now() < endAt) {
    await sleep(Math.min(60000, endAt - Date.now()))
    const b = await snapshot()
    const m = (b.t - prev.t) / 60000
    per.push({ min: per.length + 1, decoded_per_min: Math.round((b.rep - prev.rep) / m), triggers_per_min: Math.round((b.trig - prev.trig) / m), att_hz: +((b.att - prev.att) / ((b.t - prev.t) / 1000)).toFixed(1), s_hz: +((b.sCount - prev.sCount) / ((b.t - prev.t) / 1000)).toFixed(1), slots: b.slots, link: b.link, sMaxGap: +b.sMaxGap.toFixed(1), sGaps50: b.sGaps50 })
    log(JSON.stringify(per.at(-1)))
    prev = b
    save()
  }
  result.per_minute = per
  result.still_minimized = await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].isMinimized())
  await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].restore())
  await sleep(1000)
  const z = await snapshot()
  await page.getByRole('button', { name: 'Stop link' }).click()
  await waitFor(async () => !(await state())?.esp?.link, 5000, 'link stopped')
  await sleep(500)
  const T = await W(() => ({ linkTx: self.__e2e.esp.txOther.filter((l) => l[1].startsWith('LINK')).slice(-1)[0], lines: self.__e2e.esp.lines.filter((l) => /^EV link( |_end)/.test(l[1])), sGapsList: self.__e2e.esp.sGapsList, marks: self.__e2e.marks, series: self.__e2e.series }))
  const ends = linkEndStats(T.lines)
  const end = ends.at(-1) || {}
  // firmware slot counter, 1 Hz EV link lines: per-second increments while linked
  const evl = T.lines.filter((l) => l[1].startsWith('EV link slots=')).map(([t, l]) => [t, Number(/slots=(\d+)/.exec(l)[1])])
  const incs = []
  for (let i = 1; i < evl.length; i++) incs.push({ dt: evl[i][0] - evl[i - 1][0], d: evl[i][1] - evl[i - 1][1] })
  const elapsedMs = (end.t ?? Date.now()) - (T.linkTx ? T.linkTx[0] : linkUpAt)
  const elapsedSlots = elapsedMs / SLOT_MS
  const listen = (end.trig ?? 0) + (end.retry ?? 0)
  const expected = elapsedSlots - listen
  result.soak = {
    minutes, link_ms: elapsedMs, link_end: end,
    firmware_slots: end.slots, elapsed_slots: Math.round(elapsedSlots), listen_slots: listen, expected_keyed_slots: Math.round(expected),
    slots_ratio_vs_expected: end.slots ? +(end.slots / expected).toFixed(4) : null,
    ev_link_lines: evl.length, ev_link_min_inc: Math.min(...incs.map((x) => x.d)), ev_link_max_dt_ms: Math.max(...incs.map((x) => x.dt)),
    host_s_frames: z.sCount, host_s_hz: +(z.sCount / (elapsedMs / 1000)).toFixed(2), host_s_max_gap_ms: +z.sMaxGap.toFixed(1), host_s_gaps_over_50ms: z.sGaps50, host_s_gap_list: T.sGapsList,
    link_lost_count: T.marks.filter((m) => m.ev === 'state_link_false' && m.lost !== null && m.lost !== 'stopped').length,
    link_end_events: ends.map((e) => e.why),
    decoded_total: z.rep - a.rep, triggers_total: z.trig - a.trig,
    decoded_per_min: Math.round((z.rep - a.rep) / ((z.t - a.t) / 60000)),
    catch_rate: +((z.rep - a.rep) / Math.max(1, z.trig - a.trig)).toFixed(3),
    fc_attitude_hz: +((z.att - a.att) / ((z.t - a.t) / 1000)).toFixed(2),
    radio_age_ms_le_1000_frac: (() => { const s = T.series.filter((x) => x.t >= a.t && x.t <= z.t && x.age != null); return +(s.filter((x) => x.age <= 1000).length / Math.max(1, s.length)).toFixed(3) })(),
  }
  log('SOAK', JSON.stringify(result.soak, null, 1))
}

async function arm() {
  // battery must be absent: FC MSP vbat via the analog reply is not exposed; the caller checked MSP_BATTERY_STATE.
  await page.getByRole('button', { name: 'Settings' }).click()
  const thr = page.getByLabel('Max throttle, %')
  await thr.fill('15')
  await page.getByRole('button', { name: 'Settings' }).dispatchEvent('click')
  await waitFor(async () => !(await thr.isVisible()), 3000, 'settings closed')
  await page.getByRole('button', { name: 'Start link' }).click()
  await waitFor(async () => (await state())?.esp?.link, 10000, 'link up')
  log('link up via Start link button (allow_arm)')
  // wait until Betaflight sees the radio (RX failsafe cleared)
  await waitFor(async () => { const s = await state(); return s.fc.connected && s.fc.failsafe === false && !(s.fc.arming_disable || []).some((r) => /RXFAILSAFE|RX_FAILSAFE/.test(r)) }, 15000, 'BF RX ok')
  const pre = await state()
  result.pre_arm = { arming_disable: pre.fc.arming_disable, rc: pre.fc.rc, armok_stat: (await W(() => self.__e2e.esp.lines.filter((l) => l[1].startsWith('OK keyed=')).slice(-1)))[0] }
  log('pre-arm', JSON.stringify(result.pre_arm))

  const armOnce = async (label) => {
    await page.bringToFront()
    await page.keyboard.down('r')
    await sleep(1200)
    await page.keyboard.up('r')
    const ok = await waitFor(async () => (await state()).fc.armed === true, 4000, `${label}: Betaflight armed`).catch((e) => { log(String(e)); return false })
    const s = await state()
    const statArm = (await W(() => self.__e2e.esp.lines.filter((l) => l[1].startsWith('OK keyed=')).slice(-1)))[0]
    return { ok: !!ok, fc_armed: s.fc.armed, arming_disable: s.fc.arming_disable, stat: statArm, last_s: await W(() => self.__e2e.esp.lastS) }
  }

  result.arm1 = await armOnce('arm1')
  log('arm1', JSON.stringify(result.arm1))
  if (!result.arm1.ok) throw new Error('did not arm')
  await sleep(700) // past the 0.5 s arm-edge throttle hold
  // throttle ramp: hold W; the 15 % cap stops it at 1150
  const holdT0 = Date.now()
  await page.keyboard.down('w')
  // MSP_RC is AETR: throttle is rc[3]; the S line is TAER: throttle is its first value
  await waitFor(async () => (await state()).fc.rc[3] >= 1145, 5000, 'throttle at 1150 on the FC').catch((e) => log(String(e)))
  result.ramp_ms = Date.now() - holdT0
  await page.keyboard.up('w')
  const hold = []
  const holdStart = Date.now()
  while (Date.now() - holdStart < 3000) {
    const s = await state()
    const lastS = await W(() => self.__e2e.esp.lastS)
    hold.push({ t: Date.now() - holdStart, rc: s.fc.rc, motors: s.fc.motors, armed: s.fc.armed, s_line: lastS[1] })
    await sleep(250)
  }
  result.hold = hold
  result.hold_stat = (await W(() => self.__e2e.esp.lines.filter((l) => l[1].startsWith('OK keyed=')).slice(-1)))[0]
  log('hold sample', JSON.stringify(hold[Math.floor(hold.length / 2)]))
  // disarm with X
  await page.keyboard.press('x')
  const t0 = Date.now()
  await waitFor(async () => (await state()).fc.armed === false, 3000, 'Betaflight disarmed').catch((e) => log(String(e)))
  const sd = await state()
  result.disarm = { ms: Date.now() - t0, fc_armed: sd.fc.armed, rc: sd.fc.rc, motors: sd.fc.motors, last_s: await W(() => self.__e2e.esp.lastS) }
  log('disarm', JSON.stringify(result.disarm))
  await sleep(1500)

  // --- close the DevKit port while armed (throttle at minimum) and time the UI
  result.arm2 = await armOnce('arm2')
  log('arm2', JSON.stringify(result.arm2))
  await sleep(800)
  await page.evaluate(() => { window.__obs.armedAt = Date.now(); window.__obs.hits = {} })
  const closeInfo = await W(async () => {
    const p = self.__e2e.ports.esp
    const t = Date.now()
    self.__e2e.marks.push({ t, ev: 'close_requested' })
    self.__e2e.unplug('esp')
    return { t, how: 'stream-level unplug (reads/writes reject NetworkError)', port: !!p }
  })
  log('port close', JSON.stringify(closeInfo))
  // timeline for 3 s after the close: worker state (esp link, FC armed/failsafe/rc) every ~50 ms
  const timeline = []
  while (Date.now() - closeInfo.t < 3000) {
    const s = await state()
    timeline.push({ dt: Date.now() - closeInfo.t, link: s.esp.link, connected: s.esp.connected, lost: s.esp.lost_reason, fc_armed: s.fc.armed, fs: s.fc.failsafe, thr: s.fc.rc?.[0], arm_ch: s.fc.rc?.[6], motors: s.fc.motors })
    await sleep(50)
  }
  const firstAt = (pred) => timeline.find(pred)?.dt ?? null
  result.pull_timeline = timeline
  const obs = await page.evaluate(() => window.__obs)
  const marks = await W(() => self.__e2e.marks)
  const after = await W(() => self.__e2e.series.slice(-6))
  const sNow = await state()
  result.pull = {
    close: closeInfo,
    ui_link_lost_ms: obs.hits.link_lost ? obs.hits.link_lost - closeInfo.t : null,
    ui_disarmed_ms: obs.hits.disarmed ? obs.hits.disarmed - closeInfo.t : null,
    worker_marks: marks.filter((m) => m.t >= closeInfo.t - 10),
    state_after: { esp: sNow.esp, fc_armed: sNow.fc.armed, fc_failsafe: sNow.fc.failsafe, fc_rc: sNow.fc.rc, fc_dis: sNow.fc.arming_disable },
    series_after: after,
    banner: await page.evaluate(() => document.body.innerText.match(/Link lost[^\n]*/)?.[0] ?? null),
  }
  Object.assign(result.pull, {
    worker_link_false_ms: firstAt((x) => !x.link),
    fc_failsafe_ms: firstAt((x) => x.fs === true),
    fc_disarmed_ms: firstAt((x) => x.fc_armed === false),
    fc_arm_ch_low_ms: firstAt((x) => x.arm_ch !== undefined && x.arm_ch < 1500),
  })
  log('PULL', JSON.stringify({ ui_link_lost_ms: result.pull.ui_link_lost_ms, ui_disarmed_ms: result.pull.ui_disarmed_ms, banner: result.pull.banner, fc_armed: sNow.fc.armed, fc_failsafe: sNow.fc.failsafe }))
}
