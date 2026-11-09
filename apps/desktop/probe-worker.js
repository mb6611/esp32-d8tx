const r = { ua: self.navigator.userAgent }
try {
  r.wasmBytes = (await (await fetch(new URL('probe.wasm', self.location.href))).arrayBuffer()).byteLength
  await WebAssembly.instantiate(await (await fetch(new URL('probe.wasm', self.location.href))).arrayBuffer())
  r.wasmOk = true
} catch (e) { r.wasmOk = String(e) }
r.serialInSelf = 'serial' in self
r.serialInNavigator = 'serial' in navigator
r.navigatorSerial = typeof navigator.serial
try { r.ports = (await navigator.serial.getPorts()).length } catch (e) { r.getPortsError = String(e) }
postMessage(r)
