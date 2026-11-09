// Hardware end-to-end runs of the real Electron app (test mode) against the DevKit and the drone FC.
//   node e2e/run.mjs soak [minutes]   link with arming disallowed, window minimized; per-minute link/telemetry stats
//   node e2e/run.mjs autolink         auto-link timings: connect, settings change, port loss, reload, app restart,
//                                     then a second instance while the first holds the ports (in use, takeover)
//   E2E_ALLOW_ARM=1 node e2e/run.mjs arm   arm via the gate, throttle 1150 for 3 s, disarm, then lose the DevKit port
// The UI flow is the app's: Pairing panel (port Select + Connect), the link starts by itself, Settings is the gear.
// Each instance runs on its own throwaway profile under $TMPDIR/d8tx-e2e (never the owner's app data). The tap forces
// allow_arm=false on every radio settings message unless the phase is arm. Props off, no battery (checked by the caller).
// Results: e2e/results/<phase>-<time>.json
import { _electron as electron } from 'playwright'
import { createRequire } from 'node:module'
import fs from 'node:fs'
import os from 'node:os'
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
const profiles = path.join(os.tmpdir(), 'd8tx-e2e')
fs.mkdirSync(outDir, { recursive: true })
const stamp = new Date().toISOString().replace(/[:.]/g, '-')
const outFile = path.join(outDir, `${phase}-${stamp}.json`)
const log = (...a) => console.log(new Date().toISOString().slice(11, 23), ...a)
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const result = { phase, started: new Date().toISOString(), esp_port: ESP, fc_port: FCP }
const save = () => fs.writeFileSync(outFile, JSON.stringify(result, null, 1))
const hasFc = fs.existsSync(FCP)

async function waitFor(fn, ms, what) {
  const t0 = Date.now()
  for (;;) {
    const v = await fn().catch(() => null)
    if (v) return v
    if (Date.now() - t0 > ms) throw new Error(`timeout waiting for ${what}`)
    await sleep(50)
  }
}

// --- app instances ----------------------------------------------------------------------------------------------

/** Launches the app on a profile dir (fresh: emptied first) and installs the worker tap. */
async function launch(tag, profile, { fresh = false } = {}) {
  const dir = path.join(profiles, profile)
  if (fresh) fs.rmSync(dir, { recursive: true, force: true })
  fs.mkdirSync(dir, { recursive: true })
  const app = await electron.launch({
    executablePath: require('electron'),
    args: [appDir, `--user-data-dir=${dir}`],
    cwd: appDir,
    env: { ...process.env, D8TX_ESP_PORT: ESP, D8TX_FC_PORT: FCP },
  })
  app.process().stdout.on('data', (d) => { for (const l of String(d).split('\n')) if (l.trim()) log(`[${tag} main]`, l) })
  app.process().stderr.on('data', (d) => { for (const l of String(d).split('\n')) if (/d8tx|rror/.test(l)) log(`[${tag} main!]`, l) })
  const page = await app.firstWindow()
  page.on('console', (m) => { if (m.type() === 'error') log(`[${tag} page error]`, m.text()) })
  const inst = { tag, app, page, profile: dir }
  await attach(inst)
  return inst
}

/** (Re)attaches to the page's worker after a launch or reload: tap, first state, arming disallowed. */
async function attach(inst) {
  const { page } = inst
  await page.waitForLoadState('domcontentloaded')
  inst.worker = page.workers()[0] || (await page.waitForEvent('worker', { timeout: 10000 }))
  inst.W = (fn, arg) => inst.worker.evaluate(fn, arg)
  inst.state = () => inst.W(() => self.__e2e?.state)
  log(inst.tag, 'tap', await inst.worker.evaluate(installTap))
  await waitFor(() => inst.state(), 5000, `${inst.tag} first state`)
  if (phase === 'arm') return
  // The UI's first radio message can reach the host before the tap: resend the saved settings with allow_arm=false.
  // A link already running with arming allowed restarts (recorded).
  const opts = await page.evaluate(() => { try { return JSON.parse(localStorage.getItem('d8tx.settings.v1') || '{}') } catch { return {} } })
  const s = await inst.state()
  inst.armFixRestart = !!(s.esp.link && s.esp.allow_arm)
  await inst.W((o) => self.onmessage(new MessageEvent('message', { data: { type: 'radio', power: o.power ?? 127, fofs_hz: o.fofs_hz ?? 0, timeout_ms: o.timeout_ms ?? 300 } })), opts)
}

