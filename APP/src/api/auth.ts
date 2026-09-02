/**
 * 移动端正式鉴权适配契约与 HTTP 适配器。
 *
 * MOB-115 冻结了边界，MOB-133 在此之上补上真正发请求的 `createHttpAuthAdapter`。
 * 凭据与会话只允许保存在内存中，不能写入 localStorage、日志或 URL：
 * 本文件不调用 console，也不把账号、密码、token、PIN 拼进 URL 或错误消息。
 */

import { validateServerBaseUrl } from '@/utils/serverUrl'

export type AuthTransport = 'bearer' | 'cookie' | 'development-header'

export type AuthErrorCode =
  | 'AUTH_FAILED'
  | 'AUTH_LOCKED'
  | 'AUTH_UNAVAILABLE'
  | 'SESSION_EXPIRED'
  | 'AUTH_REVOKED'
  | 'STEP_UP_REQUIRED'
  | 'STEP_UP_FAILED'
  | 'STEP_UP_EXPIRED'
  | 'STEP_UP_REPLAY'
  /** 该家庭还没设置过 PIN，属于配置问题，不是会话失效。 */
  | 'STEP_UP_NOT_CONFIGURED'
  /** 该身份在多个家庭配置过 PIN，必须显式指定家庭。 */
  | 'STEP_UP_HOUSEHOLD_REQUIRED'

export class AuthAdapterError extends Error {
  readonly code: AuthErrorCode
  readonly status: number

  constructor(message: string, options: { code: AuthErrorCode; status?: number }) {
    super(message)
    this.name = 'AuthAdapterError'
    this.code = options.code
    this.status = options.status ?? 401
  }
}

export interface AuthSession {
  /** 服务端确认后的稳定 actor 标识；不由移动端自行推断。 */
  actorId: string
  /** 仍沿用主仓库授权契约的 ASCII 访问目的代码。 */
  accessPurpose: string
  /** bearer/cookie 为正式适配路径，development-header 仅保留给本地联调。 */
  transport: AuthTransport
  /** 仅 bearer 传输使用；不得持久化。 */
  accessToken?: string
  /** cookie 传输由 WebView/浏览器管理，移动端不读取 cookie 内容。 */
  sessionId?: string
  expiresAt: string
}

export interface LoginInput {
  account: string
  password: string
}

export type StepUpMethod = 'pin' | 'qr'

export interface StepUpChallenge {
  id: string
  action: string
  method: StepUpMethod
  expiresAt: string
}

export interface StepUpInput {
  challengeId: string
  action: string
  method: StepUpMethod
  code: string
}

export interface StepUpGrant {
  challengeId: string
  action: string
  confirmedAt: string
}

export interface AuthAdapter {
  login(input: LoginInput): Promise<AuthSession>
  logout(): Promise<void>
  refresh(): Promise<AuthSession | null>
  getSession(): AuthSession | null
  beginStepUp(input: { action: string; method: StepUpMethod; householdId?: string }): Promise<StepUpChallenge>
  confirmStepUp(input: StepUpInput): Promise<StepUpGrant>
}

export interface AuthTestStubOptions {
  account?: string
  password?: string
  now?: () => number
  sessionTtlMs?: number
  challengeTtlMs?: number
  maxAttempts?: number
  lockoutMs?: number
}

function iso(time: number): string {
  return new Date(time).toISOString()
}

/**
 * 仅供 Vitest 使用的内存测试桩，不代表正式登录实现。
 * 它刻意不接受 serverBaseUrl、不写存储，也不产生真实网络请求。
 */
