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

function createMemoryStorage(): Storage {
  const values = new Map<string, string>()
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => {
      values.set(key, value)
    },
    removeItem: (key: string) => {
      values.delete(key)
    },
    clear: () => values.clear(),
    key: (index: number) => [...values.keys()][index] ?? null,
    get length() {
      return values.size
    },
  }
}

function installStorages(local = createMemoryStorage(), session = createMemoryStorage()) {
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: local,
  })
  Object.defineProperty(globalThis, 'sessionStorage', {
    configurable: true,
    value: session,
  })
  return { local, session }
}

describe('assistant local chat storage', () => {
  beforeEach(() => {
    installStorages()
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

  it('keeps the transcript after a later load on the same device', () => {
    saveChatSession('parent-1', 'household-1', 'member-1', [{ role: 'user', content: '还在吗' }])

    expect(loadChatSession('parent-1', 'household-1', 'member-1')[0]?.content).toBe('还在吗')
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

  it('migrates a tab-only session into local storage once', () => {
    const { local, session } = installStorages()
    const key = 'hct-assistant-session:v1:parent-1:household-1:member-1'
    session.setItem(key, JSON.stringify([{ role: 'user', content: '旧标签页对话' }]))

    expect(loadChatSession('parent-1', 'household-1', 'member-1')[0]?.content).toBe('旧标签页对话')
    expect(local.getItem(key)).toContain('旧标签页对话')
    expect(session.getItem(key)).toBeNull()
  })

  it('does not overwrite existing local transcripts during migration', () => {
    const { local, session } = installStorages()
    const key = 'hct-assistant-session:v1:parent-1:household-1:member-1'
    local.setItem(key, JSON.stringify([{ role: 'user', content: '本机已有' }]))
    session.setItem(key, JSON.stringify([{ role: 'user', content: '过期标签页' }]))

    expect(loadChatSession('parent-1', 'household-1', 'member-1')[0]?.content).toBe('本机已有')
    expect(session.getItem(key)).toBeNull()
  })

  it('falls back to the tab store when local storage is blocked', () => {
    const session = createMemoryStorage()
    Object.defineProperty(globalThis, 'localStorage', {
      configurable: true,
      get() {
        throw new Error('blocked')
      },
    })
    Object.defineProperty(globalThis, 'sessionStorage', {
      configurable: true,
      value: session,
    })

    saveChatSession('parent-1', 'household-1', 'member-1', [{ role: 'user', content: '临时' }])
    expect(loadChatSession('parent-1', 'household-1', 'member-1')[0]?.content).toBe('临时')
  })
})
