import { reactive } from 'vue'

import { ApiClientError } from '@/api/client'
import { authGeneration, resetSessionScopedState } from '@/stores/auth'

import { normalizePhoneNumber } from '@/utils/phone'
import { validateServerBaseUrl } from '@/utils/serverUrl'

export type DataMode = 'demo' | 'live'

/** real=HCT-107 正式登录会话；dev-actor=开发期 X-Actor-Id 联调路径。 */
export type AuthMode = 'real' | 'dev-actor'

export interface SessionSettings {
  /** demo=内置虚构演示数据；live=连接家庭服务器（主仓库 FastAPI） */
  dataMode: DataMode
  /** 联机模式 API 基地址；留空表示同源（配合部署或 dev 代理） */
  serverBaseUrl: string
  /** 联机身份来源；正式构建只允许 real */
  authMode: AuthMode
  /** 仅 dev-actor 模式使用的开发期身份 */
  actorId: string
  accessPurpose: string
  /**
   * 当前选择的家庭 ID。只保存最小标识，不保存家庭名称或任何健康数据；
   * 家庭选择不是授权，服务端仍对每个请求做家庭/成员/字段/动作校验。
   */
  currentHouseholdId: string
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
  authMode: 'real',
  actorId: '',
  accessPurpose: 'family-care',
  currentHouseholdId: '',
  caregiverName: '',
  caregiverPhone: '',
  currentMemberId: '',
}

/**
 * 开发态 actor 门禁。
 *
 * 只有显式开发配置才允许 `X-Actor-Id` 路径：构建时 `VITE_ALLOW_DEV_ACTOR=true`，
 * 或本地 `vite dev`。正式构建（`npm run build` 且未设置该变量）下开发入口既不
 * 渲染，也会在启动时把已保存的 `dev-actor` 强制回退成 `real`，避免旧配置把
 * 生产请求伪装成联调请求。
 */
function computeDevActorEnabled(): boolean {
  const flag = String(import.meta.env.VITE_ALLOW_DEV_ACTOR ?? '').trim().toLowerCase()
  if (flag === 'true' || flag === '1') return true
  if (flag === 'false' || flag === '0') return false
  return import.meta.env.DEV === true
}

let devActorEnabled = computeDevActorEnabled()

export function isDevActorEnabled(): boolean {
  return devActorEnabled
}

/** 仅供测试模拟"正式构建未开启开发配置"。 */
export function setDevActorEnabledForTests(value: boolean): void {
  devActorEnabled = value
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
/** 影响联机数据边界的会话指纹；身份、目的、家庭服务器或正式会话变化都必须丢弃旧 Provider 缓存。 */
export function sessionContextKey(source: Pick<SessionSettings, 'dataMode' | 'serverBaseUrl' | 'actorId' | 'accessPurpose'> & { authMode?: AuthMode; currentHouseholdId?: string }): string {
  return [source.dataMode, source.serverBaseUrl.trim(), source.authMode ?? 'real', source.actorId.trim(), source.accessPurpose.trim(), source.currentHouseholdId ?? '', String(authorizationBoundary.generation), String(authGeneration())].join('\u001f')
}

export function normalizeSession(raw: unknown): SessionSettings {
  if (typeof raw !== 'object' || raw === null) return { ...DEFAULT_SESSION }
  const record = raw as Record<string, unknown>
  const text = (value: unknown, fallback: string): string =>
    typeof value === 'string' ? value : fallback
  const serverBaseUrl = text(record.serverBaseUrl, '')
  const validatedServerBaseUrl = validateServerBaseUrl(serverBaseUrl)
  const caregiverPhone = normalizePhoneNumber(text(record.caregiverPhone, ''))
  // 未开启开发配置时，任何已保存的 dev-actor 都回退到正式鉴权。
  const authMode: AuthMode = record.authMode === 'dev-actor' && devActorEnabled ? 'dev-actor' : 'real'
  return {
    dataMode: record.dataMode === 'live' ? 'live' : 'demo',
    serverBaseUrl: validatedServerBaseUrl.ok
      ? validatedServerBaseUrl.value
      : '',
    authMode,
    actorId: authMode === 'dev-actor' ? text(record.actorId, '') : '',
    currentHouseholdId: text(record.currentHouseholdId, ''),
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
    // 只写入非敏感的界面配置。token、密码、PIN 与健康数据永不进入 localStorage：
    // 正式会话凭据保存在 stores/auth.ts 的内存变量里，不属于 SessionSettings。
    localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(state))
  } catch {
    // 存储不可用时静默降级。
  }
}

/** 切换后必须丢弃旧上下文查询、轮询、上传和缓存的字段。 */
const SCOPE_FIELDS: readonly (keyof SessionSettings)[] = [
  'dataMode',
  'serverBaseUrl',
  'authMode',
  'actorId',
  'accessPurpose',
  'currentHouseholdId',
  'currentMemberId',
]

export function updateSession(patch: Partial<SessionSettings>): void {
  const scopeChanged = SCOPE_FIELDS.some(
    field => field in patch && patch[field] !== state[field],
  )
  Object.assign(state, patch)
  persist()
  // 切换家庭服务器、身份来源、访问目的或当前成员都会失效旧数据上下文。
  if (scopeChanged) resetSessionScopedState()
}

export function resetSession(): void {
  Object.assign(state, { ...DEFAULT_SESSION })
  persist()
  resetSessionScopedState()
}

export function useSession() {
  return { session: state, updateSession, resetSession }
}
