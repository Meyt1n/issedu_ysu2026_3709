import type {
  AccessAudit,
  ActiveModelVersion,
  AuthSession,
  ApiErrorCode,
  ApiErrorEnvelope,
  AssistantChatInput,
  AssistantAgentCatalog,
  AssistantAgentTrace,
  AssistantExternalSource,
  AssistantFileExtractionResponse,
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
  MemberAccountBindingInput,
  CreateModelVersionBindingInput,
  HardSample,
  HealthEvent,
  HealthNewsResponse,
  HealthResponse,
  CapabilityResponse,
  DashboardSummary,
  DigitalTwinMemory,
  DigitalTwinMemoryActionResponse,
  DigitalTwinResponse,
  Household,
  KnowledgeDocument,
  KnowledgeDocumentDetail,
  KnowledgeIndexSnapshot,
  KnowledgeRetrieveResponse,
  KnowledgeStagingDetail,
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
  EvidencePreview,
  FaceCredential,
  FaceChallenge,
  TrainingConsent,
  UpdateAuthorizationInput,
  UploadedFile,
  VisionQualityResponse,
  CreateVisionTaskInput,
  SubmitVisionEvidenceInput,
  VisionTask,
  VisionLlmAssistResponse,
  WeatherResponse,
  WebSearchOpsSnapshot,
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

/**
 * 演示补种一次会追加 20+ 条演示事件；慢盘 MySQL/远程隧道下可能超过默认超时。
 * 种子使用固定幂等键，超时后重试不会产生重复数据，因此单独放宽这次写请求。
 */
export const DEMO_SEED_TIMEOUT_MS = 30_000

/**
 * 人脸注册/登录（multipart 三帧）的专用超时：本地 YuNet+SFace 推理通常只要
 * 1~3 秒，但首次使用时服务端可能要从 OpenCV Zoo 下载约 37MB 的 SFace 权重，
 * 慢网络下远超默认 15 秒——之前直接被中止并误报「本地 API 不可用」（HCT-424）。
 * 只放宽人脸这几条调用，不放宽全局默认值；仍然有界，挂死请求可恢复。
 */
export const FACE_REQUEST_TIMEOUT_MS = 120_000

/**
 * 识别「网关层不可用」：请求根本没有到达本地 API，而是被中间代理挡回。
 * - Vite dev 代理在 API 未启动（ECONNREFUSED）时返回 500 且响应体为空；
 * - Compose 的 Nginx 在 api 容器不可达时返回 502/504（HTML 错误页）。
 * 真实后端错误（FastAPI HTTPException/崩溃）都带响应体，且业务错误是 JSON
 * 信封，因此不会被误判。这样页面才能把「API 未启动」与业务失败分开提示。
 */
function isGatewayUnavailable(status: number, rawBody: string): boolean {
  if (status === 502 || status === 504) return true
  return (status === 500 || status === 503) && rawBody.trim() === ''
}

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
      // 超时（API 可能只是慢或正在重启）与连接失败（API 未启动 / 端口不对）
      // 必须区分：超时说明服务端可能仍在处理（例如人脸首次推理，HCT-424），
      // 不能把一切失败都说成「API 不可用/没有改变任何数据」。
      if (timeoutSignal.aborted) {
        throw new ApiClientError(`API request timed out after ${timeoutMs}ms`, {
          status: 0,
          code: 'REQUEST_TIMEOUT',
        })
      }
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

    if (!response.ok) {
      if (response.status === 401 && !options.suppressUnauthorizedHandler) {
        this.unauthorizedHandler?.()
      }
      if (isGatewayUnavailable(response.status, text)) {
        throw new ApiClientError('API service is unavailable behind the local proxy', {
          status: response.status,
          code: 'DEPENDENCY_UNAVAILABLE',
          requestId,
        })
      }
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

  changePassword(
    currentPassword: string,
    newPassword: string,
    options?: RequestOptions,
  ): Promise<AuthSession> {
    return this.request('/api/v1/auth/change-password', {
      method: 'POST',
      body: JSON.stringify({
        current_password: currentPassword,
        new_password: newPassword,
      }),
    }, options)
  }

  recoverPassword(
    actorId: string,
    householdId: string,
    pin: string,
    newPassword: string,
  ): Promise<AuthSession> {
    return this.request('/api/v1/auth/recover-password', {
      method: 'POST',
      body: JSON.stringify({
        actor_id: actorId,
        household_id: householdId,
        pin,
        new_password: newPassword,
      }),
    })
  }

  loginWithPin(
    householdId: string,
    actorId: string,
    pin: string,
    options?: RequestOptions,
  ): Promise<AuthSession> {
    return this.request('/api/v1/auth/pin-login', {
      method: 'POST',
      body: JSON.stringify({ household_id: householdId, actor_id: actorId, pin }),
    }, options)
  }

  createFaceChallenge(householdId: string, actorId: string): Promise<FaceChallenge> {
    return this.request('/api/v1/auth/face-challenge', {
      method: 'POST',
      body: JSON.stringify({ household_id: householdId, actor_id: actorId }),
    })
  }

  createFamilyFaceChallenge(householdId: string): Promise<FaceChallenge> {
    return this.request('/api/v1/auth/family-face-challenge', {
      method: 'POST',
      body: JSON.stringify({ household_id: householdId }),
    })
  }

  loginWithFace(
    householdId: string,
    actorId: string,
    challengeId: string,
    frames: File[],
  ): Promise<AuthSession> {
    const body = new FormData()
    body.append('household_id', householdId)
    body.append('actor_id', actorId)
    body.append('challenge_id', challengeId)
    for (const frame of frames) body.append('frames', frame, frame.name)
    return this.request(
      '/api/v1/auth/face-login',
      { method: 'POST', body },
      { timeoutMs: FACE_REQUEST_TIMEOUT_MS },
    )
  }

  loginWithFamilyFace(
    householdId: string,
    challengeId: string,
    frames: File[],
  ): Promise<AuthSession> {
    const body = new FormData()
    body.append('household_id', householdId)
    body.append('challenge_id', challengeId)
    for (const frame of frames) body.append('frames', frame, frame.name)
    return this.request(
      '/api/v1/auth/family-face-login',
      { method: 'POST', body },
      { timeoutMs: FACE_REQUEST_TIMEOUT_MS },
    )
  }

  setPin(
    householdId: string,
    pin: string,
    options?: RequestOptions,
    targetActorId?: string,
  ): Promise<{ status: string; household_id: string }> {
    return this.request('/api/v1/auth/pin', {
      method: 'POST',
      body: JSON.stringify({
        household_id: householdId,
        pin,
        ...(targetActorId ? { actor_id: targetActorId } : {}),
      }),
    }, options)
  }

  listPinStatus(
    householdId: string,
    options?: RequestOptions,
  ): Promise<{ household_id: string; configured_actor_ids: string[] }> {
    return this.request(
      `/api/v1/households/${encodeURIComponent(householdId)}/pin-status`,
      undefined,
      options,
    )
  }

  logout(sessionToken: string): Promise<{ status: string }> {
    return this.request('/api/v1/auth/logout', {
      method: 'POST',
      body: JSON.stringify({ session_token: sessionToken }),
    })
  }

  introspectSession(sessionToken: string): Promise<{
    actor_id: string
    household_id: string | null
    issued_at: number
    expires_at: number
  }> {
    return this.request('/api/v1/auth/session', {
      method: 'POST',
      headers: { Authorization: `Bearer ${sessionToken}` },
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

  extractAssistantFile(
    file: File,
    options?: RequestOptions,
  ): Promise<AssistantFileExtractionResponse> {
    const body = new FormData()
    body.append('file', file)
    return this.request('/api/v1/assistant/files/extract', { method: 'POST', body }, options)
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

  assistVisionTask(
    taskId: string,
    options?: RequestOptions,
  ): Promise<VisionLlmAssistResponse> {
    return this.request(
      `/api/v1/vision-tasks/${encodeURIComponent(taskId)}/llm-assist`,
      { method: 'POST' },
      { timeoutMs: 120_000, ...options },
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

  bindMemberAccount(
    householdId: string,
    memberId: string,
    input: MemberAccountBindingInput,
    options?: RequestOptions,
  ): Promise<Member> {
    return this.request(
      `/api/v1/households/${encodeURIComponent(householdId)}/members/${encodeURIComponent(memberId)}/account`,
      { method: 'PATCH', body: JSON.stringify(input) },
      options,
    )
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

  listFaceCredentials(householdId: string, options?: RequestOptions): Promise<FaceCredential[]> {
    return this.request(
      `/api/v1/households/${encodeURIComponent(householdId)}/face-credentials`,
      undefined,
      options,
    )
  }

  registerFaceCredential(
    householdId: string,
    frames: File | File[],
    input: {
      consent: boolean
      targetActorId?: string
      replaceExisting?: boolean
      confirmationMethod: 'pin' | 'password'
      confirmationCode?: string
      confirmationChallengeId?: string
    },
    options?: RequestOptions,
  ): Promise<FaceCredential> {
    const body = new FormData()
    if (Array.isArray(frames)) {
      for (const frame of frames) body.append('frames', frame)
    } else {
      // Backward-compatible payload for older local clients; new UI uses frames.
      body.append('file', frames)
    }
    body.append('consent', String(input.consent))
    if (input.targetActorId) body.append('target_actor_id', input.targetActorId)
    body.append('replace_existing', String(input.replaceExisting ?? false))
    body.append('confirmation_method', input.confirmationMethod)
    if (input.confirmationCode) body.append('confirmation_code', input.confirmationCode)
    if (input.confirmationChallengeId) body.append('confirmation_challenge_id', input.confirmationChallengeId)
    return this.request(
      `/api/v1/households/${encodeURIComponent(householdId)}/face-credentials`,
      { method: 'POST', body },
      { ...options, timeoutMs: options?.timeoutMs ?? FACE_REQUEST_TIMEOUT_MS },
    )
  }

  deleteFaceCredential(householdId: string, credentialId: string, options?: RequestOptions): Promise<FaceCredential> {
    return this.request(
      `/api/v1/households/${encodeURIComponent(householdId)}/face-credentials/${encodeURIComponent(credentialId)}`,
      { method: 'DELETE' },
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

  getDigitalTwin(householdId: string, options?: RequestOptions): Promise<DigitalTwinResponse> {
    return this.request(
      `/api/v1/households/${encodeURIComponent(householdId)}/digital-twin`,
      undefined,
      options,
    )
  }

  listDigitalTwinMemories(
    householdId: string,
    memberId?: string,
    status?: string,
    options?: RequestOptions,
  ): Promise<DigitalTwinMemory[]> {
    const params = new URLSearchParams()
    if (memberId) params.set('member_id', memberId)
    if (status) params.set('status', status)
    const query = params.toString()
    return this.request(
      `/api/v1/households/${encodeURIComponent(householdId)}/digital-twin/memories${query ? `?${query}` : ''}`,
      undefined,
      options,
    )
  }

  confirmDigitalTwinMemory(
    householdId: string,
    memoryId: string,
    options?: RequestOptions,
  ): Promise<DigitalTwinMemoryActionResponse> {
    return this.request(
      `/api/v1/households/${encodeURIComponent(householdId)}/digital-twin/memories/${encodeURIComponent(memoryId)}/confirm`,
      { method: 'POST' },
      options,
    )
  }

  rejectDigitalTwinMemory(
    householdId: string,
    memoryId: string,
    options?: RequestOptions,
  ): Promise<DigitalTwinMemoryActionResponse> {
    return this.request(
      `/api/v1/households/${encodeURIComponent(householdId)}/digital-twin/memories/${encodeURIComponent(memoryId)}/reject`,
      { method: 'POST' },
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

  missCarePlan(
    householdId: string,
    memberId: string,
    planEventId: string,
    reason: string,
    options?: RequestOptions,
  ): Promise<HealthEvent> {
    return this.request(
      `/api/v1/households/${householdId}/members/${memberId}/plans/missed?plan_event_id=${encodeURIComponent(planEventId)}&reason=${encodeURIComponent(reason)}`,
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

  listMemberVisionTasks(
    householdId: string,
    memberId: string,
    options?: RequestOptions,
  ): Promise<VisionTask[]> {
    return this.request(
      `/api/v1/households/${encodeURIComponent(householdId)}/vision-tasks?member_id=${encodeURIComponent(memberId)}`,
      undefined,
      options,
    )
  }

  /** 携带认证请求头下载文件字节（<img> 无法带请求头，需转 blob URL）。 */
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

  getHealthNews(options?: RequestOptions): Promise<HealthNewsResponse> {
    return this.request('/api/v1/health-news', undefined, options)
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
    if (options.sessionToken) headers.set('Authorization', `Bearer ${options.sessionToken}`)
    else if (options.actorId) headers.set('X-Actor-Id', options.actorId)
    if (options.accessPurpose) headers.set('X-Access-Purpose', options.accessPurpose)

    const timeoutMs = options.timeoutMs ?? 240_000
    const timeoutSignal = AbortSignal.timeout(timeoutMs)
    const signal = options.signal
      ? AbortSignal.any([options.signal, timeoutSignal])
      : timeoutSignal

    const response = await this.fetcher(
      `${this.baseUrl}/api/v1/assistant/chat/stream${query ? `?${query}` : ''}`,
      { method: 'POST', headers, body: JSON.stringify(input), signal },
    )
    if (!response.ok) {
      const text = await response.text()
      let body: unknown = null
      try {
        body = JSON.parse(text)
      } catch {
        body = { detail: text }
      }
      throw parseErrorBody(body, response.status, response.headers.get('x-request-id'))
    }

    const reader = response.body?.getReader()
    if (!reader) {
      throw new ApiClientError('Streaming response unavailable', {
        status: 0,
        code: 'DEPENDENCY_UNAVAILABLE',
      })
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
            throw new ApiClientError('ASSISTANT_STREAM_CANCELLED', {
              status: 0,
              code: 'CANCELLED',
            })
          }
          throw new ApiClientError(String(payload.message ?? 'Stream failed'), {
            status: 0,
            code: 'DEPENDENCY_UNAVAILABLE',
          })
        }
      }
    }

    if (!finalResponse) {
      throw new ApiClientError('Assistant stream ended without a response', {
        status: 0,
        code: 'DEPENDENCY_UNAVAILABLE',
      })
    }
    return finalResponse
  }

  listAssistantTools(options?: RequestOptions): Promise<{ tools: AssistantTool[]; count: number }> {
    return this.request('/api/v1/assistant/tools', undefined, options)
  }

  listAssistantAgents(options?: RequestOptions): Promise<AssistantAgentCatalog> {
    return this.request('/api/v1/assistant/agents', undefined, options)
  }

  getAssistantWebSearchOps(options?: RequestOptions): Promise<WebSearchOpsSnapshot> {
    return this.request('/api/v1/assistant/web-search/ops', undefined, options)
  }

  clearAssistantSessionCache(
    assistantSessionId: string,
    options?: RequestOptions,
  ): Promise<{ assistant_session_id: string; cleared_entries: number }> {
    return this.request(
      '/api/v1/assistant/session-cache/clear',
      {
        method: 'POST',
        body: JSON.stringify({ assistant_session_id: assistantSessionId }),
      },
      options,
    )
  }

  listKnowledgeDocuments(options?: RequestOptions): Promise<KnowledgeDocument[]> {
    return this.request('/api/v1/knowledge/documents', undefined, options)
  }

  getKnowledgeDocument(docId: string, options?: RequestOptions): Promise<KnowledgeDocumentDetail> {
    return this.request(
      `/api/v1/knowledge/documents/${encodeURIComponent(docId)}`,
      undefined,
      options,
    )
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
    evidenceHash?: string,
    options?: RequestOptions,
  ): Promise<ModelVersionBinding> {
    return this.request(
      `/api/v1/model-version-bindings/${encodeURIComponent(bindingId)}/rollback`,
      {
        method: 'POST',
        body: JSON.stringify({ reason, ...(evidenceHash ? { evidence_hash: evidenceHash } : {}) }),
      },
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

  seedFormalDemoHealth(options?: RequestOptions): Promise<Record<string, unknown>> {
    return this.request(
      '/api/v1/demo/formal-health-seed',
      { method: 'POST' },
      { timeoutMs: DEMO_SEED_TIMEOUT_MS, ...options },
    )
  }

  listClassroomScenarios(
    options?: RequestOptions,
  ): Promise<{ scenarios: Array<Record<string, unknown>>; disclaimer?: string }> {
    return this.request('/api/v1/demo/classroom-scenarios', undefined, options)
  }

  listKnowledgeStaging(options?: RequestOptions): Promise<{
    items: Array<Record<string, unknown>>
    total: number
    auto_ingest: boolean
    disclaimer?: string
  }> {
    return this.request('/api/v1/knowledge/crawl/staging', undefined, options)
  }

  knowledgeCrawlStatus(options?: RequestOptions): Promise<Record<string, unknown>> {
    return this.request('/api/v1/knowledge/crawl/status', undefined, options)
  }

  runKnowledgeCrawl(
    options?: RequestOptions,
    params?: { dueOnly?: boolean },
  ): Promise<Record<string, unknown>> {
    const query = params?.dueOnly ? '?due_only=true' : ''
    return this.request(`/api/v1/knowledge/crawl/run${query}`, { method: 'POST' }, options)
  }

  reviewKnowledgeStaging(
    sourceId: string,
    input: { approve?: boolean; reject?: boolean; notes?: string },
    options?: RequestOptions,
  ): Promise<Record<string, unknown>> {
    const params = new URLSearchParams()
    if (input.approve) params.set('approve', 'true')
    if (input.reject) params.set('reject', 'true')
    if (input.notes) params.set('notes', input.notes)
    const query = params.toString()
    return this.request(
      `/api/v1/knowledge/crawl/staging/${encodeURIComponent(sourceId)}/review${query ? `?${query}` : ''}`,
      { method: 'POST' },
      options,
    )
  }

  promoteKnowledgeStaging(options?: RequestOptions): Promise<Record<string, unknown>> {
    return this.request('/api/v1/knowledge/crawl/promote', { method: 'POST' }, options)
  }

  getKnowledgeStagingDetail(
    sourceId: string,
    options?: RequestOptions,
  ): Promise<KnowledgeStagingDetail> {
    return this.request(
      `/api/v1/knowledge/crawl/staging/${encodeURIComponent(sourceId)}`,
      undefined,
      options,
    )
  }

  /** 教学演示：给本地夹具来源叠加模拟更新（不出网、不改仓库文件、永不自动入库）。 */
  simulateKnowledgeCrawlUpdate(
    options?: RequestOptions,
    params?: { reset?: boolean },
  ): Promise<Record<string, unknown>> {
    const query = params?.reset ? '?reset=true' : ''
    return this.request(
      `/api/v1/knowledge/crawl/simulate-update${query}`,
      { method: 'POST' },
      options,
    )
  }
}

export const apiClient = new ApiClient()
