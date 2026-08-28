export type AssistantReplyStatus = 'streaming' | 'completed' | 'ended' | 'stopped' | 'incomplete'

/**
 * Persisted chat entries predate an explicit terminal status. Derive the
 * status from the existing degraded fields so interrupted replies remain
 * identifiable after the tab restores its session.
 */
export function restoreAssistantReplyStatus(
  role: 'user' | 'assistant',
  content: string,
  degraded?: boolean,
  degradeReason?: string | null,
): AssistantReplyStatus | undefined {
  if (role !== 'assistant' || !content.trim()) return undefined
  if (degraded && degradeReason === 'reply_ended') return 'ended'
  if (degraded && degradeReason === 'user_stopped') return 'stopped'
  if (degraded && degradeReason === 'stream_incomplete') return 'incomplete'
  return 'completed'
}

export function isInterruptedAssistantReply(status?: AssistantReplyStatus): boolean {
  return status === 'ended' || status === 'stopped' || status === 'incomplete'
}

export function assistantReplyStatusLabel(status?: AssistantReplyStatus): string {
  if (status === 'streaming') return '正在生成回答…'
  if (status === 'ended') return '已结束回复，回答不完整'
  if (status === 'stopped') return '已停止，回答不完整'
  if (status === 'incomplete') return '回答未完整生成'
  if (status === 'completed') return '回答已完成'
  return ''
}