export function createAuthTestStub(options: AuthTestStubOptions = {}): AuthAdapter {
  const account = options.account ?? 'demo-account'
  const password = options.password ?? 'demo-password'
  const now = options.now ?? (() => Date.now())
  const sessionTtlMs = options.sessionTtlMs ?? 5 * 60_000
  const challengeTtlMs = options.challengeTtlMs ?? 60_000
  const maxAttempts = options.maxAttempts ?? 3
  const lockoutMs = options.lockoutMs ?? 60_000

  let session: AuthSession | null = null
  let failedAttempts = 0
  let lockedUntil = 0
  let challenge: (StepUpChallenge & { used: boolean; sessionId: string }) | null = null
  let sequence = 0

  function requireSession(): AuthSession {
    if (!session) {
      throw new AuthAdapterError('请先完成登录', { code: 'SESSION_EXPIRED' })
    }
    if (Date.parse(session.expiresAt) <= now()) {
      session = null
      throw new AuthAdapterError('登录会话已过期', { code: 'SESSION_EXPIRED' })
    }
    return session
  }

  return {
    async login(input) {
      if (lockedUntil > now()) {
        throw new AuthAdapterError('登录失败', { code: 'AUTH_FAILED' })
      }
      if (input.account !== account || input.password !== password) {
        failedAttempts += 1
        if (failedAttempts >= maxAttempts) lockedUntil = now() + lockoutMs
        // HCT-107 对外统一失败文案，避免账号枚举；不暴露剩余次数或锁定细节。
        throw new AuthAdapterError('登录失败', { code: 'AUTH_FAILED' })
      }

      failedAttempts = 0
      lockedUntil = 0
      sequence += 1
      const timestamp = now()
      session = {
        actorId: account,
        accessPurpose: 'family-care',
        transport: 'bearer',
        accessToken: `test-only-token-${sequence}`,
        sessionId: `test-session-${sequence}`,
        expiresAt: iso(timestamp + sessionTtlMs),
      }
      return session
    },

    async logout() {
      session = null
      challenge = null
    },

    async refresh() {
      if (!session) return null
      if (Date.parse(session.expiresAt) <= now()) {
        session = null
        return null
      }
      return session
    },

    getSession() {
      return session
    },

    async beginStepUp(input) {
      const activeSession = requireSession()
      sequence += 1
      challenge = {
        id: `test-challenge-${sequence}`,
        action: input.action,
        method: input.method,
        expiresAt: iso(now() + challengeTtlMs),
        used: false,
        sessionId: activeSession.sessionId ?? '',
      }
      return challenge
    },

    async confirmStepUp(input) {
      const activeSession = requireSession()
      if (!challenge || challenge.id !== input.challengeId || challenge.sessionId !== activeSession.sessionId) {
        throw new AuthAdapterError('二次确认无效', { code: 'STEP_UP_FAILED' })
      }
      if (challenge.used) {
        throw new AuthAdapterError('二次确认已使用', { code: 'STEP_UP_REPLAY' })
      }
      if (Date.parse(challenge.expiresAt) <= now()) {
        throw new AuthAdapterError('二次确认已过期', { code: 'STEP_UP_EXPIRED' })
      }
      if (challenge.action !== input.action || challenge.method !== input.method) {
        throw new AuthAdapterError('二次确认无效', { code: 'STEP_UP_FAILED' })
      }

      const expectedCode = input.method === 'pin' ? '123456' : 'QR-TEST'
      if (input.code !== expectedCode) {
        throw new AuthAdapterError('二次确认无效', { code: 'STEP_UP_FAILED' })
      }

      challenge.used = true
      return {
        challengeId: challenge.id,
        action: challenge.action,
        confirmedAt: iso(now()),
      }
    },
  }
}

// ── HCT-107 正式鉴权 HTTP 适配（MOB-133） ────────────────────────────

/** HCT-107 认证端点前缀；与业务接口共用 `/api/v1`。 */
export const AUTH_PATH_PREFIX = '/api/v1/auth'

export interface HttpAuthAdapterOptions {
  /** 家庭服务器基地址；留空表示同源。必须通过 serverUrl 明文 HTTP 边界校验。 */
  baseUrl?: string
  fetcher?: typeof fetch
  /** bearer=服务端返回会话 token；cookie=服务端下发 HttpOnly Cookie，移动端不读取内容。 */
  transport?: Extract<AuthTransport, 'bearer' | 'cookie'>
  /** ASCII 访问目的代码，随业务请求发送；不参与身份判定。 */
  accessPurpose?: string
  /**
   * 会话存放位置。默认保存在适配器闭包内；接入会话 store 时传入 store 的槽位，
   * 保证全应用只有一份会话副本，不会出现"store 已登出、适配器仍持有 token"的分叉。
   */
  session?: AuthSessionSlot
}

