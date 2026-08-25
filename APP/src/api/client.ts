import type {
  ApiErrorCode,
  ApiErrorEnvelope,
  AssistantAgentTrace,
  AssistantChatInput,
  AssistantExternalSource,
  AssistantResponse,
  CapabilityResponse,
  EvidencePreview,
  HealthEvent,
  HealthResponse,
  Household,
  Member,
  RequestOptions,
  RiskDetailResponse,
  RiskListResponse,
  AuthorizationRead,
  UploadedFile,
  VisionQualityResponse,
  VisionTask,
} from './types'
import type { AuthSession } from './auth'
import { recordRequestTrace } from './requestLog'
import { validateServerBaseUrl } from '@/utils/serverUrl'

/** 与主仓库 web 端 ApiClient 相同的错误封装与请求头约定。 */
export class ApiClientError extends Error {
  readonly status: number
  readonly code: ApiErrorCode
  readonly requestId: string | null

  constructor(message: string, options: { status: number; code: ApiErrorCode; requestId?: string | null }) {
    super(message)
    this.name = 'ApiClientError'
    this.status = options.status
    this.code = options.code
    this.requestId = options.requestId ?? null
  }
}

/** 默认请求超时；用于区分"超时"与"网络不可达"（MOB-144）。 */
const DEFAULT_TIMEOUT_MS = 15_000

function fallbackErrorCode(status: number): ApiErrorCode {
  if (status === 401) return 'UNAUTHENTICATED'
  if (status === 403) return 'FORBIDDEN_MEMBER'
  if (status === 404) return 'NOT_FOUND'
  if (status === 409) return 'VERSION_CONFLICT'
  if (status === 422) return 'VALIDATION_ERROR'
  return 'HTTP_ERROR'
}

interface ApiClientOptions {
  baseUrl?: string
  fetcher?: typeof fetch
  /** 配置后不再回退到 X-Actor-Id；未配置时保留开发期联调头。 */
  authSessionProvider?: () => AuthSession | null
}

export class ApiClient {
  private readonly baseUrl: string
  private readonly fetcher: typeof fetch
  private readonly authSessionProvider?: () => AuthSession | null

  constructor(options: ApiClientOptions = {}) {
    const baseUrl = validateServerBaseUrl(options.baseUrl ?? '')
    if (!baseUrl.ok) {
      throw new ApiClientError(baseUrl.message, { status: 0, code: 'INVALID_SERVER_URL' })
    }
    this.baseUrl = baseUrl.value
    this.fetcher = options.fetcher ?? globalThis.fetch.bind(globalThis)
    this.authSessionProvider = options.authSessionProvider
  }

