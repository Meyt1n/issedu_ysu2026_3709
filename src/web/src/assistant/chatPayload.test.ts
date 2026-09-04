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
    expect(optedIn.memory_messages).toEqual([
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
    expect(input.memory_messages).toEqual([{ role: 'user', content: '问题' }])
    expect(input.query_type_override).toBe('MEDICATION_SAFETY')
    expect(input.assistant_session_id).toBe('session-1')
    expect(input.max_tokens).toBe(4096)
  })

  it('omits empty assistant placeholders and keeps the latest turns', () => {
    const input = buildAssistantChatInput({
      history: [
        { role: 'assistant', content: '   ' },
        { role: 'user', content: '上次问过用药提醒' },
        { role: 'assistant', content: '提醒来自已确认计划。' },
        { role: 'user', content: '那和今天天气有关吗' },
      ],
      allowNetworkSearch: false,
    })
    expect(input.messages).toEqual([
      { role: 'user', content: '上次问过用药提醒' },
      { role: 'assistant', content: '提醒来自已确认计划。' },
      { role: 'user', content: '那和今天天气有关吗' },
    ])
    expect(input.memory_messages).toEqual([
      { role: 'user', content: '上次问过用药提醒' },
      { role: 'user', content: '那和今天天气有关吗' },
    ])
  })

  it('indexes more user history without adding it to the answer context', () => {
    const history = Array.from({ length: 20 }, (_, index) => ({
      role: (index % 2 ? 'assistant' : 'user') as 'user' | 'assistant',
      content: `消息 ${index}`,
    }))
    const input = buildAssistantChatInput({ history, allowNetworkSearch: false })

    expect(input.messages).toHaveLength(12)
    expect(input.memory_messages).toHaveLength(10)
    expect(input.memory_messages?.every(message => message.role === 'user')).toBe(true)
  })

  it('omits an empty assistant session id', () => {
    const input = buildAssistantChatInput({
      history: [{ role: 'user', content: '问题' }],
      allowNetworkSearch: true,
      assistantSessionId: '',
    })
    expect(input.assistant_session_id).toBeUndefined()
  })

  it('carries transient extracted attachment text with its filename', () => {
    const input = buildAssistantChatInput({
      history: [{ role: 'user', content: '帮我看看这个文件' }],
      allowNetworkSearch: false,
      attachmentText: '药品名称：阿莫西林胶囊',
      attachmentName: 'label.txt',
    })

    expect(input.attachment_text).toBe('药品名称：阿莫西林胶囊')
    expect(input.attachment_name).toBe('label.txt')
  })
})