async function closeApp(inst) {
  await inst.app.close().catch(() => undefined)
}

// --- UI helpers -------------------------------------------------------------------------------------------------

const comboName = (role) => (role === 'esp' ? 'ESP32 port' : 'Drone port')

async function openPairing(page) {
  const cb = page.getByRole('combobox', { name: 'ESP32 port' })
  if (!(await cb.isVisible().catch(() => false))) await page.getByRole('button', { name: /^Pairing/ }).click()
  await cb.waitFor({ state: 'visible', timeout: 3000 })
}

/** The Pairing panel column of one device: its port Select and Connect/Disconnect button (innermost enclosing div). */
const deviceBox = (page, role) => page.locator('div').filter({ has: page.getByRole('combobox', { name: comboName(role) }) }).last()

/** Clicks the device's Connect or Disconnect button. Connect without a granted port opens the chooser (test mode picks). */
async function clickDevice(page, role, name) {
  await openPairing(page)
  await deviceBox(page, role).getByRole('button', { name, exact: true }).click()
}

async function closePairing(page) {
  if (await page.getByRole('combobox', { name: 'ESP32 port' }).isVisible().catch(() => false)) await page.keyboard.press('Escape')
}

/** Opens Settings (gear), sets a numeric field, closes it. Returns the time the value was entered. */
async function setSetting(page, label, value) {
  await page.getByRole('button', { name: 'Settings' }).click()
  const f = page.getByLabel(label)
  await f.waitFor({ state: 'visible', timeout: 3000 })
  await f.fill(String(value))
  const t = Date.now()
  await page.keyboard.press('Escape')
  await waitFor(async () => !(await f.isVisible()), 3000, 'settings closed')
  return t
}

// --- measurements -----------------------------------------------------------------------------------------------

const up = (s) => !!(s?.esp?.link && s.esp.link_state === 'up')
/** Telemetry flowing: a decoded reply newer than 1 s, more replies than `base`. */
const tele = (s, base = 0) => (s?.radio?.replies ?? 0) > base && s.radio.age_ms != null && s.radio.age_ms < 1000

/** Times from t0 until the link is up and until telemetry flows (replies beyond `base`). */
async function timeLinkTele(inst, t0, what, base = 0, ms = 20000) {
  const r = {}
  await waitFor(async () => {
    const s = await inst.state()
    if (r.link_ms === undefined && up(s)) r.link_ms = Date.now() - t0
    if (r.link_ms !== undefined && r.telemetry_ms === undefined && tele(s, base)) r.telemetry_ms = Date.now() - t0
    return r.telemetry_ms !== undefined
  }, ms, `${inst.tag} ${what}: link and telemetry`).catch((e) => { r.error = String(e.message) })
  const s = await inst.state()
  r.power = s.esp.power
  r.allow_arm = s.esp.allow_arm
  log(inst.tag, what, JSON.stringify(r))
  return r
}

/** Link counters of an instance over `ms`: firmware slots and decoded replies per second, link ends, losses. */
async function linkWindow(inst, ms) {
  const snap = () => inst.W(() => {
    const T = self.__e2e
    return { t: Date.now(), slots: T.state.esp.slots, rep: T.state.radio.replies, link: T.state.esp.link, ends: T.esp.lines.filter((l) => l[1].startsWith('EV link_end')).length, stats: T.esp.lines.filter((l) => l[1].startsWith('OK keyed=')).length, sCount: T.esp.sCount, sMaxGap: T.esp.sMaxGap, losses: T.marks.filter((m) => m.ev === 'state_link_false').length }
  })
  const a = await snap()
  let allUp = true
  const end = a.t + ms
  while (Date.now() < end) {
    await sleep(250)
    if (!up(await inst.state())) allUp = false
  }
  const b = await snap()
  const sec = (b.t - a.t) / 1000
  return {
    seconds: +sec.toFixed(1),
    slots_per_s: +((b.slots - a.slots) / sec).toFixed(1),
    replies_per_s: +((b.rep - a.rep) / sec).toFixed(2),
    stat_replies_per_s: +((b.stats - a.stats) / sec).toFixed(2),
    s_frames_per_s: +((b.sCount - a.sCount) / sec).toFixed(1),
    s_max_gap_ms: +b.sMaxGap.toFixed(1),
    link_end_events: b.ends - a.ends,
    link_losses: b.losses - a.losses,
    link_up_throughout: allUp,
  }
}

