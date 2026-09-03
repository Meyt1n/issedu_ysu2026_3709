import { ApiClient, ApiClientError } from '@/api/client'
import { CAPABILITY_IDS, hasCapability } from '@/stores/capabilities'
import type { AuthorizationRead, HealthEvent, HealthNewsResponse, Member, PlanWorkbenchResponse, RequestOptions, RiskAcknowledgement, RiskAlert, RiskListResponse, UploadedFile, VisionTask } from '@/api/types'
import type {
  CareTask,
  CaregiverEscalation,
  DataProvider,
  EnvironmentActionState,
  HouseholdOption,
  KnowledgeDocumentSummaryView,
  KnowledgeDocumentView,
  KnowledgeSearchResult,
  MemberDetail,
  MemberSummary,
  MedicationItem,
  ProviderInfo,
  QualityCheckResult,
  RecognitionCandidate,
  RiskCard,
  RiskAuditMetadata,
  RiskAcknowledgementView,
  RiskSummary,
  ReminderPolicy,
  RiskLevel,
  ServerTaskActionPolicy,
  TaskAction,
  TaskActionPayload,
  TaskLevel,
  TimelineItem,
  TodaySnapshot,
  TrendPoint,
  VisionTaskStatusSnapshot,
  TaskActionHistoryEntry,
  AuthorizationView,
} from './types'

/**
 * 联机模式适配器：调用主仓库（issedu_ysu2026_3709）FastAPI 的既有接口。
 *
 * 事件语义与后端 `app/projection.py`、`app/routes.py` 联调对齐（2026-08-13）：
 * - 计划事实：`plan_created` / `plan_updated`（payload: drug, schedule, 可选 due_time/level）；
 * - 计划动作：`plan_confirmed` / `plan_deferred` / `plan_skipped`（payload.plan_event_id 指向计划事件）；
 *   动作在服务端按计划幂等（confirm:<id>），因此任务状态取最后一条动作事件，不做“每日重置”；
 * - 时间线只返回已确认事件，按 sequence_no 升序；
 * - 用药事实：`medication_added`（payload.drug，可选 expiry_date/stock/ingredient）。
 */

interface SessionContext {
  actorId: string
  accessPurpose: string
  /** 用户已显式选择的家庭；空字符串表示尚未选择。 */
  householdId: string
}

interface VisionDraft {
  idempotencyKey: string
  task?: VisionTask
}

