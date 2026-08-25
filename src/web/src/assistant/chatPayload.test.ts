import { describe, expect, it } from 'vitest'

import { buildAssistantChatInput } from './chatPayload'

describe('buildAssistantChatInput', () => {
  it('always carries the per-request web-search opt-in in the body', () => {
    const optedIn = buildAssistantChatInput({
      history: [{ role: 'user', content: '最近有什么流行性感冒吗' }],
      allowNetworkSearch: true,
    })
    expect(optedIn.allow_network_search).toBe(true)
    expect(optedIn.agent_mode).toBe('multi_agent')
    expect(optedIn.messages).toEqual([
      { role: 'user', content: '最近有什么流行性感冒吗' },
    ])

    const optedOut = buildAssistantChatInput({
      history: [{ role: 'user', content: '你好' }],
      allowNetworkSearch: false,
    })
    expect(optedOut.allow_network_search).toBe(false)
  })

  it('keeps only role and content from rich history entries', () => {
    const input = buildAssistantChatInput({
      history: [
        { role: 'user', content: '问题', extra: 'x' } as never,
        { role: 'assistant', content: '回答', sources: ['a'] } as never,
      ],
      allowNetworkSearch: true,
      queryTypeOverride: 'MEDICATION_SAFETY',
      assistantSessionId: 'session-1',
    })
    expect(input.messages).toEqual([
      { role: 'user', content: '问题' },
      { role: 'assistant', content: '回答' },
    ])
    expect(input.query_type_override).toBe('MEDICATION_SAFETY')
    expect(input.assistant_session_id).toBe('session-1')
    expect(input.max_tokens).toBe(1024)
  })

  it('omits an empty assistant session id', () => {
    const input = buildAssistantChatInput({
      history: [{ role: 'user', content: '问题' }],
      allowNetworkSearch: true,
      assistantSessionId: '',
    })
    expect(input.assistant_session_id).toBeUndefined()
  })
})
