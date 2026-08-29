import { Capacitor } from '@capacitor/core'
import { LocalNotifications } from '@capacitor/local-notifications'

import type { CareTask, ReminderPolicy } from '@/data/types'

export type ReminderPlatformKind = 'android' | 'pwa' | 'unavailable'
export type ReminderPermission = 'granted' | 'denied' | 'prompt'
export type ReminderSyncStatus = 'SCHEDULED' | 'NOTHING_TO_SCHEDULE' | 'PERMISSION_DENIED' | 'UNAVAILABLE'

export interface LocalReminder {
  id: number
  at: Date
  title: string
  body: string
}

export interface ReminderPlatform {
  kind: ReminderPlatformKind
  permission(): Promise<ReminderPermission>
  schedule(notifications: LocalReminder[]): Promise<void>
  cancel(ids: number[]): Promise<void>
  pending?(): Promise<number[]>
}

export interface ReminderSyncResult {
  status: ReminderSyncStatus
  reason: string
  scheduledCount: number
}

const TITLE = '家健镜提醒'
const BODY = '请打开应用查看今日安排。'

/**
 * MOB-172：提醒必须走一个显式的私有通知通道。
 * Android 的系统默认通道可能沿用设备的公开锁屏策略，无法证明锁屏
 * 只显示脱敏占位；因此不再依赖插件的隐式默认通道。
 */
export const REMINDER_CHANNEL_ID = 'hct_reminder'
export const REMINDER_CHANNEL = {
  id: REMINDER_CHANNEL_ID,
  name: '计划提醒',
  description: '仅提示打开应用查看今日安排，不包含健康内容。',
  importance: 3 as const,
  visibility: 0 as const,
  vibration: true,
}

/** Keep native notification mapping in one place so privacy fields stay testable. */
export function toNativeReminder(notification: LocalReminder) {
  return {
    ...notification,
    channelId: REMINDER_CHANNEL_ID,
    schedule: { at: notification.at, allowWhileIdle: true },
    isExactNotification: false,
    extra: { hct_reminder: 'v1' },
  }
}

function stableId(value: string): number {
  let hash = 2166136261
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  return (hash >>> 0) % 2_000_000_000 + 1
}

function validPolicy(policy: ReminderPolicy | undefined): policy is ReminderPolicy {
  if (!policy || policy.authorization !== 'AUTHORIZED' || !policy.planVersion || !policy.deduplicationKey) return false
  if (policy.maxReminders !== 1 && policy.maxReminders !== 2) return false
  const first = Date.parse(policy.firstReminderAt)
  const repeat = policy.repeatReminderAt ? Date.parse(policy.repeatReminderAt) : Number.NaN
  return Number.isFinite(first)
    && (policy.maxReminders === 1 || (Number.isFinite(repeat) && repeat > first))
}

function remindersFor(task: CareTask): LocalReminder[] {
  if (task.status !== 'PENDING' && task.status !== 'DEFERRED') return []
  if (!validPolicy(task.reminder)) return []
  const policy = task.reminder
  const firstAt = new Date(policy.firstReminderAt)
  const reminders: LocalReminder[] = []
  if (firstAt.getTime() > Date.now()) {
    reminders.push({ id: stableId(`${REMINDER_CHANNEL_ID}:${policy.deduplicationKey}:${policy.planVersion}:first`), at: firstAt, title: TITLE, body: BODY })
  }
  if (policy.maxReminders === 2 && policy.repeatReminderAt) {
    const repeatAt = new Date(policy.repeatReminderAt)
    if (repeatAt.getTime() > Date.now()) {
      reminders.push({ id: stableId(`${REMINDER_CHANNEL_ID}:${policy.deduplicationKey}:${policy.planVersion}:repeat`), at: repeatAt, title: TITLE, body: BODY })
    }
  }
  return reminders
}

export class ReminderScheduler {
  private scheduled = new Set<number>()

  constructor(private readonly platform: ReminderPlatform) {}

  async sync(tasks: CareTask[]): Promise<ReminderSyncResult> {
    if (this.platform.kind !== 'android') {
      await this.cancelAll()
      return {
        status: 'UNAVAILABLE',
        reason: '当前平台不支持可靠的后台本地提醒；请打开应用查看今日安排。',
        scheduledCount: 0,
      }
    }

    const permission = await this.platform.permission()
    if (permission !== 'granted') {
      await this.cancelAll()
      return {
        status: 'PERMISSION_DENIED',
        reason: '通知权限未开启，应用不会声称已经提醒；请在系统设置中允许通知后重新打开应用。',
        scheduledCount: 0,
      }
    }

    const next = tasks.flatMap(remindersFor)
    const nextIds = new Set(next.map(item => item.id))
    const pending = this.platform.pending ? await this.platform.pending() : []
    const known = new Set([...this.scheduled, ...pending])
    const stale = [...known].filter(id => !nextIds.has(id))
    if (stale.length > 0) await this.platform.cancel(stale)

    const additions = next.filter(item => !known.has(item.id))
    if (additions.length > 0) await this.platform.schedule(additions)
    this.scheduled = nextIds

    if (next.length === 0) {
      return {
        status: 'NOTHING_TO_SCHEDULE',
        reason: '当前计划没有可验证的授权提醒元数据，未安排本地提醒。',
        scheduledCount: 0,
      }
    }
    return { status: 'SCHEDULED', reason: '已按服务端计划安排本地提醒。', scheduledCount: next.length }
  }

  async cancelAll(): Promise<void> {
    const pending = this.platform.pending ? await this.platform.pending() : []
    const ids = [...new Set([...this.scheduled, ...pending])]
    if (ids.length > 0) await this.platform.cancel(ids)
    this.scheduled.clear()
  }
}

export function createReminderPlatform(): ReminderPlatform {
  if (!Capacitor.isNativePlatform() || Capacitor.getPlatform() !== 'android') {
    return {
      kind: 'pwa',
      async permission() { return 'denied' },
      async schedule() {},
      async cancel() {},
    }
  }
  return {
    kind: 'android',
    async permission() {
      try {
        // Fail closed if the private channel cannot be created. Falling back to
        // the plugin default could expose more than the approved lock-screen copy.
        await LocalNotifications.createChannel(REMINDER_CHANNEL)
        const current = await LocalNotifications.checkPermissions()
        if (current.display === 'granted') return 'granted'
        const requested = await LocalNotifications.requestPermissions()
        return requested.display === 'granted' ? 'granted' : 'denied'
      } catch {
        return 'denied'
      }
    },
    async schedule(notifications) {
      await LocalNotifications.schedule({
        notifications: notifications.map(toNativeReminder),
      })
    },
    async cancel(ids) {
      await LocalNotifications.cancel({ notifications: ids.map(id => ({ id })) })
    },
    async pending() {
      const pending = await LocalNotifications.getPending()
      return pending.notifications
        .filter(notification => notification.extra?.hct_reminder === 'v1')
        .map(notification => notification.id)
    },
  }
}