  private async request<T>(path: string, init: RequestInit = {}, options: RequestOptions = {}): Promise<T> {
    const headers = new Headers(init.headers)
    headers.set('Accept', 'application/json')
    if (init.body !== undefined && !(init.body instanceof FormData)) {
      headers.set('Content-Type', 'application/json')
    }
    const hasAuthProvider = this.authSessionProvider !== undefined
    const hasPerRequestAuth = Object.prototype.hasOwnProperty.call(options, 'authSession')
    const authSession = hasPerRequestAuth ? options.authSession : this.authSessionProvider?.()
    if (authSession) {
      const expiresAt = Date.parse(authSession.expiresAt)
      if (!Number.isFinite(expiresAt) || expiresAt <= Date.now()) {
        throw new ApiClientError('登录会话已过期', { status: 401, code: 'SESSION_EXPIRED' })
      }
      if (authSession.transport === 'bearer') {
        if (!authSession.accessToken) {
          throw new ApiClientError('登录会话已过期', { status: 401, code: 'SESSION_EXPIRED' })
        }
        headers.set('Authorization', `Bearer ${authSession.accessToken}`)
      } else if (authSession.transport === 'cookie') {
        // Cookie 由 WebView/浏览器管理，客户端不读取或持久化其内容。
      } else {
        headers.set('X-Actor-Id', authSession.actorId)
      }
      if (authSession.accessPurpose) headers.set('X-Access-Purpose', authSession.accessPurpose)
    } else if (!hasAuthProvider) {
      // 仅保留给主仓库 HCT-107 尚未接入前的本地联调路径。
      if (options.actorId) headers.set('X-Actor-Id', options.actorId)
      if (options.accessPurpose) headers.set('X-Access-Purpose', options.accessPurpose)
    } else if (options.accessPurpose) {
      headers.set('X-Access-Purpose', options.accessPurpose)
    }
    if (options.idempotencyKey) headers.set('Idempotency-Key', options.idempotencyKey)

    // MOB-144：15s 超时让"超时"与"网络不可达"可区分；外部传入 signal 时尊重外部控制。
    const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS
    const timeoutController = (typeof AbortController !== 'undefined' && timeoutMs > 0)
      ? new AbortController()
      : null
    const timeoutTimer = timeoutController
      ? setTimeout(() => timeoutController.abort(), timeoutMs)
      : null
    const onExternalAbort = () => timeoutController?.abort()
    options.signal?.addEventListener('abort', onExternalAbort)
    const requestInit: RequestInit = {
      ...init,
      headers,
      signal: options.signal ?? timeoutController?.signal,
    }
    if (authSession?.transport === 'cookie' && requestInit.credentials === undefined) {
      requestInit.credentials = 'include'
    }

    const traceBase = {
      method: init.method ?? 'GET',
      path,
      idempotencyKey: options.idempotencyKey,
    }

    let response: Response
    let body: unknown = null
    try {
      try {
        response = await this.fetcher(`${this.baseUrl}${path}`, requestInit)
      } catch {
        const aborted = timeoutController?.signal.aborted === true
        recordRequestTrace({
          ...traceBase,
          outcome: aborted ? 'timeout' : 'unreachable',
        })
        if (aborted) {
          throw new ApiClientError('请求超时，服务器没有在限定时间内响应', { status: 0, code: 'REQUEST_TIMEOUT' })
        }
        throw new ApiClientError('家庭服务器暂时无法访问', { status: 0, code: 'DEPENDENCY_UNAVAILABLE' })
      }

      const requestId = response.headers.get('x-request-id')
      const text = await response.text()
      if (text) {
        try {
          body = JSON.parse(text) as unknown
        } catch {
          body = { detail: text }
        }
      }

      // 成功与失败都记录可定位回执；响应体若携带事件/任务 ID 一并关联。
      const receiptId = body !== null && typeof body === 'object' && body !== null
        && typeof (body as { id?: unknown }).id === 'string'
        ? (body as { id: string }).id
        : undefined
      recordRequestTrace({
        ...traceBase,
        outcome: response.ok ? 'success' : response.status >= 500 ? 'server-error' : 'client-error',
        status: response.status,
        requestId,
        receiptId,
      })

      if (!response.ok) {
        const envelope = (body ?? {}) as ApiErrorEnvelope
        throw new ApiClientError(
          envelope.error?.message ?? envelope.detail ?? `请求失败（HTTP ${response.status}）`,
          {
            status: response.status,
            code: envelope.error?.code ?? fallbackErrorCode(response.status),
            requestId: envelope.error?.request_id ?? envelope.request_id ?? requestId,
          },
        )
      }
      return body as T
    } finally {
      if (timeoutTimer) clearTimeout(timeoutTimer)
      options.signal?.removeEventListener('abort', onExternalAbort)
    }
  }

  getHealth(options?: RequestOptions): Promise<HealthResponse> {
    return this.request('/health', undefined, options)
  }

  getCapabilities(options?: RequestOptions): Promise<CapabilityResponse> {
    return this.request('/api/v1/meta/capabilities', undefined, options)
  }

  listHouseholds(options?: RequestOptions): Promise<Household[]> {
    return this.request('/api/v1/households', undefined, options)
  }

  /**
   * 设置或更新当前身份在某个家庭的六位 PIN（HCT-427 的二次确认凭据）。
   * PIN 只出现在请求体里，不进 URL；服务端只保存哈希。
   */
  setAccountPin(householdId: string, pin: string, options?: RequestOptions): Promise<unknown> {
    return this.request(
      '/api/v1/auth/pin',
      { method: 'POST', body: JSON.stringify({ household_id: householdId, pin }) },
      options,
    )
  }

  listMembers(householdId: string, options?: RequestOptions): Promise<Member[]> {
    return this.request(`/api/v1/households/${householdId}/members`, undefined, options)
  }

  listMemberTimeline(householdId: string, memberId: string, options?: RequestOptions): Promise<HealthEvent[]> {
    return this.request(`/api/v1/households/${householdId}/members/${memberId}/timeline`, undefined, options)
  }

  /** 授权列表（HCT-102，仅 Owner；非 Owner 服务端隐藏式拒绝 403/404）。 */
  listAuthorizations(householdId: string, options?: RequestOptions): Promise<AuthorizationRead[]> {
    return this.request(`/api/v1/households/${householdId}/authorizations`, undefined, options)
  }

  listMemberRisks(householdId: string, memberId: string, options?: RequestOptions): Promise<RiskListResponse> {
    return this.request(`/api/v1/households/${householdId}/members/${memberId}/risks`, undefined, options)
  }

