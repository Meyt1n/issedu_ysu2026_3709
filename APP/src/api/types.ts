import type { AuthSession } from './auth'

/** 与主仓库 src/web/src/api/types.ts 对齐的服务端契约子集。 */

export type ApiErrorCode = string

export interface ApiErrorEnvelope {
  error?: {
    code?: ApiErrorCode
    message?: string
    details?: unknown
    request_id?: string
  }
  detail?: string
  request_id?: string
}

export interface HealthResponse {
  status: 'ok'
  service: string
  version: string
}

export interface CapabilityResponse {
  phase: string
  available: string[]
  unavailable: string[]
}

export interface Household {
  id: string
  name: string
  created_by: string
  created_at: string
  /** IANA household timezone supplied by the server for business-day reporting. */
  time_zone?: string
}

export interface Member {
  id: string
  household_id: string
  display_name: string
  role: 'SELF' | 'DEPENDENT' | 'CAREGIVER'
  actor_id: string | null
  created_at: string
}

export interface HealthEvent {
  id: string
  household_id: string
  member_id: string
  sequence_no: number
  event_type: string
  source: string
  confirmation_status: string
  payload: Record<string, unknown>
  evidence: Record<string, unknown>
  created_by: string
  occurred_at: string
  recorded_at: string
  created_at: string
}

export interface RiskAlert {
  rule_id: string
  level: string
  message: string
  source_event_ids: string[]
  created_at: string | null
}

export interface RiskListResponse {
  member_id: string
  alerts: RiskAlert[]
  total: number
  severe_count: number
  warning_count: number
}

export interface RiskSourceEventRead {
  id: string
  event_type: string
  confirmation_status: string
  created_at: string | null
}

export interface RiskDetailResponse {
  alert: RiskAlert
  source_events: RiskSourceEventRead[]
}

export interface VisionQualityMetric {
  value: number
  passed: boolean
  unit: string
  threshold: Record<string, number>
}

export interface VisionQualityResponse {
  schema_version: string
  config_version: string
  media_type: 'image' | 'video'
  decision: 'PASS' | 'RETAKE'
  allow_downstream: boolean
  /** 图片响应为逐项指标；视频响应为帧数统计等纯数字（MOB-149）。 */
  metrics: Record<string, VisionQualityMetric | number>
  reasons: string[]
  retake_prompts: string[]
  quality_receipt: string | null
}

export interface UploadedFile {
  original_name: string
  storage_key: string
  size_bytes: number
  hash_algo: string
  hash: string
  extension: string
}

export interface VisionTask {
  id: string
  household_id: string
  member_id: string | null
  file_id: string
  /** HCT-414-D1：任务绑定媒体类型；旧服务端可能缺省，视为 image。 */
  media_type?: 'image' | 'video'
  task_type: string
  status: string
  error_code: string | null
  error_message: string | null
  result: unknown
  model_version: string | null
  created_by: string
  created_at: string
}

/** HCT-102 授权对象（GET /households/{id}/authorizations，仅 Owner）。 */
export interface AuthorizationRead {
  id: string
  household_id: string
  member_id: string
  grantor_actor_id: string
  grantee_actor_id: string
  data_fields: string[]
  actions: string[]
  purpose: string
  valid_from: string
  valid_until: string
  revoked_at: string | null
  version: number
  created_at: string
  updated_at: string
}

export interface RequestOptions {
  actorId?: string
  accessPurpose?: string
  /** 单次请求覆盖值；正式会话只在内存中传入，不能写入 localStorage。 */
  authSession?: AuthSession | null
  idempotencyKey?: string
  signal?: AbortSignal
  /** 请求超时毫秒数；0 表示不启用内部超时。默认 15s（MOB-144 区分超时与不可达）。 */
  timeoutMs?: number
}

/** 本地助手聊天请求（与主仓库 AssistantChatInput 对齐的最小子集）。 */
export interface AssistantChatInput {
  messages: Array<{ role: 'user' | 'assistant' | 'system'; content: string }>
  model?: string
  temperature?: number
  max_tokens?: number
  agent_mode?: 'single' | 'multi_agent'
  allow_network_search?: boolean
}

export interface AssistantCitation {
  document_id: string
  version: string
  chunk_id: string
  document_title?: string | null
  text?: string | null
  locator?: string | null
}

export interface AssistantAgentTrace {
  agent_id: string
  role: string
  status: string
  local: boolean
  network_used: boolean
  duration_ms?: number
  summary?: string
  source_count?: number
}

export interface AssistantExternalSource {
  title: string
  url: string
  snippet?: string
  domain?: string
  source?: string
}

export interface AssistantResponse {
  answer: string
  sources: string[]
  citations?: AssistantCitation[]
  suggested_questions?: string[]
  confidence: string
  escalate: boolean
  degraded: boolean
  degrade_reason: string | null
  model?: string | null
  route?: string | null
  query_type?: string | null
  risk_notice?: string | null
  orchestration_mode?: 'single' | 'multi_agent' | null
  orchestration_id?: string | null
  all_agents_local?: boolean
  network_used?: boolean
  network_query?: string | null
  agent_trace?: AssistantAgentTrace[]
  external_sources?: AssistantExternalSource[]
}
