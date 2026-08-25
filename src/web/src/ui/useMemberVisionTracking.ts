import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { apiClient } from '../api/client'
import type { HealthEvent, VisionTask } from '../api/types'
import { rememberedVisionTasks, requestOptions, session } from '../store'
import {
  isMemberTaskActive,
  memberVisionStatusHint,
  memberVisionStatusLabel,
} from './memberStatus'

function visionTaskIdFromEvent(event: HealthEvent): string | null {
  const value = event.evidence?.vision_task_id
  return typeof value === 'string' ? value : null
}

function isTerminalFailure(status: string | null | undefined): boolean {
  return status === 'failed' || status === 'timeout' || status === 'cancelled'
}

export function useMemberVisionTracking(options?: { enablePolling?: boolean }) {
  const trackedTasks = ref<VisionTask[]>([])
  const confirmedTaskIds = ref<Set<string>>(new Set())
  let pollTimer: ReturnType<typeof setInterval> | null = null

  const hasActiveTasks = computed(() =>
    trackedTasks.value.some(task => isMemberTaskActive(task.status)),
  )

  const awaitingConfirmationTasks = computed(() =>
    trackedTasks.value.filter(task =>
      !confirmedTaskIds.value.has(task.id) && !isTerminalFailure(task.status),
    ),
  )

  function taskStatusLabel(task: VisionTask): string {
    return memberVisionStatusLabel(task.status, confirmedTaskIds.value.has(task.id))
  }

  function taskStatusHint(task: VisionTask): string {
    return memberVisionStatusHint(task.status, confirmedTaskIds.value.has(task.id))
  }

  async function refreshTracking(): Promise<void> {
    const serverTasks = session.selectedHouseholdId && session.selectedMemberId
      ? await apiClient.listMemberVisionTasks(
          session.selectedHouseholdId,
          session.selectedMemberId,
          requestOptions.value,
        ).catch(() => [] as VisionTask[])
      : []
    const ids = [...new Set([
      ...serverTasks.map(task => task.id),
      ...rememberedVisionTasks(),
    ])].slice(0, 5)
    if (!ids.length) {
      trackedTasks.value = []
      confirmedTaskIds.value = new Set()
      return
    }
    const taskResults = await Promise.allSettled(
      ids.map(id => apiClient.getVisionTask(id, requestOptions.value)),
    )
    trackedTasks.value = taskResults
      .filter((result): result is PromiseFulfilledResult<VisionTask> => result.status === 'fulfilled')
      .map(result => result.value)

    if (!session.selectedHouseholdId || !session.selectedMemberId) return
    const timeline = await apiClient.listMemberTimeline(
      session.selectedHouseholdId,
      session.selectedMemberId,
      requestOptions.value,
    ).catch(() => [] as HealthEvent[])
    confirmedTaskIds.value = new Set(
      timeline.map(visionTaskIdFromEvent).filter((id): id is string => Boolean(id)),
    )
  }

  onMounted(() => {
    void refreshTracking()
    if (options?.enablePolling !== false) {
      pollTimer = setInterval(() => {
        if (hasActiveTasks.value) void refreshTracking()
      }, 5000)
    }
  })

  onBeforeUnmount(() => {
    if (pollTimer) clearInterval(pollTimer)
  })

  return {
    trackedTasks,
    confirmedTaskIds,
    hasActiveTasks,
    awaitingConfirmationTasks,
    taskStatusLabel,
    taskStatusHint,
    refreshTracking,
  }
}
