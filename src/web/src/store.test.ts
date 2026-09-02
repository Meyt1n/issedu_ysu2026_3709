import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiClientError, apiClient } from './api/client'
import {
  changeCurrentPassword,
  completeBoundHouseholdPin,
  completeMemberPortalPin,
  connectWithFamilyFace,
  connectWithPassword,
  connectWithPin,
  createHouseholdAndEnter,
  bindFaceHousehold,
  clearBoundFaceHousehold,
  formatError,
  getBoundFaceHouseholdId,
  getBoundFaceHouseholdName,
  getBoundPinCandidates,
  portalWelcomeMessage,
  refreshCapabilities,
  recoverPasswordWithPin,
  selectedMember,
  selectHousehold,
  session,
  setView,
  signOut,
} from './store'
import { overridePortalEntryModeForTest, readWelcomeEntryHint, resetWelcomeEntryHintForTest } from './ui/portalEntry'

async function loginAs(actorId: string): Promise<void> {
  if (!vi.isMockFunction(apiClient.login)) vi.spyOn(apiClient, 'login')
  vi.mocked(apiClient.login).mockResolvedValueOnce({
    actor_id: actorId,
    session_token: `${actorId}-formal-session-token`.padEnd(48, 's'),
    expires_at: (Date.now() + 60_000) / 1000,
  })
  await connectWithPassword(actorId, 'password-123', 'family-care')
}

describe('session expiry handling', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.spyOn(apiClient, 'login').mockResolvedValue({
      actor_id: 'expiry-owner',
      session_token: 'e'.repeat(48),
      expires_at: (Date.now() + 5000) / 1000,
    })
    vi.spyOn(apiClient, 'listHouseholds').mockResolvedValue([])
  })

  afterEach(() => {
    signOut()
    vi.restoreAllMocks()
    vi.useRealTimers()
  })

  it('clears the session when the server expiry timestamp is reached', async () => {
    await connectWithPassword('expiry-owner', 'password-123', 'family-care')
    expect(session.sessionToken).toHaveLength(48)
    expect(session.sessionExpiresAt).not.toBeNull()

    vi.advanceTimersByTime(5000)

    expect(session.sessionToken).toBe('')
    expect(session.status).toBe('signed-out')
    expect(session.error).toContain('会话已过期')
  })

  it('cancels the expiry timer when the user signs out early', async () => {
    await connectWithPassword('expiry-owner', 'password-123', 'family-care')
    signOut()
    vi.advanceTimersByTime(5000)

    expect(session.error).toBe('')
    expect(session.status).toBe('signed-out')
  })

  it('registers a formal account before establishing its session', async () => {
    const register = vi.spyOn(apiClient, 'registerAccount').mockResolvedValue({
      status: 'registered',
      actor_id: 'new-owner',
    })

    await connectWithPassword('new-owner', 'password-123', 'family-care', true)

    expect(register).toHaveBeenCalledWith('new-owner', 'password-123')
    expect(apiClient.login).toHaveBeenCalledWith('new-owner', 'password-123')
    expect(session.status).toBe('empty')
  })
})

describe('formal password rotation and recovery', () => {
  beforeEach(() => {
    vi.spyOn(apiClient, 'listHouseholds').mockResolvedValue([])
    vi.spyOn(apiClient, 'logout').mockResolvedValue({ status: 'logged_out' })
  })

  afterEach(() => {
    signOut()
    vi.restoreAllMocks()
  })

  it('replaces the current bearer session after an authenticated password change', async () => {
    vi.spyOn(apiClient, 'login').mockResolvedValue({
      actor_id: 'password-owner',
      session_token: 'o'.repeat(48),
      expires_at: (Date.now() + 60_000) / 1000,
    })
    await connectWithPassword('password-owner', 'current-password', 'family-care')
    vi.spyOn(apiClient, 'changePassword').mockResolvedValue({
      actor_id: 'password-owner',
      session_token: 'n'.repeat(48),
      expires_at: (Date.now() + 120_000) / 1000,
    })

    await changeCurrentPassword('current-password', 'new-password')

    expect(apiClient.changePassword).toHaveBeenCalledWith(
      'current-password',
      'new-password',
      expect.objectContaining({
        sessionToken: 'o'.repeat(48),
        suppressUnauthorizedHandler: true,
      }),
    )
    expect(session.sessionToken).toBe('n'.repeat(48))
    expect(session.status).toBe('empty')
  })

  it('keeps the existing session state when current-password confirmation fails', async () => {
    vi.spyOn(apiClient, 'login').mockResolvedValue({
      actor_id: 'password-owner',
      session_token: 'o'.repeat(48),
      expires_at: (Date.now() + 60_000) / 1000,
    })
    await connectWithPassword('password-owner', 'current-password', 'family-care')
    vi.spyOn(apiClient, 'changePassword').mockRejectedValue(
      new ApiClientError('AUTH_FAILED', { status: 401, code: 'UNAUTHENTICATED' }),
    )

    await expect(changeCurrentPassword('wrong-password', 'new-password')).rejects.toMatchObject({
      status: 401,
    })

    expect(session.sessionToken).toBe('o'.repeat(48))
    expect(session.actorId).toBe('password-owner')
  })

  it('enters a fresh session after PIN-backed forgotten-password recovery', async () => {
    vi.spyOn(apiClient, 'recoverPassword').mockResolvedValue({
      actor_id: 'recovery-owner',
      household_id: 'household-1',
      session_token: 'r'.repeat(48),
      expires_at: (Date.now() + 60_000) / 1000,
    })

    await recoverPasswordWithPin(
      'recovery-owner',
      'household-1',
      '042006',
      'new-password',
      'family-care',
    )

    expect(apiClient.recoverPassword).toHaveBeenCalledWith(
      'recovery-owner',
      'household-1',
      '042006',
      'new-password',
    )
    expect(session.sessionToken).toBe('r'.repeat(48))
    expect(session.actorId).toBe('recovery-owner')
    expect(session.status).toBe('empty')
  })
})

