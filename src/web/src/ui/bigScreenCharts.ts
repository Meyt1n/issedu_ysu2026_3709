import type { HealthEvent } from '../api/types'

/**
 * 家庭大屏折线图的纯逻辑层（HCT-537）。
 * 只聚合「数量」：把已授权返回的已确认事件按本地日归桶，再算成 SVG 路径。
 * 不读取 payload 正文，保证大屏不投放敏感健康内容（NFR-02）。
 */

export const TREND_DAYS = 7

export interface TrendSeries {
  id: string
  name: string
  /** 主题令牌字符串（如 var(--pine)），切主题自动跟随。 */
  color: string
  counts: number[]
}

export interface ChartGeometry {
  line: string
  area: string
  dots: Array<{ x: number; y: number }>
}

export type ChartSeries = TrendSeries & ChartGeometry

export const CHART_WIDTH = 560
export const CHART_HEIGHT = 150
export const CHART_PAD_X = 26
export const CHART_PAD_TOP = 16
export const CHART_PAD_BOTTOM = 26

/** 成员线用主题的六个语义色轮转，保证与整屏同一色域。 */
export const MEMBER_CHART_COLORS = [
  'var(--pine)',
  'var(--clay)',
  'var(--gold)',
  'var(--sky)',
  'var(--rose)',
  'var(--sage)',
] as const

function pad2(value: number): string {
  return value < 10 ? `0${value}` : String(value)
}

export function dayKeyOf(date: Date): string {
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`
}

/** 最近 7 天（含今天）的本地日键，索引 0 是最早一天。 */
export function trendDayKeys(today: Date = new Date()): string[] {
  return Array.from({ length: TREND_DAYS }, (_, index) => {
    const date = new Date(today)
    date.setDate(today.getDate() - (TREND_DAYS - 1 - index))
    return dayKeyOf(date)
  })
}

/** 横轴标签：今天写「今天」，其余写星期简称。 */
export function trendDayLabels(today: Date = new Date()): string[] {
  const todayKey = dayKeyOf(today)
  return Array.from({ length: TREND_DAYS }, (_, index) => {
    const date = new Date(today)
    date.setDate(today.getDate() - (TREND_DAYS - 1 - index))
    return dayKeyOf(date) === todayKey
      ? '今天'
      : date.toLocaleDateString('zh-CN', { weekday: 'short' })
  })
}

export function zeroWeek(): number[] {
  return new Array<number>(TREND_DAYS).fill(0)
}

/** 计划执行动作 → 三条汇总线的归类；返回 null 表示与用药执行无关。 */
export function adherenceBucketOf(eventType: string): 'confirmed' | 'shifted' | 'missed' | null {
  if (eventType === 'plan_confirmed') return 'confirmed'
  if (eventType === 'plan_deferred' || eventType === 'plan_skipped') return 'shifted'
  if (eventType === 'plan_missed') return 'missed'
  return null
}

export interface MemberTimeline {
  id: string
  name: string
  events: readonly Pick<HealthEvent, 'occurred_at' | 'event_type'>[]
}

export interface TrendAggregate {
  /** 每位成员一条线：当日已确认事件条数。 */
  members: TrendSeries[]
  /** 全家合计的用药执行三条线。 */
  adherence: TrendSeries[]
}

/**
 * 把成员时间线聚合成折线图序列。
 * 非法时间戳或落在窗口外的事件直接跳过，不让大屏崩。
 */
export function aggregateTrends(
  timelines: readonly MemberTimeline[],
  today: Date = new Date(),
): TrendAggregate {
  const keys = trendDayKeys(today)
  const index = new Map(keys.map((key, position) => [key, position]))

  const confirmed = zeroWeek()
  const shifted = zeroWeek()
  const missed = zeroWeek()

  const members = timelines.map((timeline, order) => {
    const counts = zeroWeek()
    for (const event of timeline.events) {
      const time = new Date(event.occurred_at)
      if (Number.isNaN(time.getTime())) continue
      const position = index.get(dayKeyOf(time))
      if (position === undefined) continue
      counts[position] += 1
      const bucket = adherenceBucketOf(event.event_type)
      if (bucket === 'confirmed') confirmed[position] += 1
      else if (bucket === 'shifted') shifted[position] += 1
      else if (bucket === 'missed') missed[position] += 1
    }
    return {
      id: timeline.id,
      name: timeline.name,
      color: MEMBER_CHART_COLORS[order % MEMBER_CHART_COLORS.length] ?? 'var(--pine)',
      counts,
    }
  })

  return {
    members,
    adherence: [
      { id: 'confirmed', name: '按时确认', color: 'var(--pine)', counts: confirmed },
      { id: 'shifted', name: '延期或跳过', color: 'var(--gold)', counts: shifted },
      { id: 'missed', name: '漏服记录', color: 'var(--rose)', counts: missed },
    ],
  }
}

/** 逐日累加，得到「本周攒了多少」的累计曲线。 */
export function cumulativeCounts(counts: readonly number[]): number[] {
  let running = 0
  return counts.map(count => (running += count))
}

/** 各刻度的横坐标；标签与折线共用，避免两套算法漂移。 */
export function axisPositions(count: number): number[] {
  const step = (CHART_WIDTH - CHART_PAD_X * 2) / (count - 1 || 1)
  return Array.from({ length: count }, (_, index) => CHART_PAD_X + index * step)
}

/** 三条等距横向网格线，随内边距一起算，改画布尺寸不用手改魔法数。 */
export function gridPath(lines = 3): string {
  const top = CHART_PAD_TOP
  const bottom = CHART_HEIGHT - CHART_PAD_BOTTOM
  const step = (bottom - top) / (lines + 1)
  return Array.from({ length: lines }, (_, index) => {
    const y = (top + step * (index + 1)).toFixed(1)
    return `M${CHART_PAD_X} ${y}H${CHART_WIDTH - CHART_PAD_X}`
  }).join('')
}

export function chartGeometry(counts: readonly number[], max: number): ChartGeometry {
  if (counts.length === 0) return { line: '', area: '', dots: [] }
  const xs = axisPositions(counts.length)
  const maxY = Math.max(max, 1)
  const plotHeight = CHART_HEIGHT - CHART_PAD_TOP - CHART_PAD_BOTTOM
  const dots = counts.map((count, index) => ({
    x: xs[index] ?? CHART_PAD_X,
    y: CHART_PAD_TOP + plotHeight * (1 - count / maxY),
  }))
  const line = dots
    .map((point, index) => `${index === 0 ? 'M' : 'L'} ${point.x.toFixed(1)} ${point.y.toFixed(1)}`)
    .join(' ')
  const baseline = CHART_HEIGHT - CHART_PAD_BOTTOM
  const first = dots[0]!
  const last = dots[dots.length - 1]!
  const area = `${line} L ${last.x.toFixed(1)} ${baseline} L ${first.x.toFixed(1)} ${baseline} Z`
  return { line, area, dots }
}

/** 一组序列共享同一纵轴刻度，才能横向比较。 */
export function toChartSeries(series: readonly TrendSeries[]): ChartSeries[] {
  const max = Math.max(1, ...series.flatMap(item => item.counts))
  return series.map(item => ({ ...item, ...chartGeometry(item.counts, max) }))
}

export function seriesTotal(series: readonly TrendSeries[]): number {
  return series.reduce(
    (sum, item) => sum + item.counts.reduce((inner, count) => inner + count, 0),
    0,
  )
}
