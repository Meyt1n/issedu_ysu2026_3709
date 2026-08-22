import { describe, expect, it, vi } from 'vitest'

import { ApiClient } from '@/api/client'
import type { HealthEvent } from '@/api/types'
import type { CareTask } from './types'

import { deriveTaskActionHistory, deriveTasksFromEvents, deriveWeeklyTrendFromEvents, environmentActionUnavailable, HttpDataProvider } from './httpProvider'
import { clearCapabilities, setCapabilities } from '@/stores/capabilities'

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

describe('环境行动卡的受控降级（MOB-157）', () => {
  it('服务端未声明能力时不把旧环境数据或本地推断显示为行动卡', () => {
    clearCapabilities()
    expect(environmentActionUnavailable()).toMatchObject({ availability: 'UNAVAILABLE', card: null })
  })

  it('只映射带完整授权、版本和去重键的服务端提醒契约', () => {
    const complete = makeEvent({
      id: 'p-reminder',
      event_type: 'plan_created',
      payload: {
        reminder: {
          authorization: 'AUTHORIZED', plan_version: 'v3', deduplication_key: 'plan-v3',
          first_reminder_at: '2030-01-01T08:00:00.000Z', repeat_reminder_at: '2030-01-01T08:15:00.000Z', max_reminders: 2,
        },
      },
    })
    const incomplete = makeEvent({
      id: 'p-incomplete',
      event_type: 'plan_created',
      payload: { reminder: { authorization: 'AUTHORIZED', plan_version: 'v3' } },
    })

    const [authorized, rejected] = deriveTasksFromEvents([complete, incomplete], 'm1', '王秀兰')
    expect(authorized!.reminder).toMatchObject({ planVersion: 'v3', deduplicationKey: 'plan-v3', maxReminders: 2 })
    expect(rejected!.reminder).toBeUndefined()
  })

  it('即使声明能力，缺少成员授权和审计元数据契约时仍拒绝请求天气接口', () => {
    setCapabilities({ phase: 'test', available: ['environment-action-card'], unavailable: [] })
    expect(environmentActionUnavailable()).toMatchObject({ availability: 'UNAVAILABLE', card: null })
    clearCapabilities()
  })
})

describe('视觉任务状态回查（MOB-132）', () => {
  function visionTask(patch: Record<string, unknown> = {}) {
    return {
      id: 'vision-1',
      household_id: 'h1',
      member_id: 'm1',
      file_id: 'stored.jpg',
      task_type: 'ocr',
      status: 'running',
      error_code: null,
      error_message: null,
      result: null,
      model_version: 'fusion-v1',
      created_by: 'actor-1',
      created_at: '2026-08-22T08:00:00Z',
      ...patch,
    }
  }

  it('回查走 GET 单任务端点并映射状态、终态与下一步说明', async () => {
    const getVisionTask = vi.fn().mockResolvedValue(visionTask({ status: 'SUCCEEDED' }))
    const client = { getVisionTask } as unknown as ApiClient
    const provider = new HttpDataProvider(client, () => ({ actorId: 'actor-1', accessPurpose: 'family-care', householdId: 'h1' }))

    const snapshot = await provider.fetchVisionTaskStatus('vision-1')

    expect(getVisionTask).toHaveBeenCalledWith('vision-1', expect.objectContaining({ actorId: 'actor-1' }))
    expect(snapshot).toMatchObject({
      taskId: 'vision-1',
      status: 'succeeded',
      terminal: true,
      modelVersion: 'fusion-v1',
    })
    expect(snapshot.nextStep).toContain('人工复核中心')
  })

  it('failed/timeout 带出服务端错误码；queued/running 非终态', async () => {
    const failed = visionTask({ status: 'failed', error_code: 'OCR_UNAVAILABLE', error_message: 'engine offline' })
    const provider = new HttpDataProvider(
      { getVisionTask: vi.fn().mockResolvedValueOnce(failed).mockResolvedValueOnce(visionTask({ status: 'queued' })) } as unknown as ApiClient,
      () => ({ actorId: 'actor-1', accessPurpose: 'family-care', householdId: 'h1' }),
    )

    const failedSnapshot = await provider.fetchVisionTaskStatus('vision-1')
    expect(failedSnapshot.terminal).toBe(true)
    expect(failedSnapshot.errorCode).toBe('OCR_UNAVAILABLE')
    expect(failedSnapshot.errorMessage).toBe('engine offline')

    const queuedSnapshot = await provider.fetchVisionTaskStatus('vision-1')
    expect(queuedSnapshot.terminal).toBe(false)
    expect(queuedSnapshot.nextStep).toContain('不会重复创建任务')
  })

  it('未知状态停止自动回查且不当作成功', async () => {
    const provider = new HttpDataProvider(
      { getVisionTask: vi.fn().mockResolvedValue(visionTask({ status: 'paused-by-admin' })) } as unknown as ApiClient,
      () => ({ actorId: 'actor-1', accessPurpose: 'family-care', householdId: 'h1' }),
    )
    const snapshot = await provider.fetchVisionTaskStatus('vision-1')
    expect(snapshot.terminal).toBe(true)
    expect(snapshot.status).toBe('paused-by-admin')
    expect(snapshot.nextStep).toContain('未定义的状态')
  })
})

