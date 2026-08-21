import { describe, expect, it } from 'vitest'

import {
  AuthAdapterError,
  createAuthTestStub,
  createHttpAuthAdapter,
  normalizeAuthExpiresAt,
} from './auth'

interface RecordedRequest {
  url: string
  init: RequestInit
}

/** 构造一个只回放固定响应的 fetch，并记录请求以断言凭据没有进 URL。 */
function recordingFetcher(
  replies: { status?: number; body?: unknown }[],
): { fetcher: typeof fetch; requests: RecordedRequest[] } {
  const requests: RecordedRequest[] = []
  let index = 0
  const fetcher = (async (input: RequestInfo | URL, init: RequestInit = {}) => {
    requests.push({ url: String(input), init })
    const reply = replies[Math.min(index, replies.length - 1)] ?? {}
    index += 1
    const status = reply.status ?? 200
    return {
      ok: status >= 200 && status < 300,
      status,
      headers: new Headers(),
      text: async () => (reply.body === undefined ? '' : JSON.stringify(reply.body)),
    } as Response
  }) as unknown as typeof fetch
  return { fetcher, requests }
}

function bodyOf(request: RecordedRequest): Record<string, unknown> {
  return JSON.parse(String(request.init.body ?? '{}')) as Record<string, unknown>
}

describe('正式鉴权适配测试桩', () => {
  it('登录成功只在内存中产生短生命周期会话，登出立即清理', async () => {
    const adapter = createAuthTestStub({ now: () => 1_000_000, sessionTtlMs: 30_000 })

    const session = await adapter.login({ account: 'demo-account', password: 'demo-password' })

    expect(session.transport).toBe('bearer')
    expect(session.actorId).toBe('demo-account')
    expect(session.expiresAt).toBe(new Date(1_030_000).toISOString())
    expect(adapter.getSession()).toBe(session)

    await adapter.logout()
    expect(adapter.getSession()).toBeNull()
  })

  it('错误凭据使用统一 AUTH_FAILED，连续失败后仍不暴露锁定细节', async () => {
    const adapter = createAuthTestStub({ now: () => 1_000_000, maxAttempts: 2 })

    for (let attempt = 0; attempt < 3; attempt += 1) {
      await expect(adapter.login({ account: 'wrong', password: 'wrong' })).rejects.toMatchObject({
        code: 'AUTH_FAILED',
        message: '登录失败',
      })
    }
  })

  it('二次确认绑定动作、会话且同一 challenge 不能重放', async () => {
    const adapter = createAuthTestStub({ now: () => 1_000_000 })
    await adapter.login({ account: 'demo-account', password: 'demo-password' })
    const challenge = await adapter.beginStepUp({ action: 'authorization:grant', method: 'pin' })

    await expect(
      adapter.confirmStepUp({
        challengeId: challenge.id,
        action: 'authorization:revoke',
        method: 'pin',
        code: '123456',
      }),
    ).rejects.toMatchObject({ code: 'STEP_UP_FAILED' })

    await expect(
      adapter.confirmStepUp({
        challengeId: challenge.id,
        action: 'authorization:grant',
        method: 'pin',
        code: '123456',
      }),
    ).resolves.toMatchObject({ challengeId: challenge.id, action: 'authorization:grant' })

    await expect(
      adapter.confirmStepUp({
        challengeId: challenge.id,
        action: 'authorization:grant',
        method: 'pin',
        code: '123456',
      }),
    ).rejects.toMatchObject({ code: 'STEP_UP_REPLAY' })
  })

  it('会话过期后不能发起二次确认', async () => {
    let current = 1_000_000
    const adapter = createAuthTestStub({ now: () => current, sessionTtlMs: 10 })
    await adapter.login({ account: 'demo-account', password: 'demo-password' })
    current += 11

    try {
      await adapter.beginStepUp({ action: 'delete', method: 'qr' })
      throw new Error('expected expired session')
    } catch (cause) {
      expect(cause).toBeInstanceOf(AuthAdapterError)
      expect((cause as AuthAdapterError).code).toBe('SESSION_EXPIRED')
    }
    expect(adapter.getSession()).toBeNull()
  })
})

