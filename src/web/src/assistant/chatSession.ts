import type { AssistantCitation } from '../api/types'

export interface StoredChatEntry {
  role: 'user' | 'assistant'
  content: string
  sources?: string[]
  citations?: AssistantCitation[]
  confidence?: string
  degraded?: boolean
  degradeReason?: string | null
  escalate?: boolean
  suggestedQuestions?: string[]
  route?: string | null
  queryType?: string | null
  riskNotice?: string | null
}

const MAX_ENTRIES = 24
const MAX_CONTENT_LENGTH = 16_000
const SESSION_PREFIX = 'hct-assistant-session:v1:'

function storageKey(actorId: string, householdId: string, memberId: string): string {
  return `${SESSION_PREFIX}${encodeURIComponent(actorId)}:${encodeURIComponent(householdId)}:${encodeURIComponent(memberId)}`
}

function storage(): Storage | null {
  try {
    return globalThis.sessionStorage ?? null
  } catch {
    return null
  }
}

function isEntry(value: unknown): value is StoredChatEntry {
  if (!value || typeof value !== 'object') return false
  const entry = value as Partial<StoredChatEntry>
  return (entry.role === 'user' || entry.role === 'assistant') &&
    typeof entry.content === 'string' && entry.content.length <= MAX_CONTENT_LENGTH
}

function safeEntries(value: unknown): StoredChatEntry[] {
  if (!Array.isArray(value)) return []
  return value.filter(isEntry).slice(-MAX_ENTRIES)
}

/** Store only the current tab's assistant transcript; it never calls the API. */
export function loadChatSession(actorId: string, householdId: string, memberId: string): StoredChatEntry[] {
  if (!actorId || !householdId || !memberId) return []
  const target = storage()
  if (!target) return []
  try {
    return safeEntries(JSON.parse(target.getItem(storageKey(actorId, householdId, memberId)) ?? '[]'))
  } catch {
    return []
  }
}

export function saveChatSession(
  actorId: string,
  householdId: string,
  memberId: string,
  entries: StoredChatEntry[],
): void {
  if (!actorId || !householdId || !memberId) return
  const target = storage()
  if (!target) return
  try {
    target.setItem(storageKey(actorId, householdId, memberId), JSON.stringify(safeEntries(entries)))
  } catch {
    // Storage can be disabled or full; chat remains usable for this render.
  }
}

export function clearChatSession(actorId: string, householdId: string, memberId: string): void {
  if (!actorId || !householdId || !memberId) return
  try {
    storage()?.removeItem(storageKey(actorId, householdId, memberId))
  } catch {
    // Storage cleanup is best effort and must not block the assistant.
  }
}

export function clearChatSessionsForActor(actorId: string): void {
  if (!actorId) return
  const target = storage()
  if (!target) return
  const prefix = `${SESSION_PREFIX}${encodeURIComponent(actorId)}:`
  try {
    const keys: string[] = []
    for (let index = 0; index < target.length; index += 1) {
      const key = target.key(index)
      if (key?.startsWith(prefix)) keys.push(key)
    }
    for (const key of keys) target.removeItem(key)
  } catch {
    // Storage cleanup is best effort and must not block sign-out.
  }
}

export function sessionEntryToStored(entry: {
  role: StoredChatEntry['role']
  content: string
  sources?: string[]
  citations?: AssistantCitation[]
  confidence?: string
  degraded?: boolean
  degradeReason?: string | null
  escalate?: boolean
  suggestedQuestions?: string[]
  route?: string | null
  queryType?: string | null
  riskNotice?: string | null
}): StoredChatEntry {
  return {
    role: entry.role,
    content: entry.content,
    sources: entry.sources,
    citations: entry.citations,
    confidence: entry.confidence,
    degraded: entry.degraded,
    degradeReason: entry.degradeReason,
    escalate: entry.escalate,
    suggestedQuestions: entry.suggestedQuestions,
    route: entry.route,
    queryType: entry.queryType,
    riskNotice: entry.riskNotice,
  }
}
