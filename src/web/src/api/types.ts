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
  /** 单次请求超时（毫秒）。超时视为本地 API 不可用，写请求可凭幂等键安全重试。 */
  timeoutMs?: number
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

export interface ReviewCandidate {
  drug_name?: string
  confidence?: number | null
  evidence?: string[]
  dosage?: string | null
  frequency?: string | null
  [key: string]: unknown
}

export interface ReviewTask {
  id: string
  vision_task_id: string
  household_id: string
  member_id: string
  status: string
  fusion_status: string | null
  candidates: ReviewCandidate[]
  selected_candidate: Record<string, unknown> | null
  manual_payload: Record<string, unknown> | null
  model_version: string | null
  rule_version: string | null
  version: number
  confirmed_by: string | null
  confirmed_at: string | null
  created_at: string
  updated_at: string
}

export interface ConfirmReviewInput {
  expected_version: number
  selected_index?: number | null
  confirmation_note?: string | null
}

export interface CorrectReviewInput {
  expected_version: number
  manual_payload: Record<string, unknown>
  correction_note?: string | null
}

export interface SkipReviewInput {
  expected_version: number
  reason: string
}

export interface WeatherActionCard {
  rule_id?: string
  level: string
  message: string
}

export interface WeatherResponse {
  status: string
  cache_status?: string
  location_scope?: 'city' | 'district' | null
  ruleset_version?: string
  source_observed_at?: string | null
  fetched_at?: string | null
  disclaimer?: string
  degraded_reason?: string
  temperature?: number | null
  humidity?: number | null
  condition?: string | null
  wind?: string | null
  aqi?: number | null
  action_cards: WeatherActionCard[]
  reason?: string
}

export interface AssistantChatInput {
  messages: Array<{ role: 'user' | 'assistant' | 'system'; content: string }>
  model?: string
  temperature?: number
  max_tokens?: number
}

export interface AssistantCitation {
  document_id: string
  version: string
  chunk_id: string
}

export interface AssistantResponse {
  answer: string
  sources: string[]
  citations?: AssistantCitation[]
  confidence: string
  escalate: boolean
  degraded: boolean
  degrade_reason: string | null
  model?: string | null
  route?: string | null
}

export interface AssistantTool {
  name: string
  description?: string
  parameters?: Record<string, unknown>
  [key: string]: unknown
}

export interface KnowledgeDocument {
  id: string
  title: string
  source: string
  license: string
  version: string
  content_hash: string
  permission_scope: Record<string, unknown>
  status: string
  effective_from: string | null
  effective_until: string | null
  created_by: string
  created_at: string
}

export interface CreateKnowledgeDocumentInput {
  title: string
  content: string
  source: string
  license?: string
  version?: string
  permission_scope?: Record<string, unknown>
  effective_from?: string
  effective_until?: string
}

export interface KnowledgeRetrieveResult {
  chunk_id?: string
  document_id?: string
  document_title?: string
  text?: string
  score?: number
  locator?: string | null
  [key: string]: unknown
}

export interface KnowledgeRetrieveResponse {
  query: string
  results: KnowledgeRetrieveResult[]
  total: number
  query_id: string | null
  degraded: boolean
  degrade_reason: string | null
}

export interface KnowledgeIndexSnapshot {
  index_id: string
  version: string
  document_count: number
  chunk_count: number
  checksum: string
}

export interface ModelVersionBinding {
  id: string
  model_id: string
  dataset_version: string
  export_manifest_id: string | null
  fixed_set_hash: string
  release_status: string
  safety_thresholds: Record<string, unknown>
  comparison_report_hash: string | null
  approved_by: string | null
  approved_at: string | null
  revoked_by: string | null
  revoked_at: string | null
  created_by: string
  created_at: string
  updated_at: string
}

export interface CreateModelVersionBindingInput {
  model_id: string
  dataset_version: string
  export_manifest_id?: string
  fixed_set_hash: string
  safety_thresholds?: Record<string, unknown>
  comparison_report_hash?: string
}

export interface ModelBindingComparison {
  binding_id: string
  comparison_report_hash: string | null
  model_id: string
  dataset_version: string
  fixed_set_hash: string
  safety_thresholds: Record<string, unknown>
}

export interface ActiveModelVersion {
  active_model_version: string
  source: 'binding' | 'config'
}

export interface HardSample {
  id: string
  source_event_id: string
  household_id: string
  member_id: string
  category: string
  status: string
  note: string | null
  reviewed_by: string | null
  reviewed_at: string | null
  deleted_by: string | null
  deleted_at: string | null
  created_by: string
  created_at: string
  updated_at: string
}

export interface CreateHardSampleInput {
  source_event_id: string
  member_id: string
  category: string
  note?: string
}

export interface TrainingConsent {
  id: string
  hard_sample_id: string
  household_id: string
  member_id: string
  granted_by: string
  status: string
  scope: Record<string, unknown>
  license: string
  revoked_by: string | null
  revoked_at: string | null
  version: number
  created_at: string
}

export interface CorrectionDiff {
  id: string
  source_event_id: string
  household_id: string
  member_id: string
  field_path: string
  before_value: unknown
  after_value: unknown
  reason: string
  evidence: Record<string, unknown>
  operator_actor_id: string
  version: number
  created_at: string
}
