import { afterEach, describe, expect, it } from 'vitest'

import { createAuthTestStub } from '@/api/auth'
import { registerSessionCleanup, requireReauth, resetAuthState, signIn } from '@/stores/auth'
import { resetSession, sessionContextKey, updateSession, useSession } from '@/stores/session'

import {
  activeProvider,
  canSubmitWrites,
  clearHouseholdSelection,
  selectHousehold,
} from './index'

const CREDENTIALS = { account: 'demo-account', password: 'demo-password' }

function goLive(): void {
  // 同源地址（空串）通过明文 HTTP 边界校验，测试不发出真实请求。
  updateSession({ dataMode: 'live', authMode: 'real', serverBaseUrl: '', accessPurpose: 'family-care' })
}

describe('联机 Provider 的正式会话边界', () => {
  afterEach(() => {
    resetAuthState()
    resetSession()
  })

  it('演示模式不受登录状态影响', async () => {
    resetSession()
    await expect(activeProvider().listMembers()).resolves.toBeInstanceOf(Array)
    expect(canSubmitWrites()).toBe(true)
  })

  it('正式鉴权模式下未登录时读写全部 fail-closed', async () => {
    goLive()

    await expect(activeProvider().listMembers()).rejects.toMatchObject({
      status: 401,
      code: 'SESSION_EXPIRED',
    })
    await expect(activeProvider().getTodaySnapshot('member-1')).rejects.toMatchObject({ status: 401 })
    await expect(activeProvider().submitTaskAction('task-1', 'confirm')).rejects.toMatchObject({ status: 401 })
    expect(canSubmitWrites()).toBe(false)
  })

  it('会话被撤销后使用撤销错误码，页面不会显示旧会话数据', async () => {
    goLive()
    await signIn(createAuthTestStub(), CREDENTIALS)
    expect(canSubmitWrites()).toBe(true)

    requireReauth('revoked')

    await expect(activeProvider().listMembers()).rejects.toMatchObject({ code: 'AUTH_REVOKED' })
    expect(canSubmitWrites()).toBe(false)
  })

  it('登录后允许写操作，退出登录后立即再次阻断', async () => {
    goLive()
    await signIn(createAuthTestStub(), CREDENTIALS)
    expect(canSubmitWrites()).toBe(true)

    requireReauth('signed-out')
    expect(canSubmitWrites()).toBe(false)
    await expect(activeProvider().submitTaskAction('task-1', 'confirm')).rejects.toMatchObject({ status: 401 })
  })

  it('开发期身份模式不要求正式登录，但必须显式选择', async () => {
    updateSession({ dataMode: 'live', authMode: 'dev-actor', actorId: 'dev-actor', serverBaseUrl: '' })
    expect(canSubmitWrites()).toBe(true)
  })

  it('切换当前成员会丢弃上一位成员的查询与缓存上下文', () => {
    const scopes: string[] = []
    registerSessionCleanup(scope => scopes.push(scope))
    goLive()
    scopes.length = 0

    updateSession({ currentMemberId: 'member-1' })
    expect(scopes).toEqual(['context'])

    // 同值写入不应重复清理，避免刷新时白丢缓存。
    scopes.length = 0
    updateSession({ currentMemberId: 'member-1' })
    expect(scopes).toEqual([])
  })
})

describe('家庭切换的上下文清理（MOB-158）', () => {
  afterEach(() => {
    resetAuthState()
    resetSession()
  })

  it('切换家庭触发上下文清理，同一家庭重复选择不清理', async () => {
    const scopes: string[] = []
    registerSessionCleanup(scope => scopes.push(scope))
    goLive()
    await signIn(createAuthTestStub(), CREDENTIALS)
    scopes.length = 0

    selectHousehold('hh-1')
    expect(scopes).toEqual(['context'])

    scopes.length = 0
    selectHousehold('hh-1')
    expect(scopes).toEqual([])
  })

  it('切换家庭同时清掉当前成员，避免新家庭沿用旧成员', () => {
    goLive()
    updateSession({ currentHouseholdId: 'hh-1', currentMemberId: 'member-1' })

    selectHousehold('hh-2')

    const { session } = useSession()
    expect(session.currentHouseholdId).toBe('hh-2')
    expect(session.currentMemberId).toBe('')
  })

  it('清除家庭选择后回到安全选择态', () => {
    goLive()
    updateSession({ currentHouseholdId: 'hh-1', currentMemberId: 'member-1' })

    clearHouseholdSelection()

    const { session } = useSession()
    expect(session.currentHouseholdId).toBe('')
    expect(session.currentMemberId).toBe('')
  })

  it('家庭是联机指纹的一部分，换家庭必然丢弃旧 Provider 缓存', () => {
    goLive()
    updateSession({ currentHouseholdId: 'hh-1' })
    const first = sessionContextKey(useSession().session)
    updateSession({ currentHouseholdId: 'hh-2' })
    expect(sessionContextKey(useSession().session)).not.toBe(first)
  })
})