describe('family face entry context', () => {
  afterEach(() => {
    signOut()
    vi.restoreAllMocks()
  })

  it('selects the member returned by family face identification', async () => {
    vi.spyOn(apiClient, 'createFamilyFaceChallenge').mockResolvedValue({
      challenge_id: 'c'.repeat(24),
      expires_at: (Date.now() + 60_000) / 1000,
    })
    vi.spyOn(apiClient, 'loginWithFamilyFace').mockResolvedValue({
      actor_id: 'grandma-local',
      household_id: 'household-family',
      session_token: 's'.repeat(48),
      expires_at: (Date.now() + 60_000) / 1000,
    })
    vi.spyOn(apiClient, 'listHouseholds').mockResolvedValue([
      {
        id: 'household-family',
        name: '爷爷奶奶家',
        created_by: 'parent-local',
        created_at: '2026-08-22T00:00:00Z',
      },
    ])
    vi.spyOn(apiClient, 'listMembers').mockResolvedValue([
      {
        id: 'grandpa-member',
        household_id: 'household-family',
        display_name: '爷爷',
        role: 'DEPENDENT',
        actor_id: 'grandpa-local',
        created_at: '2026-08-22T00:00:00Z',
      },
      {
        id: 'grandma-member',
        household_id: 'household-family',
        display_name: '奶奶',
        role: 'DEPENDENT',
        actor_id: 'grandma-local',
        created_at: '2026-08-22T00:00:00Z',
      },
    ])
    vi.spyOn(apiClient, 'listAuthorizations').mockResolvedValue([])
    vi.spyOn(apiClient, 'getCapabilities').mockResolvedValue({
      phase: 'P0',
      available: [],
      unavailable: [],
    })

    await connectWithFamilyFace(
      'household-family',
      [new File(['frame-1'], 'frame-1.jpg'), new File(['frame-2'], 'frame-2.jpg')],
      'family-care',
    )

    expect(session.status).toBe('ready')
    expect(session.actorId).toBe('grandma-local')
    expect(session.selectedHouseholdId).toBe('household-family')
    expect(session.selectedMemberId).toBe('grandma-member')
    expect(selectedMember.value?.display_name).toBe('奶奶')
    expect(session.portal).toBe('member')
    expect(session.currentView).toBe('member-home')
  })

  it('routes PIN login for a bound member into the member portal', async () => {
    vi.spyOn(apiClient, 'loginWithPin').mockResolvedValue({
      actor_id: 'grandma-local',
      household_id: 'household-family',
      session_token: 's'.repeat(48),
      expires_at: (Date.now() + 60_000) / 1000,
    })
    vi.spyOn(apiClient, 'listHouseholds').mockResolvedValue([
      {
        id: 'household-family',
        name: '爷爷奶奶家',
        created_by: 'parent-local',
        created_at: '2026-08-22T00:00:00Z',
      },
    ])
    vi.spyOn(apiClient, 'listMembers').mockResolvedValue([
      {
        id: 'grandma-member',
        household_id: 'household-family',
        display_name: '奶奶',
        role: 'DEPENDENT',
        actor_id: 'grandma-local',
        created_at: '2026-08-22T00:00:00Z',
      },
    ])
    vi.spyOn(apiClient, 'getCapabilities').mockResolvedValue({
      phase: 'P0',
      available: [],
      unavailable: [],
    })

    await connectWithPin('grandma-local', 'household-family', '135790', 'family-care')

    expect(session.status).toBe('ready')
    expect(session.portal).toBe('member')
    expect(session.currentView).toBe('member-home')
    expect(selectedMember.value?.display_name).toBe('奶奶')
    expect(portalWelcomeMessage()).toBe('你好，奶奶。欢迎回家。')
  })
})

