// Hardware test, skipped unless D8TX_HW_PORT names a real serial device that no other process holds, e.g.
//   D8TX_HW_PORT=/dev/cu.usbserial-0001 pnpm --filter @d8tx/serial test node.hw
// Opens the device, checks a second open fails as in use (TIOCEXCL), and that it opens again after close.
import { describe, expect, it } from 'vitest'
import { PortInUseError } from '@d8tx/core'
import { NodeSerialPort } from './node.ts'

const dev = process.env.D8TX_HW_PORT
const baud = Number(process.env.D8TX_HW_BAUD ?? 921600)

describe.skipIf(!dev)('NodeSerialPort exclusive open (hardware)', () => {
  it('a second open of the same device fails with PortInUseError until the first closes', async () => {
    const a = new NodeSerialPort(dev!, baud)
    await a.open()
    try {
      const b = new NodeSerialPort(dev!, baud)
      await expect(b.open()).rejects.toBeInstanceOf(PortInUseError)
    } finally {
      await a.close()
    }
    const c = new NodeSerialPort(dev!, baud)
    await c.open()
    await c.close()
  }, 20000)
})