function createIdempotencyKey(): string {
  return globalThis.crypto?.randomUUID?.() ?? `mobile-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

const PLAN_FACT_TYPES = new Set(['plan_created', 'plan_updated'])
const PLAN_ACTION_TYPES = new Set(['plan_confirmed', 'plan_deferred', 'plan_skipped', 'plan_missed'])
const PLAN_ESCALATION_TYPES = new Set(['care_escalated', 'care_level_escalated'])
const CAREGIVER_NOTIFICATION_TYPE = 'caregiver_notified'
const TASK_LEVELS: TaskLevel[] = ['INFO', 'GENERAL', 'HIGH', 'URGENT']
const RISK_ORDER: Record<string, number> = { SEVERE: 0, WARNING: 1, INFO: 2, TIP: 3 }

/**
 * 服务端计划工作台的动作名 → 移动端动作名。
 * 顺序即按钮顺序；服务端未列出的动作在界面上保持禁用。
 */
const SERVER_ACTION_MAP_ENTRIES: ReadonlyArray<['CONFIRM' | 'DEFER' | 'SKIP' | 'MISS', TaskAction]> = [
  ['CONFIRM', 'confirm'],
  ['DEFER', 'defer'],
  ['SKIP', 'skip'],
  ['MISS', 'miss'],
]

/** 计划状态文案：直译服务端状态，不追加任何医疗判断。 */
const PLAN_STATUS_LABELS: Record<string, string> = {
  NORMAL: '正常，未到时间',
  REMINDER: '已到时间，仍在提醒窗口内',
  ESCALATED: '已超出提醒窗口',
  COMPLETED: '疗程已结束',
}

/** 知识检索降级原因：只翻译服务端给出的代码，不猜测“大概是没结果”。 */
export function knowledgeDegradeReason(code: string | null | undefined): string {
  switch (textOf(code)) {
    case 'EMPTY_QUERY':
      return '请输入要查找的内容。'
    case 'NO_AUTHORISED_DOCUMENTS':
      return '当前身份没有被授权的知识条目，服务端未返回任何内容。'
    case 'EMPTY_INDEX':
      return '家庭服务器的知识索引为空，请让管理员先在网页端导入并批准条目。'
    case 'NO_RELEVANT_RESULTS':
      return '没有匹配到相关条目，可换一个说法再试。'
    default:
      return '家庭服务器按降级返回，未提供可展示的检索结果。'
  }
}

/** HCT-305 lacks a member-scoped, audited action-card contract, so do not call it from mobile. */
export function environmentActionUnavailable(): EnvironmentActionState {
  if (!hasCapability(CAPABILITY_IDS.environmentActionCard)) {
    return { availability: 'UNAVAILABLE', reason: '环境行动服务当前未提供；应用不会使用旧天气或本地推断代替实时结果。', card: null }
  }
  return { availability: 'UNAVAILABLE', reason: '环境行动服务尚未提供成员授权、来源、有效期和版本证据；当前无法安全展示。', card: null }
}

function textOf(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function eventTitle(event: HealthEvent): string {
  const payload = event.payload ?? {}
  const drug = textOf(payload['drug'])
  const schedule = textOf(payload['schedule'])
  if (drug && schedule) return `${drug}：${schedule}`
  const direct =
    textOf(payload['title']) || textOf(payload['name']) || textOf(payload['summary']) || drug
  if (direct) return direct
  return event.event_type
}

function toTimelineItem(event: HealthEvent): TimelineItem {
  return {
    id: event.id,
    eventType: event.event_type,
    title: eventTitle(event),
    confirmationStatus: event.confirmation_status,
    occurredAt: event.occurred_at ?? event.created_at,
    source: event.source,
  }
}

function planDueAt(event: HealthEvent): string {
  const payload = event.payload ?? {}
  const dueTime = textOf(payload['due_time'])
  const match = /^(\d{1,2}):(\d{2})$/.exec(dueTime)
  const due = new Date()
  if (match) {
    due.setHours(Number(match[1]), Number(match[2]), 0, 0)
  } else {
    due.setHours(9, 0, 0, 0)
  }
  return due.toISOString()
}

function planLevel(event: HealthEvent): TaskLevel {
  const raw = textOf((event.payload ?? {})['level']).toUpperCase()
  return (TASK_LEVELS as string[]).includes(raw) ? (raw as TaskLevel) : 'GENERAL'
}

function recordOf(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : null
}

function serverEventOrder(event: HealthEvent, fallback: number): number {
  const sequence = Number(event.sequence_no)
  return Number.isFinite(sequence) ? sequence : fallback
}

function escalationStatus(value: unknown): CaregiverEscalation['status'] {
  switch (textOf(value).toUpperCase()) {
    case 'QUEUED':
    case 'SENT':
    case 'DELIVERED': return 'QUEUED'
    case 'VIEWED': return 'VIEWED'
    case 'PROCESSED': return 'PROCESSED'
    case 'FAILED': return 'FAILED'
    default: return 'UNKNOWN'
  }
}

function escalationReason(value: unknown): string {
  switch (textOf(value).toUpperCase()) {
    case 'MISSED_DOSE_ESCALATION': return '服务端记录了连续未确认任务，需要授权照护者关注。'
    case 'OVERDUE_AFTER_GRACE_PERIOD': return '服务端记录了超过安全时间窗仍未确认的任务。'
    default: return '服务端记录了未确认任务，需要关注。'
  }
}

const SAFE_ESCALATION_NEXT_STEP = '查看授权照护者的脱敏任务摘要；如情况严重，请联系家人或拨打 120。'

/**
 * 只解析时间线中由服务端产生的升级/通知事件。
 * 没有 care_escalated 事件时返回 undefined，绝不根据本地时间或任务状态猜测升级。
 */
function escalationForPlan(
  events: HealthEvent[],
  planEventId: string,
  latestAction: HealthEvent | null,
): CaregiverEscalation | undefined {
  const indexed = events.map((event, index) => ({ event, index }))
  const actionOrder = latestAction ? serverEventOrder(latestAction, events.indexOf(latestAction)) : Number.NEGATIVE_INFINITY
  const escalation = indexed
    .filter(({ event }) => PLAN_ESCALATION_TYPES.has(event.event_type))
    .filter(({ event }) => textOf((event.payload ?? {})['plan_event_id']) === planEventId)
    .filter(({ event, index }) => serverEventOrder(event, index) >= actionOrder)
    .sort((a, b) => serverEventOrder(a.event, a.index) - serverEventOrder(b.event, b.index))
    .at(-1)?.event
  if (!escalation) return undefined

  const payload = escalation.payload ?? {}
  const automationKey = textOf(payload['automation_key'])
  const notification = indexed
    .filter(({ event }) => event.event_type === CAREGIVER_NOTIFICATION_TYPE)
    .filter(({ event }) => textOf((event.payload ?? {})['plan_event_id']) === planEventId)
    .filter(({ event }) => !automationKey || textOf((event.payload ?? {})['escalation_automation_key']) === automationKey)
    .sort((a, b) => serverEventOrder(a.event, a.index) - serverEventOrder(b.event, b.index))
    .at(-1)?.event
  const notificationPayload = notification?.payload ?? {}
  const notifyCaregivers = payload['notify_caregivers'] === true
  // 计划载荷中的通知意图不是当前授权证明；只有通知事件回执存在时才展示授权照护者目标。
  const target = notification ? 'AUTHORIZED_CAREGIVER' : 'NONE'
  const status = notification
    ? escalationStatus(notificationPayload['delivery_status'])
    : notifyCaregivers ? 'CREATED' : 'UNAVAILABLE'
  const nextStep = textOf(notificationPayload['next_step']) || textOf(payload['next_step']) || (
    notification
      ? SAFE_ESCALATION_NEXT_STEP
      : notifyCaregivers
        ? '等待服务端通知回执；当前不显示照护者身份，也不尝试本地通知。'
        : '服务端未返回有效照护授权，未发送升级通知；请联系家人或拨打 120。'
  )

  return {
    status,
    target,
    reason: escalationReason(payload['reason']),
    occurredAt: escalation.occurred_at ?? escalation.created_at,
    dueAt: textOf(payload['due_at']) || null,
    nextStep,
    auditEventId: escalation.id,
    notificationEventId: notification?.id,
  }
}

/** Only a server-provided, member-authorized reminder contract may enter local scheduling. */
function planReminder(event: HealthEvent): ReminderPolicy | undefined {
  const reminder = recordOf((event.payload ?? {})['reminder'])
  if (!reminder || textOf(reminder['authorization']).toUpperCase() !== 'AUTHORIZED') return undefined
  const planVersion = textOf(reminder['plan_version'])
  const deduplicationKey = textOf(reminder['deduplication_key'])
  const firstReminderAt = textOf(reminder['first_reminder_at'])
  const repeatReminderAt = textOf(reminder['repeat_reminder_at']) || undefined
  const maxReminders = Number(reminder['max_reminders'])
  if (!planVersion || !deduplicationKey || !firstReminderAt || (maxReminders !== 1 && maxReminders !== 2)) return undefined
  if (maxReminders === 2 && !repeatReminderAt) return undefined
  return {
    authorization: 'AUTHORIZED', planVersion, deduplicationKey, firstReminderAt, repeatReminderAt,
    maxReminders: maxReminders as 1 | 2,
  }
}

/** 从时间线推导任务：计划事实 + 指向它的最后一条动作事件。 */
export function deriveTasksFromEvents(
  events: HealthEvent[],
  memberId: string,
  memberName: string,
): CareTask[] {
  const plans = events.filter(e => PLAN_FACT_TYPES.has(e.event_type))
  const actions = events.filter(e => PLAN_ACTION_TYPES.has(e.event_type))

  return plans.map(plan => {
    const related = actions.filter(a => textOf((a.payload ?? {})['plan_event_id']) === plan.id)
    const latest = related.length > 0 ? related[related.length - 1]! : null

    const task: CareTask = {
      id: `plan-${plan.id}`,
      memberId,
      memberName,
      title: eventTitle(plan),
      detail: '来自家庭服务器的计划事实；确认、延期、跳过会写回事件中心并可审计。',
      level: planLevel(plan),
      dueAt: planDueAt(plan),
      status: 'PENDING',
      planEventId: plan.id,
      reminder: planReminder(plan),
    }

    if (latest) {
      task.lastActionAt = latest.occurred_at ?? latest.created_at
      if (latest.event_type === 'plan_confirmed') {
        task.status = 'CONFIRMED'
      } else if (latest.event_type === 'plan_skipped') {
        task.status = 'SKIPPED'
        task.skipReason = textOf((latest.payload ?? {})['reason']) || undefined
      } else if (latest.event_type === 'plan_missed') {
        // 漏服只是一条已记录的事实：不推断补服、不改写计划、不修改提醒时间。
        task.status = 'MISSED'
        task.missReason = textOf((latest.payload ?? {})['reason']) || undefined
      } else {
        task.status = 'DEFERRED'
        const delay = Number((latest.payload ?? {})['delay_hours'] ?? 0)
        const base = new Date(task.lastActionAt).getTime()
        if (Number.isFinite(base) && delay > 0) {
          task.dueAt = new Date(base + delay * 3_600_000).toISOString()
        }
      }
    }
    const escalation = escalationForPlan(events, plan.id, latest)
    if (escalation) {
      task.escalation = escalation
      task.status = 'ESCALATED'
    }
    return task
  })
}

/**
 * 把服务端计划工作台条目翻译成任务卡的动作边界。
 *
 * 这是移动端唯一的动作来源：服务端没有返回该计划、返回空 `allowed_actions`
 * （疗程已结束）或字段缺失时一律返回 undefined，界面据此保持只读（fail-closed），
 * 绝不在客户端推断安全窗口。
 */
export function planActionPolicyFrom(
  workbench: PlanWorkbenchResponse | null | undefined,
  planEventId: string,
): ServerTaskActionPolicy | undefined {
  if (!workbench) return undefined
  const item = (workbench.plans ?? []).find(plan => plan.plan_event_id === planEventId)
  if (!item) return undefined
  const allowedActions = SERVER_ACTION_MAP_ENTRIES.filter(([serverAction]) =>
    (item.allowed_actions ?? []).includes(serverAction),
  ).map(([, action]) => action)
  if (allowedActions.length === 0) return undefined
  const nextActionAt = textOf(item.next_action_at)
  return {
    planVersion: textOf(workbench.generated_at) || '未提供快照时间',
    source: 'FAMILY_SERVER',
    allowedActions,
    nextAllowedAt: nextActionAt || null,
    windowLabel: `服务端计划状态：${PLAN_STATUS_LABELS[item.status] ?? item.status}`,
  }
}

/** 即将到期阈值：7 天内提示但不改变语义。 */
const EXPIRING_SOON_MS = 7 * 24 * 3_600_000

/** MOB-136：授权状态只由服务端时间/撤回字段推导；解析失败按已到期处理（fail-closed）。 */
export function authorizationStatus(
  auth: { valid_from: string; valid_until: string; revoked_at: string | null },
  now: Date = new Date(),
): AuthorizationView['status'] {
  if (auth.revoked_at) return 'REVOKED'
  const from = Date.parse(auth.valid_from)
  const until = Date.parse(auth.valid_until)
  const nowMs = now.getTime()
  if (Number.isFinite(from) && nowMs < from) return 'PENDING'
  if (!Number.isFinite(until) || nowMs > until) return 'EXPIRED'
  if (nowMs > until - EXPIRING_SOON_MS) return 'EXPIRING'
  return 'ACTIVE'
}

function authorizationViewFromRead(read: AuthorizationRead, now: Date = new Date()): AuthorizationView {
  return {
    id: read.id,
    memberId: read.member_id,
    granteeActorId: read.grantee_actor_id,
    // 服务端不返回姓名；原样展示身份标识，不做猜测映射。
    granteeName: read.grantee_actor_id,
    fields: [...read.data_fields],
    actions: [...read.actions],
    purpose: read.purpose,
    validFrom: read.valid_from,
    validUntil: read.valid_until,
    revokedAt: read.revoked_at,
    version: read.version,
    status: authorizationStatus(read, now),
  }
}

const PLAN_ACTION_LABELS: Record<string, { action: TaskAction; label: string; finalStatus: string }> = {
  plan_confirmed: { action: 'confirm', label: '确认', finalStatus: 'CONFIRMED' },
  plan_deferred: { action: 'defer', label: '延期', finalStatus: 'DEFERRED' },
  plan_skipped: { action: 'skip', label: '跳过', finalStatus: 'SKIPPED' },
}

const ESCALATION_HISTORY_LABELS: Record<string, { action: 'escalate' | 'caregiver_notify'; label: string; note: string }> = {
  care_escalated: { action: 'escalate', label: '升级照护者', note: '服务端升级审计事件' },
  care_level_escalated: { action: 'escalate', label: '升级照护者', note: '服务端升级审计事件' },
  caregiver_notified: { action: 'caregiver_notify', label: '通知授权照护者', note: '服务端通知回执事件' },
}

/**
 * MOB-135：从时间线事件推导任务操作历史。
 *
 * 只读脱敏摘要：动作、任务标题、成员、服务端时间、事件 ID、最终状态。
 * 同一 plan_event_id 的动作里只有最新一条是"有效回执"，更早的同类动作
 * 标注 SUPERSEDED（服务端幂等保留），不重复计数。
 */
export function deriveTaskActionHistory(
  events: HealthEvent[],
  memberId: string,
  memberName: string,
): TaskActionHistoryEntry[] {
  const planTitles = new Map<string, string>()
  for (const plan of events.filter(e => PLAN_FACT_TYPES.has(e.event_type))) {
    planTitles.set(plan.id, eventTitle(plan))
  }

  const grouped = new Map<string, HealthEvent[]>()
  for (const event of events) {
    const mapping = PLAN_ACTION_LABELS[event.event_type]
    if (!mapping) continue
    const planEventId = textOf((event.payload ?? {})['plan_event_id']) || event.id
    const bucket = grouped.get(planEventId) ?? []
    bucket.push(event)
    grouped.set(planEventId, bucket)
  }

  const entries: TaskActionHistoryEntry[] = []
  for (const [planEventId, bucket] of grouped) {
    // 时间线升序：最后一条是当前有效动作
    const sorted = [...bucket].sort((a, b) => eventTime(a) - eventTime(b))
    const latest = sorted[sorted.length - 1]!
    const latestMapping = PLAN_ACTION_LABELS[latest.event_type]!
    sorted.forEach((event, index) => {
      const mapping = PLAN_ACTION_LABELS[event.event_type]!
      const isLatest = index === sorted.length - 1
      entries.push({
        eventId: event.id,
        action: mapping.action,
        actionLabel: mapping.label,
        taskTitle: planTitles.get(planEventId) ?? '计划任务（标题未知）',
        memberName,
        memberId,
        serverTime: event.occurred_at ?? event.created_at,
        // 最终状态取该计划最新动作的结果，覆盖条目同样显示最新终态便于理解
        finalStatus: latestMapping.finalStatus,
        receipt: isLatest ? 'RECEIPTED' : 'SUPERSEDED',
        note: isLatest ? undefined : '该计划的后续操作已覆盖此动作（服务端幂等保留历史）',
      })
    })
  }

  for (const event of events) {
    const mapping = ESCALATION_HISTORY_LABELS[event.event_type]
    if (!mapping) continue
    const planEventId = textOf((event.payload ?? {})['plan_event_id'])
    if (!planEventId) continue
    entries.push({
      eventId: event.id,
      action: mapping.action,
      actionLabel: mapping.label,
      taskTitle: planTitles.get(planEventId) ?? '计划任务（标题未知）',
      memberName,
      memberId,
      serverTime: event.occurred_at ?? event.created_at,
      finalStatus: 'ESCALATED',
      receipt: 'RECEIPTED',
      note: mapping.note,
    })
  }

  return entries.sort((a, b) => {
    const aTime = parseHistoryTime(a.serverTime)
    const bTime = parseHistoryTime(b.serverTime)
    if (aTime === bTime) return a.eventId.localeCompare(b.eventId)
    if (!Number.isFinite(aTime)) return 1
    if (!Number.isFinite(bTime)) return -1
    return bTime - aTime
  })
}

const TREND_WEEKDAYS = ['日', '一', '二', '三', '四', '五', '六']

/**
 * 把服务端时间戳补成显式 UTC。
 *
 * 后端的 `occurred_at` / `created_at` 目前是不带时区标识的 naive 串
 * （例如 `2026-08-26T01:56:09.853583`）。`Date.parse` 会把这种带时间的 ISO 串
 * 按**浏览器本地时区**解释，于是同一条事件在 UTC+8 设备上会被提前 8 小时，
 * 落到前一个业务日 —— 这正好抵消了 MOB-143「按家庭时区分日、不用浏览器时区」
 * 的目的，而且不同国家的家人看到的趋势会互相矛盾。
 *
 * 服务端时间语义是 UTC，因此缺少时区标识时按 UTC 解释；已带 `Z` 或 `±HH:MM`
 * 偏移的串保持原样，后端补上标识后本函数无需再改。
 */
export function normalizeServerTimestamp(value: string): string {
  const trimmed = value.trim()
  if (!trimmed) return trimmed
  // 只有"日期+时间"才有本地时区歧义；纯日期串按 ISO 规范已按 UTC 处理。
  if (!trimmed.includes('T') && !trimmed.includes(' ')) return trimmed
  if (/(?:Z|[+-]\d{2}:?\d{2})$/i.test(trimmed)) return trimmed
  return `${trimmed}Z`
}

function eventTime(event: HealthEvent): number {
  return parseHistoryTime(event.occurred_at ?? event.created_at)
}

/** 无效时间不能改变历史语义；统一排到有效服务端时间之后。 */
function parseHistoryTime(value: string): number {
  const time = Date.parse(normalizeServerTimestamp(value))
  return Number.isFinite(time) ? time : Number.POSITIVE_INFINITY
}

function optionalText(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null
}

function optionalInteger(value: unknown): number | null {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0 ? value : null
}

function riskAuditMetadata(alert: RiskAlert): RiskAuditMetadata {
  const metadata: RiskAuditMetadata = {
    deduplicationKey: optionalText(alert.deduplication_key),
    mergedCount: optionalInteger(alert.merged_count),
    budgetStatus: optionalText(alert.budget_status),
    budgetReason: optionalText(alert.budget_reason),
    nextVisibleAt: optionalText(alert.next_visible_at),
    validUntil: optionalText(alert.valid_until),
    evidenceSummary: optionalText(alert.evidence_summary),
    complete: false,
  }
  metadata.complete = Object.entries(metadata)
    .filter(([key]) => key !== 'complete')
    .every(([, value]) => value !== null)
  return metadata
}

function riskSummary(response: RiskListResponse): RiskSummary {
  const summary = {
    rulesetVersion: optionalText(response.ruleset_version),
    nonSevereBudget: optionalInteger(response.non_severe_budget),
    suppressedCount: optionalInteger(response.suppressed_count),
    total: optionalInteger(response.total),
    severeCount: optionalInteger(response.severe_count),
    warningCount: optionalInteger(response.warning_count),
  }
  return { ...summary, complete: summary.rulesetVersion !== null && summary.nonSevereBudget !== null && summary.suppressedCount !== null }
}

function mergeRiskSummaries(summaries: RiskSummary[]): RiskSummary {
  const unique = <T>(values: Array<T | null>): T | null => {
    const present = values.filter((value): value is T => value !== null)
    return present.length === values.length && new Set(present).size === 1 ? present[0]! : null
  }
  const sum = (values: Array<number | null>): number | null => values.every(value => value !== null)
    ? values.reduce((total, value) => total + (value ?? 0), 0)
    : null
  const merged = {
    rulesetVersion: unique(summaries.map(item => item.rulesetVersion)),
    nonSevereBudget: unique(summaries.map(item => item.nonSevereBudget)),
    suppressedCount: sum(summaries.map(item => item.suppressedCount)),
    total: sum(summaries.map(item => item.total)),
    severeCount: sum(summaries.map(item => item.severeCount)),
    warningCount: sum(summaries.map(item => item.warningCount)),
  }
  return { ...merged, complete: summaries.length > 0 && summaries.every(item => item.complete) && merged.rulesetVersion !== null }
}

function riskAcknowledgement(alert: RiskAlert): RiskAcknowledgementView | null {
  const acknowledgement = alert.acknowledgement
  if (!acknowledgement) return null
  return {
    actorId: acknowledgement.actor_id,
    acknowledgedAt: acknowledgement.acknowledged_at,
    replayed: acknowledgement.replayed,
  }
}

function validRiskAcknowledgement(value: RiskAcknowledgement | null | undefined): value is RiskAcknowledgement {
  return Boolean(
    value
      && optionalText(value.receipt_id)
      && optionalText(value.household_id)
      && optionalText(value.member_id)
      && optionalText(value.rule_id)
      && optionalText(value.rule_version)
      && optionalText(value.risk_fingerprint)
      && optionalText(value.actor_id)
      && optionalText(value.acknowledged_at),
  )
}

function toRiskCard(
  alert: RiskAlert,
  memberId: string,
  memberName: string,
  sourceEvents: RiskCard['sourceEvents'] = [],
  explanation = '由家庭服务器确定性规则计算得出；移动端只展示服务端返回的脱敏审计信息。',
): RiskCard {
  const ruleVersion = optionalText(alert.rule_version)
  const acknowledgement = riskAcknowledgement(alert)
  return {
    ruleId: alert.rule_id,
    ruleVersion,
    level: alert.level as RiskLevel,
    message: alert.message,
    memberId,
    memberName,
    createdAt: alert.created_at,
    sourceCount: Array.isArray(alert.source_event_ids) ? alert.source_event_ids.length : 0,
    riskFingerprint: optionalText(alert.risk_fingerprint),
    acknowledgement,
    audit: riskAuditMetadata(alert),
    explanation,
    suggestion: '请查看依据后在授权范围内处理；如有医疗疑问请联系医生或药师。',
    acknowledged: Boolean(acknowledgement),
    sourceEvents,
  }
}

function stablePlanId(event: HealthEvent): string | null {
  const payload = event.payload ?? {}
  const linked = textOf(payload['plan_event_id']) || textOf(payload['plan_id'])
  if (event.event_type === 'plan_created') return linked || event.id
  return linked || null
}

function dateParts(time: number, timeZone: string): { day: string; weekday: number } | null {
  try {
    const parts = new Intl.DateTimeFormat('en-CA', {
      timeZone,
      year: 'numeric', month: '2-digit', day: '2-digit', weekday: 'short',
    }).formatToParts(new Date(time))
    const value = (kind: string) => parts.find(part => part.type === kind)?.value
    const weekday = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].indexOf(value('weekday') ?? '')
    const year = value('year'); const month = value('month'); const day = value('day')
    return year && month && day && weekday >= 0 ? { day: `${year}-${month}-${day}`, weekday } : null
  } catch { return null }
}

/**
 * Uses server timestamps and an explicit household IANA timezone. Updates must
 * reference a stable plan id; orphan updates are ignored rather than counted.
 * The total is plans active by local business-day end; done is the plan's final
 * action only, when that final action is a confirmation on that business day.
 */
export function deriveWeeklyTrendFromEvents(
  events: HealthEvent[],
  now: Date = new Date(),
  timeZone?: string,
): TrendPoint[] {
  if (!timeZone) return []
  const nowTime = now.getTime()
  const today = dateParts(nowTime, timeZone)
  if (!today) return []
  const dayFormatter = new Intl.DateTimeFormat('en-CA', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit' })
  const dayKey = (time: number) => {
    const p = dayFormatter.formatToParts(new Date(time)); const v = (type: string) => p.find(x => x.type === type)?.value
    return `${v('year')}-${v('month')}-${v('day')}`
  }
  // Calendar arithmetic is performed on YYYY-MM-DD keys, so a 23/25-hour DST
  // day cannot duplicate or omit a business date in the seven-day window.
  const addCalendarDays = (day: string, offset: number) => {
    const [year, month, date] = day.split('-').map(Number)
    return new Date(Date.UTC(year!, month! - 1, date! + offset)).toISOString().slice(0, 10)
  }
  const weekdayForDay = (day: string) => new Date(`${day}T12:00:00Z`).getUTCDay()
  const windowDays = Array.from({ length: 7 }, (_, index) => addCalendarDays(today.day, index - 6))
  const planFacts = new Map<string, HealthEvent>()
  const actions = new Map<string, HealthEvent>()
  for (const event of events) {
    const isPlanEvent = PLAN_FACT_TYPES.has(event.event_type) || PLAN_ACTION_TYPES.has(event.event_type)
    if (!isPlanEvent) continue
    const time = eventTime(event)
    if (!Number.isFinite(time)) return []
    const id = stablePlanId(event)
    if (!id) return []
    if (PLAN_FACT_TYPES.has(event.event_type)) {
      const prior = planFacts.get(id)
      // An update changes plan content, not the fact that the plan already existed.
      if (!prior || eventTime(prior) > time) planFacts.set(id, event)
    } else {
      const prior = actions.get(id)
      if (!prior || eventTime(prior) <= time) actions.set(id, event)
    }
  }
  return windowDays.map((day, index) => {
    const total = [...planFacts.values()].filter(plan => dayKey(eventTime(plan)) <= day).length
    const done = [...actions.entries()].filter(([id, action]) =>
      planFacts.has(id) && action.event_type === 'plan_confirmed' && dayKey(eventTime(action)) === day,
    ).length
    return { label: index === 6 ? '今' : TREND_WEEKDAYS[weekdayForDay(day)]!, total, done }
  })
}
function toMedication(event: HealthEvent): MedicationItem {
  const payload = event.payload ?? {}
  const expiry = textOf(payload['expiry_date'])
  const stock = Number(payload['stock'])
  const expiryTime = expiry ? Date.parse(expiry) : Number.NaN
  return {
    name: textOf(payload['drug']) || event.event_type,
    spec: textOf(payload['spec']),
    schedule: textOf(payload['schedule']),
    stockDaysLeft: Number.isFinite(stock) ? stock : null,
    expiryDate: expiry || null,
    expired: Number.isFinite(expiryTime) ? expiryTime < Date.now() : false,
    confirmed: event.confirmation_status === 'CONFIRMED',
  }
}

export class HttpDataProvider implements DataProvider {
  private readonly client: ApiClient
  private readonly context: () => SessionContext
  private householdId: string | null = null
  private householdTimeZone: string | null = null
  private memberCache = new Map<string, Member>()
  private taskCache = new Map<string, CareTask>()
  private cachedRiskSummary: RiskSummary | null = null
  /** 同一 File 的上传请求在当前运行时共享，避免重试或重复点击产生多个文件。 */
  private fileUploads = new WeakMap<File, Promise<UploadedFile>>()
  /** 视觉任务按 File + 成员保存幂等键；创建失败后重试仍复用同一上传和任务键。 */
  private visionDrafts = new WeakMap<File, Map<string, VisionDraft>>()

  constructor(client: ApiClient, context: () => SessionContext) {
    this.client = client
    this.context = context
  }

  private options(extra: Partial<RequestOptions> = {}): RequestOptions {
    const { actorId, accessPurpose } = this.context()
    return {
      actorId: actorId || undefined,
      accessPurpose: accessPurpose || undefined,
      ...extra,
    }
  }

  private uploadFileOnce(file: File): Promise<UploadedFile> {
    const existing = this.fileUploads.get(file)
    if (existing) return existing
    const upload = this.client.uploadFile(file, this.options())
    this.fileUploads.set(file, upload)
    upload.catch(() => {
      if (this.fileUploads.get(file) === upload) this.fileUploads.delete(file)
    })
    return upload
  }

  private visionDraft(file: File, memberId: string, mediaKind: 'image' | 'video' = 'image'): VisionDraft {
    let drafts = this.visionDrafts.get(file)
    if (!drafts) {
      drafts = new Map<string, VisionDraft>()
      this.visionDrafts.set(file, drafts)
    }
    const key = `${memberId}:${mediaKind}`
    let draft = drafts.get(key)
    if (!draft) {
      draft = { idempotencyKey: `vision-${mediaKind}:${createIdempotencyKey()}` }
      drafts.set(key, draft)
    }
    return draft
  }

  /**
   * 解析本轮请求使用的家庭。
   *
   * MOB-158：绝不再取 `listHouseholds()[0]` —— 列表顺序变化会让用户看错家庭。
   * 规则是：已选家庭必须仍在服务端返回的列表里；恰好一个家庭时自动选定以保持
   * 低步骤体验；可访问多个但未选择时 fail-closed，由界面要求显式选择。
   */
  private async resolveHouseholdId(): Promise<string> {
    if (this.householdId) return this.householdId
    const { actorId, accessPurpose, householdId } = this.context()
    if (!actorId.trim() || !accessPurpose.trim()) {
      throw new ApiClientError('联机模式需要身份和访问目的', {
        status: 401,
        code: 'SESSION_NOT_CONFIGURED',
      })
    }
    const households = await this.client.listHouseholds(this.options())
    if (households.length === 0) {
      throw new ApiClientError('当前身份没有可访问的家庭', {
        status: 404,
        code: 'NO_HOUSEHOLD',
      })
    }
    const choose = (household: (typeof households)[number]) => {
      this.householdId = household.id
      this.householdTimeZone = typeof household.time_zone === 'string' && household.time_zone.trim()
        ? household.time_zone.trim()
        : null
      return household.id
    }

    const selected = householdId.trim()
    if (selected) {
      const match = households.find(candidate => candidate.id === selected)
      if (!match) {
        // Revoked, removed, or outside current authorization: never fall back to another household.
        throw new ApiClientError('当前选择的家庭已不可用，请重新选择', {
          status: 404,
          code: 'HOUSEHOLD_UNAVAILABLE',
        })
      }
      return choose(match)
    }

    if (households.length === 1) return choose(households[0]!)

    throw new ApiClientError('当前身份可访问多个家庭，请先选择一个家庭', {
      status: 409,
      code: 'HOUSEHOLD_NOT_SELECTED',
    })
  }

  /** 服务端授权范围内的家庭列表；只暴露 ID 与名称，供界面显式选择。 */
  async listHouseholds(): Promise<HouseholdOption[]> {
    const households = await this.client.listHouseholds(this.options())
    return households.map(household => ({ id: household.id, name: household.name }))
  }

  async getHealthNews(): Promise<HealthNewsResponse> {
    return this.client.getHealthNews(this.options())
  }

  private async memberName(memberId: string): Promise<string> {
    const cached = this.memberCache.get(memberId)
    if (cached) return cached.display_name
    const householdId = await this.resolveHouseholdId()
    const members = await this.client.listMembers(householdId, this.options())
    this.memberCache = new Map(members.map(m => [m.id, m]))
    return this.memberCache.get(memberId)?.display_name ?? '成员'
  }

  info(): ProviderInfo {
    return {
      mode: 'live',
      label: '家庭服务器',
      detail: '连接主仓库 FastAPI；仅在授权范围内读取数据，健康数据不出家庭可信域。',
    }
  }

  async listMembers(): Promise<MemberSummary[]> {
    const householdId = await this.resolveHouseholdId()
    const members = await this.client.listMembers(householdId, this.options())
    this.memberCache = new Map(members.map(m => [m.id, m]))

    // 家庭 owner 可读授权列表；非 owner（照护者）返回 404，
    // 此时成员列表已被服务端过滤到授权范围，如实标注而不是显示“完整视角”。
    let isOwner = true
    try {
      await this.client.listAuthorizations(householdId, this.options())
    } catch {
      isOwner = false
    }
    const { accessPurpose } = this.context()

    const summaries: MemberSummary[] = []
    for (const member of members) {
      let severe = 0
      let warning = 0
      let pending = 0
      try {
        const risks = await this.client.listMemberRisks(householdId, member.id, this.options())
        severe = risks.severe_count
        warning = risks.warning_count
      } catch {
        // 无授权或规则暂不可用时不猜测，保持 0 并由详情页提示。
      }
      try {
        const timeline = await this.client.listMemberTimeline(householdId, member.id, this.options())
        pending = deriveTasksFromEvents(timeline, member.id, member.display_name).filter(
          t => t.status === 'PENDING' || t.status === 'DEFERRED',
        ).length
      } catch {
        pending = 0
      }
      summaries.push({
        id: member.id,
        name: member.display_name,
        relation: member.role === 'SELF' ? '本人' : '家庭成员',
        role: member.role,
        avatarText: member.display_name.slice(0, 1),
        visibleScope: isOwner
          ? 'FULL'
          : {
              fields: ['已确认健康事件（服务端已过滤）'],
              purpose: accessPurpose || 'family-care',
              validUntil: '',
            },
        pendingTaskCount: pending,
        severeRiskCount: severe,
        warningRiskCount: warning,
      })
    }
    return summaries
  }

  async getMemberDetail(memberId: string): Promise<MemberDetail> {
    const householdId = await this.resolveHouseholdId()
    const summaries = await this.listMembers()
    const summary = summaries.find(s => s.id === memberId)
    if (!summary) throw new Error('成员不存在或未获授权')

    let timeline: MemberDetail['timeline']
    let medications: MemberDetail['medications']
    try {
      const events = await this.client.listMemberTimeline(householdId, memberId, this.options())
      timeline = [...events].reverse().map(toTimelineItem)
      medications = events.filter(e => e.event_type === 'medication_added').map(toMedication)
    } catch {
      timeline = 'UNAUTHORIZED'
      medications = 'UNAUTHORIZED'
    }

    // MOB-136：授权列表只读展示。仅 Owner 可读；非 Owner 的 403/404 是
    // 隐藏式拒绝，映射为 'UNAUTHORIZED'（与"暂无授权"区分），其余异常如实抛出。
    let authorizations: MemberDetail['authorizations']
    try {
      const reads = await this.client.listAuthorizations(householdId, this.options())
      authorizations = reads
        .filter(read => read.member_id === memberId)
        .map(read => authorizationViewFromRead(read))
    } catch (cause) {
      if (cause instanceof ApiClientError && (cause.status === 403 || cause.status === 404)) {
        authorizations = 'UNAUTHORIZED'
      } else {
        throw cause
      }
    }

    return {
      summary,
      medications,
      timeline,
      authorizations,
    }
  }

  async getTodaySnapshot(memberId: string): Promise<TodaySnapshot> {
    const householdId = await this.resolveHouseholdId()
    const memberName = await this.memberName(memberId)
    const [events, risks, workbench] = await Promise.all([
      this.client.listMemberTimeline(householdId, memberId, this.options(), 'today-snapshot'),
      this.listRisks(memberId),
      // 动作边界是加分项而非前置条件：拿不到工作台时任务仍可展示，只是保持只读。
      this.client.getPlanWorkbench(householdId, memberId, this.options()).catch(() => null),
    ])

    const tasks = deriveTasksFromEvents(events, memberId, memberName)
    for (const task of tasks) {
      if (task.planEventId) {
        const policy = planActionPolicyFrom(workbench, task.planEventId)
        if (policy) task.actionPolicy = policy
      }
      this.taskCache.set(task.id, task)
    }

    return {
      memberId,
      tasks,
      risks,
      recentEvents: [...events].reverse().slice(0, 4).map(toTimelineItem),
      environmentAction: environmentActionUnavailable(),
    }
  }

  async listRisks(memberId?: string): Promise<RiskCard[]> {
    const householdId = await this.resolveHouseholdId()
    if (!memberId) {
      const members = await this.client.listMembers(householdId, this.options())
      if (members.length === 0) {
        throw new ApiClientError('当前家庭暂无可用成员', {
          status: 404,
          code: 'NO_MEMBERS',
        })
      }
      this.memberCache = new Map(members.map(m => [m.id, m]))
      const responses = await Promise.all(members.map(async member => {
        try {
          const response = await this.client.listMemberRisks(householdId, member.id, this.options())
          return { member, response }
        } catch {
          return null
        }
      }))
      const successful = responses.filter((item): item is { member: Member; response: RiskListResponse } => item !== null)
      this.cachedRiskSummary = mergeRiskSummaries(successful.map(item => riskSummary(item.response)))
      const all = successful.map(({ member, response }) => response.alerts.map(alert => (
        toRiskCard(alert, member.id, member.display_name)
      )))
      return all
        .flat()
        .sort((a, b) => (RISK_ORDER[a.level] ?? 9) - (RISK_ORDER[b.level] ?? 9))
    }
    const memberName = await this.memberName(memberId)
    const response = await this.client.listMemberRisks(householdId, memberId, this.options())
    this.cachedRiskSummary = riskSummary(response)
    return response.alerts
      .map(alert => toRiskCard(alert, memberId, memberName))
      .sort((a, b) => (RISK_ORDER[a.level] ?? 9) - (RISK_ORDER[b.level] ?? 9))
  }

  async getRiskSummary(): Promise<RiskSummary> {
    if (this.cachedRiskSummary) return { ...this.cachedRiskSummary }
    await this.listRisks()
    if (this.cachedRiskSummary) return this.cachedRiskSummary
    return {
      rulesetVersion: null,
      nonSevereBudget: null,
      suppressedCount: null,
      total: null,
      severeCount: null,
      warningCount: null,
      complete: false,
    }
  }

  async getRiskDetail(memberId: string, ruleId: string): Promise<RiskCard> {
    const householdId = await this.resolveHouseholdId()
    const memberName = await this.memberName(memberId)
    const detail = await this.client.getRiskDetail(householdId, memberId, ruleId, this.options())
    return toRiskCard(detail.alert, memberId, memberName, detail.source_events.map(e => ({
        id: e.id,
        eventType: e.event_type,
        confirmationStatus: e.confirmation_status,
        createdAt: e.created_at,
      })), '由家庭服务器确定性规则计算得出；以下为服务端返回的脱敏证据事件摘要。')
  }

  async acknowledgeRisk(memberId: string, ruleId: string, idempotencyKey?: string): Promise<RiskCard> {
    if (!hasCapability(CAPABILITY_IDS.riskAcknowledgement)) {
      throw new Error('家庭服务器未声明风险知晓回写能力；本页不会伪装写入成功。请先到“我的”重新测试连接。')
    }
    const householdId = await this.resolveHouseholdId()
    const memberName = await this.memberName(memberId)
    const detail = await this.client.getRiskDetail(householdId, memberId, ruleId, this.options())
    const ruleVersion = optionalText(detail.alert.rule_version)
    const riskFingerprint = optionalText(detail.alert.risk_fingerprint)
    if (!ruleVersion || !riskFingerprint) {
      throw new Error('家庭服务器未返回完整风险版本信息，无法安全回写“已知晓”状态。')
    }
    const acknowledgement = await this.client.acknowledgeRisk(
      householdId,
      memberId,
      ruleId,
      { rule_version: ruleVersion, risk_fingerprint: riskFingerprint },
      this.options({ idempotencyKey: idempotencyKey?.trim() || `risk-ack:${createIdempotencyKey()}` }),
    )
    if (!validRiskAcknowledgement(acknowledgement)) {
      throw new Error('家庭服务器回执不完整，未记录成功；请稍后重试。')
    }
    return toRiskCard(
      { ...detail.alert, acknowledgement },
      memberId,
      memberName,
      detail.source_events.map(event => ({
        id: event.id,
        eventType: event.event_type,
        confirmationStatus: event.confirmation_status,
        createdAt: event.created_at,
      })),
      '由家庭服务器确定性规则计算得出；移动端只展示服务端返回的脱敏证据事件摘要。',
    )
  }

  async submitTaskAction(
    taskId: string,
    action: TaskAction,
    payload: TaskActionPayload = {},
  ): Promise<CareTask> {
    const householdId = await this.resolveHouseholdId()
    const task = this.taskCache.get(taskId)
    if (!task?.planEventId) throw new Error('任务已过期，请刷新后重试')
    // 主仓库计划动作以 action + plan_event_id 作为幂等键；保持稳定才能让
    // 网络回执丢失后的重试返回原事件，而不是追加第二条健康事件。
    const options = this.options({ idempotencyKey: `${action}:${task.planEventId}` })

    if (action === 'confirm') {
      await this.client.confirmCarePlan(householdId, task.memberId, task.planEventId, options)
      task.status = 'CONFIRMED'
    } else if (action === 'defer') {
      const hours = payload.deferHours ?? 1
      await this.client.deferCarePlan(householdId, task.memberId, task.planEventId, hours, options)
      task.status = 'DEFERRED'
      task.dueAt = new Date(Date.now() + hours * 3_600_000).toISOString()
    } else if (action === 'miss') {
      const reason = payload.reason?.trim()
      if (!reason) throw new Error('记录漏服前请填写原因，便于家人了解情况')
      await this.client.missCarePlan(householdId, task.memberId, task.planEventId, reason, options)
      // 只落一条漏服事实：不改 dueAt、不自动补服、不修改剂量或计划。
      task.status = 'MISSED'
      task.missReason = reason
    } else {
      const reason = payload.reason?.trim()
      if (!reason) throw new Error('跳过前请填写原因，便于家人了解情况')
      await this.client.skipCarePlan(householdId, task.memberId, task.planEventId, reason, options)
      task.status = 'SKIPPED'
      task.skipReason = reason
    }
    task.lastActionAt = new Date().toISOString()
    return { ...task }
  }

  async getWeeklyTrend(memberId: string): Promise<TrendPoint[]> {
    const householdId = await this.resolveHouseholdId()
    const events = await this.client.listMemberTimeline(householdId, memberId, this.options(), 'weekly-trend')
    return deriveWeeklyTrendFromEvents(events, new Date(), this.householdTimeZone ?? undefined)
  }

  /**
   * MOB-162 知识条目只读列表。
   * 服务端已按批准状态与权限过滤，客户端不再做二次筛选，也不缓存正文。
   */
  async listKnowledgeDocuments(): Promise<KnowledgeDocumentSummaryView[]> {
    const response = await this.client.listKnowledgeDocuments(this.options())
    return (response ?? []).map((doc) => ({
      id: doc.id,
      title: doc.title,
      source: doc.source,
      version: doc.version,
      effectiveFrom: doc.effective_from,
    }))
  }

  /**
   * MOB-162 知识条目只读详情。
   * 只有服务端标记 `status === 'active'` 的条目才把分块正文带回界面；
   * 其它状态（staging、待批准、已下线）只保留元信息，避免移动端展示未批准内容。
   */
  async getKnowledgeDocument(docId: string): Promise<KnowledgeDocumentView> {
    const response = await this.client.getKnowledgeDocument(docId, this.options())
    const approved = response.status === 'active'
    return {
      id: response.id,
      title: response.title,
      source: response.source,
      license: response.license,
      version: response.version,
      status: response.status,
      approved,
      effectiveFrom: response.effective_from,
      effectiveUntil: response.effective_until,
      chunkCount: response.chunk_count,
      chunks: approved
        ? (response.chunks ?? []).map((chunk) => ({
            id: chunk.id,
            index: chunk.chunk_index,
            text: chunk.text,
            locator: chunk.locator,
          }))
        : [],
    }
  }

  /**
   * 知识条目检索。
   *
   * 服务端未声明 `knowledge-store` 能力时直接按不可用返回，不发出请求；
   * 权限预过滤、索引与排序都在服务端，移动端不做本地缓存、不做二次改写，
   * 也不把检索词写入本机存储或日志。
   */
  async searchKnowledge(query: string): Promise<KnowledgeSearchResult> {
    const trimmed = query.trim()
    if (!trimmed) {
      return { query: trimmed, hits: [], total: 0, degraded: true, reason: '请输入要查找的内容。' }
    }
    if (!hasCapability(CAPABILITY_IDS.knowledgeStore)) {
      return {
        query: trimmed,
        hits: [],
        total: 0,
        degraded: true,
        reason: '家庭服务器未提供知识库能力，检索入口保持不可用。',
      }
    }
    const householdId = this.householdId ?? this.context().householdId.trim()
    const response = await this.client.retrieveKnowledge(
      { query: trimmed, ...(householdId ? { household_id: householdId } : {}), top_k: 8 },
      this.options(),
    )
    if (response.degraded) {
      return {
        query: trimmed,
        hits: [],
        total: 0,
        degraded: true,
        reason: knowledgeDegradeReason(response.degrade_reason),
      }
    }
    return {
      query: trimmed,
      hits: (response.results ?? []).map(item => ({
        chunkId: item.chunk_id,
        documentId: item.document_id,
        title: item.title,
        source: item.source,
        version: item.version,
        text: item.text,
        locator: item.locator ?? null,
        score: item.score,
        matchReason: item.match_reason,
      })),
      total: response.total ?? (response.results ?? []).length,
      degraded: false,
      reason: '',
    }
  }

  async checkImageQuality(file: File): Promise<QualityCheckResult> {
    const response = await this.client.checkVisionQuality(file, 'image', this.options())
    return {
      decision: response.decision,
      reasons: response.reasons,
      retakePrompts: response.retake_prompts,
      metrics: Object.entries(response.metrics).map(([key, metric]) => ({
        label: key,
        value: typeof metric === 'number' ? String(metric) : `${metric.value}${metric.unit ? ` ${metric.unit}` : ''}`,
        passed: typeof metric === 'number' ? true : metric.passed,
      })),
      qualityReceipt: response.quality_receipt,
    }
  }

  /** MOB-149：短视频质量门；metrics 为帧数统计（纯数字），映射为信息型条目。 */
  async checkVideoQuality(file: File): Promise<QualityCheckResult> {
    const response = await this.client.checkVisionQuality(file, 'video', this.options())
    const numeric = (key: string): number => {
      const value = response.metrics[key]
      return typeof value === 'number' ? value : Number(value?.value ?? 0)
    }
    return {
      decision: response.decision,
      reasons: response.reasons,
      retakePrompts: response.retake_prompts,
      metrics: Object.entries(response.metrics).map(([key, metric]) => ({
        label: QUALITY_METRIC_LABELS[key] ?? key,
        value: typeof metric === 'number' ? String(metric) : `${metric.value}${metric.unit ? ` ${metric.unit}` : ''}`,
        passed: typeof metric === 'number' ? true : metric.passed,
      })),
      qualityReceipt: response.quality_receipt,
      framesSummary: {
        mediaType: 'video',
        sampledFrames: numeric('sampled_frames'),
        selectedFrames: numeric('selected_frames'),
        usableFrames: numeric('usable_frames'),
      },
    }
  }

  async recognizeMedicine(
    file: File,
    memberId: string,
    mediaKind: 'image' | 'video' = 'image',
  ): Promise<RecognitionCandidate> {
    const quality = mediaKind === 'video'
      ? await this.checkVideoQuality(file)
      : await this.checkImageQuality(file)
    if (quality.decision !== 'PASS' || !quality.qualityReceipt) {
      throw new Error(mediaKind === 'video' ? '视频未通过抽帧质量门控，请按提示重拍' : '图片未通过质量门控，请按提示重拍')
    }
    const draft = this.visionDraft(file, memberId, mediaKind)
    if (draft.task) return recognitionCandidateFromTask(draft.task, mediaKind)
    const uploaded = await this.uploadFileOnce(file)
    const task = await this.client.createVisionTask(
      {
        file_id: uploaded.storage_key,
        member_id: memberId,
        quality_receipt: quality.qualityReceipt,
        idempotency_key: draft.idempotencyKey,
        media_type: mediaKind,
      },
      this.options({ idempotencyKey: draft.idempotencyKey }),
    )
    draft.task = task
    return recognitionCandidateFromTask(task, mediaKind)
  }

  async fetchVisionTaskStatus(taskId: string): Promise<VisionTaskStatusSnapshot> {
    // 只读回查：重试必须复用同一 taskId；这里绝不创建任务或重新上传照片。
    const task = await this.client.getVisionTask(taskId, this.options())
    return visionTaskStatusSnapshotFromTask(task)
  }

  /**
   * 主动取消排队中/处理中的任务：复用同一 taskId，不重新上传、不重建任务。
   * 服务端返回的终态原样展示；`cancelled` 实测不带错误码，界面不虚构原因。
   */
  async cancelVisionTask(taskId: string): Promise<VisionTaskStatusSnapshot> {
    const task = await this.client.cancelVisionTask(
      taskId,
      this.options({ idempotencyKey: `vision-cancel:${taskId}` }),
    )
    return visionTaskStatusSnapshotFromTask(task)
  }

  async listTaskActionHistory(memberId: string): Promise<TaskActionHistoryEntry[]> {
    // 只读脱敏摘要，直接来自服务端时间线；不缓存、不在本地建第二份事实库。
    const householdId = await this.resolveHouseholdId()
    const memberName = await this.memberName(memberId)
    const events = await this.client.listMemberTimeline(householdId, memberId, this.options())
    return deriveTaskActionHistory(events, memberId, memberName)
  }
}

/** HCT-204 状态全集；集合之外的状态按"停止自动回查+原样展示"处理，不猜测为成功。 */
const KNOWN_VISION_TASK_STATUSES = new Set(['queued', 'running', 'succeeded', 'failed', 'cancelled', 'timeout'])
const VISION_TASK_TERMINAL_STATUSES = new Set(['succeeded', 'failed', 'cancelled', 'timeout'])

function visionTaskNextStep(status: string): string {
  switch (status) {
    case 'queued':
      return '任务已排队，等待家庭服务器处理；下方会按退避节奏继续回查，不会重复创建任务。'
    case 'running':
      return '家庭服务器正在提取 OCR、条码与包装特征证据；到达终态后这里会展示结果与下一步。'
    case 'succeeded':
      return '识别已完成，请到网页端“人工复核中心”查看证据并人工确认识别候选；确认前不会写入健康档案。'
    case 'failed':
      return '识别未完成。可点击“重试回查”确认状态，或回到上一步重新拍摄；重试回查不会重复创建任务。'
    case 'cancelled':
      return '任务已被取消，不会再有结果；如需识别请重新拍摄并创建新任务。'
    case 'timeout':
      return '任务在服务端超时未完成。可点击“重试回查”确认状态，或重新拍摄。'
    default:
      return `服务端返回了移动端未定义的状态“${status}”；已停止自动轮询，请到网页端人工复核中心核实，不以猜测代替结论。`
  }
}

export function visionTaskStatusSnapshotFromTask(task: VisionTask): VisionTaskStatusSnapshot {
  const status = task.status.toLowerCase()
  return {
    taskId: task.id,
    status,
    // 终态或未知状态都停止自动回查：未知状态绝不能被猜测为成功。
    terminal: VISION_TASK_TERMINAL_STATUSES.has(status) || !KNOWN_VISION_TASK_STATUSES.has(status),
    errorCode: task.error_code,
    errorMessage: task.error_message,
    modelVersion: task.model_version,
    createdAt: task.created_at,
    nextStep: visionTaskNextStep(status),
  }
}

function recognitionCandidateFromTask(task: VisionTask, mediaKind: 'image' | 'video' = 'image'): RecognitionCandidate {
  const mediaLabel = mediaKind === 'video' ? '短视频（服务端抽帧）' : '照片'
  return {
    status: 'REVIEW',
    fields: [
      { label: '视觉任务', value: task.id, source: '主数据', confidence: 1 },
      { label: '任务状态', value: task.status, source: '主数据', confidence: 1 },
      { label: '媒体类型', value: task.media_type ?? mediaKind, source: '主数据', confidence: 1 },
    ],
    conflicts: [],
    versions: { 服务端: task.model_version ?? '等待家庭服务器处理' },
    requiresHumanConfirmation: true,
    handoff: {
      taskId: task.id,
      taskStatus: task.status,
      source: 'FAMILY_SERVER',
      nextStep: '请在网页端人工复核中心查看证据并确认识别候选；移动端不会自动写入健康档案。',
    },
    notice:
      `${mediaLabel}已通过质量门控并创建视觉识别任务。识别与多证据融合在家庭服务器上执行（视频先抽帧再逐帧识别），完成后请在网页端“人工复核中心”确认候选；任一帧都不会被单独当作已确认药品。`,
  }
}

/** MOB-149：视频质量门 metrics 的中文名（帧数统计为信息型，不算通过/失败）。 */
const QUALITY_METRIC_LABELS: Record<string, string> = {
  decoded_frames: '解码帧数',
  sampled_frames: '采样帧数',
  selected_frames: '选中帧数',
  usable_frames: '可用帧数',
  sample_interval_ms: '采样间隔(ms)',
  sample_limit: '采样上限',
}