describe('pre-login capability probe (HCT-425)', () => {
  afterEach(() => {
    signOut()
    vi.restoreAllMocks()
  })

  it('loads capabilities anonymously so the welcome face tab can detect readiness', async () => {
    const spy = vi.spyOn(apiClient, 'getCapabilities').mockResolvedValue({
      phase: 'local',
      available: ['api', 'face-recognition-local'],
      unavailable: [],
    })

    await refreshCapabilities()

    expect(spy).toHaveBeenCalledWith()
    expect(session.capabilities?.available).toContain('face-recognition-local')
  })

  it('keeps the previous capabilities when the probe fails', async () => {
    vi.spyOn(apiClient, 'getCapabilities').mockResolvedValueOnce({
      phase: 'local',
      available: ['face-recognition-local'],
      unavailable: [],
    })
    await refreshCapabilities()

    vi.spyOn(apiClient, 'getCapabilities').mockRejectedValueOnce(new Error('offline'))
    await refreshCapabilities()

    expect(session.capabilities?.available).toContain('face-recognition-local')
  })
})

describe('cross-portal face household binding (HCT-425)', () => {
  afterEach(() => {
    clearBoundFaceHousehold()
    vi.restoreAllMocks()
    Reflect.deleteProperty(globalThis, 'document')
    Reflect.deleteProperty(globalThis, 'localStorage')
  })

  it('keeps the binding available to the other local port through a same-host cookie', () => {
    let cookie = ''
    Object.defineProperty(globalThis, 'document', {
      configurable: true,
      value: {
        get cookie() {
          return cookie
        },
        set cookie(value: string) {
          cookie = value
        },
      },
    })

    bindFaceHousehold('household-family', '爷爷奶奶家')

    // Node tests do not provide localStorage, so these reads exercise the
    // cross-port cookie fallback used by 5173/5174 and 5183/5184.
    expect(getBoundFaceHouseholdId()).toBe('household-family')
    expect(getBoundFaceHouseholdName()).toBe('爷爷奶奶家')
    expect(getBoundPinCandidates()).toEqual([])
    expect(cookie).toContain('hct-face-family-household=')
  })

  it('stores PIN picker members on the same binding without exposing them to a public API', () => {
    let cookie = ''
    Object.defineProperty(globalThis, 'document', {
      configurable: true,
      value: {
        get cookie() {
          return cookie
        },
        set cookie(value: string) {
          cookie = value
        },
      },
    })

    bindFaceHousehold('household-family', '爷爷奶奶家', [
      { id: 'member-grandma', display_name: '奶奶', actor_id: 'grandma-account' },
    ])

    expect(getBoundPinCandidates()).toEqual([
      { id: 'member-grandma', display_name: '奶奶', actor_id: 'grandma-account' },
    ])
  })

  it('automatically migrates an existing port-local binding to the shared cookie', () => {
    let cookie = ''
    Object.defineProperty(globalThis, 'document', {
      configurable: true,
      value: {
        get cookie() {
          return cookie
        },
        set cookie(value: string) {
          cookie = value
        },
      },
    })
    Object.defineProperty(globalThis, 'localStorage', {
      configurable: true,
      value: {
        getItem: vi.fn(() => JSON.stringify({ id: 'household-old', name: '已有家庭' })),
        setItem: vi.fn(),
        removeItem: vi.fn(),
      },
    })

    expect(getBoundFaceHouseholdId()).toBe('household-old')
    expect(cookie).toContain(encodeURIComponent('household-old'))
  })
})

