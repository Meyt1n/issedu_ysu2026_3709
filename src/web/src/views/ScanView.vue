<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { apiClient } from '../api/client'
import type { VisionTask } from '../api/types'
import AppIcon from '../components/AppIcon.vue'
import {
  formatError,
  pushToast,
  rememberVisionTask,
  rememberedVisionTasks,
  requestOptions,
  selectMember,
  session,
} from '../store'
import { askConfirm } from '../ui/confirm'
import { formatDateTime, fusionStatusLabel, visionStatusLabel } from '../ui/labels'
import VisionQualityPanel from '../vision/VisionQualityPanel.vue'
import VisionResultViewer from '../components/VisionResultViewer.vue'
import { visionErrorMessage, visionErrorNextAction, visionErrorTitle } from '../vision/visionReasons'
import { setView } from '../store'

const tasks = ref<VisionTask[]>([])
const loadingTasks = ref(false)
const cancellingId = ref<string | null>(null)
const retryingId = ref<string | null>(null)
let pollTimer: ReturnType<typeof setInterval> | null = null
const previousStatuses = new Map<string, string>()

/* ── 识别详情查看器 ── */

const expandedTaskId = ref<string | null>(null)
const imageUrls = ref<Record<string, string>>({})
const imageLoadingId = ref<string | null>(null)

async function toggleViewer(task: VisionTask): Promise<void> {
  if (expandedTaskId.value === task.id) {
    expandedTaskId.value = null
    return
  }
  expandedTaskId.value = task.id
  if (imageUrls.value[task.id]) return

  imageLoadingId.value = task.id
  try {
    const blob = await apiClient.fetchFileBlob(task.file_id, requestOptions.value)
    imageUrls.value = { ...imageUrls.value, [task.id]: URL.createObjectURL(blob) }
  } catch {
    // 原图不可用时查看器显示占位提示，不阻塞证据列表。
  } finally {
    imageLoadingId.value = null
  }
}

const TASK_PREVIEW = 5
const showAllTasks = ref(false)
const visibleTasks = computed(() =>
  showAllTasks.value ? tasks.value : tasks.value.slice(0, TASK_PREVIEW),
)

const hasActiveTasks = computed(
  () => tasks.value.some(task => task.status === 'queued' || task.status === 'running'),
)

const memberNameById = computed(
  () => new Map(session.members.map(member => [member.id, member.display_name])),
)

function statusTone(status: string): string {
  if (status === 'succeeded') return 'pine'
  if (status === 'running') return 'sky'
  if (status === 'queued') return 'gold'
  if (status === 'cancelled') return 'plain'
  return 'rose'
}

async function refreshTasks(showSpinner = false): Promise<void> {
  const ids = rememberedVisionTasks()
  if (ids.length === 0) {
    tasks.value = []
    return
  }
  if (showSpinner) loadingTasks.value = true
  try {
    const results = await Promise.allSettled(
      ids.map(id => apiClient.getVisionTask(id, requestOptions.value)),
    )
    const nextTasks = results
      .filter((result): result is PromiseFulfilledResult<VisionTask> => result.status === 'fulfilled')
      .map(result => result.value)
    for (const task of nextTasks) {
      const previous = previousStatuses.get(task.id)
      if (
        previous &&
        (previous === 'queued' || previous === 'running') &&
        task.status === 'succeeded'
      ) {
        pushToast('success', '识别完成，已生成待人工复核候选。正在打开复核中心。')
        setView('review')
      }
      previousStatuses.set(task.id, task.status)
    }
    tasks.value = nextTasks
  } finally {
    loadingTasks.value = false
  }
}

function onTaskCreated(task: VisionTask): void {
  rememberVisionTask(task.id)
  pushToast('success', '识别任务已创建，可在下方追踪进度。')
  void refreshTasks()
}

