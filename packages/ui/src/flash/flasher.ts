// Writes the bundled d8tx images to the DevKit with esptool-js on the UI thread (the worker has released the port).
// Classic ESP32 behind a CP2102: esptool's default reset (DTR/RTS) enters the ROM bootloader, the stub writes
// bootloader, partition table and app only (never erase-all, so NVS and the identity survive), verifies each image by
// MD5, then a hard reset (RTS) boots the new firmware.
import { ESPLoader, Transport, type FlashFreqValues, type FlashModeValues, type FlashSizeValues } from 'esptool-js'
import { NVS_RANGE, type Image, type Manifest } from './bundle'
import { md5 } from './md5'

/** Flash write baud: the CP2102's ceiling (2 Mbaud fails on this board); the ROM talks 115200. */
export const FLASH_BAUD = 921600

export interface FlashProgress {
  step: 'connecting' | 'writing' | 'resetting'
  /** 0..1 over all images */
  fraction: number
  detail?: string
}

/** A Web Serial port as esptool-js wants it (the UI thread's SerialPort for the DevKit). */
export type FlashPort = ConstructorParameters<typeof Transport>[0]

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

/**
 * Boots the flashed app: EN pulsed low through RTS with IO0 high (DTR off), as esptool.py's hard reset does.
 * esptool-js 0.7's after('hard_reset') only releases RTS (it never asserts it), which left the chip running the
 * flasher stub on this board.
 */
async function hardReset(t: Transport): Promise<void> {
  await t.setSignals(false, true)
  await sleep(100)
  await t.setSignals(false, false)
  await sleep(50)
}

export async function flashDevKit(port: FlashPort, m: Manifest, images: Image[], onProgress: (p: FlashProgress) => void, log: (s: string) => void = () => undefined): Promise<void> {
  for (const im of images) if (im.address < NVS_RANGE[1] && im.address + im.data.length > NVS_RANGE[0]) throw new Error(`refusing to overwrite NVS with ${im.name}`)
  const transport = new Transport(port, false)
  const terminal = { clean: () => undefined, writeLine: (s: string) => log(s), write: (s: string) => log(s) }
  const loader = new ESPLoader({ transport, baudrate: FLASH_BAUD, romBaudrate: 115200, terminal })
  let opened = false
  try {
    onProgress({ step: 'connecting', fraction: 0, detail: 'resetting into the bootloader' })
    opened = true
    const chip = await loader.main('default_reset')
    if (loader.chip.CHIP_NAME !== 'ESP32') throw new Error(`this is a ${loader.chip.CHIP_NAME} (${chip}), not a classic ESP32 DevKit`)
    const total = images.reduce((s, im) => s + im.data.length, 0)
    const before = (i: number) => images.slice(0, i).reduce((s, im) => s + im.data.length, 0)
    onProgress({ step: 'writing', fraction: 0, detail: chip })
    await loader.writeFlash({
      fileArray: images.map((im) => ({ data: im.data, address: im.address })),
      flashMode: m.flash.flash_mode as FlashModeValues,
      flashFreq: m.flash.flash_freq as FlashFreqValues,
      flashSize: m.flash.flash_size as FlashSizeValues,
      eraseAll: false,
      compress: true,
      reportProgress: (i, written, size) =>
        onProgress({ step: 'writing', fraction: (before(i) + (size ? (written / size) * images[i].data.length : 0)) / total, detail: images[i]?.name }),
      calculateMD5Hash: md5,
    })
    onProgress({ step: 'resetting', fraction: 1 })
    await hardReset(transport)
  } catch (e) {
    // leave the chip running whatever it has rather than parked in the bootloader or the stub
    if (opened) await hardReset(transport).catch(() => undefined)
    throw e
  } finally {
    if (opened) await transport.disconnect().catch(() => undefined)
  }
}
