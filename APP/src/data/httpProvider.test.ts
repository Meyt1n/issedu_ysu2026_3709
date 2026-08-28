import { describe, expect, it, vi } from 'vitest'

import { ApiClient, ApiClientError } from '@/api/client'
import type { HealthEvent } from '@/api/types'
import type { CareTask } from './types'

import { authorizationStatus, deriveTaskActionHistory, deriveTasksFromEvents, deriveWeeklyTrendFromEvents, environmentActionUnavailable, HttpDataProvider, normalizeServerTimestamp } from './httpProvider'
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

  it('只消费服务端升级事件，并在无授权通知时失败关闭', () => {
    const events = [
      makeEvent({ id: 'p1', event_type: 'plan_created', payload: { drug: 'A药', schedule: '每日' } }),
      makeEvent({
        id: 'e1',
        event_type: 'care_escalated',
        payload: {
          plan_event_id: 'p1',
          automation_key: 'escalate:p1:2026-08-13T00:00:00Z',
          reason: 'MISSED_DOSE_ESCALATION',
          due_at: '2026-08-13T01:00:00Z',
          notify_caregivers: false,
        },
      }),
    ]

    const [task] = deriveTasksFromEvents(events, 'm1', '王秀兰')
    expect(task).toMatchObject({
      status: 'ESCALATED',
      escalation: {
        status: 'UNAVAILABLE',
        target: 'NONE',
        reason: '服务端记录了连续未确认任务，需要授权照护者关注。',
        auditEventId: 'e1',
        dueAt: '2026-08-13T01:00:00Z',
      },
    })
    expect(task?.escalation?.nextStep).toContain('120')
  })

  it('有效授权只展示服务端通知回执，不展示照护者身份或授权 ID', () => {
    const events = [
      makeEvent({ id: 'p1', event_type: 'plan_created', payload: { drug: 'A药' } }),
      makeEvent({
        id: 'e1',
        event_type: 'care_escalated',
        payload: { plan_event_id: 'p1', automation_key: 'auto-1', reason: 'MISSED_DOSE_ESCALATION', notify_caregivers: true },
      }),
      makeEvent({
        id: 'n1',
        event_type: 'caregiver_notified',
        payload: {
          plan_event_id: 'p1',
          escalation_automation_key: 'auto-1',
          recipient_actor_id: 'caregiver-secret',
          authorization_id: 'auth-secret',
          delivery_status: 'QUEUED',
        },
      }),
    ]

    const [task] = deriveTasksFromEvents(events, 'm1', '王秀兰')
    expect(task?.escalation).toMatchObject({
      status: 'QUEUED',
      target: 'AUTHORIZED_CAREGIVER',
      auditEventId: 'e1',
      notificationEventId: 'n1',
    })
    expect(JSON.stringify(task?.escalation)).not.toContain('caregiver-secret')
    expect(JSON.stringify(task?.escalation)).not.toContain('auth-secret')
  })

  it('只有通知回执能证明目标有效；升级意图没有回执时不展示照护者目标', () => {
    const events = [
      makeEvent({ id: 'p1', event_type: 'plan_created', payload: { drug: 'A药' } }),
      makeEvent({
        id: 'e1',
        event_type: 'care_escalated',
        payload: { plan_event_id: 'p1', reason: 'MISSED_DOSE_ESCALATION', notify_caregivers: true },
      }),
    ]

    const [task] = deriveTasksFromEvents(events, 'm1', '王秀兰')
    expect(task?.escalation).toMatchObject({
      status: 'CREATED',
      target: 'NONE',
      nextStep: '等待服务端通知回执；当前不显示照护者身份，也不尝试本地通知。',
    })
  })

  it('动作发生在升级之后时，不把旧升级重新显示为当前状态', () => {
    const events = [
      makeEvent({ id: 'p1', event_type: 'plan_created', payload: { drug: 'A药' } }),
      makeEvent({ id: 'e1', event_type: 'care_escalated', payload: { plan_event_id: 'p1', notify_caregivers: true }, occurred_at: '2026-08-13T01:00:00Z' }),
      makeEvent({ id: 'a1', event_type: 'plan_confirmed', payload: { plan_event_id: 'p1' }, occurred_at: '2026-08-13T02:00:00Z' }),
    ]

    const [task] = deriveTasksFromEvents(events, 'm1', '王秀兰')
    expect(task?.status).toBe('CONFIRMED')
    expect(task?.escalation).toBeUndefined()
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

describe('首页健康资讯（MOB-159）', () => {
  it('把家庭服务器资讯响应透传，并携带当前访问目的', async () => {
    const response = {
      status: 'ok' as const,
      cache_status: 'fresh' as const,
      season: 'summer',
      generated_at: '2026-08-28T04:00:00.000Z',
      fetched_at: '2026-08-28T04:00:00.000Z',
      disclaimer: '仅供教学演示',
      items: [],
    }
    const getHealthNews = vi.fn().mockResolvedValue(response)
    const client = { getHealthNews } as unknown as ApiClient
    const provider = new HttpDataProvider(client, () => ({
      actorId: 'actor-1',
      accessPurpose: 'family-care',
      householdId: 'h1',
    }))

    await expect(provider.getHealthNews()).resolves.toBe(response)
    expect(getHealthNews).toHaveBeenCalledWith(expect.objectContaining({
      actorId: 'actor-1',
      accessPurpose: 'family-care',
    }))
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

  it('MOB-149：视频质量门映射帧统计并返回抽帧摘要', async () => {
    const client = {
      checkVisionQuality: vi.fn().mockResolvedValue({
        decision: 'PASS',
        reasons: [],
        retake_prompts: [],
        metrics: { decoded_frames: 90, sampled_frames: 3, selected_frames: 3, usable_frames: 3 },
        quality_receipt: 'video-receipt',
        media_type: 'video',
      }),
    } as unknown as ApiClient
    const provider = new HttpDataProvider(client, () => ({ actorId: 'actor-1', accessPurpose: 'family-care', householdId: '' }))
    const file = new File([new Uint8Array(40_000)], 'clip.mp4', { type: 'video/mp4' })

    const quality = await provider.checkVideoQuality(file)

    expect(client.checkVisionQuality).toHaveBeenCalledWith(file, 'video', expect.anything())
    expect(quality.decision).toBe('PASS')
    expect(quality.framesSummary).toMatchObject({ mediaType: 'video', sampledFrames: 3, selectedFrames: 3, usableFrames: 3 })
    const labels = quality.metrics.map(metric => metric.label)
    expect(labels).toContain('采样帧数')
    expect(quality.metrics.every(metric => metric.passed)).toBe(true)
  })

  it('MOB-149：recognizeMedicine 视频路径携带 media_type 且幂等键带视频前缀', async () => {
    const createVisionTask = vi.fn().mockResolvedValue({
      id: 'vision-video-1',
      household_id: 'h1',
      member_id: 'm1',
      file_id: 'stored.mp4',
      media_type: 'video',
      task_type: 'ocr',
      status: 'QUEUED',
      error_code: null,
      error_message: null,
      result: null,
      model_version: null,
      created_by: 'actor-1',
      created_at: '2026-08-23T08:00:00Z',
    })
    const uploadFile = vi.fn().mockResolvedValue({
      original_name: 'clip.mp4',
      storage_key: 'stored.mp4',
      size_bytes: 42,
      hash_algo: 'sha256',
      hash: 'hash',
      extension: '.mp4',
    })
    const client = {
      checkVisionQuality: vi.fn().mockResolvedValue({
        decision: 'PASS',
        reasons: [],
        retake_prompts: [],
        metrics: { sampled_frames: 2, selected_frames: 2, usable_frames: 2 },
        quality_receipt: 'video-receipt',
      }),
      uploadFile,
      createVisionTask,
    } as unknown as ApiClient
    const provider = new HttpDataProvider(client, () => ({ actorId: 'actor-1', accessPurpose: 'family-care', householdId: '' }))
    const file = new File([new Uint8Array(40_000)], 'clip.mp4', { type: 'video/mp4' })

    const result = await provider.recognizeMedicine(file, 'm1', 'video')

    expect(client.checkVisionQuality).toHaveBeenCalledWith(file, 'video', expect.anything())
    expect(createVisionTask.mock.calls[0]?.[0]).toMatchObject({
      file_id: 'stored.mp4',
      media_type: 'video',
      quality_receipt: 'video-receipt',
    })
    expect(String(createVisionTask.mock.calls[0]?.[0].idempotency_key)).toMatch(/^vision-video:/)
    expect(result.handoff?.taskId).toBe('vision-video-1')
    expect(result.fields.some(field => field.label === '媒体类型' && field.value === 'video')).toBe(true)
  })

  it('MOB-149：视频未过质量门时不创建任务不上传', async () => {
    const uploadFile = vi.fn()
    const createVisionTask = vi.fn()
    const client = {
      checkVisionQuality: vi.fn().mockResolvedValue({
        decision: 'RETAKE',
        reasons: ['没有可用证据帧'],
        retake_prompts: ['请保持药盒稳定'],
        metrics: { usable_frames: 0 },
        quality_receipt: null,
      }),
      uploadFile,
      createVisionTask,
    } as unknown as ApiClient
    const provider = new HttpDataProvider(client, () => ({ actorId: 'actor-1', accessPurpose: 'family-care', householdId: '' }))
    const file = new File([new Uint8Array(40_000)], 'clip.mp4', { type: 'video/mp4' })

    await expect(provider.recognizeMedicine(file, 'm1', 'video')).rejects.toThrow('视频未通过抽帧质量门控')
    expect(uploadFile).not.toHaveBeenCalled()
    expect(createVisionTask).not.toHaveBeenCalled()
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

describe('服务端风险审计元数据（MOB-156）', () => {
  const member = {
    id: 'm-1',
    household_id: 'hh-1',
    display_name: '合成成员',
    role: 'SELF',
    actor_id: 'actor-1',
    created_at: '2026-08-20T00:00:00Z',
  }

  function providerForRisk(alertPatch: Record<string, unknown> = {}, listPatch: Record<string, unknown> = {}) {
    const listMemberRisks = vi.fn().mockResolvedValue({
      member_id: member.id,
      alerts: [{
        rule_id: 'risk-1',
        level: 'SEVERE',
        message: '合成严重风险',
        source_event_ids: ['event-1', 'event-2'],
        created_at: '2026-08-20T02:00:00Z',
        rule_version: 'rules-v7',
        risk_fingerprint: 'f'.repeat(64),
        acknowledgement: null,
        deduplication_key: 'dedup-1',
        merged_count: 2,
        budget_status: 'VISIBLE',
        budget_reason: '严重信号不受普通预算压制',
        next_visible_at: '2026-08-21T02:00:00Z',
        valid_until: '2026-08-21T02:00:00Z',
        evidence_summary: '2 条脱敏来源事件',
        ...alertPatch,
      }],
      total: 1,
      severe_count: 1,
      warning_count: 0,
      ruleset_version: 'rules-v7',
      non_severe_budget: 10,
      suppressed_count: 3,
      ...listPatch,
    })
    const client = {
      listHouseholds: vi.fn().mockResolvedValue([{ id: 'hh-1', name: '合成家庭' }]),
      listMembers: vi.fn().mockResolvedValue([member]),
      listMemberRisks,
    } as unknown as ApiClient
    const provider = new HttpDataProvider(client, () => ({
      actorId: 'actor-1',
      accessPurpose: 'family-care',
      householdId: 'hh-1',
    }))
    return { provider, listMemberRisks }
  }

  it('只映射服务端规则版本、预算、指纹和完整审计字段', async () => {
    const { provider } = providerForRisk()

    const risks = await provider.listRisks()
    const summary = await provider.getRiskSummary()

    expect(risks[0]).toMatchObject({
      ruleVersion: 'rules-v7',
      riskFingerprint: 'f'.repeat(64),
      acknowledged: false,
      audit: {
        deduplicationKey: 'dedup-1',
        mergedCount: 2,
        budgetStatus: 'VISIBLE',
        validUntil: '2026-08-21T02:00:00Z',
        complete: true,
      },
    })
    expect(summary).toEqual({
      rulesetVersion: 'rules-v7',
      nonSevereBudget: 10,
      suppressedCount: 3,
      total: 1,
      severeCount: 1,
      warningCount: 0,
      complete: true,
    })
  })

  it('缺少服务端审计字段时不回退 rules-v0、预算默认值或本地推断', async () => {
    const { provider } = providerForRisk(
      {
        rule_version: null,
        risk_fingerprint: null,
        deduplication_key: null,
        merged_count: null,
        budget_status: null,
        budget_reason: null,
        next_visible_at: null,
        valid_until: null,
        evidence_summary: null,
      },
      { ruleset_version: null, non_severe_budget: null, suppressed_count: null },
    )

    const risks = await provider.listRisks()
    const summary = await provider.getRiskSummary()

    expect(risks[0]?.ruleVersion).toBeNull()
    expect(risks[0]?.audit.complete).toBe(false)
    expect(risks[0]?.audit.mergedCount).toBeNull()
    expect(summary.complete).toBe(false)
    expect(summary.nonSevereBudget).toBeNull()
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

  it('无效服务端时间排在有效时间之后，并以事件 ID 保证稳定顺序', () => {
    const events = [
      makeEvent({ id: 'p1', event_type: 'plan_created', payload: { drug: 'C药', schedule: '每日' } }),
      makeEvent({ id: 'a-invalid', event_type: 'plan_skipped', payload: { plan_event_id: 'p1' }, occurred_at: 'not-a-date' }),
      makeEvent({ id: 'a-valid', event_type: 'plan_confirmed', payload: { plan_event_id: 'p1' }, occurred_at: '2026-08-22T02:00:00Z' }),
    ]

    const entries = deriveTaskActionHistory(events, 'm1', '成员')
    expect(entries.map(entry => entry.eventId)).toEqual(['a-valid', 'a-invalid'])
    expect(entries[1]?.serverTime).toBe('not-a-date')
  })

  it('升级与通知事件作为服务端审计回执进入历史，不携带授权者敏感标识', () => {
    const events = [
      makeEvent({ id: 'p1', event_type: 'plan_created', payload: { drug: 'A药', schedule: '每日' } }),
      makeEvent({ id: 'e1', event_type: 'care_escalated', payload: { plan_event_id: 'p1', reason: 'MISSED_DOSE_ESCALATION' }, occurred_at: '2026-08-22T01:00:00Z' }),
      makeEvent({ id: 'n1', event_type: 'caregiver_notified', payload: { plan_event_id: 'p1', recipient_actor_id: 'private-caregiver', authorization_id: 'private-auth', delivery_status: 'QUEUED' }, occurred_at: '2026-08-22T02:00:00Z' }),
    ]

    const entries = deriveTaskActionHistory(events, 'm1', '成员')
    expect(entries.map(entry => entry.eventId)).toEqual(['n1', 'e1'])
    expect(entries[0]).toMatchObject({ action: 'caregiver_notify', actionLabel: '通知授权照护者', finalStatus: 'ESCALATED', receipt: 'RECEIPTED' })
    expect(entries[1]).toMatchObject({ action: 'escalate', actionLabel: '升级照护者', finalStatus: 'ESCALATED', receipt: 'RECEIPTED' })
    expect(JSON.stringify(entries)).not.toContain('private-caregiver')
    expect(JSON.stringify(entries)).not.toContain('private-auth')
  })
})

describe('授权范围只读呈现（MOB-136）', () => {
  const now = new Date('2026-08-23T12:00:00Z')

  it('授权状态只由服务端时间/撤回字段推导，解析失败按已到期 fail-closed', () => {
    const base = { valid_from: '2026-08-01T00:00:00Z', valid_until: '2026-09-01T00:00:00Z', revoked_at: null as string | null }
    expect(authorizationStatus(base, now)).toBe('ACTIVE')
    expect(authorizationStatus({ ...base, valid_until: '2026-08-28T00:00:00Z' }, now)).toBe('EXPIRING')
    expect(authorizationStatus({ ...base, valid_until: '2026-08-20T00:00:00Z' }, now)).toBe('EXPIRED')
    expect(authorizationStatus({ ...base, revoked_at: '2026-08-22T00:00:00Z' }, now)).toBe('REVOKED')
    expect(authorizationStatus({ ...base, valid_from: '2026-09-01T00:00:00Z', valid_until: '2026-10-01T00:00:00Z' }, now)).toBe('PENDING')
    expect(authorizationStatus({ ...base, valid_until: 'not-a-date' }, now)).toBe('EXPIRED')
  })

  function authRead(patch: Record<string, unknown> = {}) {
    return {
      id: 'auth-1',
      household_id: 'h1',
      member_id: 'm1',
      grantor_actor_id: 'owner-1',
      grantee_actor_id: 'care-1',
      data_fields: ['health_events'],
      actions: ['READ_EVENTS'],
      purpose: 'family-care',
      valid_from: '2026-08-01T00:00:00Z',
      valid_until: '2099-01-01T00:00:00Z',
      revoked_at: null,
      version: 3,
      created_at: '2026-08-01T00:00:00Z',
      updated_at: '2026-08-01T00:00:00Z',
      ...patch,
    }
  }

  it('Owner 视角映射完整字段并按成员过滤', async () => {
    const provider = new HttpDataProvider(
      {
        listHouseholds: vi.fn().mockResolvedValue([{ id: 'h1' }]),
        listMembers: vi.fn().mockResolvedValue([
          { id: 'm1', display_name: '王秀兰', role: 'DEPENDENT' },
          { id: 'm2', display_name: '李建国', role: 'DEPENDENT' },
        ]),
        listMemberTimeline: vi.fn().mockResolvedValue([]),
        listAuthorizations: vi.fn().mockResolvedValue([authRead(), authRead({ id: 'auth-2', member_id: 'm2' })]),
      } as unknown as ApiClient,
      () => ({ actorId: 'owner-1', accessPurpose: 'family-care', householdId: 'h1' }),
    )

    const detail = await provider.getMemberDetail('m1')
    expect(detail.authorizations).not.toBe('UNAUTHORIZED')
    expect(detail.authorizations).toHaveLength(1)
    expect(detail.authorizations![0]).toMatchObject({
      id: 'auth-1',
      granteeActorId: 'care-1',
      granteeName: 'care-1',
      fields: ['health_events'],
      actions: ['READ_EVENTS'],
      purpose: 'family-care',
      version: 3,
      status: 'ACTIVE',
    })
    expect(listAuthCall(provider)).toHaveBeenCalledWith('h1', expect.anything())
  })

  it('非 Owner 的 403/404 是隐藏式拒绝 → UNAUTHORIZED，与"暂无授权"区分；其他异常如实抛出', async () => {
    const unauthorized = new HttpDataProvider(
      {
        listHouseholds: vi.fn().mockResolvedValue([{ id: 'h1' }]),
        listMembers: vi.fn().mockResolvedValue([{ id: 'm1', display_name: '王秀兰', role: 'DEPENDENT' }]),
        listMemberTimeline: vi.fn().mockResolvedValue([]),
        listAuthorizations: vi.fn().mockRejectedValue(new ApiClientError('no', { status: 404, code: 'NOT_FOUND' })),
      } as unknown as ApiClient,
      () => ({ actorId: 'care-1', accessPurpose: 'family-care', householdId: 'h1' }),
    )
    const detail = await unauthorized.getMemberDetail('m1')
    expect(detail.authorizations).toBe('UNAUTHORIZED')

    const broken = new HttpDataProvider(
      {
        listHouseholds: vi.fn().mockResolvedValue([{ id: 'h1' }]),
        listMembers: vi.fn().mockResolvedValue([{ id: 'm1', display_name: '王秀兰', role: 'DEPENDENT' }]),
        listMemberTimeline: vi.fn().mockResolvedValue([]),
        listAuthorizations: vi.fn().mockRejectedValue(new ApiClientError('boom', { status: 502, code: 'HTTP_ERROR' })),
      } as unknown as ApiClient,
      () => ({ actorId: 'owner-1', accessPurpose: 'family-care', householdId: 'h1' }),
    )
    await expect(broken.getMemberDetail('m1')).rejects.toMatchObject({ status: 502 })
  })

  function listAuthCall(provider: HttpDataProvider) {
    const client = (provider as unknown as { client: { listAuthorizations: ReturnType<typeof vi.fn> } }).client
    return client.listAuthorizations
  }
})

describe('服务端时间戳的时区语义（MOB-143）', () => {
  it('缺时区标识的服务端串按 UTC 解释，不随浏览器时区漂移', () => {
    // 后端当前返回 naive 串；Date.parse 会按本地时区解释它。
    expect(normalizeServerTimestamp('2026-08-26T01:56:09.853583'))
      .toBe('2026-08-26T01:56:09.853583Z')
    expect(Date.parse(normalizeServerTimestamp('2026-08-26T01:56:09.853583')))
      .toBe(Date.parse('2026-08-26T01:56:09.853Z'))
  })

  it('已带 Z 或偏移的串保持原样，后端补标识后无需再改本函数', () => {
    expect(normalizeServerTimestamp('2026-08-26T01:56:09Z')).toBe('2026-08-26T01:56:09Z')
    expect(normalizeServerTimestamp('2026-08-26T09:56:09+08:00')).toBe('2026-08-26T09:56:09+08:00')
    expect(normalizeServerTimestamp('2026-08-26T09:56:09-0400')).toBe('2026-08-26T09:56:09-0400')
  })

  it('纯日期串不加标识（ISO 已按 UTC 处理），空串原样返回', () => {
    expect(normalizeServerTimestamp('2026-08-26')).toBe('2026-08-26')
    expect(normalizeServerTimestamp('')).toBe('')
  })

  it('趋势按家庭时区分日：同一 naive 时间戳在东八区不再被提前一天', () => {
    const events = [
      {
        id: 'plan-1',
        event_type: 'plan_created',
        occurred_at: '2026-08-26T01:56:09.100000',
        created_at: '2026-08-26T01:56:09',
        payload: { drug: '演示药', schedule: '每日 1 次' },
      },
      {
        id: 'confirm-1',
        event_type: 'plan_confirmed',
        occurred_at: '2026-08-26T01:56:09.800000',
        created_at: '2026-08-26T01:56:09',
        payload: { plan_event_id: 'plan-1' },
      },
    ] as unknown as HealthEvent[]

    const now = new Date('2026-08-26T02:30:00Z')
    const trend = deriveWeeklyTrendFromEvents(events, now, 'UTC')

    expect(trend).toHaveLength(7)
    // 事件发生在 UTC 08-26，因此必须计在窗口最后一天（今天），而不是前一天。
    expect(trend[6]).toMatchObject({ label: '今', total: 1, done: 1 })
    expect(trend[5]!.done).toBe(0)
  })
})
