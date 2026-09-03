<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { RouterLink } from 'vue-router'

import AppIcon from '@/components/AppIcon.vue'
import LevelTag from '@/components/LevelTag.vue'
import { caregiverEscalationStatusLabel, caregiverEscalationStatusTone, taskLevelTone } from '@/data/labels'
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

const panel = ref<'none' | 'defer' | 'skip' | 'miss'>('none')
const skipReason = ref('')
const skipError = ref('')
const missReason = ref('')
const missError = ref('')
const policy = computed(() => props.task.actionPolicy)
const hasActionPolicy = computed(() => Boolean(policy.value && policy.value.allowedActions.length))
const allowsAction = (action: TaskAction) => Boolean(policy.value?.allowedActions.includes(action))
const policyMessage = computed(() =>
  policy.value
    ? `服务端计划快照 ${policy.value.planVersion} · ${policy.value.windowLabel}`
    : '家庭服务器未提供本条计划的允许操作范围，这条任务当前只读。',
)

const DEFER_OPTIONS = [1, 2, 4]
const taskDomId = String(props.task.id).replace(/[^a-zA-Z0-9_-]/g, '-')
const deferPanelId = `task-${taskDomId}-defer-panel`
const skipPanelId = `task-${taskDomId}-skip-panel`
const missPanelId = `task-${taskDomId}-miss-panel`
const deferButtonId = `task-${taskDomId}-defer-button`
const skipButtonId = `task-${taskDomId}-skip-button`
const missButtonId = `task-${taskDomId}-miss-button`
const skipInputId = `task-${taskDomId}-skip-reason`
const skipErrorId = `task-${taskDomId}-skip-error`
const missInputId = `task-${taskDomId}-miss-reason`
const missErrorId = `task-${taskDomId}-miss-error`

function confirm(): void {
  if (!allowsAction('confirm')) return
  emit('action', 'confirm', {})
}

function defer(hours: number): void {
  if (!allowsAction('defer')) return
  panel.value = 'none'
  emit('action', 'defer', { deferHours: hours })
}

async function togglePanel(nextPanel: 'defer' | 'skip' | 'miss'): Promise<void> {
  panel.value = panel.value === nextPanel ? 'none' : nextPanel
  if (panel.value === 'none') return
  await nextTick()
  const targetId = nextPanel === 'defer' ? deferPanelId : nextPanel === 'skip' ? skipInputId : missInputId
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

/** 记为漏服：只记录「这次没吃」这一事实，不做补服、剂量或换药判断。 */
function submitMiss(): void {
  if (!allowsAction('miss')) return
  if (!missReason.value.trim()) {
    missError.value = '请填写漏服原因，便于家人了解情况。'
    return
  }
  missError.value = ''
  panel.value = 'none'
  emit('action', 'miss', { reason: missReason.value.trim() })
  missReason.value = ''
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
    <p v-if="props.task.missReason" class="meta-line">漏服原因：{{ props.task.missReason }}</p>

    <section v-if="props.task.escalation" class="task-escalation" aria-label="照护升级状态">
      <div class="card-title-row">
        <strong>照护升级状态</strong>
        <span class="tag" :data-tone="caregiverEscalationStatusTone(props.task.escalation.status)">
          {{ caregiverEscalationStatusLabel(props.task.escalation.status) }}
        </span>
      </div>
      <p class="meta-line">{{ props.task.escalation.reason }}</p>
      <p class="meta-line">
        目标：{{ props.task.escalation.target === 'AUTHORIZED_CAREGIVER' ? '服务端授权照护者（身份信息已隐藏）' : '无有效授权照护者' }}
      </p>
      <p class="meta-line">升级时间：{{ formatDateTime(props.task.escalation.occurredAt) }}</p>
      <p v-if="props.task.escalation.dueAt" class="meta-line">原计划时间：{{ formatDateTime(props.task.escalation.dueAt) }}</p>
      <p class="meta-line">下一步：{{ props.task.escalation.nextStep }}</p>
      <p class="meta-line">升级回执：{{ props.task.escalation.auditEventId }}</p>
      <RouterLink class="btn btn-quiet" to="/help">联系家人 / 120</RouterLink>
    </section>

    <template v-if="props.task.status === 'PENDING' || props.task.status === 'DEFERRED'">
      <p v-if="!hasActionPolicy" class="notice" data-tone="warn" role="status">
        <AppIcon name="alert" :size="16" />
        家庭服务器暂未返回本条计划的允许操作范围，按钮保持不可用；刷新后仍不可用请在网页端确认计划状态。
      </p>

      <div class="btn-row">
        <button type="button" class="btn" :disabled="props.busy || !allowsAction('confirm')" @click="confirm">
          <AppIcon name="check" :size="18" />
          完成
        </button>
        <button
          :id="deferButtonId"
          type="button"
          class="btn btn-quiet"
          :disabled="props.busy || !allowsAction('defer')"
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
          :disabled="props.busy || !allowsAction('skip')"
          :aria-expanded="panel === 'skip'"
          :aria-controls="skipPanelId"
          @click="togglePanel('skip')"
        >
          跳过
        </button>
        <button
          :id="missButtonId"
          type="button"
          class="btn btn-quiet"
          :disabled="props.busy || !allowsAction('miss')"
          :aria-expanded="panel === 'miss'"
          :aria-controls="missPanelId"
          @click="togglePanel('miss')"
        >
          <AppIcon name="alert" :size="18" />
          记漏服
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
            :disabled="props.busy || !allowsAction('defer')"
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
        <button type="button" class="btn btn-danger btn-block" :disabled="props.busy || !allowsAction('skip')" @click="submitSkip">
          记录跳过
        </button>
      </div>

      <div
        v-if="panel === 'miss'"
        :id="missPanelId"
        class="task-panel"
        role="region"
        :aria-labelledby="missButtonId"
      >
        <label class="field" :for="missInputId">
          漏服原因（必填）
          <input
            :id="missInputId"
            v-model="missReason"
            type="text"
            placeholder="例如：出门忘记带药"
            :aria-invalid="Boolean(missError)"
            :aria-describedby="missError ? `${missErrorId} ${missPanelId}-help` : `${missPanelId}-help`"
          />
        </label>
        <p :id="`${missPanelId}-help`" class="meta-line">
          漏服只记录事实，不会自动补服、也不会修改剂量或计划；后续提醒仍由家庭服务器的计划决定。
        </p>
        <p v-if="missError" :id="missErrorId" class="notice" data-tone="error" role="alert">{{ missError }}</p>
        <button type="button" class="btn btn-block" :disabled="props.busy || !allowsAction('miss')" @click="submitMiss">
          记录漏服
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
.task-escalation {
  display: grid;
  gap: 7px;
  margin-top: 12px;
  padding: 12px;
  border: 1px solid var(--c-line-strong);
  border-radius: 12px;
  background: var(--c-surface-soft);
}
.task-escalation .btn { justify-self: start; }
.task-panel {
  border-top: 1px solid var(--c-line);
  padding-top: 12px;
  display: grid;
  gap: 10px;
}
</style>
