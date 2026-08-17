import type {
  ApiErrorCode,
  ApiErrorEnvelope,
  CapabilityResponse,
  HealthEvent,
  HealthResponse,
  Household,
  Member,
  RequestOptions,
  RiskDetailResponse,
  RiskListResponse,
  UploadedFile,
  VisionQualityResponse,
  VisionTask,
} from './types'

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
}

export class ApiClient {
  private readonly baseUrl: string
  private readonly fetcher: typeof fetch

  constructor(options: ApiClientOptions = {}) {
    this.baseUrl = (options.baseUrl ?? '').replace(/\/+$/, '')
    this.fetcher = options.fetcher ?? globalThis.fetch.bind(globalThis)
  }

  private async request<T>(path: string, init: RequestInit = {}, options: RequestOptions = {}): Promise<T> {
    const headers = new Headers(init.headers)
    headers.set('Accept', 'application/json')
    if (init.body !== undefined && !(init.body instanceof FormData)) {
      headers.set('Content-Type', 'application/json')
    }
    if (options.actorId) headers.set('X-Actor-Id', options.actorId)
    if (options.accessPurpose) headers.set('X-Access-Purpose', options.accessPurpose)
    if (options.idempotencyKey) headers.set('Idempotency-Key', options.idempotencyKey)

    let response: Response
    try {
      response = await this.fetcher(`${this.baseUrl}${path}`, { ...init, headers, signal: options.signal })
    } catch {
      throw new ApiClientError('家庭服务器暂时无法访问', { status: 0, code: 'DEPENDENCY_UNAVAILABLE' })
    }

    const requestId = response.headers.get('x-request-id')
    const text = await response.text()
    let body: unknown = null
    if (text) {
      try {
        body = JSON.parse(text) as unknown
      } catch {
        body = { detail: text }
      }
    }

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

  listMembers(householdId: string, options?: RequestOptions): Promise<Member[]> {
    return this.request(`/api/v1/households/${householdId}/members`, undefined, options)
  }

  listMemberTimeline(householdId: string, memberId: string, options?: RequestOptions): Promise<HealthEvent[]> {
    return this.request(`/api/v1/households/${householdId}/members/${memberId}/timeline`, undefined, options)
  }

  /** 仅家庭 owner 可读；非 owner 返回 404（用于区分照护者视角）。 */
  listAuthorizations(householdId: string, options?: RequestOptions): Promise<unknown[]> {
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

  checkVisionQuality(file: File, options?: RequestOptions): Promise<VisionQualityResponse> {
    const body = new FormData()
    body.append('file', file)
    body.append('media_type', 'image')
    return this.request('/api/v1/vision-quality/check', { method: 'POST', body }, options)
  }

  uploadFile(file: File, options?: RequestOptions): Promise<UploadedFile> {
    const body = new FormData()
    body.append('file', file)
    return this.request('/api/v1/files/upload', { method: 'POST', body }, options)
  }

  createVisionTask(
    input: { file_id: string; member_id?: string; quality_receipt: string; idempotency_key?: string },
    options?: RequestOptions,
  ): Promise<VisionTask> {
    return this.request('/api/v1/vision-tasks', { method: 'POST', body: JSON.stringify(input) }, options)
  }
}
