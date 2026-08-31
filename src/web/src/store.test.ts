import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiClientError, apiClient } from './api/client'
import {
  connectWithFamilyFace,
  connectWithPassword,
  connectWithPin,
  createHouseholdAndEnter,
  bindFaceHousehold,
  clearBoundFaceHousehold,
  formatError,
  getBoundFaceHouseholdId,
  getBoundFaceHouseholdName,
  portalWelcomeMessage,
  refreshCapabilities,
  selectedMember,
  session,
  setView,
  signOut,
} from './store'
import { overridePortalEntryModeForTest } from './ui/portalEntry'

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
    expect(cookie).toContain('hct-face-family-household=')
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
    vi.restoreAllMocks()
  })

  it('signs an owner out of the member entry and points to the admin entry', async () => {
    overridePortalEntryModeForTest('member')
    vi.spyOn(apiClient, 'login').mockResolvedValue({
      actor_id: 'parent-admin',
      session_token: 'o'.repeat(48),
      expires_at: (Date.now() + 60_000) / 1000,
    })

    await connectWithPassword('parent-admin', 'password-123', 'family-care')

    expect(session.status).toBe('signed-out')
    expect(session.sessionToken).toBe('')
    expect(session.entryConflict).toBe('need-admin-entry')
    expect(session.error).toContain('管理后台')
    expect(apiClient.logout).toHaveBeenCalled()
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
    expect(message).toContain('数字密码')
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
    expect(message).toContain('数字密码')
    expect(message).not.toContain('匹配失败')
  })

  it('maps FACE_AUTH_FAILED / NO_MATCH to a neutral retry tip', () => {
    for (const code of ['FACE_AUTH_FAILED', 'NO_MATCH'] as const) {
      const message = formatError(new ApiClientError(code, {
        status: 401,
        code: 'HTTP_ERROR',
      }))
      expect(message).toContain('这次没有认出来')
      expect(message).toContain('数字密码')
      expect(message).not.toContain('没匹配到人')
    }
  })

  it('maps AMBIGUOUS_MATCH on 401 to a distinct-template tip', () => {
    const message = formatError(new ApiClientError('AMBIGUOUS_MATCH', {
      status: 401,
      code: 'HTTP_ERROR',
    }))

    expect(message).toContain('太像')
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
