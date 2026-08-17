import { describe, expect, it } from 'vitest'

import type { HealthEvent } from '@/api/types'

import { deriveTasksFromEvents, deriveWeeklyTrendFromEvents } from './httpProvider'

let sequence = 0

function makeEvent(patch: Partial<HealthEvent> & Pick<HealthEvent, 'id' | 'event_type'>): HealthEvent {
  sequence += 1
  return {
    household_id: 'h1',
    member_id: 'm1',
    sequence_no: sequence,
    source: 'MANUAL',
    confirmation_status: 'CONFIRMED',
    payload: {},
    evidence: {},
    created_by: 'actor-1',
    occurred_at: '2026-08-13T00:30:00Z',
    recorded_at: '2026-08-13T00:30:00Z',
    created_at: '2026-08-13T00:30:00Z',
    ...patch,
  }
}

describe('联机模式任务推导（与主仓库事件语义对齐）', () => {
  it('plan_created 无动作事件时为待处理，标题取 药名：安排', () => {
    const events = [
      makeEvent({
        id: 'p1',
        event_type: 'plan_created',
        payload: { drug: '苯磺酸氨氯地平片', schedule: '每日早餐后', due_time: '08:30' },
      }),
    ]
    const tasks = deriveTasksFromEvents(events, 'm1', '王秀兰')
    expect(tasks).toHaveLength(1)
    expect(tasks[0]!.status).toBe('PENDING')
    expect(tasks[0]!.title).toBe('苯磺酸氨氯地平片：每日早餐后')
    expect(tasks[0]!.planEventId).toBe('p1')
    const due = new Date(tasks[0]!.dueAt)
    expect(due.getHours()).toBe(8)
    expect(due.getMinutes()).toBe(30)
  })

  it('最后一条动作事件决定任务状态（confirm 幂等语义）', () => {
    const events = [
      makeEvent({ id: 'p1', event_type: 'plan_created', payload: { drug: 'A药' } }),
      makeEvent({
        id: 'a1',
        event_type: 'plan_deferred',
        payload: { plan_event_id: 'p1', delay_hours: 2 },
        occurred_at: '2026-08-13T01:00:00Z',
      }),
      makeEvent({
        id: 'a2',
        event_type: 'plan_confirmed',
        payload: { plan_event_id: 'p1' },
        occurred_at: '2026-08-13T03:00:00Z',
      }),
    ]
    const tasks = deriveTasksFromEvents(events, 'm1', '王秀兰')
    expect(tasks[0]!.status).toBe('CONFIRMED')
  })

  it('延期动作把提醒时间推后 delay_hours', () => {
    const events = [
      makeEvent({ id: 'p1', event_type: 'plan_created', payload: { drug: 'A药' } }),
      makeEvent({
        id: 'a1',
        event_type: 'plan_deferred',
        payload: { plan_event_id: 'p1', delay_hours: 4 },
        occurred_at: '2026-08-13T02:00:00Z',
      }),
    ]
    const tasks = deriveTasksFromEvents(events, 'm1', '王秀兰')
    expect(tasks[0]!.status).toBe('DEFERRED')
    expect(new Date(tasks[0]!.dueAt).toISOString()).toBe('2026-08-13T06:00:00.000Z')
  })

  it('跳过动作携带原因；不相关动作不影响其它计划', () => {
    const events = [
      makeEvent({ id: 'p1', event_type: 'plan_created', payload: { drug: 'A药' } }),
      makeEvent({ id: 'p2', event_type: 'plan_created', payload: { drug: 'B药', level: 'HIGH' } }),
      makeEvent({
        id: 'a1',
        event_type: 'plan_skipped',
        payload: { plan_event_id: 'p1', reason: '医院已服药' },
      }),
    ]
    const tasks = deriveTasksFromEvents(events, 'm1', '王秀兰')
    expect(tasks[0]!.status).toBe('SKIPPED')
    expect(tasks[0]!.skipReason).toBe('医院已服药')
    expect(tasks[1]!.status).toBe('PENDING')
    expect(tasks[1]!.level).toBe('HIGH')
  })

  it('非计划事件不会被误判为任务', () => {
    const events = [
      makeEvent({ id: 'e1', event_type: 'medication_added', payload: { drug: 'A药' } }),
      makeEvent({ id: 'e2', event_type: 'allergy_added', payload: { allergy: '青霉素' } }),
    ]
    expect(deriveTasksFromEvents(events, 'm1', '王秀兰')).toHaveLength(0)
  })
})

describe('近 7 天完成趋势推导', () => {
  const now = new Date('2026-08-13T12:00:00Z')

  it('返回按时间升序的 7 天，最后一天标记为“今”', () => {
    const points = deriveWeeklyTrendFromEvents([], now)
    expect(points).toHaveLength(7)
    expect(points[6]!.label).toBe('今')
    expect(points.every(p => p.total === 0 && p.done === 0)).toBe(true)
  })

  it('total 为截至当天已存在的计划数，done 为当天确认数', () => {
    const events = [
      makeEvent({
        id: 'p1',
        event_type: 'plan_created',
        payload: { drug: 'A药' },
        occurred_at: '2026-08-10T01:00:00Z',
      }),
      makeEvent({
        id: 'a1',
        event_type: 'plan_confirmed',
        payload: { plan_event_id: 'p1' },
        occurred_at: '2026-08-11T02:00:00Z',
      }),
      makeEvent({
        id: 'a2',
        event_type: 'plan_confirmed',
        payload: { plan_event_id: 'p1' },
        occurred_at: '2026-08-13T03:00:00Z',
      }),
    ]
    const points = deriveWeeklyTrendFromEvents(events, now)

    // 8-07 至 8-09：计划尚未创建
    expect(points[0]!.total).toBe(0)
    expect(points[2]!.total).toBe(0)
    // 8-10 起计划存在
    expect(points[3]!.total).toBe(1)
    expect(points[6]!.total).toBe(1)
    // 8-11 与今天各有一次确认
    expect(points[4]!.done).toBe(1)
    expect(points[6]!.done).toBe(1)
    // 8-12 无确认
    expect(points[5]!.done).toBe(0)
  })
})
