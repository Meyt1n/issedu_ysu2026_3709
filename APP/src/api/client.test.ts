import { describe, expect, it } from 'vitest'

import { ApiClient, ApiClientError } from './client'
import type { AuthSession } from './auth'

function response(): Response {
  return {
    ok: true,
    status: 200,
    headers: new Headers(),
    text: async () => JSON.stringify({ status: 'ok', service: 'test', version: 'test' }),
  } as Response
}

describe('ApiClient 鉴权传输适配', () => {
  it('拒绝不受信任的明文公网地址', () => {
    expect(() => new ApiClient({ baseUrl: 'http://example.com:8000' })).toThrow('明文 HTTP')
  })

  it('正式 bearer 会话发送 Authorization，并停止发送开发期身份头', async () => {
    let request: RequestInit | undefined
    const session: AuthSession = {
      actorId: 'server-actor',
      accessPurpose: 'family-care',
      transport: 'bearer',
      accessToken: 'test-only-token',
      expiresAt: new Date(Date.now() + 60_000).toISOString(),
    }
    const client = new ApiClient({
      authSessionProvider: () => session,
      fetcher: async (_input, init) => {
        request = init
        return response()
      },
    })

    await client.getHealth({ actorId: 'legacy-dev-actor', accessPurpose: 'wrong-purpose' })

    const headers = new Headers(request?.headers)
    expect(headers.get('Authorization')).toBe('Bearer test-only-token')
    expect(headers.get('X-Actor-Id')).toBeNull()
    expect(headers.get('X-Access-Purpose')).toBe('family-care')
  })

  it('cookie 会话使用 credentials=include，客户端不读取 cookie 内容', async () => {
    let request: RequestInit | undefined
    const session: AuthSession = {
      actorId: 'cookie-actor',
      accessPurpose: 'family-care',
      transport: 'cookie',
      expiresAt: new Date(Date.now() + 60_000).toISOString(),
    }
    const client = new ApiClient({
      authSessionProvider: () => session,
      fetcher: async (_input, init) => {
        request = init
        return response()
      },
    })

    await client.getHealth()

    const headers = new Headers(request?.headers)
    expect(request?.credentials).toBe('include')
    expect(headers.get('Authorization')).toBeNull()
    expect(headers.get('X-Actor-Id')).toBeNull()
  })

  it('配置正式会话提供方但未登录时不回退到开发期身份头', async () => {
    let request: RequestInit | undefined
    const client = new ApiClient({
      authSessionProvider: () => null,
      fetcher: async (_input, init) => {
        request = init
        return response()
      },
    })

    await client.getHealth({ actorId: 'legacy-dev-actor', accessPurpose: 'family-care' })

    const headers = new Headers(request?.headers)
    expect(headers.get('X-Actor-Id')).toBeNull()
    expect(headers.get('X-Access-Purpose')).toBe('family-care')
  })

  it('过期 bearer 会话在发请求前被阻断', async () => {
    const session: AuthSession = {
      actorId: 'expired-actor',
      accessPurpose: 'family-care',
      transport: 'bearer',
      accessToken: 'test-only-token',
      expiresAt: new Date(Date.now() - 1).toISOString(),
    }
    const client = new ApiClient({ authSessionProvider: () => session, fetcher: async () => response() })

    try {
      await client.getHealth()
      throw new Error('expected expired session')
    } catch (cause) {
      expect(cause).toBeInstanceOf(ApiClientError)
      expect((cause as ApiClientError).code).toBe('SESSION_EXPIRED')
      expect((cause as ApiClientError).status).toBe(401)
    }
  })
})

describe('家庭 PIN 设置（HCT-427）', () => {
  it('PIN 只出现在请求体，不进 URL 或 query', async () => {
    let url = ''
    let request: RequestInit | undefined
    const session: AuthSession = {
      actorId: 'owner',
      accessPurpose: 'family-care',
      transport: 'bearer',
      accessToken: 'test-only-token',
      expiresAt: new Date(Date.now() + 60_000).toISOString(),
    }
    const client = new ApiClient({
      authSessionProvider: () => session,
      fetcher: async (input, init) => {
        url = String(input)
        request = init
        return response()
      },
    })

    await client.setAccountPin('household-1', '135790')

    expect(url).toBe('/api/v1/auth/pin')
    expect(url).not.toContain('135790')
    expect(JSON.parse(String(request?.body))).toEqual({
      household_id: 'household-1',
      pin: '135790',
    })
    expect(new Headers(request?.headers).get('Authorization')).toBe('Bearer test-only-token')
  })
})

describe('视觉任务状态回查（MOB-132）', () => {
  it('getVisionTask 走 GET 且任务 ID 编码进路径，凭据由会话承载', async () => {
    let url = ''
    let request: RequestInit | undefined
    const session: AuthSession = {
      actorId: 'owner',
      accessPurpose: 'family-care',
      transport: 'bearer',
      accessToken: 'test-only-token',
      expiresAt: new Date(Date.now() + 60_000).toISOString(),
    }
    const client = new ApiClient({
      authSessionProvider: () => session,
      fetcher: async (input, init) => {
        url = String(input)
        request = init
        return response()
      },
    })

    await client.getVisionTask('vision/1 abc')

    expect(url).toBe('/api/v1/vision-tasks/vision%2F1%20abc')
    expect(request?.method).toBe('GET')
    expect(request?.body).toBeUndefined()
    expect(new Headers(request?.headers).get('Authorization')).toBe('Bearer test-only-token')
  })
})