const pageText = (page) => page.evaluate(() => document.body.innerText)

// --- phases -----------------------------------------------------------------------------------------------------

const insts = []
try {
  if (phase === 'soak') await soak()
  else if (phase === 'autolink') await autolink()
  else if (phase === 'arm') {
    if (process.env.E2E_ALLOW_ARM !== '1') throw new Error('arm phase arms the drone: set E2E_ALLOW_ARM=1 (props off, no battery)')
    await arm()
  } else throw new Error(`unknown phase ${phase}`)
} catch (e) {
  result.error = String((e && e.stack) || e)
  log('ERROR', result.error)
} finally {
  const main = insts.at(-1)
  if (main?.W) {
    try { result.tap = await main.W(() => { const T = self.__e2e; return { esp: { ...T.esp, lines: T.esp.lines.filter((l) => !l[1].startsWith('OK keyed=')).slice(-400) }, fc: { counts: T.fc.counts, motors: T.fc.motors.slice(-200) }, marks: T.marks, radioMsgs: T.radioMsgs, series: T.series.slice(-300) } }) } catch (e) { result.tap_error = String(e) }
  }
  result.ended = new Date().toISOString()
  save()
  log('saved', outFile)
  for (const i of insts) await closeApp(i)
}

/** Fresh instance, Connect DevKit (and drone USB when present) in the Pairing panel; the link starts by itself. */
async function freshConnected(tag, profile) {
  const A = await launch(tag, profile, { fresh: true })
  insts.push(A)
  await openPairing(A.page)
  const t = Date.now()
  await clickDevice(A.page, 'esp', 'Connect')
  const r = await timeLinkTele(A, t, 'connect')
  r.info = (await A.state()).esp.info
  if (hasFc) {
    const tf = Date.now()
    await clickDevice(A.page, 'fc', 'Connect')
    await waitFor(async () => (await A.state())?.fc?.connected, 10000, 'FC connected')
    r.fc_connect_ms = Date.now() - tf
  }
  await closePairing(A.page)
  return { A, connect: r }
}

async function snapshot(inst) {
  return inst.W(() => {
    const T = self.__e2e
    const s = T.state
    return {
      t: Date.now(), sCount: T.esp.sCount, sMaxGap: T.esp.sMaxGap, sGaps50: T.esp.sGaps50,
      att: T.fc.counts[108] || 0, rep: s.radio.replies, trig: s.radio.triggers, slots: s.esp.slots, link: s.esp.link,
    }
  })
}

function linkEndStats(lines) {
  return lines.filter((l) => l[1].startsWith('EV link_end')).map(([t, l]) => ({ t, ...Object.fromEntries(l.split(' ').slice(2).map((kv) => kv.split('=')).map(([k, v]) => [k, isNaN(+v) ? v : +v])) }))
}

