import { describe, expect, it } from 'vitest'

import {
  assistantReplyStatusLabel,
  isInterruptedAssistantReply,
  restoreAssistantReplyStatus,
} from './assistantReply'

describe('assistant reply status', () => {
  it('restores interrupted statuses from persisted degraded reasons', () => {
    expect(restoreAssistantReplyStatus('assistant', '已生成一半', true, 'reply_ended')).toBe('ended')
    expect(restoreAssistantReplyStatus('assistant', '已生成一半', true, 'user_stopped')).toBe('stopped')
    expect(restoreAssistantReplyStatus('assistant', '连接中断', true, 'stream_incomplete')).toBe('incomplete')
    expect(restoreAssistantReplyStatus('assistant', '完整回答', false, null)).toBe('completed')
  })

  it('does not mark user or empty entries as assistant replies', () => {
    expect(restoreAssistantReplyStatus('user', '问题', false)).toBeUndefined()
    expect(restoreAssistantReplyStatus('assistant', '  ', true, 'user_stopped')).toBeUndefined()
  })

  it('labels interrupted replies for visual and assistive status text', () => {
    expect(isInterruptedAssistantReply('stopped')).toBe(true)
    expect(isInterruptedAssistantReply('ended')).toBe(true)
    expect(isInterruptedAssistantReply('incomplete')).toBe(true)
    expect(isInterruptedAssistantReply('completed')).toBe(false)
    expect(assistantReplyStatusLabel('stopped')).toBe('已停止，回答不完整')
    expect(assistantReplyStatusLabel('ended')).toBe('已结束回复，回答不完整')
    expect(assistantReplyStatusLabel('incomplete')).toBe('回答未完整生成')
  })
})
