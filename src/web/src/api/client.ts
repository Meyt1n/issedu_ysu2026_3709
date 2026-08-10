import type {
  AccessAudit,
  ApiErrorCode,
  ApiErrorEnvelope,
  Authorization,
  CompensateHealthEventInput,
  CreateAuthorizationInput,
  CreateHealthEventInput,
  CreateHouseholdInput,
  CreateMemberInput,
  HealthEvent,
  HealthResponse,
  CapabilityResponse,
  Household,
  Member,
  MemberState,
  OutboxDispatchResult,
  OutboxMessage,
  ProjectionCheckpoint,
  ProjectionReplayResult,
  RequestOptions,
  RiskDetailResponse,
  RiskListResponse,
  UpdateAuthorizationInput,
  UploadedFile,
  VisionQualityResponse,
  CreateVisionTaskInput,
  VisionTask,
} from './types'

export class ApiClientError extends Error {
  readonly status: number
  readonly code: ApiErrorCode
  readonly details: unknown
  readonly requestId: string | null

  constructor(
    message: string,
    options: {
      status: number
      code: ApiErrorCode
      details?: unknown
      requestId?: string | null
    },
  ) {
    super(message)
    this.name = 'ApiClientError'
    this.status = options.status
    this.code = options.code
    this.details = options.details ?? null
    this.requestId = options.requestId ?? null
  }
}

interface ApiClientOptions {
  baseUrl?: string
  fetcher?: typeof fetch
}

function fallbackErrorCode(status: number): ApiErrorCode {
  if (status === 401) return 'UNAUTHENTICATED'
  if (status === 403) return 'FORBIDDEN_MEMBER'
  if (status === 404) return 'NOT_FOUND'
  if (status === 409) return 'VERSION_CONFLICT'
  if (status === 422) return 'VALIDATION_ERROR'
  return 'HTTP_ERROR'
}

function parseErrorBody(body: unknown, status: number, requestId: string | null): ApiClientError {
  const envelope = (body ?? {}) as ApiErrorEnvelope
  const nested = envelope.error

  return new ApiClientError(
    nested?.message ?? envelope.detail ?? `API request failed with status ${status}`,
    {
      status,
      code: nested?.code ?? fallbackErrorCode(status),
      details: nested?.details,
      requestId: nested?.request_id ?? envelope.request_id ?? requestId,
    },
  )
}

export class ApiClient {
  private readonly baseUrl: string
  private readonly fetcher: typeof fetch

  constructor(options: ApiClientOptions = {}) {
    this.baseUrl = options.baseUrl ?? ''
    this.fetcher = options.fetcher ?? globalThis.fetch.bind(globalThis)
  }

  private async request<T>(
    path: string,
    init: RequestInit = {},
    options: RequestOptions = {},
  ): Promise<T> {
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
      response = await this.fetcher(`${this.baseUrl}${path}`, {
        ...init,
        headers,
        signal: options.signal,
      })
    } catch {
      throw new ApiClientError('API service is unavailable', {
        status: 0,
        code: 'DEPENDENCY_UNAVAILABLE',
      })
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

    if (!response.ok) throw parseErrorBody(body, response.status, requestId)
    return body as T
  }

  getHealth(options?: RequestOptions): Promise<HealthResponse> {
    return this.request('/health', undefined, options)
  }

  getDatabaseHealth(options?: RequestOptions): Promise<HealthResponse> {
    return this.request('/api/v1/health/db', undefined, options)
  }

