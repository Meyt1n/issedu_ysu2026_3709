import { describe, expect, it } from 'vitest'

import {
  CHART_HEIGHT,
  CHART_PAD_BOTTOM,
  CHART_PAD_TOP,
  CHART_PAD_X,
  CHART_WIDTH,
  MEMBER_CHART_COLORS,
  TREND_DAYS,
  adherenceBucketOf,
  aggregateTrends,
  axisPositions,
  chartGeometry,
  cumulativeCounts,
  dayKeyOf,
  gridPath,
  seriesTotal,
  toChartSeries,
  trendDayKeys,
  trendDayLabels,
} from './bigScreenCharts'

/** 构造一条最小事件：折线图只看 occurred_at 与 event_type。 */
function event(occurredAt: string, eventType = 'note_added') {
  return { occurred_at: occurredAt, event_type: eventType }
}

const TODAY = new Date(2026, 8, 3, 10, 30) // 2026-09-03 本地时间

describe('trendDayKeys / trendDayLabels', () => {
  it('返回含今天在内的最近七天，末位是今天', () => {
    const keys = trendDayKeys(TODAY)
    expect(keys.length).toBe(TREND_DAYS)
    expect(keys[0]).toBe('2026-08-28')
    expect(keys[TREND_DAYS - 1]).toBe('2026-09-03')
  })

  it('标签把今天写成「今天」，其余是星期简称', () => {
    const labels = trendDayLabels(TODAY)
    expect(labels.length).toBe(TREND_DAYS)
    expect(labels[TREND_DAYS - 1]).toBe('今天')
    expect(labels.slice(0, TREND_DAYS - 1).every(label => label !== '今天')).toBe(true)
  })

  it('dayKeyOf 用本地时区补零', () => {
    expect(dayKeyOf(new Date(2026, 0, 5))).toBe('2026-01-05')
  })
})

describe('adherenceBucketOf', () => {
  it('把四种计划动作分到三条汇总线', () => {
    expect(adherenceBucketOf('plan_confirmed')).toBe('confirmed')
    expect(adherenceBucketOf('plan_deferred')).toBe('shifted')
    expect(adherenceBucketOf('plan_skipped')).toBe('shifted')
    expect(adherenceBucketOf('plan_missed')).toBe('missed')
  })

  it('与用药执行无关的事件返回 null', () => {
    expect(adherenceBucketOf('note_added')).toBeNull()
    expect(adherenceBucketOf('medication_added')).toBeNull()
  })
})

describe('aggregateTrends', () => {
  it('每位成员一条线，按本地日归桶且末位是今天', () => {
    const aggregate = aggregateTrends(
      [
        {
          id: 'm1',
          name: '奶奶',
          events: [event('2026-09-03T08:00:00'), event('2026-09-03T21:00:00'), event('2026-09-01T09:00:00')],
        },
        { id: 'm2', name: '爸爸', events: [event('2026-08-28T12:00:00')] },
      ],
      TODAY,
    )

    expect(aggregate.members.map(series => series.name)).toEqual(['奶奶', '爸爸'])
    expect(aggregate.members[0]!.counts[TREND_DAYS - 1]).toBe(2)
    expect(aggregate.members[0]!.counts[4]).toBe(1) // 2026-09-01
    expect(aggregate.members[1]!.counts[0]).toBe(1) // 2026-08-28
    expect(seriesTotal(aggregate.members)).toBe(4)
  })

  it('用药执行三条线是全家合计，与成员线互不干扰', () => {
    const aggregate = aggregateTrends(
      [
        {
          id: 'm1',
          name: '奶奶',
          events: [event('2026-09-03T08:00:00', 'plan_confirmed'), event('2026-09-03T20:00:00', 'plan_missed')],
        },
        {
          id: 'm2',
          name: '爸爸',
          events: [event('2026-09-03T09:00:00', 'plan_confirmed'), event('2026-09-02T09:00:00', 'plan_skipped')],
        },
      ],
      TODAY,
    )

    const [confirmed, shifted, missed] = aggregate.adherence
    expect(confirmed!.id).toBe('confirmed')
    expect(confirmed!.counts[TREND_DAYS - 1]).toBe(2)
    expect(shifted!.counts[TREND_DAYS - 2]).toBe(1)
    expect(missed!.counts[TREND_DAYS - 1]).toBe(1)
    // 计划动作同时计入所属成员的事件线。
    expect(seriesTotal(aggregate.members)).toBe(4)
  })

  it('窗口外与非法时间戳被跳过，不抛错', () => {
    const aggregate = aggregateTrends(
      [
        {
          id: 'm1',
          name: '奶奶',
          events: [event('2020-01-01T08:00:00'), event('not-a-date'), event('2026-09-03T08:00:00')],
        },
      ],
      TODAY,
    )
    expect(seriesTotal(aggregate.members)).toBe(1)
  })

  it('线色按主题令牌轮转，超过六人回到第一个色', () => {
    const aggregate = aggregateTrends(
      Array.from({ length: 7 }, (_, index) => ({ id: `m${index}`, name: `成员${index}`, events: [] })),
      TODAY,
    )
    expect(aggregate.members[0]!.color).toBe(MEMBER_CHART_COLORS[0])
    expect(aggregate.members[6]!.color).toBe(MEMBER_CHART_COLORS[0])
    expect(aggregate.members.every(series => series.color.startsWith('var(--'))).toBe(true)
  })

  it('没有成员时序列为空，用药线仍返回三条零值线', () => {
    const aggregate = aggregateTrends([], TODAY)
    expect(aggregate.members).toEqual([])
    expect(aggregate.adherence.length).toBe(3)
    expect(seriesTotal(aggregate.adherence)).toBe(0)
  })
})

