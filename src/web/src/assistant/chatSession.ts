import type { AssistantCitation } from '../api/types'

export interface StoredChatEntry {
  role: 'user' | 'assistant'
  content: string
  openChat?: boolean
  sources?: string[]
  citations?: AssistantCitation[]
  confidence?: string
  degraded?: boolean
  degradeReason?: string | null
  escalate?: boolean
  suggestedQuestions?: string[]
  route?: string | null
  routeExplanation?: string | null
  queryType?: string | null
  riskNotice?: string | null
}

/** 本机对话线索（多轮会话列表项）；存 localStorage，不落后端。 */
export interface ChatThreadMeta {
  id: string
  title: string
  createdAt: number
  updatedAt: number
}

const MAX_ENTRIES = 24
const MAX_CONTENT_LENGTH = 16_000
const MAX_THREADS = 12
const MAX_THREAD_TITLE_LENGTH = 40
const SESSION_PREFIX = 'hct-assistant-session:v1:'
const ASSISTANT_ID_PREFIX = 'hct-assistant-id:v1:'
const THREADS_PREFIX = 'hct-assistant-threads:v1:'
const ACTIVE_THREAD_PREFIX = 'hct-assistant-thread-active:v1:'
const CHAT_STORAGE_PREFIXES = [
  SESSION_PREFIX,
  ASSISTANT_ID_PREFIX,
  THREADS_PREFIX,
  ACTIVE_THREAD_PREFIX,
] as const

export const DEFAULT_THREAD_ID = 'default'
export const DEFAULT_THREAD_TITLE = '新对话'

function scopeSuffix(actorId: string, householdId: string, memberId: string): string {
  return `${encodeURIComponent(actorId)}:${encodeURIComponent(householdId)}:${encodeURIComponent(memberId)}`
}

// 默认线索沿用旧的存储键，保证升级前的会话仍能作为第一条线索展示。
function threadKeySuffix(threadId?: string): string {
  return !threadId || threadId === DEFAULT_THREAD_ID ? '' : `:t:${encodeURIComponent(threadId)}`
}

function storageKey(actorId: string, householdId: string, memberId: string, threadId?: string): string {
  return `${SESSION_PREFIX}${scopeSuffix(actorId, householdId, memberId)}${threadKeySuffix(threadId)}`
}

function assistantIdStorageKey(actorId: string, householdId: string, memberId: string, threadId?: string): string {
  return `${ASSISTANT_ID_PREFIX}${scopeSuffix(actorId, householdId, memberId)}${threadKeySuffix(threadId)}`
}

function threadsStorageKey(actorId: string, householdId: string, memberId: string): string {
  return `${THREADS_PREFIX}${scopeSuffix(actorId, householdId, memberId)}`
}

function activeThreadStorageKey(actorId: string, householdId: string, memberId: string): string {
  return `${ACTIVE_THREAD_PREFIX}${scopeSuffix(actorId, householdId, memberId)}`
}

function createAssistantSessionId(): string {
  return globalThis.crypto?.randomUUID?.()
    ?? `web-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 18)}`
}

function sessionStore(): Storage | null {
  try {
    return globalThis.sessionStorage ?? null
  } catch {
    return null
  }
}

function isChatStorageKey(key: string): boolean {
  return CHAT_STORAGE_PREFIXES.some(prefix => key.startsWith(prefix))
}

/** 把旧版标签页会话迁到本机 localStorage，避免升级后刷新丢掉当前对话。 */
function migrateSessionStorageToLocal(local: Storage): void {
  const session = sessionStore()
  if (!session || session === local) return
  try {
    const keys: string[] = []
    for (let index = 0; index < session.length; index += 1) {
      const key = session.key(index)
      if (key && isChatStorageKey(key)) keys.push(key)
    }
    for (const key of keys) {
      if (local.getItem(key) == null) {
        const value = session.getItem(key)
        if (value != null) {
          try {
            local.setItem(key, value)
          } catch {
            continue
          }
        }
      }
      session.removeItem(key)
    }
  } catch {
    // Migration is best effort; new chats still persist to localStorage.
  }
}

