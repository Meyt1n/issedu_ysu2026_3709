import { ApiClient, ApiClientError } from '@/api/client'
import { CAPABILITY_IDS, hasCapability } from '@/stores/capabilities'
import type { HealthEvent, Member, RequestOptions, UploadedFile, VisionTask } from '@/api/types'
import type {
  CareTask,
  DataProvider,
  EnvironmentActionState,
  HouseholdOption,
  MemberDetail,
  MemberSummary,
  MedicationItem,
  ProviderInfo,
  QualityCheckResult,
  RecognitionCandidate,
  RiskCard,
  ReminderPolicy,
  RiskLevel,
  TaskAction,
  TaskActionPayload,
  TaskLevel,
  TimelineItem,
  TodaySnapshot,
  TrendPoint,
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
const PLAN_ACTION_TYPES = new Set(['plan_confirmed', 'plan_deferred', 'plan_skipped'])
const TASK_LEVELS: TaskLevel[] = ['INFO', 'GENERAL', 'HIGH', 'URGENT']
const RISK_ORDER: Record<string, number> = { SEVERE: 0, WARNING: 1, INFO: 2, TIP: 3 }

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
      } else {
        task.status = 'DEFERRED'
        const delay = Number((latest.payload ?? {})['delay_hours'] ?? 0)
        const base = new Date(task.lastActionAt).getTime()
        if (Number.isFinite(base) && delay > 0) {
          task.dueAt = new Date(base + delay * 3_600_000).toISOString()
        }
      }
    }
    return task
  })
}

const TREND_WEEKDAYS = ['日', '一', '二', '三', '四', '五', '六']

function eventTime(event: HealthEvent): number {
  const time = Date.parse(event.occurred_at ?? event.created_at)
  return Number.isFinite(time) ? time : Number.NaN
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

  private visionDraft(file: File, memberId: string): VisionDraft {
    let drafts = this.visionDrafts.get(file)
    if (!drafts) {
      drafts = new Map<string, VisionDraft>()
      this.visionDrafts.set(file, drafts)
    }
    let draft = drafts.get(memberId)
    if (!draft) {
      draft = { idempotencyKey: `vision:${createIdempotencyKey()}` }
      drafts.set(memberId, draft)
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

    return {
      summary,
      medications,
      timeline,
      // 授权列表接口仅家庭 owner 可读，移动端暂不展示（在网页端管理）。
      authorizations: [],
    }
  }

  async getTodaySnapshot(memberId: string): Promise<TodaySnapshot> {
    const householdId = await this.resolveHouseholdId()
    const memberName = await this.memberName(memberId)
    const [events, risks] = await Promise.all([
      this.client.listMemberTimeline(householdId, memberId, this.options()),
      this.listRisks(memberId),
    ])

    const tasks = deriveTasksFromEvents(events, memberId, memberName)
    for (const task of tasks) this.taskCache.set(task.id, task)

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
      const all = await Promise.all(members.map(m => this.listRisks(m.id).catch(() => [] as RiskCard[])))
      return all
        .flat()
        .sort((a, b) => (RISK_ORDER[a.level] ?? 9) - (RISK_ORDER[b.level] ?? 9))
    }
    const memberName = await this.memberName(memberId)
    const response = await this.client.listMemberRisks(householdId, memberId, this.options())
    return response.alerts
      .map(alert => ({
        ruleId: alert.rule_id,
        ruleVersion: '服务端 rules-v0',
        level: alert.level as RiskLevel,
        message: alert.message,
        memberId,
        memberName,
        createdAt: alert.created_at,
        sourceCount: alert.source_event_ids.length,
        explanation:
          '由家庭服务器确定性规则（过期/库存/重复成分/过敏/相互作用）基于已确认事件计算得出，不是模型推断。',
        suggestion: '请查看依据后在授权范围内处理；如有医疗疑问请联系医生或药师。',
        acknowledged: false,
        sourceEvents: [],
      }))
      .sort((a, b) => (RISK_ORDER[a.level] ?? 9) - (RISK_ORDER[b.level] ?? 9))
  }

  async getRiskDetail(memberId: string, ruleId: string): Promise<RiskCard> {
    const householdId = await this.resolveHouseholdId()
    const memberName = await this.memberName(memberId)
    const detail = await this.client.getRiskDetail(householdId, memberId, ruleId, this.options())
    return {
      ruleId: detail.alert.rule_id,
      ruleVersion: '服务端 rules-v0',
      level: detail.alert.level as RiskLevel,
      message: detail.alert.message,
      memberId,
      memberName,
      createdAt: detail.alert.created_at,
      sourceCount: detail.source_events.length,
      explanation: '由家庭服务器确定性规则计算得出；以下为脱敏的证据事件摘要。',
      suggestion: '请查看依据后在授权范围内处理；如有医疗疑问请联系医生或药师。',
      acknowledged: false,
      sourceEvents: detail.source_events.map(e => ({
        id: e.id,
        eventType: e.event_type,
        confirmationStatus: e.confirmation_status,
        createdAt: e.created_at,
      })),
    }
  }

  async acknowledgeRisk(memberId: string, ruleId: string): Promise<RiskCard> {
    // 主仓库暂未提供风险“已知晓”写接口；联机模式如实拒绝，不伪装成功。
    throw new Error(`联机模式暂不支持在手机上记录“已知晓”（${memberId}/${ruleId}），请在网页端处理`)
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
    const events = await this.client.listMemberTimeline(householdId, memberId, this.options())
    return deriveWeeklyTrendFromEvents(events, new Date(), this.householdTimeZone ?? undefined)
  }

  async checkImageQuality(file: File): Promise<QualityCheckResult> {
    const response = await this.client.checkVisionQuality(file, this.options())
    return {
      decision: response.decision,
      reasons: response.reasons,
      retakePrompts: response.retake_prompts,
      metrics: Object.entries(response.metrics).map(([key, metric]) => ({
        label: key,
        value: `${metric.value}${metric.unit ? ` ${metric.unit}` : ''}`,
        passed: metric.passed,
      })),
      qualityReceipt: response.quality_receipt,
    }
  }

  async recognizeMedicine(file: File, memberId: string): Promise<RecognitionCandidate> {
    const quality = await this.checkImageQuality(file)
    if (quality.decision !== 'PASS' || !quality.qualityReceipt) {
      throw new Error('图片未通过质量门控，请按提示重拍')
    }
    const draft = this.visionDraft(file, memberId)
    if (draft.task) return recognitionCandidateFromTask(draft.task)
    const uploaded = await this.uploadFileOnce(file)
    const task = await this.client.createVisionTask(
      {
        file_id: uploaded.storage_key,
        member_id: memberId,
        quality_receipt: quality.qualityReceipt,
        idempotency_key: draft.idempotencyKey,
      },
      this.options({ idempotencyKey: draft.idempotencyKey }),
    )
    draft.task = task
    return recognitionCandidateFromTask(task)
  }
}

function recognitionCandidateFromTask(task: VisionTask): RecognitionCandidate {
  return {
    status: 'REVIEW',
    fields: [
      { label: '视觉任务', value: task.id, source: '主数据', confidence: 1 },
      { label: '任务状态', value: task.status, source: '主数据', confidence: 1 },
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
      '照片已通过质量门控并创建视觉识别任务。识别与多证据融合在家庭服务器上执行，完成后请在网页端“人工复核中心”确认候选。',
  }
}
