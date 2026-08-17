<script setup lang="ts">
import { ref } from 'vue'

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

const DEFER_OPTIONS = [1, 2, 4]

function confirm(): void {
  emit('action', 'confirm', {})
}

function defer(hours: number): void {
  panel.value = 'none'
  emit('action', 'defer', { deferHours: hours })
}

function submitSkip(): void {
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
    <p v-if="props.task.skipReason" class="meta-line">跳过原因：{{ props.task.skipReason }}</p>

    <template v-if="props.task.status === 'PENDING' || props.task.status === 'DEFERRED'">
      <div class="btn-row">
        <button type="button" class="btn" :disabled="props.busy" @click="confirm">
          <AppIcon name="check" :size="18" />
          完成
        </button>
        <button
          type="button"
          class="btn btn-quiet"
          :disabled="props.busy"
          :aria-expanded="panel === 'defer'"
          @click="panel = panel === 'defer' ? 'none' : 'defer'"
        >
          稍后
        </button>
        <button
          type="button"
          class="btn btn-danger"
          :disabled="props.busy"
          :aria-expanded="panel === 'skip'"
          @click="panel = panel === 'skip' ? 'none' : 'skip'"
        >
          跳过
        </button>
      </div>

      <div v-if="panel === 'defer'" class="task-panel">
        <p class="meta-line">延后多长时间再提醒？</p>
        <div class="btn-row">
          <button
            v-for="hours in DEFER_OPTIONS"
            :key="hours"
            type="button"
            class="btn btn-quiet"
            :disabled="props.busy"
            @click="defer(hours)"
          >
            {{ hours }} 小时
          </button>
        </div>
      </div>

      <div v-if="panel === 'skip'" class="task-panel">
        <label class="field">
          跳过原因（必填）
          <input v-model="skipReason" type="text" placeholder="例如：今日已在医院服药" />
        </label>
        <p v-if="skipError" class="notice" data-tone="error" role="alert">{{ skipError }}</p>
        <button type="button" class="btn btn-danger btn-block" :disabled="props.busy" @click="submitSkip">
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
