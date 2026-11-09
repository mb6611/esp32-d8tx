import { describe, expect, test } from 'vitest'
import * as P from './protocol.ts'
import { Reader } from './reader.ts'
import { each, hex, toHex, vec } from './vectors.ts'

describe('protocol vectors', () => {
  const cmds = vec('commands')
  test('constants', () => {
    const c = cmds.constants
    expect([P.LO, P.MID, P.HI, P.ARM_CH, P.ARM_LIMIT, P.SLOT_S, P.DEFAULT_FOFS_HZ, P.MAX_LINE]).toEqual([
      c.LO, c.MID, c.HI, c.ARM_CH, c.ARM_LIMIT, c.SLOT_S, c.DEFAULT_FOFS_HZ, c.MAX_LINE,
    ])
    expect([...P.TXID]).toEqual(c.TXID)
    expect(P.TLM_RECIPE).toBe(c.TLM_RECIPE)
  })
  each(cmds.sticks, (v) => {
    if (v.error) return expect(() => P.fmtSticks(v.ch, v.allow_arm)).toThrow(v.error)
    const r = P.fmtSticks(v.ch, v.allow_arm)
    expect(r.line).toBe(v.line)
    expect(r.channels).toEqual(v.channels)
  })
  each(cmds.check_line, (v) => {
    if (v.ok) expect(P.checkLine(v.line)).toBe(v.line)
    else expect(() => P.checkLine(v.line)).toThrow(v.error)
  })
  each(vec('replies'), (v) => expect(P.parseLine(v.line)).toEqual(v.parsed), (v) => JSON.stringify(v.line))
  const th = vec('tlm_header')
  each(th.headers, (v) => expect(P.parseTlmHeader(v.line)).toEqual(v.meta))
  each(th.payload_ok, (v) => expect(P.payloadOk(v.meta, hex(v.payload))).toBe(v.ok))
  each(vec('unpack4'), (v) => {
    expect(toHex(new Uint8Array(P.unpack4(hex(v.payload)).buffer))).toBe(v.iq8)
  })
  test('nextTid', () => {
    for (const v of vec('tid_rule')) expect(P.nextTid(v.sent, v.reply_tid)).toBe(v.next)
  })
})

describe('reader vectors', () => {
  each(vec('reader'), (v) => {
    const r = new Reader()
    const got: any[] = []
    for (const c of v.chunks) got.push(...r.feed(hex(c)))
    const norm = got.map((e) =>
      e.type === 'capture' ? { type: 'capture', meta: e.meta, payload: toHex(e.payload) } : { type: 'line', text: e.text, parsed: e.parsed },
    )
    expect(norm).toEqual(v.events)
  })
})
