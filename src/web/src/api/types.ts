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
  sequence_no: number
  event_type: string
  source: 'MANUAL' | string
  confirmation_status: 'CONFIRMED' | string
  payload: Record<string, unknown>
  evidence: Record<string, unknown>
  created_by: string
  confirmed_by: string | null
  idempotency_key: string | null
  compensates_event_id: string | null
  occurred_at: string
  recorded_at: string
  correlation_id: string
  causation_id: string | null
  supersedes_event_id: string | null
  schema_version: number
  created_at: string
}

export interface CreateHealthEventInput {
  member_id: string
  event_type: string
  source?: 'MANUAL'
  confirmation_status?: 'CONFIRMED' | 'UNCONFIRMED'
  payload: Record<string, unknown>
  evidence?: Record<string, unknown>
  idempotency_key?: string
  compensates_event_id?: string
  occurred_at?: string
}

export interface CompensateHealthEventInput {
  event_type: string
  payload: Record<string, unknown>
  evidence?: Record<string, unknown>
  reason: string
  occurred_at?: string
}

export interface MemberState {
  member_id: string
  household_id: string
  state: Record<string, unknown>
  last_event_id: string | null
  last_sequence: number
  version: number
  state_hash: string | null
  updated_at: string
}

export interface ProjectionCheckpoint {
  id: string
  member_id: string
  household_id: string
  last_sequence: number
  last_event_id: string | null
  state_hash: string
  created_by: string
  created_at: string
}

export interface ProjectionReplayResult {
  member_id: string
  checkpoint_id: string | null
  events_replayed: number
  previous_state_hash: string | null
  rebuilt_state_hash: string
  consistent_with_online: boolean
  last_sequence: number
  projection_version: number
}

export interface OutboxMessage {
  id: string
  event_id: string
  topic: string
  status: 'PENDING' | 'PROCESSING' | 'FAILED' | 'DISPATCHED'
  attempts: number
  available_at: string
  locked_at: string | null
  dispatched_at: string | null
  last_error: string | null
  created_at: string
  updated_at: string
}

export interface OutboxDispatchResult {
  inspected: number
  dispatched: number
  failed: number
  out_of_order: number
  recovered_stale: number
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
  source: {
    source_id: string
    sha256: string
    digest_scope: string
  }
  metrics: Record<string, VisionQualityMetric>
  thresholds: Record<string, number | string>
  reasons: string[]
  retake_prompts: string[]
  correction: Record<string, unknown> | null
  frames: Array<Record<string, unknown>>
  limitations: string[]
  quality_receipt: string | null
}

export interface UploadedFile {
  original_name: string
  storage_key: string
  size_bytes: number
  hash_algo: 'sha256' | string
  hash: string
  extension: string
}

export interface CreateVisionTaskInput {
  file_id: string
  member_id: string
  task_type?: string
  idempotency_key?: string
  quality_receipt: string
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
  result: EvidencePipelineResult | null
  model_version: string | null
  model_threshold: number | null
  schema_version: string | null
  code_version: string | null
  data_version: string | null
  preprocess_version: string | null
  input_digest: string | null
  created_by: string
  created_at: string
}

export type EvidenceFieldName =
  | 'drug_name'
  | 'specification'
  | 'manufacturer'
  | 'batch_number'
  | 'expiry_date'
  | 'product_barcode'
  | 'packaging_type'

export interface EvidenceRegion {
  x: number
  y: number
  width: number
  height: number
  coordinate_space: 'pixel' | 'normalized'
}

export interface OcrTokenInput {
  id: string
  channel?: 'ocr'
  raw_value: string
  region?: EvidenceRegion | null
  confidence: number
  engine_version: string
  language?: string
}

export interface BarcodeCandidateInput {
  id: string
  channel?: 'barcode'
  raw_value: string
  region?: EvidenceRegion | null
  confidence: number
  format?: 'EAN-8' | 'EAN-13' | 'UPC-A' | 'ITF-14' | 'QR' | 'DATA_MATRIX' | 'UNKNOWN'
  decoder_version: string
  checksum_valid?: boolean | null
  decode_valid?: boolean
}

export interface PackageRegionProposalInput {
  id: string
  channel?: 'yolo'
  label: string
  region: EvidenceRegion
  confidence: number
  model_version: string
}

export interface FieldProposalInput {
  field_name: EvidenceFieldName
  raw_value: string
  evidence_ids: string[]
  confidence: number
  parser_version: string
  source?: 'rule' | 'llm' | 'manual'
}

export interface SubmitVisionEvidenceInput {
  ocr_tokens?: OcrTokenInput[]
  barcodes?: BarcodeCandidateInput[]
  package_regions?: PackageRegionProposalInput[]
  field_proposals?: FieldProposalInput[]
  vision_model_version?: string
  ocr_engine_version?: string
  barcode_decoder_version?: string
  master_data_version?: string
  code_version?: string
  adapter_id: string
  adapter_version: string
  adapter_run_id: string
  adapter_receipt: string
}

export interface NormalizedEvidence {
  id: string
  channel: 'ocr' | 'barcode' | 'yolo'
  original_value: string
  normalized_value: string
  region: EvidenceRegion | null
  confidence: number
  producer_version: string
}

export interface BarcodeEvidenceResult {
  evidence_id: string
  original_value: string
  normalized_value: string
  format: string
  validation_status: 'VALID' | 'INVALID_FORMAT' | 'INVALID_CHECKSUM'
  checksum_valid: boolean | null
  confidence: number
  decoder_version: string
}

export interface FieldEvidence {
  field_name: EvidenceFieldName
  original_value: string
  normalized_value: string
  evidence_ids: string[]
  confidence: number
  parser_version: string
  model_version: string
  source: 'rule' | 'llm' | 'manual'
  confirmation_status: 'UNCONFIRMED'
}

export interface EvidenceFinding {
  code: string
  severity: 'INFO' | 'REVIEW' | 'CONFLICT'
  channel: 'ocr' | 'barcode' | 'yolo' | 'field' | 'master' | 'pipeline'
  detail: string
}

export interface EvidencePipelineResult {
  schema_version: string
  source_sha256: string | null
  source_digest_scope: 'uploaded_file_bytes'
  evidence: NormalizedEvidence[]
  barcodes: BarcodeEvidenceResult[]
  fields: FieldEvidence[]
  master_candidates: Array<{ record_id: string; reasons: Array<'BARCODE_EXACT' | 'NAME_EXACT'> }>
  missing_fields: EvidenceFieldName[]
  findings: EvidenceFinding[]
  fusion_readiness: 'READY_FOR_FUSION' | 'REVIEW' | 'UNKNOWN' | 'CONFLICT'
  requires_human_confirmation: true
  versions: Record<string, string>
}
