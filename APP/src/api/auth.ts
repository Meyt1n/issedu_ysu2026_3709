/**
 * 移动端正式鉴权适配契约。
 *
 * HCT-107 尚未提供可联调的认证接口，因此生产代码不会在这里发起登录请求。
 * 该契约只冻结移动端需要的边界，测试桩用于验证会话、登出和二次确认语义。
 * 凭据与会话只允许保存在内存中，不能写入 localStorage、日志或 URL。
 */

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
  beginStepUp(input: { action: string; method: StepUpMethod }): Promise<StepUpChallenge>
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
