import { beforeEach, describe, expect, it } from 'vitest'

import { AuthAdapterError, createAuthTestStub } from '@/api/auth'
import { ApiClientError } from '@/api/client'

import {
  authGeneration,
  changePassword,
  getAuthSession,
  handleAuthFailure,
  isWriteBlocked,
  registerSessionCleanup,
  requireReauth,
  resetAuthState,
  signIn,
  signOut,
  resetSessionScopedState,
  useAuth,
} from './auth'

const CREDENTIALS = { account: 'demo-account', password: 'demo-password' }

function storedValues(): string[] {
  const values: string[] = []
  for (let index = 0; index < localStorage.length; index += 1) {
    const key = localStorage.key(index)
    if (key) values.push(String(localStorage.getItem(key)))
  }
  return values
}

describe('正式会话生命周期', () => {
  beforeEach(() => {
    resetAuthState()
    localStorage.clear()
  })

  it('登录后凭据只在内存中，不写 localStorage，也不出现在可序列化状态里', async () => {
    const adapter = createAuthTestStub()
    await signIn(adapter, CREDENTIALS)
    const { auth } = useAuth()

    expect(auth.status).toBe('authenticated')
    expect(auth.actorId).toBe('demo-account')
    expect(getAuthSession()?.accessToken).toMatch(/^test-only-token-/)
    expect(isWriteBlocked()).toBe(false)

    expect(JSON.stringify(auth)).not.toContain('test-only-token')
    expect(storedValues().some(value => value.includes('test-only-token'))).toBe(false)
    expect(storedValues().some(value => value.includes('demo-password'))).toBe(false)
  })

  it('登录失败不留下部分会话状态', async () => {
    const adapter = createAuthTestStub()
    await expect(signIn(adapter, { account: 'demo-account', password: 'wrong' })).rejects.toMatchObject({
      code: 'AUTH_FAILED',
    })
    const { auth } = useAuth()
    expect(auth.status).toBe('anonymous')
    expect(auth.actorId).toBe('')
    expect(getAuthSession()).toBeNull()
    expect(isWriteBlocked()).toBe(true)
  })

  it('收到 401 后清理会话、阻断写入并执行会话级清理', async () => {
    const scopes: string[] = []
    registerSessionCleanup(scope => scopes.push(scope))
    await signIn(createAuthTestStub(), CREDENTIALS)
    scopes.length = 0

    const handled = handleAuthFailure(new ApiClientError('未认证', { status: 401, code: 'UNAUTHENTICATED' }))

    const { auth } = useAuth()
    expect(handled).toBe(true)
    expect(auth.status).toBe('reauth-required')
    expect(auth.reason).toBe('unauthenticated')
    expect(getAuthSession()).toBeNull()
    expect(isWriteBlocked()).toBe(true)
    expect(scopes).toEqual(['session'])
  })

  it('撤权错误码进入撤销状态，普通 404 不影响会话', async () => {
    await signIn(createAuthTestStub(), CREDENTIALS)
    const { auth } = useAuth()

    expect(handleAuthFailure(new ApiClientError('不存在', { status: 404, code: 'RESOURCE_NOT_FOUND' }))).toBe(false)
    expect(auth.status).toBe('authenticated')

    expect(handleAuthFailure(new ApiClientError('已撤回', { status: 403, code: 'CONSENT_REVOKED' }))).toBe(true)
    expect(auth.reason).toBe('revoked')
    expect(auth.status).toBe('reauth-required')
  })

  it('过期会话在读取时就被丢弃并要求重新认证', async () => {
    // 负 TTL 让测试桩直接产出已过期的会话，等价于放置一段时间后再回到前台。
    await signIn(createAuthTestStub({ sessionTtlMs: -1_000 }), CREDENTIALS)

    expect(getAuthSession()).toBeNull()
    const { auth } = useAuth()
    expect(auth.status).toBe('reauth-required')
    expect(auth.reason).toBe('expired')
  })

  it('退出登录清空会话并执行会话级清理', async () => {
    const scopes: string[] = []
    registerSessionCleanup(scope => scopes.push(scope))
    const adapter = createAuthTestStub()
    await signIn(adapter, CREDENTIALS)
    scopes.length = 0

    await signOut(adapter)

    const { auth } = useAuth()
    expect(auth.status).toBe('anonymous')
    expect(auth.reason).toBe('signed-out')
    expect(auth.actorId).toBe('')
    expect(adapter.getSession()).toBeNull()
    expect(getAuthSession()).toBeNull()
    expect(scopes).toEqual(['session'])
  })

  it('切换家庭或成员只做上下文清理，会话仍然有效', async () => {
    const scopes: string[] = []
    registerSessionCleanup(scope => scopes.push(scope))
    await signIn(createAuthTestStub(), CREDENTIALS)
    scopes.length = 0
    const before = authGeneration()

    resetSessionScopedState()

    const { auth } = useAuth()
    expect(scopes).toEqual(['context'])
    expect(auth.status).toBe('authenticated')
    expect(getAuthSession()).not.toBeNull()
    expect(authGeneration()).toBeGreaterThan(before)
  })

  it('会话指纹在每次状态变化后都推进，旧缓存必然失效', async () => {
    const start = authGeneration()
    await signIn(createAuthTestStub(), CREDENTIALS)
    const afterLogin = authGeneration()
    requireReauth('revoked')

    expect(afterLogin).toBeGreaterThan(start)
    expect(authGeneration()).toBeGreaterThan(afterLogin)
  })

  it('未发起 challenge 时不能提交二次确认', async () => {
    const adapter = createAuthTestStub()
    await signIn(adapter, CREDENTIALS)
    const { confirmStepUp } = useAuth()

    await expect(confirmStepUp(adapter, { action: 'confirm_high_risk', method: 'pin', code: '123456' }))
      .rejects.toMatchObject({ code: 'STEP_UP_REQUIRED' })
  })

  it('二次确认成功后清空 challenge，PIN 不进入状态', async () => {
    const adapter = createAuthTestStub()
    await signIn(adapter, CREDENTIALS)
    const { auth, beginStepUp, confirmStepUp } = useAuth()

    await beginStepUp(adapter, { action: 'confirm_high_risk', method: 'pin' })
    expect(auth.pendingStepUp?.action).toBe('confirm_high_risk')

    await confirmStepUp(adapter, { action: 'confirm_high_risk', method: 'pin', code: '123456' })
    expect(auth.pendingStepUp).toBeNull()
    expect(JSON.stringify(auth)).not.toContain('123456')
  })
})

