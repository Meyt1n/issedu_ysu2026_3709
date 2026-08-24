/** 移动端领域模型：命名与主仓库（issedu_ysu2026_3709）API 契约和需求文档保持一致。 */

export type TaskLevel = 'INFO' | 'GENERAL' | 'HIGH' | 'URGENT'
export type TaskStatus = 'PENDING' | 'CONFIRMED' | 'DEFERRED' | 'SKIPPED' | 'ESCALATED'
export type RiskLevel = 'SEVERE' | 'WARNING' | 'INFO' | 'TIP' | (string & {})
export type RecognitionStatus = 'MATCHED' | 'CONFLICT' | 'UNKNOWN' | 'REVIEW'

export interface CareTask {
  id: string
  memberId: string
  memberName: string
  title: string
  detail: string
  level: TaskLevel
  dueAt: string
  status: TaskStatus
  /** 联机模式对应主仓库计划事件 ID，用于 confirm/defer/skip API */
  planEventId?: string
  /** Server-authorized reminder metadata. UI-only dueAt must never be scheduled without this evidence. */
  reminder?: ReminderPolicy
  lastActionAt?: string
  skipReason?: string
}

export type TaskAction = 'confirm' | 'defer' | 'skip'

export interface TaskActionPayload {
  deferHours?: number
  reason?: string
}

export interface VisibleScope {
  fields: string[]
  purpose: string
  validUntil: string
}

export interface MemberSummary {
  id: string
  name: string
  relation: string
  role: 'SELF' | 'DEPENDENT' | 'CAREGIVER' | (string & {})
  avatarText: string
  /** 'FULL' 表示本人或家庭管理员完整视角；否则展示被授权的字段范围 */
  visibleScope: VisibleScope | 'FULL'
  pendingTaskCount: number
  severeRiskCount: number
  warningRiskCount: number
}

export interface TimelineItem {
  id: string
  eventType: string
  title: string
  confirmationStatus: 'CONFIRMED' | 'UNCONFIRMED' | (string & {})
  occurredAt: string
  source: string
}

export interface MedicationItem {
  name: string
  spec: string
  schedule: string
  stockDaysLeft: number | null
  expiryDate: string | null
  expired: boolean
  confirmed: boolean
}

/** MOB-136：授权状态只按服务端时间字段推导，不由 APP 猜测。 */
export type AuthorizationStatus = 'PENDING' | 'ACTIVE' | 'EXPIRING' | 'EXPIRED' | 'REVOKED'

export interface AuthorizationView {
  id: string
  memberId: string
  /** 服务端只返回身份标识（actor id）；移动端不做姓名映射猜测。 */
  granteeActorId: string
  granteeName: string
  fields: string[]
  actions: string[]
  purpose: string
  validFrom: string
  validUntil: string
  revokedAt: string | null
  version: number
  status: AuthorizationStatus
}

export interface MemberDetail {
  summary: MemberSummary
  medications: MedicationItem[] | 'UNAUTHORIZED'
  timeline: TimelineItem[] | 'UNAUTHORIZED'
  /** 'UNAUTHORIZED'：当前身份无权查看授权管理（隐藏式拒绝），不等于"暂无授权"。 */
  authorizations: AuthorizationView[] | 'UNAUTHORIZED'
}

export interface RiskSourceEvent {
  id: string
  eventType: string
  confirmationStatus: string
  createdAt: string | null
}

export interface RiskCard {
  ruleId: string
  ruleVersion: string
  level: RiskLevel
  message: string
  memberId: string
  memberName: string
  createdAt: string | null
  sourceCount: number
  /** 为什么出现这条提醒：来自确定性规则的解释，不是模型生成的医疗判断 */
  explanation: string
  /** 非医疗处置建议：只指向确认、补录、联系家人/专业人员 */
  suggestion: string
  acknowledged: boolean
  sourceEvents: RiskSourceEvent[]
}

export interface QualityMetricView {
  label: string
  value: string
  passed: boolean
}

export interface QualityCheckResult {
  decision: 'PASS' | 'RETAKE'
  reasons: string[]
  retakePrompts: string[]
  metrics: QualityMetricView[]
  qualityReceipt: string | null
  /** MOB-149：视频质量门的帧级摘要（选中/可用帧数）；图片为空。 */
  framesSummary?: {
    mediaType: 'video'
    selectedFrames: number
    usableFrames: number
    sampledFrames: number
  }
}

export interface EvidenceFieldView {
  label: string
  value: string
  source: 'OCR' | '条码' | '主数据' | '包装特征'
  confidence: number
}

export interface RecognitionCandidate {
  status: RecognitionStatus
  fields: EvidenceFieldView[]
  conflicts: string[]
  versions: Record<string, string>
  /** 永远为 true：任何候选都必须人工确认（主仓库 FR-03 硬约束） */
  requiresHumanConfirmation: true
  notice: string
  handoff?: ReviewHandoff
}

export interface ReviewHandoff {
  taskId: string
  taskStatus: string
  source: 'DEMO' | 'FAMILY_SERVER'
  nextStep: string
}