  getRiskDetail(
    householdId: string,
    memberId: string,
    ruleId: string,
    options?: RequestOptions,
  ): Promise<RiskDetailResponse> {
    return this.request(
      `/api/v1/households/${householdId}/members/${memberId}/risks/${encodeURIComponent(ruleId)}`,
      undefined,
      options,
    )
  }

  confirmCarePlan(
    householdId: string,
    memberId: string,
    planEventId: string,
    options?: RequestOptions,
  ): Promise<HealthEvent> {
    return this.request(
      `/api/v1/households/${householdId}/members/${memberId}/plans/confirm?plan_event_id=${encodeURIComponent(planEventId)}`,
      { method: 'POST' },
      options,
    )
  }

  deferCarePlan(
    householdId: string,
    memberId: string,
    planEventId: string,
    delayHours: number,
    options?: RequestOptions,
  ): Promise<HealthEvent> {
    return this.request(
      `/api/v1/households/${householdId}/members/${memberId}/plans/defer?plan_event_id=${encodeURIComponent(planEventId)}&delay_hours=${delayHours}`,
      { method: 'POST' },
      options,
    )
  }

  skipCarePlan(
    householdId: string,
    memberId: string,
    planEventId: string,
    reason: string,
    options?: RequestOptions,
  ): Promise<HealthEvent> {
    return this.request(
      `/api/v1/households/${householdId}/members/${memberId}/plans/skip?plan_event_id=${encodeURIComponent(planEventId)}&reason=${encodeURIComponent(reason)}`,
      { method: 'POST' },
      options,
    )
  }

  checkVisionQuality(
    file: File,
    mediaType: 'image' | 'video' = 'image',
    options?: RequestOptions,
  ): Promise<VisionQualityResponse> {
    const body = new FormData()
    body.append('file', file)
    body.append('media_type', mediaType)
    return this.request('/api/v1/vision-quality/check', { method: 'POST', body }, options)
  }

  uploadFile(file: File, options?: RequestOptions): Promise<UploadedFile> {
    const body = new FormData()
    body.append('file', file)
    return this.request('/api/v1/files/upload', { method: 'POST', body }, options)
  }

  createVisionTask(
    input: {
      file_id: string
      member_id?: string
      quality_receipt: string
      idempotency_key?: string
      media_type?: 'image' | 'video'
    },
    options?: RequestOptions,
  ): Promise<VisionTask> {
    return this.request('/api/v1/vision-tasks', { method: 'POST', body: JSON.stringify(input) }, options)
  }

  /** 回查单个视觉任务的状态；身份由会话承载，路径只包含服务端签发的任务 ID。 */
  getVisionTask(taskId: string, options?: RequestOptions): Promise<VisionTask> {
    return this.request(
      `/api/v1/vision-tasks/${encodeURIComponent(taskId)}`,
      { method: 'GET' },
      options,
    )
  }

  /**
   * 本地助手聊天：连向「我的」里配置的家庭服务器（例如电脑上的 FastAPI）。
   * 不上传音频；只发送用户确认后的文字草稿。本地大模型可能较慢，超时放宽到 240s。
   */
  assistantChat(
    input: AssistantChatInput,
    householdId?: string,
    memberId?: string,
    options?: RequestOptions,
  ): Promise<AssistantResponse> {
    const params = new URLSearchParams()
    if (householdId) params.set('household_id', householdId)
    if (memberId) params.set('member_id', memberId)
    const query = params.toString()
    return this.request(
      `/api/v1/assistant/chat${query ? `?${query}` : ''}`,
      { method: 'POST', body: JSON.stringify(input) },
      { timeoutMs: 240_000, ...options },
    )
  }

