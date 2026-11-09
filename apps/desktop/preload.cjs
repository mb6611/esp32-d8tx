'use strict'
const { ipcRenderer } = require('electron')
// Wrap navigator.serial.requestPort so the main process learns which role's
// VID/PID filter is active when it fires 'select-serial-port'. The preload
// runs in an isolated world; the page's own navigator.serial is patched by
// injecting a main-world script.
const { webFrame } = require('electron')
webFrame.executeJavaScript(`(() => {
  if (!navigator.serial || navigator.serial.__d8tx) return
  const orig = navigator.serial.requestPort.bind(navigator.serial)
  navigator.serial.requestPort = (opts) => { window.postMessage({ __d8txFilters: (opts && opts.filters) || [] }, '*'); return orig(opts) }
  navigator.serial.__d8tx = true
})()`)
window.addEventListener('message', (e) => {
  if (e.source === window && e.data && e.data.__d8txFilters) ipcRenderer.send('d8tx:filters', e.data.__d8txFilters)
})