async function soak() {
  const { A, connect } = await freshConnected('A', 'soak')
  result.connect = connect
  if (connect.error) throw new Error(connect.error)
  const linkUpAt = Date.now()
  log('link up (arm disallowed)', JSON.stringify(connect))
  await sleep(3000)
  await A.app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].minimize())
  await sleep(500)
  result.minimized = await A.app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].isMinimized())
  result.visibility_when_minimized = await A.page.evaluate(() => document.visibilityState)
  log('minimized', result.minimized, result.visibility_when_minimized)
  const a = await snapshot(A)
  const per = []
  const endAt = a.t + minutes * 60000
  let prev = a
  while (Date.now() < endAt) {
    await sleep(Math.min(60000, endAt - Date.now()))
    const b = await snapshot(A)
    const m = (b.t - prev.t) / 60000
    per.push({ min: per.length + 1, decoded_per_min: Math.round((b.rep - prev.rep) / m), triggers_per_min: Math.round((b.trig - prev.trig) / m), att_hz: +((b.att - prev.att) / ((b.t - prev.t) / 1000)).toFixed(1), s_hz: +((b.sCount - prev.sCount) / ((b.t - prev.t) / 1000)).toFixed(1), slots: b.slots, link: b.link, sMaxGap: +b.sMaxGap.toFixed(1), sGaps50: b.sGaps50 })
    log(JSON.stringify(per.at(-1)))
    prev = b
    save()
  }
  result.per_minute = per
  result.still_minimized = await A.app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].isMinimized())
  await A.app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].restore())
  await sleep(1000)
  const z = await snapshot(A)
  // Disconnect in the Pairing panel: stops transmitting (STOP) and closes the port
  await clickDevice(A.page, 'esp', 'Disconnect')
  await waitFor(async () => !(await A.state())?.esp?.link, 5000, 'link stopped')
  await sleep(500)
  const T = await A.W(() => ({ linkTx: self.__e2e.esp.txOther.filter((l) => l[1].startsWith('LINK')).slice(-1)[0], lines: self.__e2e.esp.lines.filter((l) => /^EV link( |_end)/.test(l[1])), sGapsList: self.__e2e.esp.sGapsList, marks: self.__e2e.marks, series: self.__e2e.series }))
  const ends = linkEndStats(T.lines)
  const end = ends.at(-1) || {}
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
    ev_link_lines: evl.length, ev_link_min_inc: incs.length ? Math.min(...incs.map((x) => x.d)) : null, ev_link_max_dt_ms: incs.length ? Math.max(...incs.map((x) => x.dt)) : null,
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

