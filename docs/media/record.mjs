// Records the mock-mode app (vite preview on :4173) to docs/media/raw.webm + screenshots. Needs local Chrome.
import { createRequire } from 'node:module'
const require = createRequire(new URL('../../apps/desktop/package.json', import.meta.url))
const { chromium } = require('playwright')
const out = new URL('./', import.meta.url).pathname
const mode = process.argv[2] ?? 'shot'
const browser = await chromium.launch({ channel: 'chrome' })
const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1,
  ...(mode === 'video' ? { recordVideo: { dir: out + 'tmp', size: { width: 1280, height: 800 } } } : {}) })
const page = await ctx.newPage()
page.on('console', (m) => console.log('console', m.text()))
// The mock drone reports a fixed attitude; swing it so the 3D drone visibly tilts in the recording (patches only the served copy).
await page.route(/worker-.*\.js/, async (route) => {
  const r = await route.fetch()
  const body = (await r.text()).replace('attitude:[1.5,-2,90]', 'get attitude(){const t=Date.now()/1e3;return[22*Math.sin(t*1.9),14*Math.sin(t*1.2+1),90+25*Math.sin(t*.6)]}')
  await route.fulfill({ response: r, body })
})
// Recording only: hide the mock badge and simulated-port wording (the app always shows them in ?mock=1).
await page.addInitScript(() => {
  const fix = () => {
    const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT)
    for (let n = w.nextNode(); n; n = w.nextNode()) {
      const t = n.nodeValue ?? ''
      if (t.trim() === 'MOCK' || t.startsWith('Simulated link')) n.parentElement?.style.setProperty('display', 'none')
      else if (t === 'Simulated DevKit') n.nodeValue = 'ESP32 DevKit (CP2102)'
      else if (t === 'Simulated drone') n.nodeValue = 'Betaflight FC (STM32 VCP)'
    }
  }
  new MutationObserver(fix).observe(document, { subtree: true, childList: true, characterData: true })
})
await page.goto('http://localhost:4173/?mock=1')
await page.waitForTimeout(1200)
const hold = async (keys, ms) => { for (const k of keys) await page.keyboard.down(k); await page.waitForTimeout(ms); for (const k of keys) await page.keyboard.up(k) }
if (mode === 'shot') {
  await page.getByRole('button', { name: /Pairing/ }).click()
  await page.waitForTimeout(600)
  await page.screenshot({ path: out + 'pairing.png' })
  await page.keyboard.press('Escape')
  await page.mouse.click(640, 700)
  await page.waitForTimeout(300)
  await hold(['r'], 1300)
  await hold(['w'], 1500)
  await hold(['ArrowRight', 'ArrowUp'], 900)
  await page.screenshot({ path: out + 'sticks.png' })
} else {
  await page.getByRole('button', { name: /Pairing/ }).click()
  await page.waitForTimeout(1500)
  await page.keyboard.press('Escape')
  await page.mouse.click(640, 700)
  await page.waitForTimeout(500)
  await hold(['r'], 1300)
  await hold(['w'], 1400)
  await hold(['ArrowRight'], 900)
  await hold(['ArrowLeft'], 1100)
  await hold(['ArrowUp'], 800)
  await hold(['ArrowDown'], 900)
  await hold(['a'], 600)
  await hold(['d'], 600)
  await page.waitForTimeout(600)
}
await ctx.close(); await browser.close()