describe('portal view guards (HCT-439)', () => {
  afterEach(() => {
    signOut()
    vi.restoreAllMocks()
  })

  it('keeps member accounts inside member-only views', async () => {
    vi.spyOn(apiClient, 'listHouseholds').mockResolvedValue([
      {
        id: 'household-member',
        name: '爷爷奶奶家',
        created_by: 'parent-admin',
        created_at: '2026-08-24T00:00:00Z',
      },
    ])
    vi.spyOn(apiClient, 'listMembers').mockResolvedValue([
      {
        id: 'member-grandma',
        household_id: 'household-member',
        display_name: '奶奶',
        role: 'DEPENDENT',
        actor_id: 'grandma-account',
        created_at: '2026-08-24T00:00:00Z',
      },
    ])
    vi.spyOn(apiClient, 'getCapabilities').mockResolvedValue({
      phase: 'local',
      available: ['api'],
      unavailable: [],
    })

    await loginAs('grandma-account')
    expect(session.portal).toBe('member')
    setView('review')
    expect(session.currentView).toBe('member-home')
    setView('member-help')
    expect(session.currentView).toBe('member-help')
  })

  it('keeps admin accounts out of member-only views', async () => {
    vi.spyOn(apiClient, 'listHouseholds').mockResolvedValue([
      {
        id: 'household-admin',
        name: '管理家庭',
        created_by: 'parent-admin',
        created_at: '2026-08-24T00:00:00Z',
      },
    ])
    vi.spyOn(apiClient, 'listMembers').mockResolvedValue([
      {
        id: 'member-grandma',
        household_id: 'household-admin',
        display_name: '奶奶',
        role: 'DEPENDENT',
        actor_id: 'grandma-account',
        created_at: '2026-08-24T00:00:00Z',
      },
    ])
    vi.spyOn(apiClient, 'listReviewTasks').mockResolvedValue([])
    vi.spyOn(apiClient, 'getCapabilities').mockResolvedValue({
      phase: 'local',
      available: ['api'],
      unavailable: [],
    })

    await loginAs('parent-admin')
    expect(session.portal).toBe('admin')
    setView('member-capture')
    expect(session.currentView).toBe('overview')
  })

  it('keeps a member on the shared assistant view when the household scope reloads', async () => {
    // 侧栏给成员提供「健康助手」入口（SHARED_VIEWS），因此重新加载家庭作用域
    // 时不能把他踢回首页——此前该判定只认 MEMBER_VIEWS，多家庭成员在助手页
    // 切换家庭就会被弹走。
    vi.spyOn(apiClient, 'listHouseholds').mockResolvedValue([
      {
        id: 'household-a',
        name: '爷爷奶奶家',
        created_by: 'parent-admin',
        created_at: '2026-08-24T00:00:00Z',
      },
      {
        id: 'household-b',
        name: '外公外婆家',
        created_by: 'parent-admin',
        created_at: '2026-08-24T00:00:00Z',
      },
    ])
    vi.spyOn(apiClient, 'listMembers').mockResolvedValue([
      {
        id: 'member-grandma',
        household_id: 'household-a',
        display_name: '奶奶',
        role: 'DEPENDENT',
        actor_id: 'grandma-account',
        created_at: '2026-08-24T00:00:00Z',
      },
    ])
    vi.spyOn(apiClient, 'getCapabilities').mockResolvedValue({
      phase: 'local',
      available: ['api'],
      unavailable: [],
    })

    await loginAs('grandma-account')
    expect(session.portal).toBe('member')
    setView('assistant')
    expect(session.currentView).toBe('assistant')

    await selectHousehold('household-b')

    expect(session.currentView).toBe('assistant')
  })
})

