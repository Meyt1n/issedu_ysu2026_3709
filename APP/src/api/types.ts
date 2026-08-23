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
  metrics: Record<string, VisionQualityMetric>
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
