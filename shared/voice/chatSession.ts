export interface StoredChatEntry {
  role: 'user' | 'assistant'
  content: string
  sources?: string[]
  confidence?: string
  degraded?: boolean
  degradeReason?: string | null
  escalate?: boolean
  suggestedQuestions?: string[]
}

/** 标签页内的对话线索；只保存到当前标签页的 sessionStorage，不落后端。 */
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
const DRAFT_PREFIX = 'hct-assistant-draft:v1:'

export const DEFAULT_THREAD_ID = 'default'
export const DEFAULT_THREAD_TITLE = '新对话'

function scopeSuffix(actorId: string, householdId: string, memberId: string): string {
  return `${encodeURIComponent(actorId)}:${encodeURIComponent(householdId)}:${encodeURIComponent(memberId)}`
}

// 默认线索沿用旧键，升级前的单会话记录仍会显示在历史栏第一项。
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

function draftStorageKey(actorId: string, householdId: string, memberId: string, threadId?: string): string {
  return `${DRAFT_PREFIX}${scopeSuffix(actorId, householdId, memberId)}${threadKeySuffix(threadId)}`
}

function createAssistantSessionId(): string {
  return globalThis.crypto?.randomUUID?.()
    ?? `app-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 18)}`
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
    // Storage can be disabled or full; chat remains usable in memory.
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
    // Best effort cleanup.
  }
}

export function loadChatDraft(
  actorId: string,
  householdId: string,
  memberId: string,
  threadId?: string,
): string {
  if (!actorId || !householdId || !memberId) return ''
  try {
    const value = storage()?.getItem(draftStorageKey(actorId, householdId, memberId, threadId))
    return typeof value === 'string' ? value.slice(0, MAX_CONTENT_LENGTH) : ''
  } catch {
    return ''
  }
}

export function saveChatDraft(
  actorId: string,
  householdId: string,
  memberId: string,
  draft: string,
  threadId?: string,
): void {
  if (!actorId || !householdId || !memberId) return
  try {
    const target = storage()
    if (!target) return
    const value = draft.slice(0, MAX_CONTENT_LENGTH)
    if (value) target.setItem(draftStorageKey(actorId, householdId, memberId, threadId), value)
    else target.removeItem(draftStorageKey(actorId, householdId, memberId, threadId))
  } catch {
    // Storage can be disabled or full; the in-memory draft remains usable.
  }
}

export function clearChatDraft(
  actorId: string,
  householdId: string,
  memberId: string,
  threadId?: string,
): void {
  if (!actorId || !householdId || !memberId) return
  try {
    storage()?.removeItem(draftStorageKey(actorId, householdId, memberId, threadId))
  } catch {
    // Best effort cleanup.
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
    // Keep the in-memory id when storage is unavailable.
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
    // Metadata is a convenience view; chat remains usable without it.
  }
}

/** 当前作用域的会话列表；没有元数据时回退为兼容旧存档的默认会话。 */
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
    // Best effort; the view keeps the active id in memory.
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

/** 更新最近活跃时间；首条用户提问会成为会话标题。 */
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
  persistThreads(actorId, householdId, memberId, threads.sort((a, b) => b.updatedAt - a.updatedAt))
}

export function renameChatThread(
  actorId: string,
  householdId: string,
  memberId: string,
  threadId: string,
  title: string,
): ChatThreadMeta[] {
  if (!actorId || !householdId || !memberId || !threadId) return listChatThreads(actorId, householdId, memberId)
  const threads = listChatThreads(actorId, householdId, memberId)
  const index = threads.findIndex(thread => thread.id === threadId)
  if (index < 0) return threads
  threads[index] = {
    ...threads[index]!,
    title: normalizeThreadTitle(title),
    updatedAt: Date.now(),
  }
  persistThreads(actorId, householdId, memberId, threads.sort((a, b) => b.updatedAt - a.updatedAt))
  return threads
}

export function deleteChatThread(
  actorId: string,
  householdId: string,
  memberId: string,
  threadId: string,
): ChatThreadMeta[] {
  if (!actorId || !householdId || !memberId || !threadId) return listChatThreads(actorId, householdId, memberId)
  try {
    const target = storage()
    target?.removeItem(storageKey(actorId, householdId, memberId, threadId))
    target?.removeItem(assistantIdStorageKey(actorId, householdId, memberId, threadId))
    target?.removeItem(draftStorageKey(actorId, householdId, memberId, threadId))
  } catch {
    // Best effort cleanup.
  }
  const remaining = listChatThreads(actorId, householdId, memberId).filter(thread => thread.id !== threadId)
  const threads = remaining.length > 0 ? remaining : [defaultThreadMeta()]
  persistThreads(actorId, householdId, memberId, threads)
  if (getActiveChatThreadId(actorId, householdId, memberId) === threadId || remaining.length === 0) {
    setActiveChatThread(actorId, householdId, memberId, threads[0]!.id)
  }
  return threads
}

export function clearChatSessionsForActor(actorId: string): void {
  if (!actorId) return
  const target = storage()
  if (!target) return
  const prefixes = [
    `${SESSION_PREFIX}${encodeURIComponent(actorId)}:`,
    `${ASSISTANT_ID_PREFIX}${encodeURIComponent(actorId)}:`,
    `${THREADS_PREFIX}${encodeURIComponent(actorId)}:`,
    `${ACTIVE_THREAD_PREFIX}${encodeURIComponent(actorId)}:`,
    `${DRAFT_PREFIX}${encodeURIComponent(actorId)}:`,
  ]
  try {
    const keys: string[] = []
    for (let index = 0; index < target.length; index += 1) {
      const key = target.key(index)
      if (key && prefixes.some(prefix => key.startsWith(prefix))) keys.push(key)
    }
    for (const key of keys) target.removeItem(key)
  } catch {
    // Best effort cleanup on sign-out/revocation.
  }
}

export function sessionEntryToStored(entry: StoredChatEntry): StoredChatEntry {
  return {
    role: entry.role,
    content: entry.content.slice(0, MAX_CONTENT_LENGTH),
    sources: entry.sources,
    confidence: entry.confidence,
    degraded: entry.degraded,
    degradeReason: entry.degradeReason,
    escalate: entry.escalate,
    suggestedQuestions: entry.suggestedQuestions,
  }
}