export interface AuthSessionSlot {
  get(): AuthSession | null
  set(next: AuthSession | null): void
}

function memorySessionSlot(): AuthSessionSlot {
  let value: AuthSession | null = null
  return {
    get: () => value,
    set: next => {
      value = next
    },
  }
}

/**
 * 把服务端过期时间归一化成 ISO 字符串。
 *
 * HCT-107 现实现返回 `time.time()` 秒级浮点数，契约也允许 ISO 字符串；
 * 两种都接受，无法解析时视为契约不足而不是"永不过期"。
 */
export function normalizeAuthExpiresAt(value: unknown): string | null {
  if (typeof value === 'number' && Number.isFinite(value) && value > 0) {
    // 小于 1e12 视为秒级时间戳（约 2001-09 之后的毫秒时间戳都大于 1e12）。
    const ms = value < 1e12 ? value * 1000 : value
    return new Date(ms).toISOString()
  }
  if (typeof value === 'string' && value.trim()) {
    const parsed = Date.parse(value.trim())
    if (Number.isFinite(parsed)) return new Date(parsed).toISOString()
  }
  return null
}

type AuthOperation = 'login' | 'logout' | 'session' | 'stepUpBegin' | 'stepUpConfirm'

/** 契约不一致（缺字段、参数形态不同）统一按"暂时不可用"提示，不引导用户重试密码。 */
const CONTRACT_MISMATCH = '家庭服务器的鉴权接口与移动端契约不一致，请联系维护者核对 HCT-107 接口。'

function detailOf(body: unknown): string {
  if (typeof body !== 'object' || body === null) return ''
  const record = body as Record<string, unknown>
  const nested = record['error']
  if (typeof nested === 'object' && nested !== null) {
    const code = (nested as Record<string, unknown>)['code']
    if (typeof code === 'string') return code
  }
  return typeof record['detail'] === 'string' ? record['detail'] : ''
}

/**
 * 把 HTTP 状态和服务端 detail 映射成移动端错误码。
 *
 * 登录失败统一文案避免账号枚举；会话类失败区分过期与撤销，便于页面选择
 * "重新登录"还是"重新发起操作"。永不回显账号、密码、token 或 PIN。
 */
function mapAuthError(operation: AuthOperation, status: number, body: unknown): AuthAdapterError {
  const detail = detailOf(body).toUpperCase()
  if (status === 0) {
    return new AuthAdapterError('家庭服务器暂时无法访问', { code: 'AUTH_UNAVAILABLE', status: 0 })
  }
  if (status === 429 || detail.startsWith('LOCKED')) {
    return new AuthAdapterError('登录暂时被锁定，请稍后再试', { code: 'AUTH_LOCKED', status })
  }
  // 二次确认的配置问题必须先于"契约不一致"和会话失效分支判断：
  // 它既不是接口缺失，也不该导致清空会话把用户踢回登录页。
  if (detail === 'PIN_NOT_CONFIGURED') {
    return new AuthAdapterError('尚未设置家庭 PIN', { code: 'STEP_UP_NOT_CONFIGURED', status })
  }
  if (detail === 'HOUSEHOLD_REQUIRED') {
    return new AuthAdapterError('需要先选定家庭', { code: 'STEP_UP_HOUSEHOLD_REQUIRED', status })
  }
  if (detail === 'STEP_UP_REPLAY') {
    return new AuthAdapterError('二次确认已经使用过', { code: 'STEP_UP_REPLAY', status })
  }
  if (detail === 'STEP_UP_EXPIRED') {
    return new AuthAdapterError('二次确认已过期', { code: 'STEP_UP_EXPIRED', status })
  }
  if (detail === 'STEP_UP_FAILED') {
    return new AuthAdapterError('二次确认未通过', { code: 'STEP_UP_FAILED', status })
  }
  if (status === 422 || status === 400 || status === 404 || status === 405 || status >= 500) {
    return new AuthAdapterError(CONTRACT_MISMATCH, { code: 'AUTH_UNAVAILABLE', status })
  }
  if (operation === 'login') {
    return new AuthAdapterError('登录失败', { code: 'AUTH_FAILED', status })
  }
  if (operation === 'stepUpBegin' || operation === 'stepUpConfirm') {
    if (status === 409 || status === 410) {
      return new AuthAdapterError('二次确认已过期或已经使用', { code: 'STEP_UP_EXPIRED', status })
    }
    if (status === 403) {
      return new AuthAdapterError('二次确认未通过', { code: 'STEP_UP_FAILED', status })
    }
  }
  if (status === 403) {
    return new AuthAdapterError('登录会话已被撤销', { code: 'AUTH_REVOKED', status })
  }
  return new AuthAdapterError('登录会话已失效', { code: 'SESSION_EXPIRED', status })
}

