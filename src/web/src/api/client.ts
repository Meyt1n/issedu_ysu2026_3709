import type {
  AccessAudit,
  ApiErrorCode,
  ApiErrorEnvelope,
  Authorization,
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
  RequestOptions,
  RiskDetailResponse,
  RiskListResponse,
  UpdateAuthorizationInput,
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
    this.fetcher = options.fetcher ?? fetch
  }

  private async request<T>(
    path: string,
    init: RequestInit = {},
    options: RequestOptions = {},
  ): Promise<T> {
    const headers = new Headers(init.headers)
    headers.set('Accept', 'application/json')
    if (init.body !== undefined) headers.set('Content-Type', 'application/json')
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
        confirmation_status: 'CONFIRMED',
      }),
    }, options)
  }

  listHealthEvents(
    householdId: string,
    memberId?: string,
    options?: RequestOptions,
  ): Promise<HealthEvent[]> {
    const query = memberId ? `?member_id=${encodeURIComponent(memberId)}` : ''
    return this.request(`/api/v1/households/${householdId}/events${query}`, undefined, options)
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