  /**
   * 多智能体流式聊天：逐步接收 trace / status / token / done。
   * 仅推送校验后的最终回答文本；失败时可回退到 assistantChat。
   */
  async assistantChatStream(
    input: AssistantChatInput,
    handlers: {
      onTrace?: (trace: AssistantAgentTrace) => void
      onToken?: (token: string) => void
      onStatus?: (phase: string) => void
      onExternalSources?: (sources: AssistantExternalSource[], networkQuery?: string | null) => void
      onEvidencePreview?: (preview: EvidencePreview) => void
      onCancelled?: () => void
    },
    householdId?: string,
    memberId?: string,
    options: RequestOptions = {},
  ): Promise<AssistantResponse> {
    const params = new URLSearchParams()
    if (householdId) params.set('household_id', householdId)
    if (memberId) params.set('member_id', memberId)
    const query = params.toString()
    const headers = new Headers({ Accept: 'text/event-stream', 'Content-Type': 'application/json' })

    const hasAuthProvider = this.authSessionProvider !== undefined
    const hasPerRequestAuth = Object.prototype.hasOwnProperty.call(options, 'authSession')
    const authSession = hasPerRequestAuth ? options.authSession : this.authSessionProvider?.()
    if (authSession) {
      if (authSession.transport === 'bearer' && authSession.accessToken) {
        headers.set('Authorization', `Bearer ${authSession.accessToken}`)
      } else if (authSession.transport !== 'cookie') {
        headers.set('X-Actor-Id', authSession.actorId)
      }
      if (authSession.accessPurpose) headers.set('X-Access-Purpose', authSession.accessPurpose)
    } else if (!hasAuthProvider) {
      if (options.actorId) headers.set('X-Actor-Id', options.actorId)
      if (options.accessPurpose) headers.set('X-Access-Purpose', options.accessPurpose)
    }

    const timeoutMs = options.timeoutMs ?? 240_000
    const timeoutController = typeof AbortController !== 'undefined' ? new AbortController() : null
    const timeoutTimer = timeoutController ? setTimeout(() => timeoutController.abort(), timeoutMs) : null
    const onExternalAbort = () => timeoutController?.abort()
    options.signal?.addEventListener('abort', onExternalAbort)

    try {
      const response = await this.fetcher(
        `${this.baseUrl}/api/v1/assistant/chat/stream${query ? `?${query}` : ''}`,
        {
          method: 'POST',
          headers,
          body: JSON.stringify(input),
          signal: options.signal ?? timeoutController?.signal,
          credentials: authSession?.transport === 'cookie' ? 'include' : undefined,
        },
      )
      if (!response.ok) {
        const text = await response.text()
        let body: unknown = null
        try {
          body = JSON.parse(text)
        } catch {
          body = { detail: text }
        }
        const envelope = (body ?? {}) as ApiErrorEnvelope
        throw new ApiClientError(
          envelope.error?.message ?? envelope.detail ?? `请求失败（HTTP ${response.status}）`,
          {
            status: response.status,
            code: envelope.error?.code ?? fallbackErrorCode(response.status),
            requestId: envelope.error?.request_id ?? envelope.request_id ?? response.headers.get('x-request-id'),
          },
        )
      }

      const reader = response.body?.getReader()
      if (!reader) {
        throw new ApiClientError('流式响应不可用', { status: 0, code: 'DEPENDENCY_UNAVAILABLE' })
      }

      const decoder = new TextDecoder()
      let buffer = ''
      let finalResponse: AssistantResponse | null = null

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const chunks = buffer.split('\n\n')
        buffer = chunks.pop() ?? ''
        for (const chunk of chunks) {
          if (!chunk.trim()) continue
          let eventName = 'message'
          let dataLine = ''
          for (const line of chunk.split('\n')) {
            if (line.startsWith('event:')) eventName = line.slice(6).trim()
            if (line.startsWith('data:')) dataLine = line.slice(5).trim()
          }
          if (!dataLine) continue
          const payload = JSON.parse(dataLine) as Record<string, unknown>
          if (eventName === 'trace') handlers.onTrace?.(payload.trace as AssistantAgentTrace)
          if (eventName === 'status') handlers.onStatus?.(String(payload.phase ?? ''))
          if (eventName === 'token') handlers.onToken?.(String(payload.token ?? ''))
          if (eventName === 'evidence_preview') {
            handlers.onEvidencePreview?.(payload as unknown as EvidencePreview)
          }
          if (eventName === 'external_sources') {
            handlers.onExternalSources?.(
              (payload.external_sources as AssistantExternalSource[]) ?? [],
              (payload.network_query as string | null | undefined) ?? null,
            )
          }
          if (eventName === 'done') finalResponse = payload.response as AssistantResponse
          if (eventName === 'cancelled') {
            handlers.onCancelled?.()
            throw new ApiClientError('ASSISTANT_STREAM_CANCELLED', {
              status: 0,
              code: 'CANCELLED',
            })
          }
          if (eventName === 'error') {
            const code = String(payload.code ?? '')
            if (code === 'CANCELLED' || String(payload.message ?? '') === 'CANCELLED') {
              handlers.onCancelled?.()
              throw new ApiClientError('ASSISTANT_STREAM_CANCELLED', { status: 0, code: 'CANCELLED' })
            }
            throw new ApiClientError(String(payload.message ?? '流式失败'), {
              status: 0,
              code: 'DEPENDENCY_UNAVAILABLE',
            })
          }
        }
      }

      if (!finalResponse) {
        throw new ApiClientError('流式结束但未收到回答', { status: 0, code: 'DEPENDENCY_UNAVAILABLE' })
      }
      return finalResponse
    } finally {
      if (timeoutTimer) clearTimeout(timeoutTimer)
      options.signal?.removeEventListener('abort', onExternalAbort)
    }
  }
}
