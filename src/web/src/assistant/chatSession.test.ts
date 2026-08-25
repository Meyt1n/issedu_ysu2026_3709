import { beforeEach, describe, expect, it } from 'vitest'

import {
  clearChatSession,
  clearChatSessionsForActor,
  getAssistantSessionId,
  loadChatSession,
  regenerateAssistantSessionId,
  saveChatSession,
  sessionEntryToStored,
} from './chatSession'

describe('assistant tab session storage', () => {
  beforeEach(() => {
    const values = new Map<string, string>()
    Object.defineProperty(globalThis, 'sessionStorage', {
      configurable: true,
      value: {
        getItem: (key: string) => values.get(key) ?? null,
        setItem: (key: string, value: string) => values.set(key, value),
        removeItem: (key: string) => values.delete(key),
        clear: () => values.clear(),
        key: (index: number) => [...values.keys()][index] ?? null,
        get length() { return values.size },
      },
    })
  })

  it('round-trips only the current actor and scope', () => {
    saveChatSession('parent-1', 'household-1', 'member-1', [
      { role: 'user', content: '当前有哪些记录？' },
      { role: 'assistant', content: '当前没有已确认记录。', degraded: false },
    ])

    expect(loadChatSession('parent-1', 'household-1', 'member-1')).toHaveLength(2)
    expect(loadChatSession('parent-2', 'household-1', 'member-1')).toEqual([])
    expect(loadChatSession('parent-1', 'household-2', 'member-1')).toEqual([])
  })

  it('clears the scoped transcript without touching another scope', () => {
    saveChatSession('parent-1', 'household-1', 'member-1', [{ role: 'user', content: 'A' }])
    saveChatSession('parent-1', 'household-1', 'member-2', [{ role: 'user', content: 'B' }])

    clearChatSession('parent-1', 'household-1', 'member-1')

    expect(loadChatSession('parent-1', 'household-1', 'member-1')).toEqual([])
    expect(loadChatSession('parent-1', 'household-1', 'member-2')).toHaveLength(1)
  })

  it('clears every scoped transcript when the actor signs out', () => {
    saveChatSession('parent-1', 'household-1', 'member-1', [{ role: 'user', content: 'A' }])
    saveChatSession('parent-1', 'household-2', 'member-2', [{ role: 'user', content: 'B' }])
    saveChatSession('parent-2', 'household-1', 'member-1', [{ role: 'user', content: 'C' }])

    clearChatSessionsForActor('parent-1')

    expect(loadChatSession('parent-1', 'household-1', 'member-1')).toEqual([])
    expect(loadChatSession('parent-1', 'household-2', 'member-2')).toEqual([])
    expect(loadChatSession('parent-2', 'household-1', 'member-1')).toHaveLength(1)
  })

  it('bounds and ignores malformed entries', () => {
    saveChatSession('parent-1', 'household-1', 'member-1', [
      { role: 'user', content: 'valid' },
      { role: 'system' as 'user', content: 'invalid' },
      ...Array.from({ length: 30 }, (_, index) => ({ role: 'user' as const, content: String(index) })),
    ])

    const entries = loadChatSession('parent-1', 'household-1', 'member-1')
    expect(entries).toHaveLength(24)
    expect(entries.at(-1)?.content).toBe('29')
  })

  it('keeps an opaque assistant id stable per scope and rotates it on demand', () => {
    const first = getAssistantSessionId('parent-1', 'household-1', 'member-1')
    const stable = getAssistantSessionId('parent-1', 'household-1', 'member-1')
    const otherMember = getAssistantSessionId('parent-1', 'household-1', 'member-2')
    const rotated = regenerateAssistantSessionId('parent-1', 'household-1', 'member-1')

    expect(first).toBe(stable)
    expect(otherMember).not.toBe(first)
    expect(rotated).not.toBe(first)
    expect(getAssistantSessionId('parent-1', 'household-1', 'member-1')).toBe(rotated)
  })

  it('persists the route explanation with the scoped transcript', () => {
    const stored = sessionEntryToStored({
      role: 'assistant',
      content: '已核对。',
      routeExplanation: '显式按用药安全路径检索。',
    })
    saveChatSession('parent-1', 'household-1', 'member-1', [stored])

    expect(loadChatSession('parent-1', 'household-1', 'member-1')[0]?.routeExplanation)
      .toBe('显式按用药安全路径检索。')
  })
})