describe('portal entry lock (HCT-453)', () => {
  const household = {
    id: 'household-entry',
    name: '入口测试家庭',
    created_by: 'parent-admin',
    created_at: '2026-08-25T00:00:00Z',
  }
  const grandma = {
    id: 'member-grandma',
    household_id: household.id,
    display_name: '奶奶',
    role: 'DEPENDENT' as const,
    actor_id: 'grandma-account',
    created_at: '2026-08-25T00:00:00Z',
  }

  beforeEach(() => {
    vi.spyOn(apiClient, 'listHouseholds').mockResolvedValue([household])
    vi.spyOn(apiClient, 'listMembers').mockResolvedValue([grandma])
    vi.spyOn(apiClient, 'listReviewTasks').mockResolvedValue([])
    vi.spyOn(apiClient, 'getCapabilities').mockResolvedValue({
      phase: 'local',
      available: ['api'],
      unavailable: [],
    })
    vi.spyOn(apiClient, 'logout').mockResolvedValue({ status: 'logged_out' })
  })

  afterEach(() => {
    overridePortalEntryModeForTest(null)
    signOut()
    clearBoundFaceHousehold()
    resetWelcomeEntryHintForTest()
    vi.restoreAllMocks()
    Reflect.deleteProperty(globalThis, 'document')
  })

  it('keeps an owner on the member entry in the family-picker staging state', async () => {
    overridePortalEntryModeForTest('member')
    vi.spyOn(apiClient, 'login').mockResolvedValue({
      actor_id: 'parent-admin',
      session_token: 'o'.repeat(48),
      expires_at: (Date.now() + 60_000) / 1000,
    })

    await connectWithPassword('parent-admin', 'password-123', 'family-care')

    expect(session.status).toBe('selecting-member')
    expect(session.sessionToken).toHaveLength(48)
    expect(session.entryConflict).toBeNull()
    expect(session.portal).toBe('admin')
    expect(apiClient.logout).not.toHaveBeenCalled()
  })

  it('exchanges the owner staging session for the selected member after PIN', async () => {
    overridePortalEntryModeForTest('member')
    vi.spyOn(apiClient, 'login').mockResolvedValue({
      actor_id: 'parent-admin',
      session_token: 'o'.repeat(48),
      expires_at: (Date.now() + 60_000) / 1000,
    })
    vi.spyOn(apiClient, 'loginWithPin').mockResolvedValue({
      actor_id: 'grandma-account',
      household_id: household.id,
      session_token: 'm'.repeat(48),
      expires_at: (Date.now() + 60_000) / 1000,
    })

    await connectWithPassword('parent-admin', 'password-123', 'family-care')
    await completeMemberPortalPin(grandma.id, '135790')

    expect(session.status).toBe('ready')
    expect(session.actorId).toBe('grandma-account')
    expect(session.portal).toBe('member')
    expect(session.currentView).toBe('member-home')
    expect(selectedMember.value?.display_name).toBe('奶奶')
    expect(apiClient.logout).toHaveBeenCalled()
  })

  it('keeps the family picker when the member PIN is wrong', async () => {
    overridePortalEntryModeForTest('member')
    vi.spyOn(apiClient, 'login').mockResolvedValue({
      actor_id: 'parent-admin',
      session_token: 'o'.repeat(48),
      expires_at: (Date.now() + 60_000) / 1000,
    })
    vi.spyOn(apiClient, 'loginWithPin').mockRejectedValue(
      new ApiClientError('AUTH_FAILED', { status: 401, code: 'UNAUTHENTICATED' }),
    )

    await connectWithPassword('parent-admin', 'password-123', 'family-care')
    await completeMemberPortalPin(grandma.id, '000000')

    expect(session.status).toBe('selecting-member')
    expect(session.actorId).toBe('parent-admin')
    expect(session.sessionToken).toHaveLength(48)
    expect(session.error).toContain('六位数字密码不正确')
    expect(apiClient.logout).not.toHaveBeenCalled()
  })

  it('signs a plain member out of the admin entry and points to the member entry', async () => {
    overridePortalEntryModeForTest('admin')
    vi.spyOn(apiClient, 'loginWithPin').mockResolvedValue({
      actor_id: 'grandma-account',
      household_id: household.id,
      session_token: 'm'.repeat(48),
      expires_at: (Date.now() + 60_000) / 1000,
    })

    await connectWithPin('grandma-account', household.id, '135790', 'family-care')

    expect(session.status).toBe('signed-out')
    expect(session.sessionToken).toBe('')
    expect(session.entryConflict).toBe('need-member-entry')
    expect(session.error).toContain('成员前台')
  })

  it('lets matching accounts through on their own entry', async () => {
    overridePortalEntryModeForTest('member')
    await loginAs('grandma-account')
    expect(session.status).toBe('ready')
    expect(session.portal).toBe('member')
    expect(session.entryConflict).toBeNull()
    signOut()

    overridePortalEntryModeForTest('admin')
    await loginAs('parent-admin')
    expect(session.status).toBe('ready')
    expect(session.portal).toBe('admin')
    expect(session.entryConflict).toBeNull()
  })

  it('keeps the legacy auto entry role-based (HCT-439 behaviour)', async () => {
    overridePortalEntryModeForTest('auto')
    await loginAs('parent-admin')
    expect(session.status).toBe('ready')
    expect(session.portal).toBe('admin')
    expect(session.entryConflict).toBeNull()
  })

  it('clears the conflict once a matching login succeeds', async () => {
    overridePortalEntryModeForTest('admin')
    vi.spyOn(apiClient, 'loginWithPin').mockResolvedValue({
      actor_id: 'grandma-account',
      household_id: household.id,
      session_token: 'm'.repeat(48),
      expires_at: (Date.now() + 60_000) / 1000,
    })
    await connectWithPin('grandma-account', household.id, '135790', 'family-care')
    expect(session.entryConflict).toBe('need-member-entry')

    await loginAs('parent-admin')
    expect(session.status).toBe('ready')
    expect(session.entryConflict).toBeNull()
  })

  it('rewrites the conflict message after creating a household on the member entry', async () => {
    overridePortalEntryModeForTest('member')
    vi.spyOn(apiClient, 'listHouseholds')
      .mockResolvedValueOnce([])
      .mockResolvedValue([{ ...household, created_by: 'parent-admin' }])
    vi.spyOn(apiClient, 'createHousehold').mockResolvedValue({
      ...household,
      created_by: 'parent-admin',
    })
    vi.spyOn(apiClient, 'createMember').mockResolvedValue(grandma)
    vi.spyOn(apiClient, 'logout').mockResolvedValue({ status: 'logged_out' })

    await loginAs('parent-admin')
    expect(session.status).toBe('empty')

    await createHouseholdAndEnter('入口测试家庭', [
      { displayName: '奶奶', role: 'DEPENDENT', actorId: 'grandma-account' },
    ])

    expect(session.status).toBe('signed-out')
    expect(session.entryConflict).toBe('need-admin-entry')
    expect(session.error).toContain('家庭已创建')
    expect(session.error).toContain('管理后台')
  })

  it('opens login setup after creating a household on the admin entry', async () => {
    overridePortalEntryModeForTest('admin')
    vi.spyOn(apiClient, 'listHouseholds')
      .mockResolvedValueOnce([])
      .mockResolvedValue([household])
    vi.spyOn(apiClient, 'createHousehold').mockResolvedValue({
      ...household,
      created_by: 'parent-admin',
    })
    vi.spyOn(apiClient, 'createMember').mockResolvedValue(grandma)

    await loginAs('parent-admin')
    expect(session.status).toBe('empty')

    await createHouseholdAndEnter('入口测试家庭', [
      { displayName: '奶奶', role: 'DEPENDENT', actorId: 'grandma-account' },
    ])

    expect(session.status).toBe('ready')
    expect(session.portal).toBe('admin')
    expect(session.currentView).toBe('face-credentials')
  })

  it('binds the selected household when an owner signs into the admin entry', async () => {
    const jar = new Map<string, string>()
    Object.defineProperty(globalThis, 'document', {
      configurable: true,
      value: {
        get cookie() {
          return [...jar.entries()].map(([key, value]) => `${key}=${value}`).join('; ')
        },
        set cookie(value: string) {
          const pair = value.split(';')[0] ?? ''
          const eq = pair.indexOf('=')
          if (eq < 0) return
          const key = pair.slice(0, eq).trim()
          const stored = pair.slice(eq + 1).trim()
          if (/Max-Age=0/i.test(value)) jar.delete(key)
          else jar.set(key, stored)
        },
      },
    })
    overridePortalEntryModeForTest('admin')
    await loginAs('parent-admin')

    expect(session.status).toBe('ready')
    expect(getBoundFaceHouseholdId()).toBe(household.id)
    expect(getBoundFaceHouseholdName()).toBe(household.name)
    expect(getBoundPinCandidates()).toEqual([
      { id: grandma.id, display_name: '奶奶', actor_id: 'grandma-account' },
    ])
  })

  it('lets a bound device PIN-login a member without an owner password session', async () => {
    let cookie = ''
    Object.defineProperty(globalThis, 'document', {
      configurable: true,
      value: {
        get cookie() {
          return cookie
        },
        set cookie(value: string) {
          cookie = value
        },
      },
    })
    overridePortalEntryModeForTest('member')
    bindFaceHousehold(household.id, household.name, [
      { id: grandma.id, display_name: '奶奶', actor_id: 'grandma-account' },
    ])
    vi.spyOn(apiClient, 'loginWithPin').mockResolvedValue({
      actor_id: 'grandma-account',
      household_id: household.id,
      session_token: 'm'.repeat(48),
      expires_at: (Date.now() + 60_000) / 1000,
    })

    await completeBoundHouseholdPin(grandma.id, '135790')

    expect(session.status).toBe('ready')
    expect(session.actorId).toBe('grandma-account')
    expect(session.portal).toBe('member')
    expect(session.currentView).toBe('member-home')
    expect(apiClient.loginWithPin).toHaveBeenCalled()
  })

  it('member sign-out keeps the next auto welcome page on the member entry', async () => {
    let cookie = ''
    Object.defineProperty(globalThis, 'document', {
      configurable: true,
      value: {
        get cookie() {
          return cookie
        },
        set cookie(value: string) {
          cookie = value
        },
      },
    })
    overridePortalEntryModeForTest('auto')
    bindFaceHousehold(household.id, household.name, [
      { id: grandma.id, display_name: '奶奶', actor_id: 'grandma-account' },
    ])
    vi.spyOn(apiClient, 'loginWithPin').mockResolvedValue({
      actor_id: 'grandma-account',
      household_id: household.id,
      session_token: 'm'.repeat(48),
      expires_at: (Date.now() + 60_000) / 1000,
    })

    await completeBoundHouseholdPin(grandma.id, '135790')
    signOut()

    expect(session.status).toBe('signed-out')
    expect(readWelcomeEntryHint()).toBe('member')
  })
})

