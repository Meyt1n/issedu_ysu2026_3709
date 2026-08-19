import { computed, reactive, readonly } from 'vue'

import { ApiClientError, apiClient } from './api/client'
import type {
  CapabilityResponse,
  Household,
  Member,
  RequestOptions,
} from './api/types'

export type ViewName =
  | 'overview'
  | 'members'
  | 'scan'
  | 'review'
  | 'risks'
  | 'plans'
  | 'graph'
  | 'assistant'
  | 'authorizations'
  | 'bigscreen'
  | 'knowledge'
  | 'modellab'

export type SessionStatus = 'signed-out' | 'loading' | 'ready' | 'empty' | 'error'

export interface Toast {
  id: number
  kind: 'success' | 'error' | 'info'
  text: string
}

interface SessionState {
  actorId: string
  sessionToken: string
  sessionExpiresAt: number | null
  authMode: 'development' | 'session'
  accessPurpose: string
  status: SessionStatus
  error: string
  currentView: ViewName
  households: Household[]
  selectedHouseholdId: string
  members: Member[]
  selectedMemberId: string
  isOwnerView: boolean
  capabilities: CapabilityResponse | null
  loadingScope: boolean
  toasts: Toast[]
}

const state = reactive<SessionState>({
  actorId: '',
  sessionToken: '',
  sessionExpiresAt: null,
  authMode: 'development',
  accessPurpose: 'family-care',
  status: 'signed-out',
  error: '',
  currentView: 'overview',
  households: [],
  selectedHouseholdId: '',
  members: [],
  selectedMemberId: '',
  isOwnerView: false,
  capabilities: null,
  loadingScope: false,
  toasts: [],
})

let toastSeq = 0

export const session = readonly(state)

export const requestOptions = computed<RequestOptions>(() => ({
  actorId: state.sessionToken ? undefined : state.actorId.trim() || undefined,
  sessionToken: state.sessionToken || undefined,
  accessPurpose: state.accessPurpose.trim() || undefined,
}))

export const selectedHousehold = computed(
  () => state.households.find(item => item.id === state.selectedHouseholdId) ?? null,
)

export const selectedMember = computed(
  () => state.members.find(item => item.id === state.selectedMemberId) ?? null,
)

export const memberNames = computed(
  () => new Map(state.members.map(member => [member.id, member.display_name])),
)

