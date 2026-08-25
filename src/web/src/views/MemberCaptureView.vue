<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { apiClient } from '../api/client'
import type { HealthEvent, VisionTask } from '../api/types'
import AppIcon from '../components/AppIcon.vue'
import {
  pushToast,
  rememberVisionTask,
  rememberedVisionTasks,
  requestOptions,
  session,
} from '../store'
import {
  isMemberTaskActive,
  memberVisionStatusHint,
  memberVisionStatusLabel,
} from '../ui/memberStatus'
import VisionQualityPanel from '../vision/VisionQualityPanel.vue'

const submittedTask = ref<VisionTask | null>(null)
const trackedTasks = ref<VisionTask[]>([])
const confirmedTaskIds = ref<Set<string>>(new Set())
let pollTimer: ReturnType<typeof setInterval> | null = null

const hasActiveTasks = computed(() => trackedTasks.value.some(task => isMemberTaskActive(task.status)))

// 状态映射集中在 ui/memberStatus.ts，配套单测保证内部状态码不会透出到成员前台。
function taskStatusLabel(task: VisionTask): string {
  return memberVisionStatusLabel(task.status, confirmedTaskIds.value.has(task.id))
}

function taskStatusHint(task: VisionTask): string {
  return memberVisionStatusHint(task.status, confirmedTaskIds.value.has(task.id))
}

function visionTaskIdFromEvent(event: HealthEvent): string | null {
  const value = event.evidence?.vision_task_id
  return typeof value === 'string' ? value : null
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

function onTaskCreated(task: VisionTask): void {
  rememberVisionTask(task.id)
  submittedTask.value = task
  void refreshTracking()
  pushToast('success', '照片已提交，等家庭管理员确认后才会记入家庭记录。')
}

onMounted(() => {
  void refreshTracking()
  pollTimer = setInterval(() => {
    if (hasActiveTasks.value) void refreshTracking()
  }, 5000)
})

onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<template>
  <section class="page-hero member-portal-hero">
    <p class="eyebrow">拍照录药</p>
    <h2 class="hero-greeting">把药盒拍清楚就可以了</h2>
    <p class="hero-sub">你只需要拍照并提交，药品名称和用法由家庭管理员检查后再保存。</p>
  </section>

  <p class="notice ok member-confirmation-note" role="status">
    <AppIcon name="lock" :size="16" />
    你提交的是待确认照片，不会直接写进健康记录。
  </p>

  <VisionQualityPanel
    :actor-id="session.actorId"
    :member-id="session.selectedMemberId || undefined"
    :access-purpose="session.accessPurpose"
    audience="member"
    @task-created="onTaskCreated"
  />

  <section v-if="submittedTask" class="card member-next-step">
    <AppIcon name="check" :size="22" />
    <div><strong>接下来由家庭管理员确认</strong><p>确认后，你可以在“我的记录”里看到结果。</p></div>
  </section>

  <section v-if="trackedTasks.length" class="card member-capture-status">
    <div class="card-heading">
      <div><p class="eyebrow">照片进度</p><h3 class="card-title">最近提交</h3></div>
      <span v-if="hasActiveTasks" class="pill gold">处理中</span>
    </div>
    <ul class="list-plain member-status-list">
      <li v-for="task in trackedTasks" :key="task.id" class="member-status-row">
        <span class="member-status-icon" :class="confirmedTaskIds.has(task.id) ? 'confirmed' : task.status === 'failed' || task.status === 'timeout' ? 'failed' : 'pending'">
          <AppIcon :name="confirmedTaskIds.has(task.id) ? 'check' : task.status === 'failed' || task.status === 'timeout' ? 'alert' : 'scan'" :size="17" />
        </span>
        <span><strong>{{ taskStatusLabel(task) }}</strong><small>{{ taskStatusHint(task) }}</small></span>
      </li>
    </ul>
  </section>
</template>
