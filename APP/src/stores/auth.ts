import { reactive } from 'vue'

import { AuthAdapterError } from '@/api/auth'
import type {
  AuthAdapter,
  AuthSession,
  AuthSessionSlot,
  LoginInput,
  StepUpChallenge,
  StepUpMethod,
} from '@/api/auth'
import { ApiClientError } from '@/api/client'

/**
 * MOB-133 正式会话生命周期。
 *
 * 安全边界：
 * - 会话凭据（token / sessionId）只保存在模块内的普通变量里，不进响应式状态、
 *   不写 localStorage、不进 URL、不进日志或通知；页面只能读到 actorId 和过期时间。
 * - 401、会话过期、撤权都收敛到 `requireReauth`，它会清空凭据、执行清理注册表
 *   并把状态推进到 `reauth-required`，此后写操作一律阻断。
 * - `generation` 参与联机 Provider 指纹，保证会话变化后旧缓存立即被丢弃。
 */

export type AuthStatus = 'anonymous' | 'authenticated' | 'reauth-required'

export type ReauthReason = 'none' | 'expired' | 'revoked' | 'unauthenticated' | 'signed-out'

export interface AuthPublicState {
  status: AuthStatus
  reason: ReauthReason
  /** 服务端确认的 actor；仅用于展示"当前身份"，不参与权限判定。 */
  actorId: string
  expiresAt: string
  /** 会话每次变化都自增，用于失效联机 Provider 与页面缓存。 */
  generation: number
  pendingStepUp: StepUpChallenge | null
}

const state = reactive<AuthPublicState>({
  status: 'anonymous',
  reason: 'none',
  actorId: '',
  expiresAt: '',
  generation: 0,
  pendingStepUp: null,
})

/** 凭据只存在于这里，永不进入响应式图、存储或序列化输出。 */
let credentials: AuthSession | null = null

/** 清理范围：session=身份本身变化（登录/登出/失效）；context=家庭、成员或服务器切换。 */
export type CleanupScope = 'session' | 'context'

type SessionCleanup = (scope: CleanupScope) => void

const cleanups = new Set<SessionCleanup>()

/**
 * 注册会话级清理动作（查询结果、轮询、上传草稿、缓存快照）。
 * 登出、会话失效、切换家庭/成员都会执行；返回取消注册的函数。
 */
export function registerSessionCleanup(cleanup: SessionCleanup): () => void {
  cleanups.add(cleanup)
  return () => cleanups.delete(cleanup)
}

function runCleanups(scope: CleanupScope): void {
  for (const cleanup of [...cleanups]) {
    try {
      cleanup(scope)
    } catch {
      // 单个清理失败不得阻断其余清理或会话销毁。
    }
  }
}

function forgetCredentials(): void {
  credentials = null
  state.actorId = ''
  state.expiresAt = ''
  state.pendingStepUp = null
}

export function authGeneration(): number {
  return state.generation
}

/**
 * HTTP 适配器与 store 共用的唯一会话槽位。
 * 适配器不再自己保存一份凭据，避免出现"store 已登出、适配器仍持有 token"的分叉。
 */
export const authSessionSlot: AuthSessionSlot = {
  get: () => credentials,
  set: next => {
    if (next) adopt(next)
    else forgetCredentials()
  },
}

/** 当前是否处于"必须重新认证"状态；此时禁止任何写操作。 */
export function isWriteBlocked(): boolean {
  return state.status !== 'authenticated'
}

/**
 * 供 ApiClient 读取的会话提供方。
 * 过期会话在这里就被丢弃，避免带着废凭据发出请求。
 */
export function getAuthSession(): AuthSession | null {
  if (!credentials) return null
  if (Date.parse(credentials.expiresAt) <= Date.now()) {
    requireReauth('expired')
    return null
  }
  return credentials
}

/** 会话失效：清空凭据与派生状态，阻断写入，等待重新认证。 */
export function requireReauth(reason: Exclude<ReauthReason, 'none'>): void {
  forgetCredentials()
  state.reason = reason
  state.status = reason === 'signed-out' ? 'anonymous' : 'reauth-required'
  state.generation += 1
  runCleanups('session')
}

/**
 * 切换家庭 / 成员：会话本身仍然有效，但与旧上下文关联的查询、轮询、
 * 上传草稿和缓存必须一起丢弃，避免新上下文显示旧数据。
 */
export function resetSessionScopedState(): void {
  state.generation += 1
  runCleanups('context')
}

