import { ApiClient, ApiClientError } from '@/api/client'
import { clearRequestTraces } from '@/api/requestLog'
import {
  getAuthSession,
  handleAuthFailure,
  registerSessionCleanup,
  useAuth,
} from '@/stores/auth'
import {
  isAuthorizationRejection,
  requireAuthorizationReverification,
  sessionContextKey,
  useAuthorizationBoundary,
  useSession,
} from '@/stores/session'
import { clearCapabilities } from '@/stores/capabilities'

import { demoProvider } from './demoProvider'
import { HttpDataProvider } from './httpProvider'
import type { DataProvider } from './types'

let liveProvider: HttpDataProvider | null = null
let liveProviderKey: string | null = null

function dropLiveProvider(): void {
  // 上传草稿、成员/任务缓存和已解析的家庭 ID 都挂在 Provider 实例上，
  // 丢弃实例即等于清理这一轮会话的查询与缓存状态。
  liveProvider = null
  liveProviderKey = null
}

/** 会话或上下文变化时丢弃联机缓存；身份变化时连能力探测快照一起作废。 */
registerSessionCleanup(scope => {
  dropLiveProvider()
  // MOB-144：会话/上下文变化时清空请求回执追踪，旧身份的标识不残留。
  clearRequestTraces()
  if (scope === 'session') clearCapabilities()
})

function rejectingProvider(error: () => ApiClientError): DataProvider {
  return new Proxy({} as DataProvider, {
    get(_target, property) {
      if (typeof property !== 'string') return undefined
      return () => Promise.reject(error())
    },
  })
}

function authorizationBlockedProvider(): DataProvider {
  return rejectingProvider(() => new ApiClientError('授权状态需要重新验证', {
    status: 403,
    code: 'AUTHORIZATION_REVERIFICATION_REQUIRED',
  }))
}

/**
 * 正式鉴权模式下未登录 / 会话已失效：读写全部 fail-closed。
 * 页面拿不到任何旧会话数据，也无法提交写操作，只能重新登录。
 */
function reauthRequiredProvider(): DataProvider {
  const { auth } = useAuth()
  const revoked = auth.reason === 'revoked'
  return rejectingProvider(() => new ApiClientError(
    revoked ? '登录会话已被撤销，请重新登录' : '登录会话已失效，请重新登录',
    { status: 401, code: revoked ? 'AUTH_REVOKED' : 'SESSION_EXPIRED' },
  ))
}

/**
 * A single authorization denial invalidates every page's context key. No API
 * response is cached locally: capabilities, selected member and provider
 * in-memory state are discarded before callers render their error guidance.
 */
function guardAuthorization(provider: DataProvider): DataProvider {
  return new Proxy(provider, {
    get(target, property, receiver) {
      const value = Reflect.get(target, property, receiver)
      if (typeof value !== 'function') return value
      return (...args: unknown[]) => Promise.resolve(value.apply(target, args)).catch((cause: unknown) => {
        // 401/会话过期/撤权先收敛到正式会话生命周期，再落到授权边界。
        if (handleAuthFailure(cause)) throw cause
        // 已选家庭失效：丢弃缓存让后续请求继续 fail-closed，但**保留**这个失效的
        // 选择，好让设置页读到它并明确告诉用户"之前选的家庭已不可用"。若在这里就
        // 清空，用户之后只会看到泛泛的"请选择家庭"，无从知道原因（NFR-07）。
        if (cause instanceof ApiClientError && cause.code === 'HOUSEHOLD_UNAVAILABLE') {
          dropLiveProvider()
          throw cause
        }
        if (isAuthorizationRejection(cause)) {
          clearCapabilities()
          requireAuthorizationReverification()
          dropLiveProvider()
        }
        throw cause
      })
    },
  }) as DataProvider
}

/** Returns the active provider with a fail-closed authorization boundary in live mode. */
export function activeProvider(): DataProvider {
  const { session } = useSession()
  const { authorizationBoundary } = useAuthorizationBoundary()
  const { auth } = useAuth()
  if (session.dataMode !== 'live') return demoProvider
  if (session.authMode === 'real' && auth.status !== 'authenticated') return reauthRequiredProvider()
  if (authorizationBoundary.status !== 'active') return authorizationBlockedProvider()

  const providerKey = sessionContextKey(session)
  if (!liveProvider || liveProviderKey !== providerKey) {
    liveProviderKey = providerKey
    const client = new ApiClient({
      baseUrl: session.serverBaseUrl,
      // 正式模式：只从内存会话读取凭据，永不回退 X-Actor-Id。
      // 开发模式：不注入提供方，保留显式标注的开发期身份头路径。
      ...(session.authMode === 'real' ? { authSessionProvider: getAuthSession } : {}),
    })
    liveProvider = new HttpDataProvider(client, () => ({
      // 正式模式使用服务端确认的 actor，仅用于前置校验；请求身份由 Bearer/Cookie 承载。
      actorId: session.authMode === 'real' ? auth.actorId : session.actorId,
      accessPurpose: session.accessPurpose,
      householdId: session.currentHouseholdId,
    }))
  }
  return guardAuthorization(liveProvider)
}

/**
 * 联机模式下构造指向「家庭服务器」的 ApiClient（例如电脑本机 FastAPI）。
 * 演示模式返回 null，由页面给出诚实降级说明，不伪装助手可用。
 */
export function createLiveApiClient(): ApiClient | null {
  const { session } = useSession()
  const { auth } = useAuth()
  if (session.dataMode !== 'live') return null
  if (session.authMode === 'real' && auth.status !== 'authenticated') return null
  return new ApiClient({
    baseUrl: session.serverBaseUrl,
    ...(session.authMode === 'real' ? { authSessionProvider: getAuthSession } : {}),
  })
}

/** 当前是否允许发起写操作；正式会话失效时页面必须禁用提交入口。 */
export function canSubmitWrites(): boolean {
  const { session } = useSession()
  const { auth } = useAuth()
  if (session.dataMode !== 'live') return true
  if (session.authMode === 'dev-actor') return true
  return auth.status === 'authenticated'
}

/**
 * 显式选择家庭。
 *
 * 走 `updateSession` 是必须的：它会触发上下文清理，丢弃上一个家庭的成员、任务、
 * 风险、时间线、上传草稿与 Provider 缓存，避免新家庭页面上出现旧家庭数据。
 */
export function selectHousehold(householdId: string): void {
  const { session, updateSession } = useSession()
  if (session.currentHouseholdId === householdId) return
  updateSession({ currentHouseholdId: householdId, currentMemberId: '' })
}

/** 让当前家庭选择失效，回到安全选择态（撤权、删除或列表变化时使用）。 */
export function clearHouseholdSelection(): void {
  const { session, updateSession } = useSession()
  if (!session.currentHouseholdId && !session.currentMemberId) return
  updateSession({ currentHouseholdId: '', currentMemberId: '' })
}
