import { reactive } from 'vue'

import { ApiClientError } from '@/api/client'

import { normalizePhoneNumber } from '@/utils/phone'
import { validateServerBaseUrl } from '@/utils/serverUrl'

export type DataMode = 'demo' | 'live'

export interface SessionSettings {
  /** demo=内置虚构演示数据；live=连接家庭服务器（主仓库 FastAPI） */
  dataMode: DataMode
  /** 联机模式 API 基地址；留空表示同源（配合部署或 dev 代理） */
  serverBaseUrl: string
  actorId: string
  accessPurpose: string
  /** 紧急联系人（本地保存，仅用于拨号按钮） */
  caregiverName: string
  caregiverPhone: string
  /** 当前正在查看/照护的成员 */
  currentMemberId: string
}

export const SESSION_STORAGE_KEY = 'hct-mobile.session.v1'

export const DEFAULT_SESSION: SessionSettings = {
  dataMode: 'demo',
  serverBaseUrl: '',
  actorId: '',
  accessPurpose: 'family-care',
  caregiverName: '',
  caregiverPhone: '',
  currentMemberId: '',
}

export type AuthorizationBoundaryStatus = 'active' | 'reverification-required'

/** Memory-only fail-closed state; authorization is never restored from a local snapshot. */
const authorizationBoundary = reactive<{
  status: AuthorizationBoundaryStatus
  generation: number
}>({ status: 'active', generation: 0 })

export function isAuthorizationRejection(cause: unknown): cause is ApiClientError {
  if (!(cause instanceof ApiClientError)) return false
  const code = cause.code.toUpperCase()
  return cause.status === 401
    || cause.status === 403
    || cause.status === 404
    || code === 'CONSENT_REVOKED'
    || code === 'AUTHORIZATION_EXPIRED'
    || code === 'AUTH_REVOKED'
    || code === 'RESOURCE_NOT_FOUND'
}

/** Clear local member selection and block further data requests until re-verification. */
export function requireAuthorizationReverification(): void {
  authorizationBoundary.status = 'reverification-required'
  authorizationBoundary.generation += 1
  state.currentMemberId = ''
  persist()
}

/** Only an explicit settings or re-authentication action may reopen the boundary. */
export function resumeAuthorizationBoundary(): void {
  authorizationBoundary.status = 'active'
  authorizationBoundary.generation += 1
}

export function useAuthorizationBoundary() {
  return { authorizationBoundary, requireAuthorizationReverification, resumeAuthorizationBoundary }
}
/** 影响联机数据边界的会话指纹；身份、目的或家庭服务器变化都必须丢弃旧 Provider 缓存。 */
export function sessionContextKey(source: Pick<SessionSettings, 'dataMode' | 'serverBaseUrl' | 'actorId' | 'accessPurpose'>): string {
  return [source.dataMode, source.serverBaseUrl.trim(), source.actorId.trim(), source.accessPurpose.trim(), String(authorizationBoundary.generation)].join('\u001f')
}

export function normalizeSession(raw: unknown): SessionSettings {
  if (typeof raw !== 'object' || raw === null) return { ...DEFAULT_SESSION }
  const record = raw as Record<string, unknown>
  const text = (value: unknown, fallback: string): string =>
    typeof value === 'string' ? value : fallback
  const serverBaseUrl = text(record.serverBaseUrl, '')
  const validatedServerBaseUrl = validateServerBaseUrl(serverBaseUrl)
  const caregiverPhone = normalizePhoneNumber(text(record.caregiverPhone, ''))
  return {
    dataMode: record.dataMode === 'live' ? 'live' : 'demo',
    serverBaseUrl: validatedServerBaseUrl.ok
      ? validatedServerBaseUrl.value
      : '',
    actorId: text(record.actorId, ''),
    accessPurpose: text(record.accessPurpose, 'family-care') || 'family-care',
    caregiverName: text(record.caregiverName, ''),
    caregiverPhone: caregiverPhone ?? '',
    currentMemberId: text(record.currentMemberId, ''),
  }
}

function load(): SessionSettings {
  if (typeof localStorage === 'undefined') return { ...DEFAULT_SESSION }
  try {
    const text = localStorage.getItem(SESSION_STORAGE_KEY)
    if (!text) return { ...DEFAULT_SESSION }
    return normalizeSession(JSON.parse(text))
  } catch {
    return { ...DEFAULT_SESSION }
  }
}

const state = reactive<SessionSettings>(load())

function persist(): void {
  if (typeof localStorage === 'undefined') return
  try {
    localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(state))
  } catch {
    // 存储不可用时静默降级。
  }
}

export function updateSession(patch: Partial<SessionSettings>): void {
  Object.assign(state, patch)
  persist()
}

export function resetSession(): void {
  Object.assign(state, { ...DEFAULT_SESSION })
  persist()
}

export function useSession() {
  return { session: state, updateSession, resetSession }
}
