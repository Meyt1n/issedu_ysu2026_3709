import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiClientError, apiClient } from './api/client'
import {
  connect,
  connectWithFamilyFace,
  connectWithPassword,
  connectWithPin,
  formatError,
  portalWelcomeMessage,
  refreshCapabilities,
  selectedMember,
  session,
  setView,
  signOut,
} from './store'

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

    await connect('grandma-account', 'family-care')
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

    await connect('parent-admin', 'family-care')
    expect(session.portal).toBe('admin')
    setView('member-capture')
    expect(session.currentView).toBe('overview')
  })
})

describe('formatError 区分真实失败原因（HCT-401 爬虫面板）', () => {
  it('连接失败提示如何启动并验证 API，而不是含糊的“服务不可用”', () => {
    const message = formatError(
      new ApiClientError('API service is unavailable', {
        status: 0,
        code: 'DEPENDENCY_UNAVAILABLE',
      }),
    )
    expect(message).toContain('无法连接本地 API')
    expect(message).toContain('/health')
    expect(message).toContain('没有改变任何数据')
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

  it('501 REAL_AUTH_REQUIRED 提示开发身份头已关闭', () => {
    const message = formatError(
      new ApiClientError('REAL_AUTH_REQUIRED', { status: 501, code: 'HTTP_ERROR' }),
    )
    expect(message).toContain('ALLOW_DEV_ACTOR_HEADER')
  })

  it('未识别的 5xx 展示 HTTP 状态与服务端 detail 供定位', () => {
    const message = formatError(
      new ApiClientError('SOMETHING_BROKE', { status: 500, code: 'HTTP_ERROR' }),
    )
    expect(message).toContain('HTTP 500')
    expect(message).toContain('SOMETHING_BROKE')
  })
})
