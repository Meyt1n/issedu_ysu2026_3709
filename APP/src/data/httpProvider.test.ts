import { describe, expect, it, vi } from 'vitest'

import { ApiClient } from '@/api/client'
import type { HealthEvent } from '@/api/types'
import type { CareTask } from './types'

import { deriveTasksFromEvents, deriveWeeklyTrendFromEvents, HttpDataProvider } from './httpProvider'

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

describe('联机会话初始化边界', () => {
  it('身份或访问目的缺失时不请求家庭，也不进入空数据状态', async () => {
    const client = { listHouseholds: vi.fn() } as unknown as ApiClient
    const provider = new HttpDataProvider(client, () => ({ actorId: '', accessPurpose: '', householdId: '' }))

    await expect(provider.listMembers()).rejects.toMatchObject({ code: 'SESSION_NOT_CONFIGURED', status: 401 })
    expect(client.listHouseholds).not.toHaveBeenCalled()
  })

  it('身份没有家庭时返回可被设置页识别的错误码', async () => {
    const client = { listHouseholds: vi.fn().mockResolvedValue([]) } as unknown as ApiClient
    const provider = new HttpDataProvider(client, () => ({ actorId: 'actor-a', accessPurpose: 'family-care', householdId: '' }))

    await expect(provider.listMembers()).rejects.toMatchObject({ code: 'NO_HOUSEHOLD', status: 404 })
  })
})

describe('联机写请求的幂等与重试', () => {
  it('计划动作重试复用 action + plan_event_id 幂等键', async () => {
    const confirmCarePlan = vi.fn().mockResolvedValue({})
    const client = {
      listHouseholds: vi.fn().mockResolvedValue([{ id: 'h1' }]),
      confirmCarePlan,
    } as unknown as ApiClient
    const provider = new HttpDataProvider(client, () => ({ actorId: 'actor-1', accessPurpose: 'family-care', householdId: '' }))
    const task: CareTask = {
      id: 'task-1',
      memberId: 'm1',
      memberName: '演示成员',
      title: '演示计划',
      detail: '演示',
      level: 'INFO',
      dueAt: '2026-08-19T08:00:00Z',
      status: 'PENDING',
      planEventId: 'plan-1',
    }
    ;(provider as unknown as { taskCache: Map<string, CareTask> }).taskCache.set(task.id, task)

    await provider.submitTaskAction(task.id, 'confirm')
    await provider.submitTaskAction(task.id, 'confirm')

    expect(confirmCarePlan).toHaveBeenCalledTimes(2)
    expect(confirmCarePlan.mock.calls[0]?.[3]).toMatchObject({ idempotencyKey: 'confirm:plan-1' })
    expect(confirmCarePlan.mock.calls[1]?.[3]).toMatchObject({ idempotencyKey: 'confirm:plan-1' })
  })

  it('视觉任务创建失败后重试不重复上传并复用任务幂等键', async () => {
    const createVisionTask = vi.fn()
      .mockRejectedValueOnce(new Error('网络中断'))
      .mockResolvedValue({
        id: 'vision-1',
        household_id: 'h1',
        member_id: 'm1',
        file_id: 'stored.jpg',
        task_type: 'ocr',
        status: 'QUEUED',
        error_code: null,
        error_message: null,
        result: null,
        model_version: null,
        created_by: 'actor-1',
        created_at: '2026-08-19T08:00:00Z',
      })
    const uploadFile = vi.fn().mockResolvedValue({
      original_name: 'medicine.jpg',
      storage_key: 'stored.jpg',
      size_bytes: 42,
      hash_algo: 'sha256',
      hash: 'hash',
      extension: '.jpg',
    })
    const client = {
      checkVisionQuality: vi.fn().mockResolvedValue({
        decision: 'PASS',
        reasons: [],
        retake_prompts: [],
        metrics: {},
        quality_receipt: 'receipt',
      }),
      uploadFile,
      createVisionTask,
    } as unknown as ApiClient
    const provider = new HttpDataProvider(client, () => ({ actorId: 'actor-1', accessPurpose: 'family-care', householdId: '' }))
    const file = new File(['safe demo image'], 'medicine.jpg', { type: 'image/jpeg' })

    await expect(provider.recognizeMedicine(file, 'm1')).rejects.toThrow('网络中断')
    const result = await provider.recognizeMedicine(file, 'm1')

    expect(result.handoff?.taskId).toBe('vision-1')
    expect(uploadFile).toHaveBeenCalledTimes(1)
    expect(createVisionTask).toHaveBeenCalledTimes(2)
    const first = createVisionTask.mock.calls[0]
    const second = createVisionTask.mock.calls[1]
    expect(first?.[0].idempotency_key).toBeTruthy()
    expect(second?.[0].idempotency_key).toBe(first?.[0].idempotency_key)
    expect(second?.[1]).toMatchObject({ idempotencyKey: first?.[0].idempotency_key })
  })
})

