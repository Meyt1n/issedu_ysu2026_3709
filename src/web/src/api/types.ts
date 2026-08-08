export type ApiErrorCode = string

export type MemberRole = 'SELF' | 'DEPENDENT' | 'CAREGIVER'

export type AuthorizationAction = 'READ_EVENTS' | 'WRITE_EVENTS'

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
}

export interface CreateHouseholdInput {
  name: string
}

export interface Member {
  id: string
  household_id: string
  display_name: string
  role: MemberRole
  actor_id: string | null
  created_at: string
}

export interface CreateMemberInput {
  display_name: string
  role?: MemberRole
  actor_id?: string | null
}

export interface Authorization {
  id: string
  household_id: string
  member_id: string
  grantor_actor_id: string
  grantee_actor_id: string
  data_fields: string[]
  actions: AuthorizationAction[]
  purpose: string
  valid_from: string
  valid_until: string
  revoked_at: string | null
  version: number
  created_at: string
  updated_at: string
}

export interface CreateAuthorizationInput {
  member_id: string
  grantee_actor_id: string
  data_fields: string[]
  actions: AuthorizationAction[]
  purpose: string
  valid_until: string
}

export interface UpdateAuthorizationInput {
  expected_version: number
  data_fields?: string[]
  actions?: AuthorizationAction[]
  purpose?: string
  valid_until?: string
}

export interface AccessAudit {
  id: string
  household_id: string
  authorization_id: string | null
  actor_id: string
  operation: string
  action: string
  data_field: string
  purpose: string | null
  outcome: string
  reason: string | null
  before_version: number | null
  after_version: number | null
  created_at: string
}

export interface HealthEvent {
  id: string
  household_id: string
  member_id: string
  event_type: string
  source: 'MANUAL' | string
  confirmation_status: 'CONFIRMED' | string
  payload: Record<string, unknown>
  evidence: Record<string, unknown>
  created_by: string
  confirmed_by: string
  created_at: string
}

export interface CreateHealthEventInput {
  member_id: string
  event_type: string
  source?: 'MANUAL'
  confirmation_status?: 'CONFIRMED'
  payload: Record<string, unknown>
  evidence?: Record<string, unknown>
}

export interface MemberState {
  member_id: string
  household_id: string
  state: Record<string, unknown>
  last_event_id: string | null
  updated_at: string
}

export type RiskLevel = 'SEVERE' | 'WARNING' | 'INFO' | 'TIP' | string

export interface RiskAlert {
  rule_id: string
  level: RiskLevel
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

export interface RiskSourceEvent {
  id: string
  event_type: string
  confirmation_status: string
  created_at: string | null
}

export interface RiskDetailResponse {
  alert: RiskAlert
  source_events: RiskSourceEvent[]
}

export interface RequestOptions {
  actorId?: string
  accessPurpose?: string
  idempotencyKey?: string
  signal?: AbortSignal
}