function storage(): Storage | null {
  try {
    const local = globalThis.localStorage ?? null
    if (local) {
      migrateSessionStorageToLocal(local)
      return local
    }
  } catch {
    // Private mode can block localStorage; keep this tab usable.
  }
  return sessionStore()
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

/** Store the assistant transcript on this device; it never calls the API. */
export function loadChatSession(
  actorId: string,
  householdId: string,
  memberId: string,
  threadId?: string,
): StoredChatEntry[] {
  if (!actorId || !householdId || !memberId) return []
  const target = storage()
  if (!target) return []
  try {
    return safeEntries(JSON.parse(target.getItem(storageKey(actorId, householdId, memberId, threadId)) ?? '[]'))
  } catch {
    return []
  }
}

export function saveChatSession(
  actorId: string,
  householdId: string,
  memberId: string,
  entries: StoredChatEntry[],
  threadId?: string,
): void {
  if (!actorId || !householdId || !memberId) return
  const target = storage()
  if (!target) return
  try {
    target.setItem(storageKey(actorId, householdId, memberId, threadId), JSON.stringify(safeEntries(entries)))
  } catch {
    // Storage can be disabled or full; chat remains usable for this render.
  }
}

export function clearChatSession(
  actorId: string,
  householdId: string,
  memberId: string,
  threadId?: string,
): void {
  if (!actorId || !householdId || !memberId) return
  try {
    storage()?.removeItem(storageKey(actorId, householdId, memberId, threadId))
  } catch {
    // Storage cleanup is best effort and must not block the assistant.
  }
}

export function getAssistantSessionId(
  actorId: string,
  householdId: string,
  memberId: string,
  threadId?: string,
): string {
  if (!actorId || !householdId || !memberId) return ''
  const target = storage()
  if (!target) return createAssistantSessionId()
  const key = assistantIdStorageKey(actorId, householdId, memberId, threadId)
  try {
    const existing = target.getItem(key)
    if (existing) return existing
    const created = createAssistantSessionId()
    target.setItem(key, created)
    return created
  } catch {
    return createAssistantSessionId()
  }
}

export function regenerateAssistantSessionId(
  actorId: string,
  householdId: string,
  memberId: string,
  threadId?: string,
): string {
  if (!actorId || !householdId || !memberId) return ''
  const created = createAssistantSessionId()
  try {
    storage()?.setItem(assistantIdStorageKey(actorId, householdId, memberId, threadId), created)
  } catch {
    // The opaque in-memory id still isolates this render if storage is blocked.
  }
  return created
}

function isThreadMeta(value: unknown): value is ChatThreadMeta {
  if (!value || typeof value !== 'object') return false
  const meta = value as Partial<ChatThreadMeta>
  return typeof meta.id === 'string' && meta.id.length > 0
    && typeof meta.title === 'string'
    && typeof meta.createdAt === 'number'
    && typeof meta.updatedAt === 'number'
}

function defaultThreadMeta(): ChatThreadMeta {
  const now = Date.now()
  return { id: DEFAULT_THREAD_ID, title: DEFAULT_THREAD_TITLE, createdAt: now, updatedAt: now }
}

function normalizeThreadTitle(title: string): string {
  const cleaned = title.replaceAll(/\s+/g, ' ').trim()
  if (!cleaned) return DEFAULT_THREAD_TITLE
  return cleaned.length > MAX_THREAD_TITLE_LENGTH
    ? `${cleaned.slice(0, MAX_THREAD_TITLE_LENGTH)}…`
    : cleaned
}

function persistThreads(actorId: string, householdId: string, memberId: string, threads: ChatThreadMeta[]): void {
  try {
    storage()?.setItem(
      threadsStorageKey(actorId, householdId, memberId),
      JSON.stringify(threads.slice(0, MAX_THREADS)),
    )
  } catch {
    // Thread metadata is a convenience view; chat remains usable without it.
  }
}

/** 当前范围下的线索列表；没有存档时回退为单条默认线索（兼容旧存档）。 */
export function listChatThreads(actorId: string, householdId: string, memberId: string): ChatThreadMeta[] {
  if (!actorId || !householdId || !memberId) return [defaultThreadMeta()]
  const target = storage()
  if (!target) return [defaultThreadMeta()]
  try {
    const parsed: unknown = JSON.parse(target.getItem(threadsStorageKey(actorId, householdId, memberId)) ?? '[]')
    const threads = Array.isArray(parsed) ? parsed.filter(isThreadMeta).slice(0, MAX_THREADS) : []
    return threads.length > 0 ? threads : [defaultThreadMeta()]
  } catch {
    return [defaultThreadMeta()]
  }
}

export function getActiveChatThreadId(actorId: string, householdId: string, memberId: string): string {
  const threads = listChatThreads(actorId, householdId, memberId)
  try {
    const stored = storage()?.getItem(activeThreadStorageKey(actorId, householdId, memberId))
    if (stored && threads.some(thread => thread.id === stored)) return stored
  } catch {
    // Fall through to the first thread.
  }
  return threads[0]?.id ?? DEFAULT_THREAD_ID
}

export function setActiveChatThread(actorId: string, householdId: string, memberId: string, threadId: string): void {
  if (!actorId || !householdId || !memberId || !threadId) return
  try {
    storage()?.setItem(activeThreadStorageKey(actorId, householdId, memberId), threadId)
  } catch {
    // Best effort; the view keeps the active thread in memory.
  }
}

export function createChatThread(actorId: string, householdId: string, memberId: string): ChatThreadMeta {
  const now = Date.now()
  const meta: ChatThreadMeta = {
    id: createAssistantSessionId(),
    title: DEFAULT_THREAD_TITLE,
    createdAt: now,
    updatedAt: now,
  }
  const threads = [meta, ...listChatThreads(actorId, householdId, memberId).filter(item => item.id !== meta.id)]
  persistThreads(actorId, householdId, memberId, threads)
  setActiveChatThread(actorId, householdId, memberId, meta.id)
  return meta
}

/** 更新线索的时间戳；首条用户提问会成为线索标题。 */
export function touchChatThread(
  actorId: string,
  householdId: string,
  memberId: string,
  threadId: string,
  title?: string,
): void {
  if (!actorId || !householdId || !memberId || !threadId) return
  const threads = listChatThreads(actorId, householdId, memberId)
  const index = threads.findIndex(thread => thread.id === threadId)
  const existing = threads[index]
  const next: ChatThreadMeta = existing
    ? { ...existing, updatedAt: Date.now() }
    : { ...defaultThreadMeta(), id: threadId }
  if (title && (next.title === DEFAULT_THREAD_TITLE || !existing)) {
    next.title = normalizeThreadTitle(title)
  }
  if (index >= 0) threads[index] = next
  else threads.unshift(next)
  persistThreads(actorId, householdId, memberId, threads)
}

export function deleteChatThread(
  actorId: string,
  householdId: string,
  memberId: string,
  threadId: string,
): ChatThreadMeta[] {
  if (!actorId || !householdId || !memberId || !threadId) {
    return listChatThreads(actorId, householdId, memberId)
  }
  try {
    storage()?.removeItem(storageKey(actorId, householdId, memberId, threadId))
    storage()?.removeItem(assistantIdStorageKey(actorId, householdId, memberId, threadId))
  } catch {
    // Best effort cleanup.
  }
  const remaining = listChatThreads(actorId, householdId, memberId).filter(thread => thread.id !== threadId)
  persistThreads(actorId, householdId, memberId, remaining)
  const threads = remaining.length > 0 ? remaining : [defaultThreadMeta()]
  if (getActiveChatThreadId(actorId, householdId, memberId) === threadId || remaining.length === 0) {
    setActiveChatThread(actorId, householdId, memberId, threads[0]!.id)
  }
  return threads
}

export function clearChatSessionsForActor(actorId: string): void {
  if (!actorId) return
  const target = storage()
  if (!target) return
  const prefixes = CHAT_STORAGE_PREFIXES.map(prefix => `${prefix}${encodeURIComponent(actorId)}:`)
  try {
    const keys: string[] = []
    for (let index = 0; index < target.length; index += 1) {
      const key = target.key(index)
      if (key && prefixes.some(prefix => key.startsWith(prefix))) keys.push(key)
    }
    for (const key of keys) target.removeItem(key)
  } catch {
    // Storage cleanup is best effort and must not block sign-out.
  }
}

export function sessionEntryToStored(entry: {
  role: StoredChatEntry['role']
  content: string
  openChat?: boolean
  sources?: string[]
  citations?: AssistantCitation[]
  confidence?: string
  degraded?: boolean
  degradeReason?: string | null
  escalate?: boolean
  suggestedQuestions?: string[]
  route?: string | null
  routeExplanation?: string | null
  queryType?: string | null
  riskNotice?: string | null
}): StoredChatEntry {
  return {
    role: entry.role,
    content: entry.content,
    openChat: entry.openChat,
    sources: entry.sources,
    citations: entry.citations,
    confidence: entry.confidence,
    degraded: entry.degraded,
    degradeReason: entry.degradeReason,
    escalate: entry.escalate,
    suggestedQuestions: entry.suggestedQuestions,
    route: entry.route,
    routeExplanation: entry.routeExplanation,
    queryType: entry.queryType,
    riskNotice: entry.riskNotice,
  }
}