async function cancelTask(task: VisionTask): Promise<void> {
  const accepted = await askConfirm({
    title: '取消这个识别任务？',
    message: '任务取消后不可恢复；已上传的图片不会自动写入任何健康记录。',
    confirmText: '取消任务',
  })
  if (!accepted) return

  cancellingId.value = task.id
  try {
    await apiClient.cancelVisionTask(task.id, requestOptions.value)
    pushToast('info', '任务已取消。')
    await refreshTasks()
  } catch (cause) {
    pushToast('error', formatError(cause))
  } finally {
    cancellingId.value = null
  }
}

async function retryTask(task: VisionTask): Promise<void> {
  if (retryingId.value) return
  retryingId.value = task.id
  try {
    await apiClient.retryVisionTask(task.id, requestOptions.value)
    previousStatuses.set(task.id, 'queued')
    pushToast('info', '任务已重新排队，仍会在完成后进入人工复核。')
    await refreshTasks()
  } catch (cause) {
    pushToast('error', formatError(cause))
  } finally {
    retryingId.value = null
  }
}

function onMemberChange(event: Event): void {
  selectMember((event.target as HTMLSelectElement).value)
}

onMounted(() => {
  void refreshTasks(true)
  pollTimer = setInterval(() => {
    if (hasActiveTasks.value) void refreshTasks()
  }, 5000)
})

onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer)
  for (const url of Object.values(imageUrls.value)) URL.revokeObjectURL(url)
})
</script>