describe('过期时间归一化', () => {
  it('接受秒级时间戳、毫秒时间戳和 ISO 字符串', () => {
    expect(normalizeAuthExpiresAt(1_760_000_000)).toBe(new Date(1_760_000_000_000).toISOString())
    expect(normalizeAuthExpiresAt(1_760_000_000_000)).toBe(new Date(1_760_000_000_000).toISOString())
    expect(normalizeAuthExpiresAt('2026-08-20T10:00:00Z')).toBe('2026-08-20T10:00:00.000Z')
  })

  it('无法解析时返回 null，不当作永不过期', () => {
    expect(normalizeAuthExpiresAt(undefined)).toBeNull()
    expect(normalizeAuthExpiresAt('')).toBeNull()
    expect(normalizeAuthExpiresAt('not-a-date')).toBeNull()
    expect(normalizeAuthExpiresAt(0)).toBeNull()
  })
})

describe('HCT-107 正式鉴权 HTTP 适配', () => {
  const future = () => Math.floor((Date.now() + 600_000) / 1000)

  it('账号密码只出现在 POST body，不进 URL 或 query', async () => {
    const { fetcher, requests } = recordingFetcher([
      { body: { session_token: 'server-token', expires_at: future(), actor_id: 'family-owner' } },
    ])
    const adapter = createHttpAuthAdapter({ baseUrl: 'http://192.168.1.10:8000', fetcher })

    const session = await adapter.login({ account: 'family-owner', password: 'correct horse' })

    expect(requests).toHaveLength(1)
    expect(requests[0]!.url).toBe('http://192.168.1.10:8000/api/v1/auth/login')
    expect(requests[0]!.url).not.toContain('correct')
    expect(requests[0]!.url).not.toContain('password')
    expect(bodyOf(requests[0]!)).toEqual({ actor_id: 'family-owner', password: 'correct horse' })
    expect(session.actorId).toBe('family-owner')
    expect(session.transport).toBe('bearer')
    expect(session.accessToken).toBe('server-token')
    expect(Date.parse(session.expiresAt)).toBeGreaterThan(Date.now())
  })

  it('秒级 expires_at 归一化成 ISO，并在后续请求带上 Bearer', async () => {
    const expires = future()
    const { fetcher, requests } = recordingFetcher([
      { body: { session_token: 'server-token', expires_at: expires } },
      { body: { session_token: 'server-token', expires_at: expires } },
    ])
    const adapter = createHttpAuthAdapter({ baseUrl: '', fetcher })

    const session = await adapter.login({ account: 'owner', password: 'pw' })
    expect(session.expiresAt).toBe(new Date(expires * 1000).toISOString())

    await adapter.refresh()
    expect(new Headers(requests[1]!.init.headers).get('Authorization')).toBe('Bearer server-token')
  })

  it('凭据错误统一返回 AUTH_FAILED，不透出账号是否存在', async () => {
    const { fetcher } = recordingFetcher([{ status: 401, body: { detail: 'AUTH_FAILED' } }])
    const adapter = createHttpAuthAdapter({ fetcher })

    await expect(adapter.login({ account: 'owner', password: 'wrong' })).rejects.toMatchObject({
      code: 'AUTH_FAILED',
      message: '登录失败',
    })
    expect(adapter.getSession()).toBeNull()
  })

  it('速率限制锁定映射为 AUTH_LOCKED', async () => {
    const { fetcher } = recordingFetcher([{ status: 429, body: { detail: 'LOCKED:280' } }])
    const adapter = createHttpAuthAdapter({ fetcher })

    await expect(adapter.login({ account: 'owner', password: 'pw' })).rejects.toMatchObject({
      code: 'AUTH_LOCKED',
    })
  })

  it('接口形态不一致（422/404）按契约不足报告，不引导用户改密码', async () => {
    const { fetcher } = recordingFetcher([{ status: 422, body: { detail: [{ loc: ['query', 'actor_id'] }] } }])
    const adapter = createHttpAuthAdapter({ fetcher })

    await expect(adapter.login({ account: 'owner', password: 'pw' })).rejects.toMatchObject({
      code: 'AUTH_UNAVAILABLE',
    })
  })

  it('缺少会话 token 或过期时间时拒绝建立会话，不当作永不过期', async () => {
    const noToken = createHttpAuthAdapter({ fetcher: recordingFetcher([{ body: { expires_at: future() } }]).fetcher })
    await expect(noToken.login({ account: 'owner', password: 'pw' })).rejects.toMatchObject({
      code: 'AUTH_UNAVAILABLE',
    })

    const noExpiry = createHttpAuthAdapter({ fetcher: recordingFetcher([{ body: { session_token: 't' } }]).fetcher })
    await expect(noExpiry.login({ account: 'owner', password: 'pw' })).rejects.toMatchObject({
      code: 'AUTH_UNAVAILABLE',
    })
  })

  it('服务端回显一次性 PIN 时拒绝该二次确认', async () => {
    const { fetcher } = recordingFetcher([
      { body: { session_token: 'server-token', expires_at: future() } },
      { body: { pin: '123456', challenge_id: 'c-1', expires_at: future() } },
    ])
    const adapter = createHttpAuthAdapter({ fetcher })
    await adapter.login({ account: 'owner', password: 'pw' })

    await expect(adapter.beginStepUp({ action: 'confirm_high_risk', method: 'pin' })).rejects.toMatchObject({
      code: 'AUTH_UNAVAILABLE',
    })
  })

  it('二次确认成功后返回确认时间，失败按 403 映射为 STEP_UP_FAILED', async () => {
    const okFetch = recordingFetcher([
      { body: { session_token: 'server-token', expires_at: future() } },
      { body: { challenge_id: 'c-1', action: 'confirm_high_risk', expires_at: future() } },
      { body: { status: 'confirmed' } },
    ])
    const adapter = createHttpAuthAdapter({ fetcher: okFetch.fetcher })
    await adapter.login({ account: 'owner', password: 'pw' })
    const challenge = await adapter.beginStepUp({ action: 'confirm_high_risk', method: 'pin' })
    expect(challenge.id).toBe('c-1')

    const grant = await adapter.confirmStepUp({
      challengeId: 'c-1',
      action: 'confirm_high_risk',
      method: 'pin',
      code: '123456',
    })
    expect(grant.action).toBe('confirm_high_risk')
    expect(bodyOf(okFetch.requests[2]!)).toMatchObject({ challenge_id: 'c-1', code: '123456' })

    const failFetch = recordingFetcher([
      { body: { session_token: 'server-token', expires_at: future() } },
      { body: { challenge_id: 'c-2', expires_at: future() } },
      { status: 403, body: { detail: 'PIN_INVALID' } },
    ])
    const failing = createHttpAuthAdapter({ fetcher: failFetch.fetcher })
    await failing.login({ account: 'owner', password: 'pw' })
    await failing.beginStepUp({ action: 'confirm_high_risk', method: 'pin' })
    await expect(failing.confirmStepUp({
      challengeId: 'c-2',
      action: 'confirm_high_risk',
      method: 'pin',
      code: '000000',
    })).rejects.toMatchObject({ code: 'STEP_UP_FAILED' })
  })

  it('登出在服务端不可达时也清空本地会话', async () => {
    let calls = 0
    const fetcher = (async (_input: RequestInfo | URL, _init?: RequestInit) => {
      calls += 1
      if (calls === 1) {
        return {
          ok: true,
          status: 200,
          headers: new Headers(),
          text: async () => JSON.stringify({ session_token: 'server-token', expires_at: future() }),
        } as Response
      }
      throw new TypeError('network down')
    }) as unknown as typeof fetch

    const adapter = createHttpAuthAdapter({ fetcher })
    await adapter.login({ account: 'owner', password: 'pw' })
    await adapter.logout()
    expect(adapter.getSession()).toBeNull()
  })

  it('会话续验被服务端否认时返回 null 并清空会话', async () => {
    const { fetcher } = recordingFetcher([
      { body: { session_token: 'server-token', expires_at: future() } },
      { status: 401, body: { detail: 'SESSION_INVALID' } },
    ])
    const adapter = createHttpAuthAdapter({ fetcher })
    await adapter.login({ account: 'owner', password: 'pw' })

    expect(await adapter.refresh()).toBeNull()
    expect(adapter.getSession()).toBeNull()
  })

  it('拒绝不可信的明文公网地址', () => {
    expect(() => createHttpAuthAdapter({ baseUrl: 'http://example.com:8000' })).toThrow('明文 HTTP')
  })
})