describe('近 7 天完成趋势推导', () => {
  const now = new Date('2026-08-13T12:00:00Z')

  it('返回按时间升序的 7 天，最后一天标记为“今”', () => {
    const points = deriveWeeklyTrendFromEvents([], now, 'Asia/Shanghai')
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
    const points = deriveWeeklyTrendFromEvents(events, now, 'Asia/Shanghai')

    // 8-07 至 8-09：计划尚未创建
    expect(points[0]!.total).toBe(0)
    expect(points[2]!.total).toBe(0)
    // 8-10 起计划存在
    expect(points[3]!.total).toBe(1)
    expect(points[6]!.total).toBe(1)
    // 重复确认按最终服务端动作折叠，只在最后一次确认日计数
    expect(points[4]!.done).toBe(0)
    expect(points[6]!.done).toBe(1)
    // 8-12 无确认
    expect(points[5]!.done).toBe(0)
  })
  it('folds plan updates by stable plan_event_id and counts only the final confirmation', () => {
    const events = [
      makeEvent({ id: 'p1', event_type: 'plan_created', occurred_at: '2026-08-12T14:30:00Z' }),
      makeEvent({ id: 'u1', event_type: 'plan_updated', payload: { plan_event_id: 'p1' }, occurred_at: '2026-08-12T15:00:00Z' }),
      makeEvent({ id: 'a1', event_type: 'plan_deferred', payload: { plan_event_id: 'p1' }, occurred_at: '2026-08-13T00:10:00Z' }),
      makeEvent({ id: 'a2', event_type: 'plan_confirmed', payload: { plan_event_id: 'p1' }, occurred_at: '2026-08-13T00:20:00Z' }),
    ]
    const points = deriveWeeklyTrendFromEvents(events, now, 'Asia/Shanghai')
    expect(points[6]).toMatchObject({ total: 1, done: 1 })
  })

  it('returns no trend rather than applying the browser timezone when household timezone is absent', () => {
    expect(deriveWeeklyTrendFromEvents([], now)).toEqual([])
  })
  it('uses household calendar days across a DST transition instead of fixed 24-hour browser days', () => {
    const dstNow = new Date('2026-03-09T04:30:00Z')
    const points = deriveWeeklyTrendFromEvents([], dstNow, 'America/New_York')
    expect(points).toHaveLength(7)
    expect(points.map(point => point.label)).toEqual(['二', '三', '四', '五', '六', '日', '今'])
  })

  it('keeps a plan created before the window in totals after an in-window update', () => {
    const events = [
      makeEvent({ id: 'p-before', event_type: 'plan_created', occurred_at: '2026-08-01T03:00:00Z' }),
      makeEvent({ id: 'p-update', event_type: 'plan_updated', payload: { plan_event_id: 'p-before' }, occurred_at: '2026-08-12T03:00:00Z' }),
    ]
    const points = deriveWeeklyTrendFromEvents(events, now, 'Asia/Shanghai')
    expect(points[0]).toMatchObject({ total: 1, done: 0 })
    expect(points[6]).toMatchObject({ total: 1, done: 0 })
  })

  it('uses the latest action: a later defer or skip prevents an earlier confirmation from counting', () => {
    const events = [
      makeEvent({ id: 'p-final', event_type: 'plan_created', occurred_at: '2026-08-13T00:00:00Z' }),
      makeEvent({ id: 'c-final', event_type: 'plan_confirmed', payload: { plan_event_id: 'p-final' }, occurred_at: '2026-08-13T01:00:00Z' }),
      makeEvent({ id: 's-final', event_type: 'plan_skipped', payload: { plan_event_id: 'p-final' }, occurred_at: '2026-08-13T02:00:00Z' }),
    ]
    expect(deriveWeeklyTrendFromEvents(events, now, 'Asia/Shanghai')[6]).toMatchObject({ total: 1, done: 0 })
  })

  it('returns unavailable when a plan update or action has no stable relation or timestamp', () => {
    const orphanUpdate = [makeEvent({ id: 'u-orphan', event_type: 'plan_updated', occurred_at: '2026-08-13T01:00:00Z' })]
    const invalidAction = [makeEvent({ id: 'a-invalid', event_type: 'plan_confirmed', payload: { plan_event_id: 'p1' }, occurred_at: 'not-a-time' })]
    expect(deriveWeeklyTrendFromEvents(orphanUpdate, now, 'Asia/Shanghai')).toEqual([])
    expect(deriveWeeklyTrendFromEvents(invalidAction, now, 'Asia/Shanghai')).toEqual([])
  })
})