function adopt(session: AuthSession): void {
  credentials = session
  state.actorId = session.actorId
  state.expiresAt = session.expiresAt
  state.status = 'authenticated'
  state.reason = 'none'
  state.pendingStepUp = null
  state.generation += 1
}

/** 登录成功后建立正式会话；失败时不留下任何部分状态。 */
export async function signIn(adapter: AuthAdapter, input: LoginInput): Promise<void> {
  forgetCredentials()
  state.status = 'anonymous'
  try {
    // 旧上下文的查询、上传和缓存必须在新身份可用之前清空。
    runCleanups('session')
    adopt(await adapter.login(input))
  } catch (cause) {
    forgetCredentials()
    state.status = 'anonymous'
    state.reason = 'unauthenticated'
    state.generation += 1
    throw cause
  }
}

/** 主动登出：先本地清理再通知服务端，网络失败也不恢复本地会话。 */
export async function signOut(adapter: AuthAdapter | null): Promise<void> {
  requireReauth('signed-out')
  if (!adapter) return
  await adapter.logout()
}

/** 冷启动或恢复前台时续验会话；服务端否认即进入重新认证。 */
export async function revalidate(adapter: AuthAdapter): Promise<boolean> {
  if (!credentials) return false
  const session = await adapter.refresh()
  if (!session) {
    requireReauth('expired')
    return false
  }
  adopt(session)
  return true
}

export async function beginStepUp(
  adapter: AuthAdapter,
  input: { action: string; method: StepUpMethod; householdId?: string },
): Promise<StepUpChallenge> {
  const challenge = await adapter.beginStepUp(input)
  state.pendingStepUp = challenge
  return challenge
}

/** 二次确认成功后清空 challenge；一次性口令不写入任何状态或存储。 */
export async function confirmStepUp(
  adapter: AuthAdapter,
  input: { action: string; method: StepUpMethod; code: string },
): Promise<void> {
  const challenge = state.pendingStepUp
  if (!challenge) {
    throw new AuthAdapterError('请先发起二次确认', { code: 'STEP_UP_REQUIRED', status: 403 })
  }
  await adapter.confirmStepUp({
    challengeId: challenge.id,
    action: input.action,
    method: input.method,
    code: input.code,
  })
  state.pendingStepUp = null
}

export function cancelStepUp(): void {
  state.pendingStepUp = null
}

/**
 * 修改当前身份的登录密码。
 *
 * 服务端会撤销该身份的全部会话并签发新会话，因此这里直接采纳新会话：
 * `generation` 自增会让联机 Provider 与页面缓存自动失效，用户不必重新登录。
 * 两个密码只作为参数传给适配器，不写入 store、存储或日志。
 */
export async function changePassword(
  adapter: AuthAdapter,
  input: { currentPassword: string; newPassword: string },
): Promise<void> {
  const next = await adapter.changePassword(input)
  adopt(next)
  // 旧会话已被服务端作废：与旧会话关联的查询、轮询和上传草稿一并丢弃。
  runCleanups('context')
}

/**
 * 统一处理 API/鉴权异常中的会话失效信号。
 * 返回 true 表示已进入重新认证状态，调用方只需展示提示，不要再重试写操作。
 */
export function handleAuthFailure(cause: unknown): boolean {
  if (cause instanceof AuthAdapterError) {
    if (cause.code === 'AUTH_REVOKED') {
      requireReauth('revoked')
      return true
    }
    if (cause.code === 'SESSION_EXPIRED') {
      requireReauth('expired')
      return true
    }
    return false
  }
  if (!(cause instanceof ApiClientError)) return false
  const code = cause.code.toUpperCase()
  if (code === 'AUTH_REVOKED' || code === 'CONSENT_REVOKED' || code === 'AUTHORIZATION_EXPIRED') {
    requireReauth('revoked')
    return true
  }
  if (cause.status === 401 || code === 'SESSION_EXPIRED' || code === 'UNAUTHENTICATED') {
    requireReauth(code === 'SESSION_EXPIRED' ? 'expired' : 'unauthenticated')
    return true
  }
  return false
}

/**
 * 仅供测试重置会话状态。
 * 故意不清空清理注册表：Provider、能力探测等模块在导入时就注册了清理动作，
 * 清空会让后续用例失去 fail-closed 行为。
 */
export function resetAuthState(): void {
  forgetCredentials()
  state.status = 'anonymous'
  state.reason = 'none'
  state.generation = 0
}

export function useAuth() {
  return {
    auth: state,
    signIn,
    signOut,
    revalidate,
    beginStepUp,
    confirmStepUp,
    cancelStepUp,
    changePassword,
    isWriteBlocked,
    requireReauth,
  }
}
