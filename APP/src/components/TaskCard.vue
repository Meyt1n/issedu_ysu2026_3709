<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'

import AppIcon from '@/components/AppIcon.vue'
import LevelTag from '@/components/LevelTag.vue'
import { taskLevelTone } from '@/data/labels'
import type { CareTask, TaskAction, TaskActionPayload } from '@/data/types'
import { formatDateTime } from '@/utils/format'

const props = defineProps<{
  task: CareTask
  /** 是否显示成员名（跨成员汇总视图使用） */
  showMember?: boolean
  busy?: boolean
}>()

const emit = defineEmits<{
  (event: 'action', action: TaskAction, payload: TaskActionPayload): void
}>()

const panel = ref<'none' | 'defer' | 'skip'>('none')
const skipReason = ref('')
const skipError = ref('')
const policy = computed(() => props.task.actionPolicy)
const hasActionPolicy = computed(() => Boolean(policy.value && policy.value.allowedActions.length))
const allowsAction = (action: TaskAction) => Boolean(policy.value?.allowedActions.includes(action))
const policyMessage = computed(() => policy.value ? 'Server plan version: ' + policy.value.planVersion + '; ' + policy.value.windowLabel : 'Server safety window is unavailable. This task is read-only.')

const DEFER_OPTIONS = [1, 2, 4]
const taskDomId = String(props.task.id).replace(/[^a-zA-Z0-9_-]/g, '-')
const deferPanelId = `task-${taskDomId}-defer-panel`
const skipPanelId = `task-${taskDomId}-skip-panel`
const deferButtonId = `task-${taskDomId}-defer-button`
const skipButtonId = `task-${taskDomId}-skip-button`
const skipInputId = `task-${taskDomId}-skip-reason`
const skipErrorId = `task-${taskDomId}-skip-error`

function confirm(): void {
  if (!allowsAction('confirm')) return
  emit('action', 'confirm', {})
}

function defer(hours: number): void {
  if (!allowsAction('defer')) return
  panel.value = 'none'
  emit('action', 'defer', { deferHours: hours })
}

async function togglePanel(nextPanel: 'defer' | 'skip'): Promise<void> {
  panel.value = panel.value === nextPanel ? 'none' : nextPanel
  if (panel.value === 'none') return
  await nextTick()
  const targetId = nextPanel === 'defer' ? deferPanelId : skipInputId
  document.getElementById(targetId)?.focus()
}

function submitSkip(): void {
  if (!allowsAction('skip')) return
  if (!skipReason.value.trim()) {
    skipError.value = '请填写跳过原因，便于家人了解情况。'
    return
  }
  skipError.value = ''
  panel.value = 'none'
  emit('action', 'skip', { reason: skipReason.value.trim() })
  skipReason.value = ''
}
</script>

<template>
  <article class="card task-card" :data-tone="taskLevelTone(props.task.level)">
    <div class="task-head">
      <span class="icon-disc" :data-tone="taskLevelTone(props.task.level)" aria-hidden="true">
        <AppIcon name="pill" :size="22" />
      </span>
      <div class="task-title">
        <h3>{{ props.task.title }}</h3>
        <p class="meta-line">
          <AppIcon name="clock" :size="14" />
          {{ formatDateTime(props.task.dueAt) }}
          <template v-if="props.showMember">· {{ props.task.memberName }}</template>
        </p>
      </div>
      <div class="task-tags">
        <LevelTag kind="task" :value="props.task.level" />
        <LevelTag v-if="props.task.status !== 'PENDING'" kind="taskStatus" :value="props.task.status" />
      </div>
    </div>

    <p class="task-detail">{{ props.task.detail }}</p>
    <p class="meta-line">{{ policyMessage }}</p>
    <p v-if="policy?.nextAllowedAt" class="meta-line">下一允许时间：{{ formatDateTime(policy.nextAllowedAt) }}</p>
    <p v-if="props.task.skipReason" class="meta-line">跳过原因：{{ props.task.skipReason }}</p>

    <template v-if="props.task.status === 'PENDING' || props.task.status === 'DEFERRED'">
      <div class="btn-row">
        <button type="button" class="btn" :disabled="props.busy || !hasActionPolicy" @click="confirm">
          <AppIcon name="check" :size="18" />
          完成
        </button>
        <button
          :id="deferButtonId"
          type="button"
          class="btn btn-quiet"
          :disabled="props.busy || !hasActionPolicy"
          :aria-expanded="panel === 'defer'"
          :aria-controls="deferPanelId"
          @click="togglePanel('defer')"
        >
          稍后
        </button>
        <button
          :id="skipButtonId"
          type="button"
          class="btn btn-danger"
          :disabled="props.busy || !hasActionPolicy"
          :aria-expanded="panel === 'skip'"
          :aria-controls="skipPanelId"
          @click="togglePanel('skip')"
        >
          跳过
        </button>
      </div>

      <div
        v-if="panel === 'defer'"
        :id="deferPanelId"
        class="task-panel"
        role="region"
        :aria-labelledby="deferButtonId"
        tabindex="-1"
      >
        <p class="meta-line">延后多长时间再提醒？</p>
        <div class="btn-row">
          <button
            v-for="hours in DEFER_OPTIONS"
            :key="hours"
            type="button"
            class="btn btn-quiet"
            :disabled="props.busy || !hasActionPolicy"
            @click="defer(hours)"
          >
            {{ hours }} 小时
          </button>
        </div>
      </div>

      <div
        v-if="panel === 'skip'"
        :id="skipPanelId"
        class="task-panel"
        role="region"
        :aria-labelledby="skipButtonId"
      >
        <label class="field" :for="skipInputId">
          跳过原因（必填）
          <input
            :id="skipInputId"
            v-model="skipReason"
            type="text"
            placeholder="例如：今日已在医院服药"
            :aria-invalid="Boolean(skipError)"
            :aria-describedby="skipError ? skipErrorId : undefined"
          />
        </label>
        <p v-if="skipError" :id="skipErrorId" class="notice" data-tone="error" role="alert">{{ skipError }}</p>
        <button type="button" class="btn btn-danger btn-block" :disabled="props.busy || !hasActionPolicy" @click="submitSkip">
          记录跳过
        </button>
      </div>
    </template>
  </article>
</template>

<style scoped>
.task-card { position: relative; overflow: hidden; }
/* 左缘等级色条：与图标盘同色，强化等级识别（配合文字标签，不只靠颜色） */
.task-card::before {
  content: '';
  position: absolute;
  left: 0;
  top: 16px;
  bottom: 16px;
  width: 4.5px;
  border-radius: 0 5px 5px 0;
  background: var(--edge, var(--c-info));
}
.task-card[data-tone='danger']::before { --edge: var(--c-danger); }
.task-card[data-tone='warn']::before { --edge: var(--c-warn); }
.task-card[data-tone='info']::before { --edge: var(--c-info); }
.task-card[data-tone='neutral']::before { --edge: var(--c-line-strong); }
html[data-contrast='high'] .task-card::before { background: #000; }

.task-head { display: flex; gap: 12px; align-items: flex-start; }
.task-title { flex: 1; min-width: 0; display: grid; gap: 4px; }
.task-tags { display: grid; gap: 5px; justify-items: end; }
.task-detail { color: var(--c-ink-soft); font-size: 0.9rem; }
.task-panel {
  border-top: 1px solid var(--c-line);
  padding-top: 12px;
  display: grid;
  gap: 10px;
}
</style>
