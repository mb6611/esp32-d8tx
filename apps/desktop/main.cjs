'use strict'
const { app, BrowserWindow, protocol, net, session, dialog } = require('electron')
const path = require('node:path')
const fs = require('node:fs')
const { pathToFileURL } = require('node:url')

// USB IDs per role; keep in step with USB_DEVICES in packages/serial/src/web.ts (DevKits ship CP2102, CH340 or CH9102).
const ESP = { ids: [[0x10c4, 0xea60], [0x1a86, 0x7523], [0x1a86, 0x55d4]], env: 'D8TX_ESP_PORT', name: 'DevKit' }
const FC = { ids: [[0x0483, 0x5740]], env: 'D8TX_FC_PORT', name: 'FC' }
const SCHEME = 'app'
const HOST = 'd8tx'

protocol.registerSchemesAsPrivileged([
  { scheme: SCHEME, privileges: { standard: true, secure: true, supportFetchAPI: true, stream: true, corsEnabled: true } },
])

const webRoot = app.isPackaged
  ? path.join(process.resourcesPath, 'web')
  : path.join(__dirname, '..', 'web', 'dist')

// Minimal valid empty wasm module, used by probe.html.
const EMPTY_WASM = Buffer.from([0x00, 0x61, 0x73, 0x6d, 0x01, 0x00, 0x00, 0x00])

const num = (v) => (typeof v === 'string' ? parseInt(v, v.startsWith('0x') ? 16 : 10) : v)

function roleOf(filters) {
  for (const f of filters || []) {
    const v = num(f.usbVendorId ?? f.vendorId), p = num(f.usbProductId ?? f.productId)
    for (const r of [ESP, FC]) if (r.ids.some(([vid, pid]) => v === vid && (p === undefined || p === pid))) return r
  }
  return null
}

function matches(port, role) {
  const v = num(port.vendorId), p = num(port.productId)
  return role.ids.some(([vid, pid]) => v === vid && p === pid)
}

function serveFile(root, rel) {
  const full = path.normalize(path.join(root, rel))
  if (!full.startsWith(root)) return new Response('forbidden', { status: 403 })
  return net.fetch(pathToFileURL(full).toString())
}

function registerProtocol() {
  protocol.handle(SCHEME, (request) => {
    const url = new URL(request.url)
    if (url.host !== HOST) return new Response('not found', { status: 404 })
    let p = decodeURIComponent(url.pathname)
    if (p === '/__desktop/probe.wasm') {
      return new Response(EMPTY_WASM, { headers: { 'content-type': 'application/wasm' } })
    }
    if (p.startsWith('/__desktop/')) return serveFile(__dirname, p.slice('/__desktop/'.length))
    if (p === '/' || p === '') p = '/index.html'
    return serveFile(webRoot, p)
  })
}

function setupSession(ses) {
  ses.setPermissionCheckHandler((_wc, permission) => permission === 'serial' || permission === 'clipboard-sanitized-write')
  ses.setPermissionRequestHandler((_wc, permission, cb) => cb(permission === 'serial'))
  ses.setDevicePermissionHandler((d) => d.deviceType === 'serial')
  ses.on('select-serial-port', async (event, portList, wc, callback) => {
    event.preventDefault()
    if (process.env.D8TX_SELFTEST) console.log('[d8tx] select-serial-port', JSON.stringify(portList), JSON.stringify(wc.__lastFilters))
    // Chromium already filters portList by the request's filters, so derive the role from it; the preload's
    // filter IPC can land after this event and then holds the previous request's filters.
    const listRoles = [ESP, FC].filter((r) => portList.length && portList.every((p) => matches(p, r)))
    const role = listRoles.length === 1 ? listRoles[0] : roleOf(wc.__lastFilters)
    const candidates = role ? portList.filter((p) => matches(p, role)) : portList
    const forced = role && process.env[role.env]
    let pick
    if (forced) {
      pick = candidates.find((p) => p.portName === forced || p.portName === path.basename(forced) || forced.endsWith(p.portName)) || candidates[0]
      console.log(`[d8tx] test mode ${role.name}: ${pick ? pick.portName : 'none'}`)
    } else if (candidates.length === 1 && process.env.D8TX_AUTOPICK) {
      pick = candidates[0]
    } else if (candidates.length) {
      const { response } = await dialog.showMessageBox({
        type: 'question',
        message: `Select ${role ? role.name : 'serial'} port`,
        buttons: [...candidates.map((p) => `${p.displayName || p.portName} (${p.portName})`), 'Cancel'],
        cancelId: candidates.length,
        defaultId: 0,
      })
      pick = candidates[response]
    }
    callback(pick ? pick.portId : '')
  })
  ses.on('serial-port-added', () => {})
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1200,
    height: 800,
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      backgroundThrottling: false,
    },
  })
  // Record the filters of the pending requestPort() call (via preload) so the
  // main process can tell DevKit from FC.
  const { ipcMain } = require('electron')
  ipcMain.on('d8tx:filters', (e, filters) => { e.sender.__lastFilters = filters })
  const target = process.env.D8TX_PAGE || (process.env.D8TX_MOCK ? 'index.html?mock=1' : 'index.html')
  win.loadURL(`${SCHEME}://${HOST}/${target.startsWith('__') ? '' : ''}${target}`)
  if (process.env.D8TX_SELFTEST) {
    // Headless-ish check used by agents: report load result and probe output, then quit.
    win.webContents.on('console-message', (_e, ...a) => console.log('[page]', ...a.map((x) => (typeof x === 'object' ? x.message : x))))
    win.webContents.once('did-fail-load', (_e, c, d) => { console.log('SELFTEST load-failed', c, d); app.exit(2) })
    win.webContents.once('did-finish-load', async () => {
      await new Promise((r) => setTimeout(r, Number(process.env.D8TX_SELFTEST_MS || 3000)))
      if (process.env.D8TX_SELFTEST_PICK) {
        const f = process.env.D8TX_SELFTEST_PICK === 'fc' ? '{usbVendorId:0x0483,usbProductId:0x5740}' : '{usbVendorId:0x10c4,usbProductId:0xea60}'
        const r = await win.webContents.executeJavaScript(`navigator.serial.requestPort({filters:[${f}]}).then(p=>JSON.stringify(p.getInfo()),e=>'ERR '+e)`, true)
        console.log('SELFTEST pick', process.env.D8TX_SELFTEST_PICK, r)
      }
      const info = await win.webContents.executeJavaScript('JSON.stringify({title: document.title, probe: window.__probe || null, root: document.getElementById("root") ? document.getElementById("root").children.length : -1, text: document.body.innerText.slice(0, 200)})')
      console.log('SELFTEST', info)
      app.exit(0)
    })
  }
  if (process.env.D8TX_DEVTOOLS) win.webContents.openDevTools({ mode: 'detach' })
  return win
}

app.whenReady().then(() => {
  registerProtocol()
  setupSession(session.defaultSession)
  createWindow()
  app.on('activate', () => { if (!BrowserWindow.getAllWindows().length) createWindow() })
})
app.on('window-all-closed', () => app.quit())
