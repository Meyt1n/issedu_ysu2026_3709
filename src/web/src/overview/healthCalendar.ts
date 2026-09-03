import type { HealthEvent, PlanWorkbenchItem, ReviewTask } from '../api/types'

/**
 * 健康日历的纯逻辑层（HCT-532）。
 * 只聚合「数量与类别标签」，不读取事件 payload / 药品正文，
 * 保证日历格子与日期摘要不展示敏感健康正文（NFR-02）。
 */

export interface CalendarCell {
  /** 本地时区当天的 yyyy-MM-dd 键；补位空格子为 null。 */
  key: string | null
  day: number | null
  inMonth: boolean
}

export interface DayBucket {
  /** 已确认健康事件（按 occurred_at 归日）。 */
  events: number
  /** 已确认用药计划的近期动作（按 next_action_at 归日）。 */
  plans: number
  /** 识别复核任务（按 created_at 归日）。 */
  reviews: number
}

const WEEKDAY_LABELS = ['一', '二', '三', '四', '五', '六', '日'] as const

export function calendarWeekdayLabels(): readonly string[] {
  return WEEKDAY_LABELS
}

function pad2(value: number): string {
  return value < 10 ? `0${value}` : String(value)
}

export function dayKeyOf(date: Date): string {
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`
}

function dayKeyFromTimestamp(value: string | null | undefined): string | null {
  if (!value) return null
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return null
  return dayKeyOf(date)
}

/** 以周一为一周起点，生成覆盖整月的周矩阵（含前后补位空格）。 */
export function monthMatrix(year: number, month: number): CalendarCell[] {
  const firstDay = new Date(year, month - 1, 1)
  if (
    firstDay.getFullYear() !== year ||
    firstDay.getMonth() !== month - 1 ||
    month < 1 ||
    month > 12
  ) {
    return []
  }
  const daysInMonth = new Date(year, month, 0).getDate()
  // getDay(): 周日=0 → 转成周一=0。
  const leadingBlanks = (firstDay.getDay() + 6) % 7

  const cells: CalendarCell[] = []
  for (let i = 0; i < leadingBlanks; i += 1) {
    cells.push({ key: null, day: null, inMonth: false })
  }
  for (let day = 1; day <= daysInMonth; day += 1) {
    cells.push({ key: `${year}-${pad2(month)}-${pad2(day)}`, day, inMonth: true })
  }
  while (cells.length % 7 !== 0) {
    cells.push({ key: null, day: null, inMonth: false })
  }
  return cells
}

export function emptyDayBucket(): DayBucket {
  return { events: 0, plans: 0, reviews: 0 }
}

/**
 * 把首页已加载的三类数据按本地日聚合。
 * 输入异常（非法时间戳）只跳过该条，不让日历崩溃。
 */
export function bucketByDay(
  events: readonly Pick<HealthEvent, 'occurred_at'>[],
  plans: readonly Pick<PlanWorkbenchItem, 'next_action_at'>[],
  reviews: readonly Pick<ReviewTask, 'created_at'>[],
): Map<string, DayBucket> {
  const buckets = new Map<string, DayBucket>()
  const bucketFor = (key: string): DayBucket => {
    const existing = buckets.get(key)
    if (existing) return existing
    const fresh = emptyDayBucket()
    buckets.set(key, fresh)
    return fresh
  }

  for (const event of events) {
    const key = dayKeyFromTimestamp(event.occurred_at)
    if (key) bucketFor(key).events += 1
  }
  for (const plan of plans) {
    const key = dayKeyFromTimestamp(plan.next_action_at)
    if (key) bucketFor(key).plans += 1
  }
  for (const review of reviews) {
    const key = dayKeyFromTimestamp(review.created_at)
    if (key) bucketFor(key).reviews += 1
  }
  return buckets
}

export function dayBucketTotal(bucket: DayBucket | null | undefined): number {
  if (!bucket) return 0
  return bucket.events + bucket.plans + bucket.reviews
}

/** 无障碍与展开摘要用的文本：只有类别数量，不含健康正文。 */
export function daySummaryLabel(bucket: DayBucket | null | undefined): string {
  if (!bucket || dayBucketTotal(bucket) === 0) return '当日无记录'
  const parts: string[] = []
  if (bucket.events > 0) parts.push(`事件 ${bucket.events}`)
  if (bucket.plans > 0) parts.push(`用药 ${bucket.plans}`)
  if (bucket.reviews > 0) parts.push(`识别 ${bucket.reviews}`)
  return parts.join(' · ')
}

export function calendarMonthLabel(year: number, month: number): string {
  return `${year}年${month}月`
}

/** 月份步进（1–12 循环），供前后翻月按钮使用。 */
export function shiftMonth(year: number, month: number, delta: number): { year: number; month: number } {
  const total = year * 12 + (month - 1) + delta
  return {
    year: Math.floor(total / 12),
    month: (total % 12) + 1,
  }
}