describe('二次确认的配置错误不会被当成会话失效', () => {
  const future = () => Math.floor((Date.now() + 600_000) / 1000)

  async function signedInAdapter(replies: { status?: number; body?: unknown }[]) {
    const recorded = recordingFetcher([
      { body: { session_token: 'server-token', expires_at: future() } },
      ...replies,
    ])
    const adapter = createHttpAuthAdapter({ fetcher: recorded.fetcher })
    await adapter.login({ account: 'owner', password: 'pw-at-least-8' })
    return { adapter, requests: recorded.requests }
  }

  it('未设置家庭 PIN 返回专用错误码，不报"会话已失效"', async () => {
    const { adapter } = await signedInAdapter([
      { status: 409, body: { detail: 'PIN_NOT_CONFIGURED' } },
    ])

    await expect(adapter.beginStepUp({ action: 'confirm_high_risk', method: 'pin' }))
      .rejects.toMatchObject({ code: 'STEP_UP_NOT_CONFIGURED' })
    // 会话必须保留：这只是配置缺失，不能把用户踢回登录页。
    expect(adapter.getSession()).not.toBeNull()
  })

  it('多家庭歧义返回需要选定家庭，而不是会话失效', async () => {
    const { adapter } = await signedInAdapter([
      { status: 409, body: { detail: 'HOUSEHOLD_REQUIRED' } },
    ])

    await expect(adapter.beginStepUp({ action: 'confirm_high_risk', method: 'pin' }))
      .rejects.toMatchObject({ code: 'STEP_UP_HOUSEHOLD_REQUIRED' })
    expect(adapter.getSession()).not.toBeNull()
  })

  it('重放与过期按服务端 detail 精确区分', async () => {
    const replay = await signedInAdapter([
      { body: { challenge_id: 'c-1', expires_at: future() } },
      { status: 409, body: { detail: 'STEP_UP_REPLAY' } },
    ])
    await replay.adapter.beginStepUp({ action: 'confirm_high_risk', method: 'pin' })
    await expect(replay.adapter.confirmStepUp({
      challengeId: 'c-1',
      action: 'confirm_high_risk',
      method: 'pin',
      code: '135790',
    })).rejects.toMatchObject({ code: 'STEP_UP_REPLAY' })

    const expired = await signedInAdapter([
      { body: { challenge_id: 'c-2', expires_at: future() } },
      { status: 409, body: { detail: 'STEP_UP_EXPIRED' } },
    ])
    await expired.adapter.beginStepUp({ action: 'confirm_high_risk', method: 'pin' })
    await expect(expired.adapter.confirmStepUp({
      challengeId: 'c-2',
      action: 'confirm_high_risk',
      method: 'pin',
      code: '135790',
    })).rejects.toMatchObject({ code: 'STEP_UP_EXPIRED' })
  })

  it('指定家庭时把 household_id 放进请求体', async () => {
    const { adapter, requests } = await signedInAdapter([
      { body: { challenge_id: 'c-3', expires_at: future() } },
    ])

    await adapter.beginStepUp({
      action: 'confirm_high_risk',
      method: 'pin',
      householdId: 'household-1',
    })

    expect(bodyOf(requests[1]!)).toMatchObject({
      action: 'confirm_high_risk',
      household_id: 'household-1',
    })
    expect(requests[1]!.url).not.toContain('household-1')
  })

  it('不指定家庭时不发送 household_id，由服务端解析', async () => {
    const { adapter, requests } = await signedInAdapter([
      { body: { challenge_id: 'c-4', expires_at: future() } },
    ])

    await adapter.beginStepUp({ action: 'confirm_high_risk', method: 'pin' })

    expect('household_id' in bodyOf(requests[1]!)).toBe(false)
  })
})