async function autolink() {
  // 1. connect -> link + telemetry
  let { A, connect } = await freshConnected('A', 'autolink-a')
  result.connect = connect
  save()

  // 2. settings change (Power 127 -> 100) -> the link restarts with it
  await sleep(3000)
  const rep0 = (await A.state()).radio.replies
  const tSet = await setSetting(A.page, 'Power (0–127)', 100)
  const r2 = {}
  await waitFor(async () => {
    const s = await A.state()
    if (r2.link_down_ms === undefined && !s.esp.link) r2.link_down_ms = Date.now() - tSet
    if (r2.link_ms === undefined && up(s) && s.esp.power === 100) r2.link_ms = Date.now() - tSet
    if (r2.link_ms !== undefined && r2.telemetry_ms === undefined && tele(s, rep0) && s.radio.age_ms < Date.now() - tSet) r2.telemetry_ms = Date.now() - tSet
    return r2.telemetry_ms !== undefined
  }, 20000, 'settings restart').catch((e) => { r2.error = String(e.message) })
  r2.note = 'from the field edit; includes the UI 600 ms settings debounce'
  r2.lines = await A.W((t) => self.__e2e.esp.txOther.filter((l) => l[0] >= t && /^(STOP|LINK|FOFS|ARMOK)/.test(l[1])).map((l) => l[1]), tSet)
  result.settings_change = r2
  log('settings change', JSON.stringify(r2))
  save()

  // 3. simulated port loss (reads and writes fail like an unplug) -> reopen and relink
  await sleep(3000)
  const tLoss = await A.W(() => { const t = Date.now(); self.__e2e.marks.push({ t, ev: 'unplug' }); self.__e2e.unplug('esp'); return t })
  const r3 = {}
  await waitFor(async () => {
    const s = await A.state()
    if (r3.lost_ms === undefined && !s.esp.link) { r3.lost_ms = Date.now() - tLoss; r3.lost_state = s.esp.link_state; r3.lost_reason = s.esp.lost_reason ?? s.esp.retry_reason }
    if (r3.lost_ms !== undefined && r3.link_ms === undefined && up(s)) r3.link_ms = Date.now() - tLoss
    if (r3.link_ms !== undefined && tele(s) && s.radio.age_ms < Date.now() - tLoss - r3.link_ms + 1000) r3.telemetry_ms ??= Date.now() - tLoss
    return r3.telemetry_ms !== undefined
  }, 20000, 'relink after port loss').catch((e) => { r3.error = String(e.message) })
  result.port_loss = r3
  log('port loss', JSON.stringify(r3))
  save()

  // 4. reload -> the page reconnects the saved ports by itself, settings kept
  await sleep(3000)
  const tRel = Date.now()
  await A.page.reload()
  await attach(A)
  const r4 = await timeLinkTele(A, tRel, 'reload')
  r4.arm_fix_restart = A.armFixRestart
  r4.settings_kept = r4.power === 100
  if (hasFc) r4.fc_connected = !!(await waitFor(async () => (await A.state())?.fc?.connected, 10000, 'FC after reload').catch(() => false))
  result.reload = r4
  save()

  // 5. app restart -> auto reconnect
  await sleep(3000)
  const tQuit = Date.now()
  await closeApp(A)
  insts.splice(insts.indexOf(A), 1)
  result.app_close_ms = Date.now() - tQuit
  const tStart = Date.now()
  A = await launch('A2', 'autolink-a')
  insts.push(A)
  const r5 = await timeLinkTele(A, tStart, 'app restart')
  r5.arm_fix_restart = A.armFixRestart
  r5.settings_kept = r5.power === 100
  if (hasFc) r5.fc_connected = !!(await waitFor(async () => (await A.state())?.fc?.connected, 10000, 'FC after restart').catch(() => false))
  result.app_restart = r5
  save()

  // 6. second instance while A holds the ports: B shows in use and A's link is undisturbed; close A -> B takes over
  await sleep(2000)
  const base = await linkWindow(A, 10000)
  log('A baseline', JSON.stringify(base))
  const B = await launch('B', 'autolink-b', { fresh: true })
  insts.push(B)
  await openPairing(B.page)
  const tB = Date.now()
  await clickDevice(B.page, 'esp', 'Connect')
  const r6 = { a_baseline: base }
  await waitFor(async () => (await B.state())?.esp?.in_use, 10000, 'B esp in_use')
  r6.b_esp_in_use_ms = Date.now() - tB
  await waitFor(async () => /DevKit in use by another app or tab/.test(await pageText(B.page)), 5000, 'B in-use text')
  r6.b_esp_text_ms = Date.now() - tB
  if (hasFc) {
    const tf = Date.now()
    await clickDevice(B.page, 'fc', 'Connect')
    await waitFor(async () => (await B.state())?.fc?.in_use, 10000, 'B fc in_use')
    await waitFor(async () => /Drone USB in use by another app or tab/.test(await pageText(B.page)), 5000, 'B fc in-use text')
    r6.b_fc_in_use_ms = Date.now() - tf
  }
  r6.b_errors = await B.W(() => self.__e2e.marks.filter((m) => m.ev === 'worker_error'))
  r6.a_during_b = await linkWindow(A, 20000)
  const bs = await B.state()
  r6.b_state = { link_state: bs.esp.link_state, retry_reason: bs.esp.retry_reason, attempt: bs.esp.attempt, connected: bs.esp.connected, fc_in_use: bs.fc.in_use }
  r6.b_text = (await pageText(B.page)).split('\n').filter((l) => /in use/i.test(l))
  log('A during B', JSON.stringify(r6.a_during_b), 'B', JSON.stringify(r6.b_state))
  await B.page.screenshot({ path: path.join(outDir, `autolink-${stamp}-b-in-use.png`) }).catch(() => undefined)
  save()
  const tClose = Date.now()
  await closeApp(A)
  insts.splice(insts.indexOf(A), 1)
  r6.takeover = await timeLinkTele(B, tClose, 'takeover after A closed')
  if (hasFc) {
    r6.takeover.fc_connected = !!(await waitFor(async () => (await B.state())?.fc?.connected, 10000, 'B FC').catch(() => false))
    r6.takeover.fc_ms = Date.now() - tClose
  }
  r6.b_after = await linkWindow(B, 5000)
  result.two_instances = r6
  log('two instances', JSON.stringify(r6))
  save()
  await clickDevice(B.page, 'esp', 'Disconnect')
  await waitFor(async () => !(await B.state())?.esp?.link, 5000, 'B link stopped')
}

