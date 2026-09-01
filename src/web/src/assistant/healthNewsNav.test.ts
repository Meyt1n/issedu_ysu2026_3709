import { describe, expect, it } from 'vitest'

import {
  consumeAssistantSeed,
  consumeAssistantSeedPrompt,
  openAssistantWithPrompt,
  session,
  SHARED_VIEWS,
} from '../store'

describe('assistant seed prompt', () => {
  it('allows shared assistant view and stores a seed prompt', () => {
    expect(SHARED_VIEWS).toContain('assistant')
    openAssistantWithPrompt('换季容易着凉，一般可以了解哪些用药资料？')
    expect(session.currentView).toBe('assistant')
    expect(consumeAssistantSeedPrompt()).toContain('换季')
    expect(consumeAssistantSeedPrompt()).toBe('')
  })

  it('lets health-news jumps start a new thread with network search on', () => {
    openAssistantWithPrompt(
      '请阅读这篇公开网页后再回答：https://www.who.int/zh/example\n首页看到公开资讯「示例标题」，这件事和家里的日常照护有关系吗？',
      {
        allowNetworkSearch: true,
        newThread: true,
      },
    )
    const seeded = consumeAssistantSeed()
    expect(seeded.prompt).toContain('https://www.who.int/zh/example')
    expect(seeded.prompt).toContain('公开资讯')
    expect(seeded.allowNetworkSearch).toBe(true)
    expect(seeded.newThread).toBe(true)
  })
})
