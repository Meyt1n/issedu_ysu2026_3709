import { describe, expect, it } from 'vitest'

import {
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
})
