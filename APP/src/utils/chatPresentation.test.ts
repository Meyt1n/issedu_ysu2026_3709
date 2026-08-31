import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  chatEntryAriaLabel,
  chatTimestampIso,
  formatChatTimestamp,
  isChatGroupEnd,
  isChatGroupStart,
} from './chatPresentation'

const reference = new Date(2026, 7, 29, 15, 4, 0).getTime()

afterEach(() => {
  vi.useRealTimers()
})

describe('chat presentation', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('formats today, yesterday, same-year and cross-year timestamps', () => {
    expect(formatChatTimestamp(new Date(2026, 7, 29, 8, 9).getTime(), reference)).toBe('今天 08:09')
    expect(formatChatTimestamp(new Date(2026, 7, 28, 20, 10).getTime(), reference)).toBe('昨天 20:10')
    expect(formatChatTimestamp(new Date(2026, 6, 1, 7, 5).getTime(), reference)).toBe('7月1日 07:05')
    expect(formatChatTimestamp(new Date(2025, 11, 31, 23, 59).getTime(), reference)).toBe('2025年12月31日 23:59')
  })

  it('fails closed for missing or invalid timestamps', () => {
    expect(formatChatTimestamp(undefined, reference)).toBe('')
    expect(formatChatTimestamp(Number.NaN, reference)).toBe('')
    expect(chatTimestampIso(undefined)).toBeUndefined()
  })

  it('provides a speaker/content/time label for TalkBack', () => {
    vi.useFakeTimers()
    vi.setSystemTime(reference)
    const timestamp = new Date(2026, 7, 29, 8, 9).getTime()
    expect(chatEntryAriaLabel({ role: 'assistant', content: '请先确认计划', createdAt: timestamp }, reference))
      .toBe('助手：请先确认计划，今天 08:09')
  })

  it('detects adjacent messages that can share a visual group', () => {
    const entries = [
      { role: 'user' as const, content: '你好' },
      { role: 'user' as const, content: '还有一个问题' },
      { role: 'assistant' as const, content: '请说' },
    ]
    expect(isChatGroupStart(entries, 0)).toBe(true)
    expect(isChatGroupStart(entries, 1)).toBe(false)
    expect(isChatGroupEnd(entries, 1)).toBe(true)
    expect(isChatGroupEnd(entries, 2)).toBe(true)
  })
})
