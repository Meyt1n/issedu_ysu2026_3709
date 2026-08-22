import { reactive } from 'vue'

import type { CareTask } from '@/data/types'
import { registerSessionCleanup } from '@/stores/auth'

import { createReminderPlatform, ReminderScheduler, type ReminderSyncResult } from './reminderScheduler'

export const reminderState = reactive<ReminderSyncResult>({
  status: 'NOTHING_TO_SCHEDULE',
  reason: '尚未同步可验证的计划提醒。',
  scheduledCount: 0,
})

const scheduler = new ReminderScheduler(createReminderPlatform())

export async function synchronizeReminders(tasks: CareTask[]): Promise<ReminderSyncResult> {
  try {
    const result = await scheduler.sync(tasks)
    Object.assign(reminderState, result)
    return result
  } catch {
    const result: ReminderSyncResult = {
      status: 'UNAVAILABLE',
      reason: '本地提醒当前不可用；应用不会声称已经提醒，请打开应用查看今日安排。',
      scheduledCount: 0,
    }
    Object.assign(reminderState, result)
    return result
  }
}

export async function cancelScheduledReminders(): Promise<void> {
  try {
    await scheduler.cancelAll()
  } finally {
    Object.assign(reminderState, {
      status: 'NOTHING_TO_SCHEDULE',
      reason: '当前计划提醒已取消，等待服务端重新同步。',
      scheduledCount: 0,
    })
  }
}

// Logout, authorization rejection, household/member switching, and server changes share this cleanup path.
registerSessionCleanup(() => { void cancelScheduledReminders() })