describe('formatError 区分真实失败原因（HCT-401 爬虫面板）', () => {
  it('连接失败用家用文案提示，不暴露运维脚本路径', () => {
    const message = formatError(
      new ApiClientError('API service is unavailable', {
        status: 0,
        code: 'DEPENDENCY_UNAVAILABLE',
      }),
    )
    expect(message).toContain('暂时连不上')
    expect(message).toContain('没有改变任何数据')
    expect(message).not.toContain('scripts/')
    expect(message).not.toContain('/health')
  })

  it('请求超时与连接失败给出不同解释', () => {
    const message = formatError(
      new ApiClientError('API request timed out after 15000ms', {
        status: 0,
        code: 'REQUEST_TIMEOUT',
      }),
    )
    expect(message).toContain('超时')
    expect(message).not.toContain('无法连接本地 API')
  })

  it('403 KNOWLEDGE_STEWARD_REQUIRED 显示知识管理员指引，绝不误报 API 不可用', () => {
    const message = formatError(
      new ApiClientError('KNOWLEDGE_STEWARD_REQUIRED', {
        status: 403,
        code: 'FORBIDDEN_MEMBER',
      }),
    )
    expect(message).toContain('知识管理员')
    expect(message).toContain('demo-parent')
    expect(message).toContain('KNOWLEDGE_ADMIN_ACTORS')
    expect(message).not.toContain('API 服务不可用')
    expect(message).not.toContain('无法连接')
  })

  it('503 KNOWLEDGE_CRAWL_CONFIG_MISSING 指出部署缺少 allowlist 与夹具', () => {
    const message = formatError(
      new ApiClientError('KNOWLEDGE_CRAWL_CONFIG_MISSING', {
        status: 503,
        code: 'HTTP_ERROR',
      }),
    )
    expect(message).toContain('allowlist.json')
    expect(message).not.toContain('无法连接')
  })

  it('501 REAL_AUTH_REQUIRED 提示重新建立正式会话', () => {
    const message = formatError(
      new ApiClientError('REAL_AUTH_REQUIRED', { status: 501, code: 'HTTP_ERROR' }),
    )
    expect(message).toContain('正式会话')
    expect(message).toContain('账号密码')
    expect(message).not.toContain('ALLOW_DEV_ACTOR_HEADER')
  })

  it('未识别的 5xx 不向家庭用户泄漏服务端 detail', () => {
    const message = formatError(
      new ApiClientError('SOMETHING_BROKE', { status: 500, code: 'HTTP_ERROR' }),
    )
    expect(message).toContain('没有改变任何数据')
    expect(message).not.toContain('HTTP 500')
    expect(message).not.toContain('SOMETHING_BROKE')
  })

  it('409 EVENT_ALREADY_SUPERSEDED 说明记录已被更正，不要求盲目刷新', () => {
    const message = formatError(
      new ApiClientError('EVENT_ALREADY_SUPERSEDED', { status: 409, code: 'VERSION_CONFLICT' }),
    )
    expect(message).toContain('已被补偿更正')
    expect(message).not.toContain('其它位置被修改')
  })

  it('409 ACCOUNT_EXISTS 明确引导回到正式账号登录', () => {
    const message = formatError(new ApiClientError('ACCOUNT_EXISTS', { status: 409, code: 'HTTP_ERROR' }))
    expect(message).toContain('正式账号已经存在')
    expect(message).toContain('返回登录')
    expect(message).not.toContain('其它位置被修改')
  })

  it('401 AUTH_FAILED 在登录卡片内提示账号或密码不正确', () => {
    const message = formatError(
      new ApiClientError('AUTH_FAILED', { status: 401, code: 'UNAUTHENTICATED' }),
    )
    expect(message).toContain('账号或密码不正确')
    expect(message).not.toContain('AUTH_FAILED')
  })

  it('422 PASSWORD_FORMAT_INVALID 要求字母和数字', () => {
    const message = formatError(
      new ApiClientError('PASSWORD_FORMAT_INVALID', { status: 422, code: 'VALIDATION_ERROR' }),
    )
    expect(message).toContain('英文字母')
    expect(message).toContain('数字')
    expect(message).not.toContain('PASSWORD_FORMAT_INVALID')
  })
})