describe('多家庭选择与隔离（MOB-158）', () => {
  const two = [
    { id: 'hh-1', name: '王家' },
    { id: 'hh-2', name: '李家' },
  ]

  function providerFor(households: { id: string; name: string }[], selected: string) {
    const listHouseholds = vi.fn().mockResolvedValue(households)
    const listMembers = vi.fn().mockResolvedValue([])
    const listAuthorizations = vi.fn().mockResolvedValue([])
    const client = { listHouseholds, listMembers, listAuthorizations } as unknown as ApiClient
    const provider = new HttpDataProvider(client, () => ({
      actorId: 'actor-1',
      accessPurpose: 'family-care',
      householdId: selected,
    }))
    return { provider, listHouseholds, listMembers }
  }

  it('可访问多个家庭且未选择时 fail-closed，绝不默认取第一个', async () => {
    const { provider, listMembers } = providerFor(two, '')

    await expect(provider.listMembers()).rejects.toMatchObject({
      code: 'HOUSEHOLD_NOT_SELECTED',
      status: 409,
    })
    // 关键：没有任何成员请求被发出，也就不会显示某个家庭的数据。
    expect(listMembers).not.toHaveBeenCalled()
  })

  it('只有一个家庭时自动选定，保持低步骤体验', async () => {
    const { provider, listMembers } = providerFor([two[0]!], '')

    await provider.listMembers()

    expect(listMembers).toHaveBeenCalledWith('hh-1', expect.anything())
  })

  it('使用已选家庭而不是列表顺序', async () => {
    const { provider, listMembers } = providerFor(two, 'hh-2')

    await provider.listMembers()

    expect(listMembers).toHaveBeenCalledWith('hh-2', expect.anything())
  })

  it('列表顺序变化不改变已选家庭', async () => {
    const { provider, listMembers } = providerFor([two[1]!, two[0]!], 'hh-1')

    await provider.listMembers()

    expect(listMembers).toHaveBeenCalledWith('hh-1', expect.anything())
  })

  it('已选家庭被撤权或删除时报专用错误码，不自动切到另一个家庭', async () => {
    const { provider, listMembers } = providerFor([two[1]!], 'hh-1')

    await expect(provider.listMembers()).rejects.toMatchObject({
      code: 'HOUSEHOLD_UNAVAILABLE',
      status: 404,
    })
    expect(listMembers).not.toHaveBeenCalled()
  })

  it('没有任何可访问家庭时仍返回 NO_HOUSEHOLD', async () => {
    const { provider } = providerFor([], 'hh-1')

    await expect(provider.listMembers()).rejects.toMatchObject({
      code: 'NO_HOUSEHOLD',
      status: 404,
    })
  })

  it('listHouseholds 只暴露 ID 与名称', async () => {
    const listHouseholds = vi.fn().mockResolvedValue([
      { id: 'hh-1', name: '王家', created_by: 'actor-1', created_at: '2026-08-01T00:00:00Z' },
    ])
    const client = { listHouseholds } as unknown as ApiClient
    const provider = new HttpDataProvider(client, () => ({
      actorId: 'actor-1',
      accessPurpose: 'family-care',
      householdId: '',
    }))

    await expect(provider.listHouseholds()).resolves.toEqual([{ id: 'hh-1', name: '王家' }])
  })
})
