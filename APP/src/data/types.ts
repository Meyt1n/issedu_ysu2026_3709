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

export interface AuthorizationView {
  granteeName: string
  fields: string[]
  purpose: string
  validUntil: string
}

export interface MemberDetail {
  summary: MemberSummary
  medications: MedicationItem[] | 'UNAUTHORIZED'
  timeline: TimelineItem[] | 'UNAUTHORIZED'
  authorizations: AuthorizationView[]
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
}

export interface TodaySnapshot {
  memberId: string
  tasks: CareTask[]
  risks: RiskCard[]
  recentEvents: TimelineItem[]
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
export interface DataProvider {
  info(): ProviderInfo
  listMembers(): Promise<MemberSummary[]>
  getMemberDetail(memberId: string): Promise<MemberDetail>
  getTodaySnapshot(memberId: string): Promise<TodaySnapshot>
  listRisks(memberId?: string): Promise<RiskCard[]>
  getRiskDetail(memberId: string, ruleId: string): Promise<RiskCard>
  acknowledgeRisk(memberId: string, ruleId: string): Promise<RiskCard>
  submitTaskAction(taskId: string, action: TaskAction, payload?: TaskActionPayload): Promise<CareTask>
  checkImageQuality(file: File): Promise<QualityCheckResult>
  recognizeMedicine(file: File, memberId: string): Promise<RecognitionCandidate>
  /** 近 7 天任务完成趋势（含今天，共 7 项，时间升序）。 */
  getWeeklyTrend(memberId: string): Promise<TrendPoint[]>
}