/** 服务端视觉任务状态（HCT-204 契约）；未知状态原样保留，不猜测为成功。 */
export type VisionTaskServerStatus =
  | 'queued'
  | 'running'
  | 'succeeded'
  | 'failed'
  | 'cancelled'
  | 'timeout'
  | (string & {})

/** 移动端视角的任务状态快照：只做展示映射，不承载健康数据。 */
export interface VisionTaskStatusSnapshot {
  taskId: string
  status: VisionTaskServerStatus
  terminal: boolean
  errorCode: string | null
  errorMessage: string | null
  modelVersion: string | null
  createdAt: string
  nextStep: string
}

export type EnvironmentActionAvailability = 'AVAILABLE' | 'UNAVAILABLE' | 'UNAUTHORIZED'

/**
 * MOB-135：任务操作历史的回执状态。
 * - RECEIPTED：服务端已落库的事件回执（历史事实）；
 * - SUPERSEDED：服务端幂等保留的更早动作，已被同一计划的后续动作覆盖；
 * - LOCAL_PENDING / LOCAL_FAILED：仅存在于内存展示层的本地尝试，
 *   未获服务端回执前一律不当作成功，切换会话/成员即丢弃。
 */
export type TaskActionReceipt = 'RECEIPTED' | 'SUPERSEDED' | 'LOCAL_PENDING' | 'LOCAL_FAILED'

export interface TaskActionHistoryEntry {
  /** 服务端事件 ID（回执标识）；本地条目使用临时标记。 */
  eventId: string
  action: TaskAction | 'unknown'
  actionLabel: string
  taskTitle: string
  memberName: string
  memberId: string
  /** 服务端记录的时间（occurred_at），本地条目为本机提交时间。 */
  serverTime: string
  /** 该计划当前最终状态（CONFIRMED/DEFERRED/SKIPPED/PENDING…）。 */
  finalStatus: string
  receipt: TaskActionReceipt
  /** 覆盖/失败等补充说明。 */
  note?: string
}

/** A server-produced, display-only low-risk environment arrangement. */
export interface EnvironmentActionCard {
  id: string
  action: string
  source: string
  generatedAt: string
  validUntil: string
  ruleVersion: string
  configVersion: string
  deduplicationKey: string
}

export interface ReminderPolicy {
  authorization: 'AUTHORIZED'
  planVersion: string
  deduplicationKey: string
  firstReminderAt: string
  repeatReminderAt?: string
  maxReminders: 1 | 2
}

/** Fail-closed result for the optional environment-action dependency. */
export interface EnvironmentActionState {
  availability: EnvironmentActionAvailability
  reason: string
  card: EnvironmentActionCard | null
}

export interface TodaySnapshot {
  memberId: string
  tasks: CareTask[]
  risks: RiskCard[]
  recentEvents: TimelineItem[]
  environmentAction: EnvironmentActionState
}

/** 近 7 天任务完成趋势中的一天。 */
export interface TrendPoint {
  /** 显示标签，如“一/二/…/今” */
  label: string
  done: number
  total: number
}

export interface ProviderInfo {
  mode: 'demo' | 'live'
  label: string
  detail: string
}

/** 数据提供方接口：演示数据与家庭服务器联机共用同一契约。 */
export interface HouseholdOption {
  id: string
  /** 服务端授权范围内的家庭名称；仅用于展示，不参与权限判定。 */
  name: string
}

export interface DataProvider {
  info(): ProviderInfo
  /** 当前身份被服务端授权访问的家庭；用于显式选择，不代表任何额外权限。 */
  listHouseholds(): Promise<HouseholdOption[]>
  listMembers(): Promise<MemberSummary[]>
  getMemberDetail(memberId: string): Promise<MemberDetail>
  getTodaySnapshot(memberId: string): Promise<TodaySnapshot>
  listRisks(memberId?: string): Promise<RiskCard[]>
  getRiskDetail(memberId: string, ruleId: string): Promise<RiskCard>
  acknowledgeRisk(memberId: string, ruleId: string): Promise<RiskCard>
  submitTaskAction(taskId: string, action: TaskAction, payload?: TaskActionPayload): Promise<CareTask>
  checkImageQuality(file: File): Promise<QualityCheckResult>
  /** MOB-149：短视频质量门（帧级摘要）；仅在服务端声明 vision-task-video 时可用。 */
  checkVideoQuality(file: File): Promise<QualityCheckResult>
  recognizeMedicine(file: File, memberId: string, mediaKind?: 'image' | 'video'): Promise<RecognitionCandidate>
  /** 回查视觉任务状态；只读，重试必须复用同一 taskId，不得重新创建任务。 */
  fetchVisionTaskStatus(taskId: string): Promise<VisionTaskStatusSnapshot>
  /** 任务操作历史：服务端时间线动作事件的只读脱敏摘要，不建立第二份事实库。 */
  listTaskActionHistory(memberId: string): Promise<TaskActionHistoryEntry[]>
  /** 近 7 天任务完成趋势（含今天，共 7 项，时间升序）。 */
  getWeeklyTrend(memberId: string): Promise<TrendPoint[]>
}