  getCapabilities(options?: RequestOptions): Promise<CapabilityResponse> {
    return this.request('/api/v1/meta/capabilities', undefined, options)
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

  deleteUploadedFile(storageKey: string, options?: RequestOptions): Promise<{ deleted: boolean }> {
    return this.request(
      `/api/v1/files/${encodeURIComponent(storageKey)}`,
      { method: 'DELETE' },
      options,
    )
  }

  createVisionTask(input: CreateVisionTaskInput, options?: RequestOptions): Promise<VisionTask> {
    return this.request(
      '/api/v1/vision-tasks',
      { method: 'POST', body: JSON.stringify(input) },
      options,
    )
  }

  listHouseholds(options?: RequestOptions): Promise<Household[]> {
    return this.request('/api/v1/households', undefined, options)
  }

  createHousehold(
    input: CreateHouseholdInput,
    options?: RequestOptions,
  ): Promise<Household> {
    return this.request('/api/v1/households', {
      method: 'POST',
      body: JSON.stringify(input),
    }, options)
  }

  createMember(
    householdId: string,
    input: CreateMemberInput,
    options?: RequestOptions,
  ): Promise<Member> {
    return this.request(`/api/v1/households/${householdId}/members`, {
      method: 'POST',
      body: JSON.stringify(input),
    }, options)
  }

  listMembers(
    householdId: string,
    options?: RequestOptions,
  ): Promise<Member[]> {
    return this.request(
      `/api/v1/households/${householdId}/members`,
      undefined,
      options,
    )
  }

  createAuthorization(
    householdId: string,
    input: CreateAuthorizationInput,
    options?: RequestOptions,
  ): Promise<Authorization> {
    return this.request(`/api/v1/households/${householdId}/authorizations`, {
      method: 'POST',
      body: JSON.stringify(input),
    }, options)
  }

  listAuthorizations(
    householdId: string,
    options?: RequestOptions,
  ): Promise<Authorization[]> {
    return this.request(
      `/api/v1/households/${householdId}/authorizations`,
      undefined,
      options,
    )
  }

  updateAuthorization(
    householdId: string,
    authorizationId: string,
    input: UpdateAuthorizationInput,
    options?: RequestOptions,
  ): Promise<Authorization> {
    return this.request(
      `/api/v1/households/${householdId}/authorizations/${authorizationId}`,
      { method: 'PATCH', body: JSON.stringify(input) },
      options,
    )
  }

  revokeAuthorization(
    householdId: string,
    authorizationId: string,
    expectedVersion: number,
    options?: RequestOptions,
  ): Promise<Authorization> {
    return this.request(
      `/api/v1/households/${householdId}/authorizations/${authorizationId}/revoke`,
      { method: 'POST', body: JSON.stringify({ expected_version: expectedVersion }) },
      options,
    )
  }

  listAuthorizationAudits(
    householdId: string,
    options?: RequestOptions,
  ): Promise<AccessAudit[]> {
    return this.request(
      `/api/v1/households/${householdId}/authorization-audits`,
      undefined,
      options,
    )
  }

  appendHealthEvent(
    householdId: string,
    input: CreateHealthEventInput,
    options?: RequestOptions,
  ): Promise<HealthEvent> {
    return this.request(`/api/v1/households/${householdId}/events`, {
      method: 'POST',
      body: JSON.stringify({
        ...input,
        source: 'MANUAL',
        confirmation_status: input.confirmation_status ?? 'CONFIRMED',
      }),
    }, options)
  }

  compensateHealthEvent(
    householdId: string,
    eventId: string,
    input: CompensateHealthEventInput,
    options?: RequestOptions,
  ): Promise<HealthEvent> {
    return this.request(
      `/api/v1/households/${householdId}/events/${eventId}/compensations`,
      { method: 'POST', body: JSON.stringify(input) },
      options,
    )
  }

  listHealthEvents(
    householdId: string,
    memberId?: string,
    options?: RequestOptions,
  ): Promise<HealthEvent[]> {
    const query = memberId ? `?member_id=${encodeURIComponent(memberId)}` : ''
    return this.request(`/api/v1/households/${householdId}/events${query}`, undefined, options)
  }

  listMemberTimeline(
    householdId: string,
    memberId: string,
    options?: RequestOptions,
  ): Promise<HealthEvent[]> {
    return this.request(
      `/api/v1/households/${householdId}/members/${memberId}/timeline`,
      undefined,
      options,
    )
  }

  getMemberState(
    householdId: string,
    memberId: string,
    options?: RequestOptions,
  ): Promise<MemberState> {
    return this.request(
      `/api/v1/households/${householdId}/members/${memberId}/state`,
      undefined,
      options,
    )
  }

  createProjectionCheckpoint(
    householdId: string,
    memberId: string,
    options?: RequestOptions,
  ): Promise<ProjectionCheckpoint> {
    return this.request(
      `/api/v1/households/${householdId}/members/${memberId}/state/checkpoints`,
      { method: 'POST' },
      options,
    )
  }

  replayMemberState(
    householdId: string,
    memberId: string,
    checkpointId?: string,
    options?: RequestOptions,
  ): Promise<ProjectionReplayResult> {
    return this.request(
      `/api/v1/households/${householdId}/members/${memberId}/state/replay`,
      {
        method: 'POST',
        body: JSON.stringify({ checkpoint_id: checkpointId }),
      },
      options,
    )
  }

  listOutboxMessages(
    householdId: string,
    options?: RequestOptions,
  ): Promise<OutboxMessage[]> {
    return this.request(`/api/v1/households/${householdId}/outbox`, undefined, options)
  }

  dispatchOutbox(
    householdId: string,
    options?: RequestOptions,
  ): Promise<OutboxDispatchResult> {
    return this.request(
      `/api/v1/households/${householdId}/outbox/dispatch`,
      {
        method: 'POST',
        body: JSON.stringify({ max_messages: 50, stale_after_seconds: 300 }),
      },
      options,
    )
  }

  listMemberRisks(
    householdId: string,
    memberId: string,
    options?: RequestOptions,
  ): Promise<RiskListResponse> {
    return this.request(
      `/api/v1/households/${householdId}/members/${memberId}/risks`,
      undefined,
      options,
    )
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
}

export const apiClient = new ApiClient()