describe('cumulativeCounts', () => {
  it('逐日累加', () => {
    expect(cumulativeCounts([1, 0, 2, 3])).toEqual([1, 1, 3, 6])
  })

  it('空输入返回空数组', () => {
    expect(cumulativeCounts([])).toEqual([])
  })
})

describe('axisPositions / chartGeometry', () => {
  it('刻度覆盖左右内边距之间的完整宽度', () => {
    const xs = axisPositions(TREND_DAYS)
    expect(xs[0]).toBe(CHART_PAD_X)
    expect(xs[TREND_DAYS - 1]).toBeCloseTo(CHART_WIDTH - CHART_PAD_X, 5)
  })

  it('单点也能取到坐标，不出现除零', () => {
    expect(axisPositions(1)).toEqual([CHART_PAD_X])
  })

  it('最大值落在顶部内边距，零值落在基线', () => {
    const { dots, line, area } = chartGeometry([0, 4], 4)
    expect(dots[1]!.y).toBeCloseTo(CHART_PAD_TOP, 5)
    expect(dots[0]!.y).toBeCloseTo(CHART_HEIGHT - CHART_PAD_BOTTOM, 5)
    expect(line.startsWith('M ')).toBe(true)
    expect(area.endsWith('Z')).toBe(true)
  })

  it('全零序列不除零，整条线压在基线上', () => {
    const { dots } = chartGeometry([0, 0, 0], 0)
    expect(dots.every(dot => Math.abs(dot.y - (CHART_HEIGHT - CHART_PAD_BOTTOM)) < 1e-6)).toBe(true)
  })

  it('空序列返回空路径', () => {
    expect(chartGeometry([], 3)).toEqual({ line: '', area: '', dots: [] })
  })
})

describe('gridPath', () => {
  it('网格线落在绘图区内且左右对齐刻度范围', () => {
    const path = gridPath(3)
    const ys = [...path.matchAll(/M26 ([\d.]+)H534/g)].map(match => Number(match[1]))
    expect(ys.length).toBe(3)
    expect(ys.every(y => y > CHART_PAD_TOP && y < CHART_HEIGHT - CHART_PAD_BOTTOM)).toBe(true)
    // 等距：相邻间隔一致。
    expect(ys[1]! - ys[0]!).toBeCloseTo(ys[2]! - ys[1]!, 5)
  })
})

describe('toChartSeries', () => {
  it('同组序列共享纵轴刻度，便于横向比较', () => {
    const [low, high] = toChartSeries([
      { id: 'low', name: '低', color: 'var(--pine)', counts: [0, 1] },
      { id: 'high', name: '高', color: 'var(--clay)', counts: [0, 2] },
    ])
    // 共享 max=2 时，1 只到一半高度，2 才触顶。
    expect(high!.dots[1]!.y).toBeCloseTo(CHART_PAD_TOP, 5)
    expect(low!.dots[1]!.y).toBeGreaterThan(high!.dots[1]!.y)
  })

  it('保留原序列的标识与颜色', () => {
    const [series] = toChartSeries([{ id: 'a', name: '甲', color: 'var(--sky)', counts: [1] }])
    expect(series).toMatchObject({ id: 'a', name: '甲', color: 'var(--sky)' })
  })
})
