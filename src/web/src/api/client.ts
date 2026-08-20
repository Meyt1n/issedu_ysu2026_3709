import type {
  AccessAudit,
  ActiveModelVersion,
  AuthSession,
  ApiErrorCode,
  ApiErrorEnvelope,
  AssistantChatInput,
  AssistantResponse,
  AssistantTool,
  Authorization,
  CompensateHealthEventInput,
  ConfirmReviewInput,
  CorrectionDiff,
  CorrectReviewInput,
  CreateAuthorizationInput,
  CreateHardSampleInput,
  CreateHealthEventInput,
  CreateHouseholdInput,
  CreateKnowledgeDocumentInput,
  CreateMemberInput,
  CreateModelVersionBindingInput,
  HardSample,
  HealthEvent,
  HealthResponse,
  CapabilityResponse,
  DashboardSummary,
  Household,
  KnowledgeDocument,
  KnowledgeIndexSnapshot,
  KnowledgeRetrieveResponse,
  Member,
  MemberState,
  ModelBindingComparison,
  ModelVersionBinding,
  OutboxDispatchResult,
  OutboxMessage,
  ProjectionCheckpoint,
  ProjectionReplayResult,
  PlanWorkbenchResponse,
  RelationshipGraph,
  RequestOptions,
  ReviewTask,
  SkipReviewInput,
  RiskAlert,
  RiskAcknowledgement,
  RiskDetailResponse,
  RiskListResponse,
  EvidencePipelineResult,
  TrainingConsent,
  UpdateAuthorizationInput,
  UploadedFile,
  VisionQualityResponse,
  CreateVisionTaskInput,
  SubmitVisionEvidenceInput,
  VisionTask,
  WeatherResponse,
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

/** 默认请求超时：覆盖本地推理接口的最慢路径，同时保证挂起请求可在可感知时间内恢复。 */
const DEFAULT_REQUEST_TIMEOUT_MS = 15_000

export class ApiClient {
  private readonly baseUrl: string
  private readonly fetcher: typeof fetch
  private unauthorizedHandler: (() => void) | null = null

  constructor(options: ApiClientOptions = {}) {
    this.baseUrl = options.baseUrl ?? ''
    this.fetcher = options.fetcher ?? globalThis.fetch.bind(globalThis)
  }

  setUnauthorizedHandler(handler: (() => void) | null): void {
    this.unauthorizedHandler = handler
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
    if (options.sessionToken) headers.set('Authorization', `Bearer ${options.sessionToken}`)
    else if (options.actorId) headers.set('X-Actor-Id', options.actorId)
    if (options.accessPurpose) headers.set('X-Access-Purpose', options.accessPurpose)
    if (options.idempotencyKey) headers.set('Idempotency-Key', options.idempotencyKey)

    // 默认超时兜底：本地 API 或 dev 代理偶发丢失响应时，请求不能永远挂起，
    // 否则界面会停在"正在保存"且用户无法恢复。写请求携带幂等键，超时后重试安全。
    const timeoutMs = options.timeoutMs ?? DEFAULT_REQUEST_TIMEOUT_MS
    const timeoutSignal = AbortSignal.timeout(timeoutMs)
    const signal = options.signal
      ? AbortSignal.any([options.signal, timeoutSignal])
      : timeoutSignal

    let response: Response
    try {
      response = await this.fetcher(`${this.baseUrl}${path}`, {
        ...init,
        headers,
        signal,
      })
    } catch (cause) {
      if (options.signal?.aborted) throw cause
      throw new ApiClientError(
        timeoutSignal.aborted
          ? `API request timed out after ${timeoutMs}ms`
          : 'API service is unavailable',
        {
          status: 0,
          code: 'DEPENDENCY_UNAVAILABLE',
        },
      )
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
      if (response.status === 401) this.unauthorizedHandler?.()
      throw parseErrorBody(body, response.status, requestId)
    }
    return body as T
  }

  registerAccount(actorId: string, password: string): Promise<{ status: string; actor_id: string }> {
    return this.request('/api/v1/auth/register', {
      method: 'POST',
      body: JSON.stringify({ actor_id: actorId, password }),
    })
  }

  login(actorId: string, password: string): Promise<AuthSession> {
    return this.request('/api/v1/auth/login', {
      method: 'POST',
      body: JSON.stringify({ actor_id: actorId, password }),
    })
  }

  logout(sessionToken: string): Promise<{ status: string }> {
    return this.request('/api/v1/auth/logout', {
      method: 'POST',
      body: JSON.stringify({ session_token: sessionToken }),
    })
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

  submitVisionEvidence(
    taskId: string,
    input: SubmitVisionEvidenceInput,
    options?: RequestOptions,
  ): Promise<EvidencePipelineResult> {
    return this.request(
      `/api/v1/vision-tasks/${encodeURIComponent(taskId)}/evidence`,
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

  getRelationshipGraph(
    householdId: string,
    memberId: string,
    options?: RequestOptions,
  ): Promise<RelationshipGraph> {
    return this.request(
      `/api/v1/households/${householdId}/members/${memberId}/relationship-graph`,
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

  getPlanWorkbench(
    householdId: string,
    memberId: string,
    options?: RequestOptions,
  ): Promise<PlanWorkbenchResponse> {
    return this.request(
      `/api/v1/households/${householdId}/members/${memberId}/plan-workbench`,
      undefined,
      options,
    )
  }

  getDashboardSummary(householdId: string, options?: RequestOptions): Promise<DashboardSummary> {
    return this.request(`/api/v1/households/${householdId}/dashboard-summary`, undefined, options)
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

  runMemberRules(
    householdId: string,
    memberId: string,
    options?: RequestOptions,
  ): Promise<RiskAlert[]> {
    return this.request(
      `/api/v1/households/${householdId}/rules/run?member_id=${encodeURIComponent(memberId)}`,
      { method: 'POST' },
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

  acknowledgeRisk(
    householdId: string,
    memberId: string,
    ruleId: string,
    input: { rule_version: string; risk_fingerprint: string },
    options?: RequestOptions,
  ): Promise<RiskAcknowledgement> {
    return this.request(
      `/api/v1/households/${householdId}/members/${memberId}/risks/${encodeURIComponent(ruleId)}/acknowledge`,
      { method: 'POST', body: JSON.stringify(input) },
      options,
    )
  }

  getVisionTask(taskId: string, options?: RequestOptions): Promise<VisionTask> {
    return this.request(
      `/api/v1/vision-tasks/${encodeURIComponent(taskId)}`,
      undefined,
      options,
    )
  }

  /** 携带开发身份头下载文件字节（<img> 无法带请求头，需转 blob URL）。 */
  async fetchFileBlob(storageKey: string, options: RequestOptions = {}): Promise<Blob> {
    const headers = new Headers()
    if (options.sessionToken) headers.set('Authorization', `Bearer ${options.sessionToken}`)
    else if (options.actorId) headers.set('X-Actor-Id', options.actorId)
    if (options.accessPurpose) headers.set('X-Access-Purpose', options.accessPurpose)
    let response: Response
    try {
      response = await this.fetcher(
        `${this.baseUrl}/api/v1/files/${encodeURIComponent(storageKey)}`,
        { headers, signal: options.signal },
      )
    } catch {
      throw new ApiClientError('API service is unavailable', {
        status: 0,
        code: 'DEPENDENCY_UNAVAILABLE',
      })
    }
    if (!response.ok) {
      throw new ApiClientError(`file download failed with status ${response.status}`, {
        status: response.status,
        code: fallbackErrorCode(response.status),
      })
    }
    return response.blob()
  }

  cancelVisionTask(taskId: string, options?: RequestOptions): Promise<VisionTask> {
    return this.request(
      `/api/v1/vision-tasks/${encodeURIComponent(taskId)}/cancel`,
      { method: 'POST' },
      options,
    )
  }

  retryVisionTask(taskId: string, options?: RequestOptions): Promise<VisionTask> {
    return this.request(
      `/api/v1/vision-tasks/${encodeURIComponent(taskId)}/retry`,
      { method: 'POST' },
      options,
    )
  }

  listReviewTasks(
    householdId: string,
    memberId: string,
    options?: RequestOptions,
  ): Promise<ReviewTask[]> {
    return this.request(
      `/api/v1/households/${householdId}/members/${memberId}/review-tasks`,
      undefined,
      options,
    )
  }

  confirmReviewTask(
    householdId: string,
    taskId: string,
    input: ConfirmReviewInput,
    options?: RequestOptions,
  ): Promise<ReviewTask> {
    return this.request(
      `/api/v1/households/${householdId}/review-tasks/${encodeURIComponent(taskId)}/confirm`,
      { method: 'POST', body: JSON.stringify(input) },
      options,
    )
  }

  correctReviewTask(
    householdId: string,
    taskId: string,
    input: CorrectReviewInput,
    options?: RequestOptions,
  ): Promise<ReviewTask> {
    return this.request(
      `/api/v1/households/${householdId}/review-tasks/${encodeURIComponent(taskId)}/correct`,
      { method: 'POST', body: JSON.stringify(input) },
      options,
    )
  }

  skipReviewTask(
    householdId: string,
    taskId: string,
    input: SkipReviewInput,
    options?: RequestOptions,
  ): Promise<ReviewTask> {
    return this.request(
      `/api/v1/households/${householdId}/review-tasks/${encodeURIComponent(taskId)}/skip`,
      { method: 'POST', body: JSON.stringify(input) },
      options,
    )
  }

  getWeatherActionCards(
    cityCode?: string,
    districtCode?: string,
    options?: RequestOptions,
  ): Promise<WeatherResponse> {
    const params = new URLSearchParams()
    if (cityCode) params.set('city_code', cityCode)
    if (districtCode) params.set('district_code', districtCode)
    const query = params.toString()
    return this.request(
      `/api/v1/weather/action-cards${query ? `?${query}` : ''}`,
      undefined,
      options,
    )
  }

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
    // 本地 4bit 大模型单次生成约 25~90 秒，远超默认 15 秒超时。
    return this.request(
      `/api/v1/assistant/chat${query ? `?${query}` : ''}`,
      { method: 'POST', body: JSON.stringify(input) },
      { timeoutMs: 240_000, ...options },
    )
  }

  listAssistantTools(options?: RequestOptions): Promise<{ tools: AssistantTool[]; count: number }> {
    return this.request('/api/v1/assistant/tools', undefined, options)
  }

  listKnowledgeDocuments(options?: RequestOptions): Promise<KnowledgeDocument[]> {
    return this.request('/api/v1/knowledge/documents', undefined, options)
  }

  createKnowledgeDocument(
    input: CreateKnowledgeDocumentInput,
    options?: RequestOptions,
  ): Promise<KnowledgeDocument> {
    return this.request(
      '/api/v1/knowledge/documents',
      { method: 'POST', body: JSON.stringify(input) },
      options,
    )
  }

  deleteKnowledgeDocument(
    docId: string,
    options?: RequestOptions,
  ): Promise<{ status: string; document_id: string }> {
    return this.request(
      `/api/v1/knowledge/documents/${encodeURIComponent(docId)}`,
      { method: 'DELETE' },
      options,
    )
  }

  retrieveKnowledge(
    query: string,
    topK: number,
    householdId?: string,
    memberId?: string,
    options?: RequestOptions,
  ): Promise<KnowledgeRetrieveResponse> {
    return this.request(
      '/api/v1/knowledge/retrieve',
      {
        method: 'POST',
        body: JSON.stringify({
          query,
          top_k: topK,
          household_id: householdId,
          member_id: memberId,
        }),
      },
      options,
    )
  }

  createKnowledgeSnapshot(
    version: string,
    options?: RequestOptions,
  ): Promise<KnowledgeIndexSnapshot> {
    return this.request(
      `/api/v1/knowledge/index/snapshot?version=${encodeURIComponent(version)}`,
      { method: 'POST' },
      options,
    )
  }

  listModelBindings(options?: RequestOptions): Promise<ModelVersionBinding[]> {
    return this.request('/api/v1/model-version-bindings', undefined, options)
  }

  createModelBinding(
    input: CreateModelVersionBindingInput,
    options?: RequestOptions,
  ): Promise<ModelVersionBinding> {
    return this.request(
      '/api/v1/model-version-bindings',
      { method: 'POST', body: JSON.stringify(input) },
      options,
    )
  }

  activateModelBinding(
    bindingId: string,
    approvedBy: string,
    options?: RequestOptions,
  ): Promise<ModelVersionBinding> {
    return this.request(
      `/api/v1/model-version-bindings/${encodeURIComponent(bindingId)}/activate`,
      { method: 'POST', body: JSON.stringify({ approved_by: approvedBy }) },
      options,
    )
  }

  rollbackModelBinding(
    bindingId: string,
    reason: string,
    options?: RequestOptions,
  ): Promise<ModelVersionBinding> {
    return this.request(
      `/api/v1/model-version-bindings/${encodeURIComponent(bindingId)}/rollback`,
      { method: 'POST', body: JSON.stringify({ reason }) },
      options,
    )
  }

  getModelBindingComparison(
    bindingId: string,
    options?: RequestOptions,
  ): Promise<ModelBindingComparison> {
    return this.request(
      `/api/v1/model-version-bindings/${encodeURIComponent(bindingId)}/comparison`,
      undefined,
      options,
    )
  }

  getActiveModelVersion(options?: RequestOptions): Promise<ActiveModelVersion> {
    return this.request('/api/v1/meta/active-model-version', undefined, options)
  }

  listHardSamples(
    householdId: string,
    options?: RequestOptions,
  ): Promise<HardSample[]> {
    return this.request(
      `/api/v1/households/${householdId}/hard-samples`,
      undefined,
      options,
    )
  }

  createHardSample(
    householdId: string,
    input: CreateHardSampleInput,
    options?: RequestOptions,
  ): Promise<HardSample> {
    return this.request(
      `/api/v1/households/${householdId}/hard-samples`,
      { method: 'POST', body: JSON.stringify(input) },
      options,
    )
  }

  updateHardSample(
    householdId: string,
    sampleId: string,
    status: string,
    note?: string,
    options?: RequestOptions,
  ): Promise<HardSample> {
    return this.request(
      `/api/v1/households/${householdId}/hard-samples/${encodeURIComponent(sampleId)}`,
      { method: 'PATCH', body: JSON.stringify({ status, note }) },
      options,
    )
  }

  getTrainingConsent(
    householdId: string,
    sampleId: string,
    options?: RequestOptions,
  ): Promise<TrainingConsent | null> {
    return this.request(
      `/api/v1/households/${householdId}/hard-samples/${encodeURIComponent(sampleId)}/training-consent`,
      undefined,
      options,
    )
  }

  grantTrainingConsent(
    householdId: string,
    sampleId: string,
    license: string,
    options?: RequestOptions,
  ): Promise<TrainingConsent> {
    return this.request(
      `/api/v1/households/${householdId}/hard-samples/${encodeURIComponent(sampleId)}/training-consent`,
      { method: 'POST', body: JSON.stringify({ scope: {}, license }) },
      options,
    )
  }

  revokeTrainingConsent(
    householdId: string,
    sampleId: string,
    reason: string,
    options?: RequestOptions,
  ): Promise<TrainingConsent> {
    return this.request(
      `/api/v1/households/${householdId}/hard-samples/${encodeURIComponent(sampleId)}/training-consent/revoke`,
      { method: 'POST', body: JSON.stringify({ reason }) },
      options,
    )
  }

  listCorrectionDiffs(
    householdId: string,
    memberId?: string,
    options?: RequestOptions,
  ): Promise<CorrectionDiff[]> {
    const query = memberId ? `?member_id=${encodeURIComponent(memberId)}` : ''
    return this.request(
      `/api/v1/households/${householdId}/correction-diffs${query}`,
      undefined,
      options,
    )
  }
}

export const apiClient = new ApiClient()
