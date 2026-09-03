import { describe, expect, it } from 'vitest'

import {
  bucketByDay,
  calendarMonthLabel,
  dayBucketTotal,
  dayKeyOf,
  daySummaryLabel,
  monthMatrix,
  shiftMonth,
} from './healthCalendar'

describe('monthMatrix', () => {
  it('2026 年 9 月从周二开始（周一为一周起点），补位 1 格且共 35 格', () => {
    const cells = monthMatrix(2026, 9)
    // 2026-09-01 是周二。
    expect(cells[0]).toEqual({ key: null, day: null, inMonth: false })
    expect(cells[1]).toEqual({ key: '2026-09-01', day: 1, inMonth: true })
    expect(cells.length).toBe(35)
    expect(cells.filter(cell => cell.inMonth).length).toBe(30)
  })

  it('整周对齐的月份不产生多余空行', () => {
    // 2027-02-01 是周一且 2 月有 28 天，正好 4 周。
    const cells = monthMatrix(2027, 2)
    expect(cells.length).toBe(28)
    expect(cells[0]).toEqual({ key: '2027-02-01', day: 1, inMonth: true })
    expect(cells.every(cell => cell.inMonth)).toBe(true)
  })

  it('非法月份返回空数组', () => {
    expect(monthMatrix(2026, 0)).toEqual([])
    expect(monthMatrix(2026, 13)).toEqual([])
  })
})

describe('bucketByDay', () => {
  it('按本地日聚合事件、用药与识别数量', () => {
    const buckets = bucketByDay(
      [
        { occurred_at: '2026-09-01T08:30:00+08:00' },
        { occurred_at: '2026-09-01T21:00:00+08:00' },
        { occurred_at: '2026-09-02T10:00:00+08:00' },
      ],
      [{ next_action_at: '2026-09-02T09:00:00+08:00' }],
      [{ created_at: '2026-08-31T12:00:00+08:00' }],
    )
    expect(buckets.get('2026-09-01')).toEqual({ events: 2, plans: 0, reviews: 0 })
    expect(buckets.get('2026-09-02')).toEqual({ events: 1, plans: 1, reviews: 0 })
    expect(buckets.get('2026-08-31')).toEqual({ events: 0, plans: 0, reviews: 1 })
  })

  it('非法时间戳被跳过而不是抛错', () => {
    const buckets = bucketByDay(
      [{ occurred_at: 'not-a-date' }, { occurred_at: '' }],
      [{ next_action_at: null as unknown as string }],
      [],
    )
    expect(buckets.size).toBe(0)
  })

  it('发生在本地时区跨午夜的事件按本地日归档', () => {
    // UTC 2026-09-01T17:30Z = 东八区 2026-09-02T01:30（假设运行时为 +08:00）。
    const buckets = bucketByDay([{ occurred_at: '2026-09-01T17:30:00Z' }], [], [])
    expect(buckets.size).toBe(1)
    const [key] = [...buckets.keys()]
    // 只断言与 dayKeyOf 的换算一致，不假设 CI 的时区。
    expect(key).toBe(dayKeyOf(new Date('2026-09-01T17:30:00Z')))
  })
})

describe('daySummaryLabel', () => {
  it('只输出类别与数量，不包含正文', () => {
    expect(daySummaryLabel({ events: 2, plans: 1, reviews: 0 })).toBe('事件 2 · 用药 1')
  })

  it('空桶显示当日无记录', () => {
    expect(daySummaryLabel(null)).toBe('当日无记录')
    expect(daySummaryLabel({ events: 0, plans: 0, reviews: 0 })).toBe('当日无记录')
  })
})

describe('shiftMonth / 标签', () => {
  it('月份步进在年界循环', () => {
    expect(shiftMonth(2026, 1, -1)).toEqual({ year: 2025, month: 12 })
    expect(shiftMonth(2026, 12, 1)).toEqual({ year: 2027, month: 1 })
    expect(shiftMonth(2026, 9, 0)).toEqual({ year: 2026, month: 9 })
  })

  it('月标签与总数工具', () => {
    expect(calendarMonthLabel(2026, 9)).toBe('2026年9月')
    expect(dayBucketTotal({ events: 1, plans: 2, reviews: 3 })).toBe(6)
    expect(dayBucketTotal(null)).toBe(0)
  })
})
