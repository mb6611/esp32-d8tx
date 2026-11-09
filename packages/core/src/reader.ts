import { parseLine, parseTlmHeader, type Parsed, type TlmMeta } from './protocol.ts'

export type ReaderEvent =
  | { type: 'line'; text: string; parsed: Parsed }
  | { type: 'capture'; meta: TlmMeta; payload: Uint8Array }

const MAX_PAYLOAD = 65536
const NO_NEWLINE_FLUSH = 4096

/** Byte-oriented reader: lines plus `EV tlm ... bytes=N` + N payload bytes + "\n" (port of link.py `_read_loop`). */
export class Reader {
  private buf = new Uint8Array(0)
  private pending: TlmMeta | null = null

  feed(data: Uint8Array): ReaderEvent[] {
    const nb = new Uint8Array(this.buf.length + data.length)
    nb.set(this.buf)
    nb.set(data, this.buf.length)
    let buf = nb
    const out: ReaderEvent[] = []
    for (;;) {
      if (this.pending) {
        const nbytes = this.pending.bytes as number
        if (buf.length < nbytes + 1) break
        out.push({ type: 'capture', meta: this.pending, payload: buf.slice(0, nbytes) })
        buf = buf.subarray(nbytes + 1)
        this.pending = null
        continue
      }
      const i = buf.indexOf(10)
      if (i < 0) {
        if (buf.length > NO_NEWLINE_FLUSH) buf = buf.subarray(buf.length)
        break
      }
      const text = latin1Ascii(buf.subarray(0, i))
      buf = buf.subarray(i + 1)
      if (text.startsWith('EV tlm ')) {
        const meta = parseTlmHeader(text)
        const n = meta.bytes
        if (typeof n === 'number' && n > 0 && n <= MAX_PAYLOAD) {
          this.pending = meta
          continue
        }
      }
      out.push({ type: 'line', text, parsed: parseLine(text) })
    }
    this.buf = buf.slice()
    return out
  }
}

/** ascii decode with errors replaced by U+FFFD (python `decode("ascii","replace")`). */
function latin1Ascii(b: Uint8Array): string {
  let s = ''
  for (let i = 0; i < b.length; i++) s += b[i] < 128 ? String.fromCharCode(b[i]) : '\ufffd'
  return s
}