export function createIdempotencyKey(): string {
  return globalThis.crypto?.randomUUID?.() ?? `web-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export function formatError(cause: unknown): string {
  if (cause instanceof ApiClientError) {
    if (cause.code === 'DEPENDENCY_UNAVAILABLE') return '本地 API 服务不可用，本次没有改变任何数据。'
    if (cause.status === 401) {
      return state.authMode === 'session'
        ? '账号、密码或会话无效，请重新登录。'
        : '需要先填写开发身份才能继续这次请求。'
    }
    if (cause.status === 404) return '当前身份无权访问该资源，或资源不存在。'
    if (cause.status === 409) return '数据已在其它位置被修改，请刷新后再试。'
    if (cause.status === 422) return `请求内容未通过校验：${cause.message}`
    if (cause.status === 429) return '尝试过于频繁，请稍后再试。'
  }
  return '请求未能完成，页面不会显示未经授权的健康数据。'
}

export function pushToast(kind: Toast['kind'], text: string): void {
  const id = ++toastSeq
  state.toasts.push({ id, kind, text })
  setTimeout(() => {
    const index = state.toasts.findIndex(toast => toast.id === id)
    if (index >= 0) state.toasts.splice(index, 1)
  }, 4600)
}

export function dismissToast(id: number): void {
  const index = state.toasts.findIndex(toast => toast.id === id)
  if (index >= 0) state.toasts.splice(index, 1)
}

export function setView(view: ViewName): void {
  state.currentView = view
}

function sessionIsSignedOut(): boolean {
  return state.status === 'signed-out'
}

export function setIdentityDraft(actorId: string, accessPurpose: string): void {
  state.actorId = actorId
  state.accessPurpose = accessPurpose
}

export function signOut(): void {
  const token = state.sessionToken
  if (token) void apiClient.logout(token).catch(() => undefined)
  clearSessionContext()
}

function clearSessionContext(): void {
  state.actorId = ''
  state.sessionToken = ''
  state.sessionExpiresAt = null
  state.status = 'signed-out'
  state.error = ''
  state.currentView = 'overview'
  state.households = []
  state.selectedHouseholdId = ''
  state.members = []
  state.selectedMemberId = ''
  state.isOwnerView = false
  state.capabilities = null
}

export function expireSession(): void {
  clearSessionContext()
  state.error = '会话已过期或已被撤销，请重新登录。'
}

export async function connect(actorId: string, accessPurpose: string): Promise<void> {
  clearSessionContext()
  state.actorId = actorId.trim()
  state.accessPurpose = accessPurpose.trim()
  state.authMode = 'development'
  if (!state.actorId) {
    state.status = 'signed-out'
    state.error = '请先填写开发身份。'
    return
  }

  state.status = 'loading'
  state.error = ''
  state.households = []
  state.selectedHouseholdId = ''
  state.members = []
  state.selectedMemberId = ''
  state.isOwnerView = false
  try {
    state.households = await apiClient.listHouseholds(requestOptions.value)
    if (state.households.length === 0) {
      state.status = 'empty'
      return
    }
    state.selectedHouseholdId = state.households[0]?.id ?? ''
    await loadHouseholdScope()
    if (sessionIsSignedOut()) return
    state.status = 'ready'
  } catch (cause) {
    state.status = 'error'
    state.error = formatError(cause)
  }
}

export async function connectWithPassword(
  actorId: string,
  password: string,
  accessPurpose: string,
  register = false,
): Promise<void> {
  clearSessionContext()
  state.authMode = 'session'
  state.actorId = actorId.trim()
  state.accessPurpose = accessPurpose.trim()
  if (!state.actorId || !password) {
    state.status = 'signed-out'
    state.error = '请输入本地账号和密码。'
    return
  }

  state.status = 'loading'
  state.error = ''
  try {
    if (register) await apiClient.registerAccount(state.actorId, password)
    const sessionResult = await apiClient.login(state.actorId, password)
    state.sessionToken = sessionResult.session_token
    state.sessionExpiresAt = sessionResult.expires_at
    state.actorId = sessionResult.actor_id
    state.households = await apiClient.listHouseholds(requestOptions.value)
    if (state.households.length === 0) {
      state.status = 'empty'
      return
    }
    state.selectedHouseholdId = state.households[0]?.id ?? ''
    await loadHouseholdScope()
    if (sessionIsSignedOut()) return
    state.status = 'ready'
  } catch (cause) {
    const sessionExpired = sessionIsSignedOut() && state.error.includes('会话已过期')
    if (!sessionExpired) clearSessionContext()
    state.authMode = 'session'
    state.status = 'signed-out'
    if (sessionExpired) return
    state.error = formatError(cause)
  }
}

export async function createHouseholdAndEnter(
  householdName: string,
  memberDrafts: Array<{ displayName: string; role: 'SELF' | 'DEPENDENT' | 'CAREGIVER' }>,
): Promise<void> {
  const created = await apiClient.createHousehold(
    { name: householdName },
    { ...requestOptions.value, idempotencyKey: createIdempotencyKey() },
  )
  for (const draft of memberDrafts) {
    if (!draft.displayName.trim()) continue
    await apiClient.createMember(
      created.id,
      { display_name: draft.displayName.trim(), role: draft.role },
      { ...requestOptions.value, idempotencyKey: createIdempotencyKey() },
    )
  }
  state.households = await apiClient.listHouseholds(requestOptions.value)
  state.selectedHouseholdId = created.id
  await loadHouseholdScope()
  if (sessionIsSignedOut()) return
  state.status = 'ready'
}

export async function selectHousehold(householdId: string): Promise<void> {
  if (state.selectedHouseholdId === householdId) return
  state.selectedHouseholdId = householdId
  await loadHouseholdScope()
}

export function selectMember(memberId: string): void {
  state.selectedMemberId = memberId
}

export async function loadHouseholdScope(): Promise<void> {
  const householdId = state.selectedHouseholdId
  if (!householdId) return

  state.loadingScope = true
  state.error = ''
  state.members = []
  state.selectedMemberId = ''
  state.isOwnerView = false
  try {
    state.members = await apiClient.listMembers(householdId, requestOptions.value)
    state.selectedMemberId = state.members[0]?.id ?? ''

    try {
      await apiClient.listAuthorizations(householdId, requestOptions.value)
      state.isOwnerView = true
    } catch (cause) {
      if (cause instanceof ApiClientError && cause.status === 404) {
        state.isOwnerView = false
      } else {
        throw cause
      }
    }

    try {
      state.capabilities = await apiClient.getCapabilities(requestOptions.value)
    } catch {
      state.capabilities = null
    }
  } catch (cause) {
    state.members = []
    if (!sessionIsSignedOut()) state.error = formatError(cause)
  } finally {
    state.loadingScope = false
  }
}

export async function refreshMembers(): Promise<void> {
  const householdId = state.selectedHouseholdId
  if (!householdId) return
  state.members = await apiClient.listMembers(householdId, requestOptions.value)
  if (!state.members.some(member => member.id === state.selectedMemberId)) {
    state.selectedMemberId = state.members[0]?.id ?? ''
  }
}

const VISION_TASK_STORAGE = 'hct-vision-tasks'

export function rememberVisionTask(taskId: string): void {
  const key = `${VISION_TASK_STORAGE}:${state.actorId}`
  try {
    const existing = JSON.parse(globalThis.localStorage?.getItem(key) ?? '[]') as string[]
    if (!existing.includes(taskId)) existing.unshift(taskId)
    globalThis.localStorage?.setItem(key, JSON.stringify(existing.slice(0, 30)))
  } catch {
    // localStorage unavailable: task tracking degrades to the current page session.
  }
}

export function rememberedVisionTasks(): string[] {
  const key = `${VISION_TASK_STORAGE}:${state.actorId}`
  try {
    return JSON.parse(globalThis.localStorage?.getItem(key) ?? '[]') as string[]
  } catch {
    return []
  }
}

apiClient.setUnauthorizedHandler(() => {
  if (state.sessionToken) expireSession()
})