describe('二次确认失败不得连带清空登录会话', () => {
  beforeEach(() => {
    resetAuthState()
    localStorage.clear()
  })

  it('未配置 PIN、需要选定家庭、重放和过期都保留当前会话', async () => {
    await signIn(createAuthTestStub(), CREDENTIALS)
    const { auth } = useAuth()

    for (const code of [
      'STEP_UP_NOT_CONFIGURED',
      'STEP_UP_HOUSEHOLD_REQUIRED',
      'STEP_UP_REPLAY',
      'STEP_UP_EXPIRED',
      'STEP_UP_FAILED',
    ] as const) {
      const handled = handleAuthFailure(
        new AuthAdapterError('step-up rejected', { code, status: 409 }),
      )
      expect(handled).toBe(false)
      expect(auth.status).toBe('authenticated')
      expect(getAuthSession()).not.toBeNull()
      expect(isWriteBlocked()).toBe(false)
    }
  })

  it('真正的会话失效仍然清空会话', async () => {
    await signIn(createAuthTestStub(), CREDENTIALS)
    const handled = handleAuthFailure(
      new AuthAdapterError('session gone', { code: 'SESSION_EXPIRED', status: 401 }),
    )
    expect(handled).toBe(true)
    expect(useAuth().auth.status).toBe('reauth-required')
    expect(getAuthSession()).toBeNull()
  })
})

describe('修改密码后的会话轮换', () => {
  beforeEach(() => {
    resetAuthState()
    localStorage.clear()
  })

  it('采纳服务端新会话、保持已登录，并让上下文缓存失效', async () => {
    const adapter = createAuthTestStub({ account: 'demo-account', password: 'Current-pw1' })
    await signIn(adapter, { account: 'demo-account', password: 'Current-pw1' })
    const { auth } = useAuth()
    const before = getAuthSession()?.accessToken
    const generationBefore = authGeneration()

    const scopes: string[] = []
    const unregister = registerSessionCleanup(scope => scopes.push(scope))

    await changePassword(adapter, { currentPassword: 'Current-pw1', newPassword: 'Rotated-pw2' })

    expect(auth.status).toBe('authenticated')
    expect(getAuthSession()?.accessToken).not.toBe(before)
    expect(authGeneration()).toBeGreaterThan(generationBefore)
    // 旧会话已被服务端作废：只清上下文缓存，不把用户踢回登录页。
    expect(scopes).toEqual(['context'])
    expect(isWriteBlocked()).toBe(false)

    // 密码与新 token 都不得落到可序列化状态或 localStorage。
    expect(JSON.stringify(auth)).not.toContain('Rotated-pw2')
    expect(JSON.stringify(auth)).not.toContain('test-only-token')
    expect(storedValues().some(value => value.includes('Rotated-pw2'))).toBe(false)
    unregister()
  })

  it('改密失败时会话与凭据保持原样', async () => {
    const adapter = createAuthTestStub({ account: 'demo-account', password: 'Current-pw1' })
    await signIn(adapter, { account: 'demo-account', password: 'Current-pw1' })
    const before = getAuthSession()?.accessToken

    await expect(changePassword(adapter, { currentPassword: 'Wrong-pw1', newPassword: 'Rotated-pw2' }))
      .rejects.toMatchObject({ code: 'AUTH_FAILED' })

    expect(useAuth().auth.status).toBe('authenticated')
    expect(getAuthSession()?.accessToken).toBe(before)
  })
})