describe('connectWithPassword login error wording (HCT-512)', () => {
  afterEach(() => {
    signOut()
    vi.restoreAllMocks()
  })

  it('maps login PASSWORD_FORMAT_INVALID to 账号或密码不正确', async () => {
    vi.spyOn(apiClient, 'login').mockRejectedValue(
      new ApiClientError('PASSWORD_FORMAT_INVALID', { status: 422, code: 'VALIDATION_ERROR' }),
    )
    await connectWithPassword('demo-parent', 'onlyletters', 'family-care')
    expect(session.status).toBe('signed-out')
    expect(session.error).toContain('账号或密码不正确')
    expect(session.error).not.toContain('英文字母')
  })

  it('maps login pydantic 422 to 账号或密码不正确', async () => {
    vi.spyOn(apiClient, 'login').mockRejectedValue(
      new ApiClientError('[object Object]', { status: 422, code: 'VALIDATION_ERROR' }),
    )
    await connectWithPassword('demo-parent', 'onlyletters', 'family-care')
    expect(session.error).toContain('账号或密码不正确')
    expect(session.error).not.toContain('不符合要求')
  })

  it('keeps policy wording when registration is rejected', async () => {
    vi.spyOn(apiClient, 'registerAccount').mockRejectedValue(
      new ApiClientError('PASSWORD_FORMAT_INVALID', { status: 422, code: 'VALIDATION_ERROR' }),
    )
    await connectWithPassword('new-owner', 'onlyletters', 'family-care', true)
    expect(session.status).toBe('signed-out')
    expect(session.error).toContain('英文字母')
  })
})

