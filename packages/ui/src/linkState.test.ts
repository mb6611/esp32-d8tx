import { describe, expect, it } from 'vitest'
import { ESP_IN_USE, linkText, lostWhy } from './linkState'

describe('link state text', () => {
  it('names a DevKit held by another app or tab', () => {
    const esp = { link_state: 'lost', in_use: true, retry_reason: 'port_in_use', retry_in_ms: 1500 } as const
    expect(linkText(esp)).toEqual({ text: 'DevKit in use', tone: 'bad' })
    expect(lostWhy(esp)).toBe(ESP_IN_USE)
  })
  it('shows the retry countdown for other losses', () => {
    expect(linkText({ link_state: 'lost', retry_reason: 'timeout', retry_in_ms: 1500 }).text).toBe('lost · retry 2 s')
  })
})
