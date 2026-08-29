import { beforeEach, describe, expect, it, vi } from 'vitest'

const nativeMocks = vi.hoisted(() => ({
  createChannel: vi.fn(),
  checkPermissions: vi.fn(),
  requestPermissions: vi.fn(),
  schedule: vi.fn(),
  cancel: vi.fn(),
  getPending: vi.fn(),
}))

vi.mock('@capacitor/core', () => ({
  Capacitor: {
    isNativePlatform: () => true,
    getPlatform: () => 'android',
  },
}))

vi.mock('@capacitor/local-notifications', () => ({
  LocalNotifications: nativeMocks,
}))

import { createReminderPlatform, REMINDER_CHANNEL, REMINDER_CHANNEL_ID } from './reminderScheduler'

describe('Android 计划提醒平台（MOB-172）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    nativeMocks.createChannel.mockResolvedValue(undefined)
    nativeMocks.checkPermissions.mockResolvedValue({ display: 'granted' })
    nativeMocks.requestPermissions.mockResolvedValue({ display: 'granted' })
    nativeMocks.getPending.mockResolvedValue({ notifications: [] })
    nativeMocks.schedule.mockResolvedValue({ notifications: [] })
    nativeMocks.cancel.mockResolvedValue(undefined)
  })

  it('先创建私有通道，再检查权限并带通道安排提醒', async () => {
    const platform = createReminderPlatform()

    await expect(platform.permission()).resolves.toBe('granted')
    expect(nativeMocks.createChannel).toHaveBeenCalledWith(REMINDER_CHANNEL)

    await platform.schedule([{
      id: 101,
      at: new Date('2030-01-01T08:00:00.000Z'),
      title: '家健镜提醒',
      body: '请打开应用查看今日安排。',
    }])
    expect(nativeMocks.schedule).toHaveBeenCalledWith({
      notifications: [expect.objectContaining({
        id: 101,
        channelId: REMINDER_CHANNEL_ID,
        body: '请打开应用查看今日安排。',
        extra: { hct_reminder: 'v1' },
      })],
    })
  })

  it('私有通道创建失败时拒绝安排，避免回退到未知锁屏策略', async () => {
    nativeMocks.createChannel.mockRejectedValueOnce(new Error('channel unavailable'))
    const platform = createReminderPlatform()

    await expect(platform.permission()).resolves.toBe('denied')
    expect(nativeMocks.checkPermissions).not.toHaveBeenCalled()
    expect(nativeMocks.schedule).not.toHaveBeenCalled()
  })
})