describe('formatError timeout vs unavailability (HCT-424)', () => {
  it('explains a timeout as possibly still processing, never as API down', () => {
    // 人脸注册首次推理/模型下载超过超时上限时，服务端可能仍在保存；
    // 不能显示「本地 API 不可用/没有改变任何数据」。
    const message = formatError(new ApiClientError('API request timed out after 120000ms', {
      status: 0,
      code: 'REQUEST_TIMEOUT',
    }))

    expect(message).toContain('超时')
    expect(message).not.toContain('不可用')
    expect(message).not.toContain('没有改变任何数据')
  })

  it('keeps the unavailable copy for real connection failures', () => {
    const message = formatError(new ApiClientError('API service is unavailable', {
      status: 0,
      code: 'DEPENDENCY_UNAVAILABLE',
    }))

    expect(message).toContain('暂时连不上')
    expect(message).not.toContain('scripts/')
  })

  it('503 FACE_DETECTOR_UNAVAILABLE 给出家用回退，绝不透出本机路径或运维脚本', () => {
    // Windows 中文路径导致的 ONNX 加载失败已由后端译为该稳定错误码；
    // 前端必须提示模型缺失/加载失败，而不是 OpenCV C++ 堆栈或 scripts/。
    const message = formatError(new ApiClientError('FACE_DETECTOR_UNAVAILABLE', {
      status: 503,
      code: 'HTTP_ERROR',
    }))

    expect(message).toContain('人脸功能暂时不可用')
    expect(message).toContain('没有改变任何数据')
    expect(message).toContain('账号密码')
    expect(message).not.toContain('ensure_face_models')
    expect(message).not.toContain('scripts/')
    expect(message).not.toContain('ONNX')
    expect(message).not.toContain('C:\\')
  })
})

describe('formatError face login failure buckets (HCT-425)', () => {
  it('maps LIVENESS_FAILED on 401 to pose coaching, not a generic match failure', () => {
    const message = formatError(new ApiClientError('LIVENESS_FAILED', {
      status: 401,
      code: 'HTTP_ERROR',
    }))

    expect(message).toContain('转头')
    expect(message).toContain('账号密码')
    expect(message).not.toContain('匹配失败')
  })

  it('maps FACE_AUTH_FAILED / NO_MATCH to a neutral retry tip', () => {
    for (const code of ['FACE_AUTH_FAILED', 'NO_MATCH'] as const) {
      const message = formatError(new ApiClientError(code, {
        status: 401,
        code: 'HTTP_ERROR',
      }))
      expect(message).toContain('这次没有认出来')
      expect(message).toContain('账号密码')
      expect(message).not.toContain('没匹配到人')
    }
  })

  it('maps AMBIGUOUS_MATCH on 401 to a distinct-template tip', () => {
    const message = formatError(new ApiClientError('AMBIGUOUS_MATCH', {
      status: 401,
      code: 'HTTP_ERROR',
    }))

    expect(message).toContain('确认是谁')
  })

  it('does not leak 422 English codes or 500 detail to family UI', () => {
    const validation = formatError(new ApiClientError('SOME_UNKNOWN_CODE', {
      status: 422,
      code: 'HTTP_ERROR',
    }))
    expect(validation).not.toContain('SOME_UNKNOWN_CODE')
    expect(validation).toContain('不符合要求')

    const server = formatError(new ApiClientError('OpenCV path C:\\\\secret\\\\face.onnx', {
      status: 500,
      code: 'HTTP_ERROR',
    }))
    expect(server).not.toContain('OpenCV')
    expect(server).not.toContain('face.onnx')
    expect(server).toContain('没有改变任何数据')
  })
})