/**
 * 对接 HCT-107 的正式鉴权适配器。
 *
 * 契约（见 docs/stories/MOB-133-正式鉴权与会话生命周期联调.md）：
 * - 凭据只走 POST JSON body，绝不进 query string，避免落进访问日志与浏览器历史；
 * - `POST {prefix}/login` → `{ actor_id, session_token, expires_at }`（HCT-423 起已是 JSON body）；
 * - `POST {prefix}/logout` → body `{ session_token }`，服务端销毁会话；移动端无论成败都清空本地会话；
 * - `POST {prefix}/session` → 会话续验，401 表示已过期或已撤销；
 * - `POST {prefix}/pin-challenge` → `{ challenge_id, action, expires_at }`，**不得回显 PIN**；
 * - `POST {prefix}/pin-verify` → `{ status: "confirmed" }`。
 *
 * 尚未提供或形态不符的端点会返回 `AUTH_UNAVAILABLE`，页面如实提示契约不一致，
 * 不伪造登录成功或二次确认成功。
 */
export function createHttpAuthAdapter(options: HttpAuthAdapterOptions = {}): AuthAdapter {
  const validated = validateServerBaseUrl(options.baseUrl ?? '')
  if (!validated.ok) {
    throw new AuthAdapterError(validated.message, { code: 'AUTH_UNAVAILABLE', status: 0 })
  }
  const baseUrl = validated.value
  const fetcher = options.fetcher ?? globalThis.fetch.bind(globalThis)
  const transport = options.transport ?? 'bearer'
  const accessPurpose = (options.accessPurpose ?? 'family-care').trim() || 'family-care'

  /** 会话唯一副本；不进响应式状态，也不写任何存储。 */
  const slot = options.session ?? memorySessionSlot()

  async function post(
    operation: AuthOperation,
    path: string,
    body: Record<string, unknown>,
    authorize: boolean,
  ): Promise<Record<string, unknown>> {
    const headers = new Headers({ Accept: 'application/json', 'Content-Type': 'application/json' })
    headers.set('X-Access-Purpose', accessPurpose)
    const current = slot.get()
    if (authorize && transport === 'bearer' && current?.accessToken) {
      headers.set('Authorization', `Bearer ${current.accessToken}`)
    }

    let response: Response
    try {
      response = await fetcher(`${baseUrl}${AUTH_PATH_PREFIX}${path}`, {
        method: 'POST',
        headers,
        body: JSON.stringify(body),
        credentials: transport === 'cookie' ? 'include' : undefined,
      })
    } catch {
      throw mapAuthError(operation, 0, null)
    }

    const text = await response.text()
    let parsed: unknown = null
    if (text) {
      try {
        parsed = JSON.parse(text) as unknown
      } catch {
        parsed = { detail: 'NON_JSON_RESPONSE' }
      }
    }
    if (!response.ok) throw mapAuthError(operation, response.status, parsed)
    return (typeof parsed === 'object' && parsed !== null ? parsed : {}) as Record<string, unknown>
  }

  function readText(source: Record<string, unknown>, ...keys: string[]): string {
    for (const key of keys) {
      const value = source[key]
      if (typeof value === 'string' && value.trim()) return value.trim()
    }
    return ''
  }

  function contractMismatch(): AuthAdapterError {
    return new AuthAdapterError(CONTRACT_MISMATCH, { code: 'AUTH_UNAVAILABLE', status: 502 })
  }

  function buildSession(payload: Record<string, unknown>, account: string): AuthSession {
    const expiresAt = normalizeAuthExpiresAt(payload['expires_at'] ?? payload['expiresAt'])
    if (!expiresAt) throw contractMismatch()
    const accessToken = readText(payload, 'session_token', 'access_token')
    // bearer 传输必须拿到会话 token；cookie 传输由 WebView/浏览器持有，客户端不读取。
    if (transport === 'bearer' && !accessToken) throw contractMismatch()

    const built: AuthSession = {
      // 契约要求服务端回显已认证的 actor；缺失时退回本次已通过密码校验的账号，
      // 不从姓名、成员 ID 或页面角色推断身份。
      actorId: readText(payload, 'actor_id', 'actorId') || account,
      accessPurpose,
      transport,
      expiresAt,
    }
    if (transport === 'bearer') built.accessToken = accessToken
    const sessionId = readText(payload, 'session_id', 'sessionId')
    if (sessionId) built.sessionId = sessionId
    return built
  }

  function activeSession(): AuthSession {
    const current = slot.get()
    if (!current) throw new AuthAdapterError('请先完成登录', { code: 'SESSION_EXPIRED' })
    if (Date.parse(current.expiresAt) <= Date.now()) {
      slot.set(null)
      throw new AuthAdapterError('登录会话已过期', { code: 'SESSION_EXPIRED' })
    }
    return current
  }

  return {
    async login(input) {
      const account = input.account.trim()
      if (!account || !input.password) {
        throw new AuthAdapterError('登录失败', { code: 'AUTH_FAILED', status: 401 })
      }
      // 账号密码只出现在请求体里；不拼 URL、不写日志、不进异常消息。
      const payload = await post('login', '/login', { actor_id: account, password: input.password }, false)
      const next = buildSession(payload, account)
      slot.set(next)
      return next
    },

    async logout() {
      const current = slot.get()
      // 先本地清理，保证网络失败也不残留可用凭据。
      slot.set(null)
      if (!current) return
      try {
        await post(
          'logout',
          '/logout',
          current.accessToken ? { session_token: current.accessToken } : {},
          false,
        )
      } catch (cause) {
        // 服务端不可达时本地已经登出；仅当会话仍可能存活才向上报告。
        if (cause instanceof AuthAdapterError && cause.code === 'AUTH_UNAVAILABLE') return
        throw cause
      }
    },

    async refresh() {
      const current = slot.get()
      if (!current) return null
      if (Date.parse(current.expiresAt) <= Date.now()) {
        slot.set(null)
        return null
      }
      try {
        const payload = await post('session', '/session', {}, true)
        const next = buildSession(payload, current.actorId)
        slot.set(next)
        return next
      } catch (cause) {
        if (cause instanceof AuthAdapterError
          && (cause.code === 'SESSION_EXPIRED' || cause.code === 'AUTH_REVOKED')) {
          slot.set(null)
          return null
        }
        throw cause
      }
    },

    getSession() {
      return slot.get()
    },

    async beginStepUp(input) {
      activeSession()
      const payload = await post('stepUpBegin', '/pin-challenge', {
        action: input.action,
        method: input.method,
        // 家庭由服务端校验成员关系；只在调用方已知家庭时显式指定，避免多家庭歧义。
        ...(input.householdId ? { household_id: input.householdId } : {}),
      }, true)
      // 服务端回显一次性口令等于把二次确认降级成摆设；契约禁止，检测到即拒绝。
      if (readText(payload, 'pin', 'pin_code', 'code')) throw contractMismatch()
      const id = readText(payload, 'challenge_id', 'challengeId', 'id')
      const expiresAt = normalizeAuthExpiresAt(payload['expires_at'] ?? payload['expiresAt'])
      if (!id || !expiresAt) throw contractMismatch()
      return {
        id,
        action: readText(payload, 'action') || input.action,
        method: input.method,
        expiresAt,
      }
    },

    async confirmStepUp(input) {
      activeSession()
      const payload = await post('stepUpConfirm', '/pin-verify', {
        challenge_id: input.challengeId,
        action: input.action,
        method: input.method,
        code: input.code,
      }, true)
      if (readText(payload, 'status') !== 'confirmed') throw contractMismatch()
      return {
        challengeId: input.challengeId,
        action: input.action,
        confirmedAt: normalizeAuthExpiresAt(payload['confirmed_at']) ?? new Date().toISOString(),
      }
    },
  }
}
