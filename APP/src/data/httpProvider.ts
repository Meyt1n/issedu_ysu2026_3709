import { ApiClient } from '@/api/client'
import type { HealthEvent, Member, RequestOptions } from '@/api/types'
import type {
  CareTask,
  DataProvider,
  MemberDetail,
  MemberSummary,
  MedicationItem,
  ProviderInfo,
  QualityCheckResult,
  RecognitionCandidate,
  RiskCard,
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
}

function createIdempotencyKey(): string {
  return globalThis.crypto?.randomUUID?.() ?? `mobile-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

const PLAN_FACT_TYPES = new Set(['plan_created', 'plan_updated'])
const PLAN_ACTION_TYPES = new Set(['plan_confirmed', 'plan_deferred', 'plan_skipped'])
const TASK_LEVELS: TaskLevel[] = ['INFO', 'GENERAL', 'HIGH', 'URGENT']
const RISK_ORDER: Record<string, number> = { SEVERE: 0, WARNING: 1, INFO: 2, TIP: 3 }

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
  return Number.isFinite(time) ? time : 0
}

/**
 * 从时间线事件推导近 7 天完成趋势：
 * 某天的 total = 截至当天结束已存在的计划事实数；
 * done = 当天发生的 plan_confirmed 动作数（服务端按计划幂等）。
 */
export function deriveWeeklyTrendFromEvents(events: HealthEvent[], now: Date = new Date()): TrendPoint[] {
  const plans = events.filter(e => PLAN_FACT_TYPES.has(e.event_type))
  const confirms = events.filter(e => e.event_type === 'plan_confirmed')

  const points: TrendPoint[] = []
  for (let offset = 6; offset >= 0; offset -= 1) {
    const dayStart = new Date(now)
    dayStart.setDate(dayStart.getDate() - offset)
    dayStart.setHours(0, 0, 0, 0)
    const dayEnd = dayStart.getTime() + 24 * 3600 * 1000

    points.push({
      label: offset === 0 ? '今' : TREND_WEEKDAYS[dayStart.getDay()]!,
      total: plans.filter(p => eventTime(p) < dayEnd).length,
      done: confirms.filter(c => {
        const time = eventTime(c)
        return time >= dayStart.getTime() && time < dayEnd
      }).length,
    })
  }
  return points
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
  private memberCache = new Map<string, Member>()
  private taskCache = new Map<string, CareTask>()

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

  private async resolveHouseholdId(): Promise<string> {
    if (this.householdId) return this.householdId
    const households = await this.client.listHouseholds(this.options())
    const first = households[0]
    if (!first) throw new Error('当前身份看不到任何家庭，请先在网页端创建家庭或检查授权')
    this.householdId = first.id
    return first.id
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
    }
  }

  async listRisks(memberId?: string): Promise<RiskCard[]> {
    const householdId = await this.resolveHouseholdId()
    if (!memberId) {
      const members = await this.client.listMembers(householdId, this.options())
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
    const options = this.options({ idempotencyKey: createIdempotencyKey() })

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
    return deriveWeeklyTrendFromEvents(events)
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
    const uploaded = await this.client.uploadFile(file, this.options())
    const task = await this.client.createVisionTask(
      {
        file_id: uploaded.storage_key,
        member_id: memberId,
        quality_receipt: quality.qualityReceipt,
        idempotency_key: createIdempotencyKey(),
      },
      this.options(),
    )
    return {
      status: 'REVIEW',
      fields: [
        { label: '视觉任务', value: task.id, source: '主数据', confidence: 1 },
        { label: '任务状态', value: task.status, source: '主数据', confidence: 1 },
      ],
      conflicts: [],
      versions: { 服务端: task.model_version ?? '等待家庭服务器处理' },
      requiresHumanConfirmation: true,
      notice:
        '照片已通过质量门控并创建视觉识别任务。识别与多证据融合在家庭服务器上执行，完成后请在网页端“人工复核中心”确认候选。',
    }
  }
}