async function arm() {
  // arming allowed for this phase only: the tap passes allow_arm through
  const { A, connect } = await freshConnected('A', 'arm')
  result.connect = connect
  await A.W(() => { self.__e2e.noArm = false })
  await setSetting(A.page, 'Max throttle, %', 15)
  await A.W(() => self.onmessage(new MessageEvent('message', { data: { type: 'radio', power: 127, fofs_hz: 0, timeout_ms: 300, allow_arm: true } })))
  await waitFor(async () => { const s = await A.state(); return up(s) && s.esp.allow_arm }, 10000, 'link up with arming allowed')
  const { page } = A
  const state = A.state
  const W = A.W
  await page.evaluate(() => {
    window.__obs = { armedAt: null, hits: {} }
    const check = () => {
      const o = window.__obs
      if (o.armedAt === null) return
      const txt = document.body.innerText
      for (const [k, re] of [['link_lost', /Radio link lost/], ['disarmed', /\bDISARMED\b/]]) if (!o.hits[k] && re.test(txt)) o.hits[k] = Date.now()
    }
    new MutationObserver(check).observe(document.body, { subtree: true, childList: true, characterData: true })
  })
  await waitFor(async () => { const s = await state(); return s.fc.connected && s.fc.failsafe === false && !(s.fc.arming_disable || []).some((r) => /RXFAILSAFE|RX_FAILSAFE/.test(r)) }, 15000, 'BF RX ok')
  const armOnce = async (label) => {
    await page.bringToFront()
    await page.keyboard.down('r')
    await sleep(1200)
    await page.keyboard.up('r')
    const ok = await waitFor(async () => (await state()).fc.armed === true, 4000, `${label}: Betaflight armed`).catch((e) => { log(String(e)); return false })
    const s = await state()
    return { ok: !!ok, fc_armed: s.fc.armed, arming_disable: s.fc.arming_disable, last_s: await W(() => self.__e2e.esp.lastS) }
  }
  result.arm1 = await armOnce('arm1')
  log('arm1', JSON.stringify(result.arm1))
  if (!result.arm1.ok) throw new Error('did not arm')
  await sleep(700)
  const holdT0 = Date.now()
  await page.keyboard.down('w')
  await waitFor(async () => (await state()).fc.rc[3] >= 1145, 5000, 'throttle at 1150 on the FC').catch((e) => log(String(e)))
  result.ramp_ms = Date.now() - holdT0
  await page.keyboard.up('w')
  await sleep(3000)
  await page.keyboard.press('x')
  const t0 = Date.now()
  await waitFor(async () => (await state()).fc.armed === false, 3000, 'Betaflight disarmed').catch((e) => log(String(e)))
  result.disarm = { ms: Date.now() - t0, fc_armed: (await state()).fc.armed }
  await sleep(1500)
  result.arm2 = await armOnce('arm2')
  await sleep(800)
  await page.evaluate(() => { window.__obs.armedAt = Date.now(); window.__obs.hits = {} })
  const tc = await W(() => { const t = Date.now(); self.__e2e.marks.push({ t, ev: 'unplug' }); self.__e2e.unplug('esp'); return t })
  await sleep(3000)
  const obs = await page.evaluate(() => window.__obs)
  const s = await state()
  result.pull = { ui_link_lost_ms: obs.hits.link_lost ? obs.hits.link_lost - tc : null, ui_disarmed_ms: obs.hits.disarmed ? obs.hits.disarmed - tc : null, fc_armed: s.fc.armed, fc_failsafe: s.fc.failsafe, esp: { link_state: s.esp.link_state, link: s.esp.link } }
  log('PULL', JSON.stringify(result.pull))
}
