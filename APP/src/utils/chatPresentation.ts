export type ChatPresentationRole = 'user' | 'assistant'

export interface ChatPresentationEntry {
  role: ChatPresentationRole
  content: string
  createdAt?: number
}

const DAY_MS = 24 * 60 * 60 * 1000

function validDate(value: number | undefined): Date | null {
  if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}

function calendarDay(date: Date): number {
  return Date.UTC(date.getFullYear(), date.getMonth(), date.getDate())
}

function clockLabel(date: Date): string {
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}

/** 将会话时间压缩成适合气泡底部的本地化标签。 */
export function formatChatTimestamp(value: number | undefined, now = Date.now()): string {
  const date = validDate(value)
  const reference = validDate(now)
  if (!date || !reference) return ''

  const daysAgo = Math.round((calendarDay(reference) - calendarDay(date)) / DAY_MS)
  const sameYear = date.getFullYear() === reference.getFullYear()
  if (daysAgo === 0) return `今天 ${clockLabel(date)}`
  if (daysAgo === 1) return `昨天 ${clockLabel(date)}`
  if (sameYear) return `${date.getMonth() + 1}月${date.getDate()}日 ${clockLabel(date)}`
  return `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日 ${clockLabel(date)}`
}

export function chatTimestampIso(value: number | undefined): string | undefined {
  return validDate(value)?.toISOString()
}

export function chatEntryAriaLabel(entry: ChatPresentationEntry): string {
  const speaker = entry.role === 'user' ? '我' : '助手'
  const content = entry.content.trim() || '正在生成回答'
  const time = formatChatTimestamp(entry.createdAt)
  return `${speaker}：${content}${time ? `，${time}` : ''}`
}

export function isChatGroupStart(entries: readonly ChatPresentationEntry[], index: number): boolean {
  return index <= 0 || entries[index - 1]?.role !== entries[index]?.role
}

export function isChatGroupEnd(entries: readonly ChatPresentationEntry[], index: number): boolean {
  return index >= entries.length - 1 || entries[index + 1]?.role !== entries[index]?.role
}