describe('任务操作历史推导（MOB-135）', () => {
  it('动作事件带任务/成员/服务端时间/回执标识与最终状态', () => {
    const events = [
      makeEvent({
        id: 'p1',
        event_type: 'plan_created',
        payload: { drug: '氨氯地平片', schedule: '每日早餐后' },
      }),
      makeEvent({
        id: 'a1',
        event_type: 'plan_confirmed',
        payload: { plan_event_id: 'p1' },
        occurred_at: '2026-08-22T01:00:00Z',
      }),
    ]
    const entries = deriveTaskActionHistory(events, 'm1', '王秀兰（演示）')

    expect(entries).toHaveLength(1)
    expect(entries[0]).toMatchObject({
      eventId: 'a1',
      action: 'confirm',
      actionLabel: '确认',
      taskTitle: '氨氯地平片：每日早餐后',
      memberName: '王秀兰（演示）',
      memberId: 'm1',
      serverTime: '2026-08-22T01:00:00Z',
      finalStatus: 'CONFIRMED',
      receipt: 'RECEIPTED',
    })
  })

  it('同一计划重复动作只计一条有效回执，更早动作标注覆盖且不重复计数', () => {
    const events = [
      makeEvent({ id: 'p1', event_type: 'plan_created', payload: { drug: 'A药', schedule: '每日' } }),
      makeEvent({ id: 'a1', event_type: 'plan_deferred', payload: { plan_event_id: 'p1', delay_hours: 1 }, occurred_at: '2026-08-22T01:00:00Z' }),
      makeEvent({ id: 'a2', event_type: 'plan_confirmed', payload: { plan_event_id: 'p1' }, occurred_at: '2026-08-22T02:00:00Z' }),
    ]
    const entries = deriveTaskActionHistory(events, 'm1', '成员')

    expect(entries).toHaveLength(2)
    expect(entries.filter(e => e.receipt === 'RECEIPTED')).toHaveLength(1)
    expect(entries[0]).toMatchObject({ eventId: 'a2', receipt: 'RECEIPTED', finalStatus: 'CONFIRMED' })
    expect(entries[1]).toMatchObject({ eventId: 'a1', receipt: 'SUPERSEDED', finalStatus: 'CONFIRMED' })
    expect(entries[1]!.note).toContain('覆盖')
    // 按服务端时间倒序
    expect(Date.parse(entries[0]!.serverTime)).toBeGreaterThan(Date.parse(entries[1]!.serverTime))
  })

  it('无动作事件时返回空数组；列表TaskActionHistory走时间线端点', async () => {
    expect(deriveTaskActionHistory([makeEvent({ id: 'p1', event_type: 'plan_created', payload: {} })], 'm1', '成员')).toEqual([])

    const listMemberTimeline = vi.fn().mockResolvedValue([
      makeEvent({ id: 'p1', event_type: 'plan_created', payload: { drug: 'B药', schedule: '每晚' } }),
      makeEvent({ id: 'a1', event_type: 'plan_skipped', payload: { plan_event_id: 'p1', reason: '外出' } }),
    ])
    const listMembers = vi.fn().mockResolvedValue([{ id: 'm1', display_name: '成员', role: 'DEPENDENT' }])
    const client = { listMemberTimeline, listMembers, listHouseholds: vi.fn().mockResolvedValue([{ id: 'h1' }]) } as unknown as ApiClient
    const provider = new HttpDataProvider(client, () => ({ actorId: 'actor-1', accessPurpose: 'family-care', householdId: 'h1' }))

    const entries = await provider.listTaskActionHistory('m1')
    expect(listMemberTimeline).toHaveBeenCalledWith('h1', 'm1', expect.anything())
    expect(entries).toHaveLength(1)
    expect(entries[0]).toMatchObject({ action: 'skip', actionLabel: '跳过', finalStatus: 'SKIPPED', receipt: 'RECEIPTED' })
  })
})