<template>
  <section class="page-hero">
    <div class="card-heading" style="margin-bottom: 0">
      <div>
        <h2 class="hero-greeting">视觉扫描中心</h2>
        <p class="hero-sub">
          拍摄药盒或报告，经本地质量门控后进入识别队列；冲突结果进入人工复核。
        </p>
      </div>
      <label class="context-select">
        归属成员
        <select :value="session.selectedMemberId" @change="onMemberChange">
          <option v-for="member in session.members" :key="member.id" :value="member.id">
            {{ member.display_name }}
          </option>
        </select>
      </label>
    </div>
  </section>

  <VisionQualityPanel
    :member-id="session.selectedMemberId || undefined"
    :access-purpose="session.accessPurpose"
    audience="admin"
    @task-created="onTaskCreated"
  />

  <section class="card">
    <div class="card-heading">
      <div>
        <p class="eyebrow">任务状态</p>
        <h3 class="card-title">本机创建的识别任务</h3>
      </div>
      <div class="heading-actions">
        <span v-if="hasActiveTasks" class="pill gold">自动刷新中</span>
        <button type="button" class="btn btn-ghost btn-small" :disabled="loadingTasks" @click="refreshTasks(true)">
          <AppIcon name="refresh" :size="15" />
          刷新
        </button>
      </div>
    </div>

    <div v-if="loadingTasks" class="inline-loading">
      <span class="loading-dots"><span /><span /><span /></span>
      正在读取任务状态
    </div>
    <div v-else-if="tasks.length === 0" class="empty-state">
      <AppIcon class="empty-art" name="scan" :size="40" />
      <strong>还没有识别任务</strong>
      <p>在上方完成一次图片质量检查并创建任务后，任务进度会显示在这里。</p>
    </div>
    <ul v-else class="list-plain">
      <li v-for="task in visibleTasks" :key="task.id" class="row-card">
        <div class="row-top">
          <span class="row-title">
            <AppIcon name="scan" :size="17" style="color: var(--clay)" />
            {{ task.task_type.toUpperCase() }} 识别
            <span class="pill" :class="statusTone(task.status)">{{ visionStatusLabel(task.status) }}</span>
          </span>
          <div class="row-actions">
            <button
              type="button"
              class="btn btn-ghost btn-small"
              @click="toggleViewer(task)"
            >
              <AppIcon name="eye" :size="14" />
              {{ expandedTaskId === task.id ? '收起详情' : '识别详情' }}
            </button>
            <button
              v-if="task.status === 'queued' || task.status === 'running'"
              type="button"
              class="btn btn-danger btn-small"
              :disabled="cancellingId === task.id"
              @click="cancelTask(task)"
            >
              {{ cancellingId === task.id ? '正在取消' : '取消任务' }}
            </button>
          </div>
        </div>
        <p class="row-meta" style="margin: 0">
          归属成员：{{ task.member_id ? memberNameById.get(task.member_id) ?? task.member_id : '未指定' }} ·
          创建于 {{ formatDateTime(task.created_at) }} · 文件 {{ task.file_id }}
        </p>
        <p class="row-meta mono-wrap" style="margin: 0; font-family: ui-monospace, monospace; font-size: 12px">
          任务编号 {{ task.id }} · 提交者 {{ task.created_by }} · 用途 {{ session.accessPurpose || '未填' }}
        </p>
        <p v-if="task.status === 'queued'" class="row-meta" style="margin: 0">
          已进入本地 OCR 队列；worker 会在本机处理，首次加载 PaddleOCR 模型可能需要十几秒。识别结果不会自动入档，须人工复核。
        </p>
        <p v-if="task.status === 'running'" class="row-meta" style="margin: 0">
          本地 OCR 正在处理图片，完成后会自动生成待人工复核的候选结果（仍不会自动写入健康记录）。
        </p>
        <div v-if="task.error_detail" class="notice error vision-task-error" style="margin: 0">
          <AppIcon name="alert" :size="15" />
          <div>
            <strong>{{ visionErrorTitle(task.error_detail.code) }}</strong>：{{ visionErrorMessage(task.error_detail) }}
            <p class="row-meta" style="margin: 3px 0 0">下一步：{{ visionErrorNextAction(task.error_detail) }}</p>
          </div>
          <button
            v-if="task.error_detail.retryable"
            type="button"
            class="btn btn-danger btn-small"
            :disabled="retryingId === task.id"
            @click="retryTask(task)"
          >
            {{ retryingId === task.id ? '正在重新处理' : '重新处理' }}
          </button>
        </div>
        <p v-else-if="task.status === 'failed' || task.status === 'timeout'" class="notice error" style="margin: 0">
          识别没有完成，健康记录没有被修改。请保持药盒正面、完整入框并重新拍摄；如仍失败，请让家人检查本地服务（任务 {{ task.id.slice(0, 8) }}…）。
        </p>
        <template v-if="task.status === 'succeeded' && task.result">
          <div class="capability-chips">
            <span class="pill sky">证据 {{ task.result.evidence?.length ?? 0 }} 条</span>
            <span class="pill sky">字段 {{ task.result.fields?.length ?? 0 }} 个</span>
            <span class="pill" :class="task.result.fusion_readiness === 'READY_FOR_FUSION' || task.result.fusion_readiness === 'MATCHED' ? 'pine' : 'gold'">
              {{ fusionStatusLabel(task.result.fusion_readiness) }}
            </span>
            <span class="pill clay">需人工确认</span>
            <button type="button" class="btn btn-clay btn-small" style="margin-left: auto" @click="setView('review')">
              去人工复核
              <AppIcon name="arrow-right" :size="14" />
            </button>
          </div>
        </template>

        <VisionResultViewer
          v-if="expandedTaskId === task.id"
          :task="task"
          :image-url="imageUrls[task.id] ?? null"
          :image-loading="imageLoadingId === task.id"
        />
      </li>
    </ul>
    <div v-if="tasks.length > TASK_PREVIEW" class="more-wrap">
      <button type="button" class="more-btn" :class="{ open: showAllTasks }" @click="showAllTasks = !showAllTasks">
        <AppIcon name="arrow-right" :size="13" />
        {{ showAllTasks ? '收起任务' : `展开更早的 ${tasks.length - TASK_PREVIEW} 个任务` }}
      </button>
    </div>
  </section>
</template>
