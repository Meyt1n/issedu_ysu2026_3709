import { afterEach, describe, expect, it, vi } from 'vitest'

import { notifyVisionTaskTerminal, requestVisionNoticePermission, visionNoticeSupport } from './localNotice'

type PermissionState = 'granted' | 'denied' | 'default'

class FakeNotification {
  static permission: PermissionState = 'default'
  static instances: FakeNotification[] = []
  static requestPermission = vi.fn(async (): Promise<PermissionState> => FakeNotification.permission)
  constructor(public title: string, public options?: NotificationOptions) {
    FakeNotification.instances.push(this)
  }
}

function installNotification(permission: PermissionState): void {
  FakeNotification.permission = permission
  FakeNotification.instances = []
  FakeNotification.requestPermission.mockClear()
  vi.stubGlobal('Notification', FakeNotification)
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('视觉任务本地提醒边界（MOB-132）', () => {
  it('权限已授予时发出通知，且文案不含健康数据与任务编号', () => {
    installNotification('granted')
    expect(visionNoticeSupport()).toBe('granted')

    const result = notifyVisionTaskTerminal('succeeded')
    expect(result).toBe('shown')
    expect(FakeNotification.instances).toHaveLength(1)
    const notice = FakeNotification.instances[0]!
    expect(notice.title).not.toMatch(/task-\d|苯|药名/)
    expect(notice.options?.body ?? '').not.toMatch(/task-\d/)
  })

  it('权限被拒绝时不构造通知并返回 denied', () => {
    installNotification('denied')
    expect(visionNoticeSupport()).toBe('denied')
    expect(notifyVisionTaskTerminal('failed')).toBe('denied')
    expect(FakeNotification.instances).toHaveLength(0)
  })

  it('默认态先请求权限，未批准前不发通知', async () => {
    installNotification('default')
    expect(visionNoticeSupport()).toBe('default')
    // 未授权时直接通知不会发出
    expect(notifyVisionTaskTerminal('succeeded')).toBe('denied')
    expect(FakeNotification.instances).toHaveLength(0)

    FakeNotification.permission = 'granted'
    await expect(requestVisionNoticePermission()).resolves.toBe('granted')
    expect(FakeNotification.requestPermission).toHaveBeenCalledTimes(1)
  })
})
