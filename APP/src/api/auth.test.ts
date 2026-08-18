import { describe, expect, it } from 'vitest'

import { AuthAdapterError, createAuthTestStub } from './auth'

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
