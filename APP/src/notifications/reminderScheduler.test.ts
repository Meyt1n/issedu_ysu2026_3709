import { describe, expect, it } from 'vitest'

import type { CareTask } from '@/data/types'

import { ReminderScheduler, REMINDER_CHANNEL, REMINDER_CHANNEL_ID, toNativeReminder, type ReminderPlatform } from './reminderScheduler'

function task(overrides: Partial<CareTask> = {}): CareTask {
  return {
    id: 'task-1',
    memberId: 'member-1',
    memberName: '成员姓名不应进入通知',
    title: '药品名称不应进入通知',
    detail: '健康正文不应进入通知',
    level: 'GENERAL',
    dueAt: '2030-01-01T08:00:00.000Z',
    status: 'PENDING',
    planEventId: 'plan-1',
    reminder: {
      authorization: 'AUTHORIZED',
      planVersion: 'plan-v3',
      deduplicationKey: 'reminder-plan-1-v3',
      firstReminderAt: '2030-01-01T08:00:00.000Z',
      repeatReminderAt: '2030-01-01T08:15:00.000Z',
      maxReminders: 2,
    },
    ...overrides,
  }
}

function platform(overrides: Partial<ReminderPlatform> = {}): ReminderPlatform & { scheduled: Array<{ id: number; title: string; body: string }>; cancelled: number[] } {
  const scheduled: Array<{ id: number; title: string; body: string }> = []
  const cancelled: number[] = []
  return {
    kind: 'android',
    async permission() { return 'granted' },
    async schedule(next) { scheduled.push(...next) },
    async cancel(ids) { cancelled.push(...ids) },
    scheduled,
    cancelled,
    ...overrides,
  }
}

describe('ReminderScheduler', () => {
  it('使用私有计划提醒通道并固定脱敏通知载荷', () => {
    const native = toNativeReminder({
      id: 7,
      at: new Date('2030-01-01T08:00:00.000Z'),
      title: '家健镜提醒',
      body: '请打开应用查看今日安排。',
    })

    expect(REMINDER_CHANNEL).toMatchObject({
      id: REMINDER_CHANNEL_ID,
      visibility: 0,
      description: expect.not.stringMatching(/成员|药品|健康正文/),
    })
    expect(native).toMatchObject({
      channelId: REMINDER_CHANNEL_ID,
      extra: { hct_reminder: 'v1' },
      isExactNotification: false,
      schedule: { allowWhileIdle: true },
    })
    expect(native.body).toBe('请打开应用查看今日安排。')
  })

  it('只调度有完整授权和版本证据的提醒，通知不含健康正文', async () => {
    const native = platform()
    const scheduler = new ReminderScheduler(native)

    const result = await scheduler.sync([task(), task({ id: 'unsafe', reminder: undefined })])

    expect(result.status).toBe('SCHEDULED')
    expect(native.scheduled).toHaveLength(2)
    for (const notification of native.scheduled) {
      expect(notification.title).toBe('家健镜提醒')
      expect(notification.body).toBe('请打开应用查看今日安排。')
      expect(notification.body).not.toMatch(/成员|药品|健康/)
    }
  })

  it('同一计划版本重复同步不会重复安排，并在任务状态变化后取消', async () => {
    const native = platform()
    const scheduler = new ReminderScheduler(native)

    await scheduler.sync([task()])
    await scheduler.sync([task()])
    expect(native.scheduled).toHaveLength(2)

    await scheduler.sync([task({ status: 'CONFIRMED' })])
    expect(native.cancelled).toHaveLength(2)
  })

  it('权限拒绝和 PWA 都明确降级，不声称已提醒', async () => {
    const denied = new ReminderScheduler(platform({ async permission() { return 'denied' } }))
    await expect(denied.sync([task()])).resolves.toMatchObject({ status: 'PERMISSION_DENIED' })

    const pwa = new ReminderScheduler(platform({ kind: 'pwa' }))
    await expect(pwa.sync([task()])).resolves.toMatchObject({ status: 'UNAVAILABLE' })
  })

  it('撤权、登出和成员切换可取消当前上下文的全部提醒', async () => {
    const native = platform()
    const scheduler = new ReminderScheduler(native)
    await scheduler.sync([task()])

    await scheduler.cancelAll()
    expect(native.cancelled).toHaveLength(2)
  })
})
