<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'

import { apiClient } from '../api/client'
import type { HealthEvent } from '../api/types'
import AppIcon from '../components/AppIcon.vue'
import {
  createIdempotencyKey,
  formatError,
  pushToast,
  requestOptions,
  selectMember,
  selectedMember,
  session,
} from '../store'
import { eventTypeLabel, formatDateTime, relativeTime } from '../ui/labels'
import { buildFactsFromTimeline } from '../ui/projection'

interface PlanFact {
  drug: string
  schedule: string
  planEventId: string
}

const timeline = ref<HealthEvent[]>([])
const loading = ref(false)
const loadError = ref('')
const busyPlanId = ref<string | null>(null)
const celebratingPlanId = ref<string | null>(null)

const actionDraft = reactive({
  planEventId: '',
  action: 'confirm' as 'confirm' | 'defer' | 'skip',
  delayHours: 4,
  skipReason: '',
})

const plans = computed<PlanFact[]>(() =>
  buildFactsFromTimeline(timeline.value).plans.map(plan => ({
    drug: plan.drug,
    schedule: plan.schedule,
    planEventId: plan.addedBy,
  })),
)

const planActivity = computed(() =>
  [...timeline.value]
    .filter(event => ['plan_confirmed', 'plan_deferred', 'plan_skipped'].includes(event.event_type))
    .reverse()
    .slice(0, 8),
)

const lastActionByPlan = computed(() => {
  const map = new Map<string, HealthEvent>()
  for (const event of timeline.value) {
    if (!['plan_confirmed', 'plan_deferred', 'plan_skipped'].includes(event.event_type)) continue
    const planId = String((event.payload as Record<string, unknown>)?.plan_event_id ?? '')
    if (planId) map.set(planId, event)
  }
  return map
})

async function loadPlans(): Promise<void> {
  const householdId = session.selectedHouseholdId
  const memberId = session.selectedMemberId
  if (!householdId || !memberId) return

  loading.value = true
  loadError.value = ''
  try {
    timeline.value = await apiClient.listMemberTimeline(householdId, memberId, requestOptions.value)
  } catch (cause) {
    timeline.value = []
    loadError.value = formatError(cause)
  } finally {
    loading.value = false
  }
}

function openAction(plan: PlanFact, action: 'confirm' | 'defer' | 'skip'): void {
  if (actionDraft.planEventId === plan.planEventId && actionDraft.action === action) {
    actionDraft.planEventId = ''
    return
  }
  actionDraft.planEventId = plan.planEventId
  actionDraft.action = action
  actionDraft.delayHours = 4
  actionDraft.skipReason = ''
}

async function submitAction(plan: PlanFact): Promise<void> {
  const householdId = session.selectedHouseholdId
  const memberId = session.selectedMemberId
  if (!householdId || !memberId || busyPlanId.value) return
  if (actionDraft.action === 'skip' && !actionDraft.skipReason.trim()) {
    pushToast('error', '跳过服药前请填写原因，方便家人了解情况。')
    return
  }

  busyPlanId.value = plan.planEventId
  const options = { ...requestOptions.value, idempotencyKey: createIdempotencyKey() }
  try {
    if (actionDraft.action === 'confirm') {
      await apiClient.confirmCarePlan(householdId, memberId, plan.planEventId, options)
      pushToast('success', `已确认「${plan.drug}」按计划服用。`)
      celebratingPlanId.value = plan.planEventId
      setTimeout(() => {
        if (celebratingPlanId.value === plan.planEventId) celebratingPlanId.value = null
      }, 1400)
    } else if (actionDraft.action === 'defer') {
      await apiClient.deferCarePlan(householdId, memberId, plan.planEventId, actionDraft.delayHours, options)
      pushToast('success', `「${plan.drug}」已延期 ${actionDraft.delayHours} 小时提醒。`)
    } else {
      await apiClient.skipCarePlan(householdId, memberId, plan.planEventId, actionDraft.skipReason.trim(), options)
      pushToast('info', `已记录跳过「${plan.drug}」及原因。`)
    }
    actionDraft.planEventId = ''
    await loadPlans()
  } catch (cause) {
    pushToast('error', formatError(cause))
  } finally {
    busyPlanId.value = null
  }
}

function activityTone(eventType: string): string {
  if (eventType === 'plan_confirmed') return 'pine'
  if (eventType === 'plan_deferred') return 'gold'
  return 'rose'
}

function onMemberChange(event: Event): void {
  selectMember((event.target as HTMLSelectElement).value)
}

watch(
  () => [session.selectedHouseholdId, session.selectedMemberId],
  () => void loadPlans(),
)

onMounted(() => void loadPlans())
</script>

<template>
  <section class="page-hero">
    <div class="card-heading" style="margin-bottom: 0">
      <div>
        <h2 class="hero-greeting">健康计划中心</h2>
        <p class="hero-sub">
          医嘱事实只读；提醒的确认、延期与跳过在安全时间窗内进行，每一次操作都会留下记录。
        </p>
      </div>
      <label class="context-select">
        成员
        <select :value="session.selectedMemberId" :disabled="loading" @change="onMemberChange">
          <option v-for="member in session.members" :key="member.id" :value="member.id">
            {{ member.display_name }}
          </option>
        </select>
      </label>
    </div>
  </section>

  <p v-if="loadError" class="notice error" role="alert">
    <AppIcon name="alert" :size="16" />
    {{ loadError }}
  </p>

  <div class="grid-main-side" style="gap: 34px">
    <section aria-label="用药计划">
      <div class="sec-head">
        <span class="sec-no">01</span>
        <h3>{{ selectedMember?.display_name ?? '成员' }}的用药计划</h3>
        <span class="sec-line" />
        <span class="sec-hint">医嘱事实只读 · {{ plans.length }} 个计划</span>
      </div>

      <div v-if="loading" class="inline-loading">
        <span class="loading-dots"><span /><span /><span /></span>
        正在读取计划事实
      </div>
      <div v-else-if="plans.length === 0" class="empty-state">
        <AppIcon class="empty-art" name="plan" :size="40" />
        <strong>还没有已确认的用药计划</strong>
        <p>请先在「成员档案」录入一条「创建用药计划」事实，计划将出现在这里。</p>
      </div>
      <ul v-else class="list-plain">
        <li v-for="plan in plans" :key="plan.planEventId" class="row-card">
          <div class="row-top">
            <span class="row-title">
              <AppIcon name="pill" :size="18" style="color: var(--pine)" />
              {{ plan.drug }}
            </span>
            <span
              v-if="lastActionByPlan.get(plan.planEventId)"
              class="pill"
              :class="activityTone(lastActionByPlan.get(plan.planEventId)!.event_type)"
            >
              {{ eventTypeLabel(lastActionByPlan.get(plan.planEventId)!.event_type) }} ·
              {{ relativeTime(lastActionByPlan.get(plan.planEventId)!.created_at) }}
            </span>
          </div>
          <p class="row-meta" style="margin: 0">
            <AppIcon name="clock" :size="14" style="vertical-align: -2px" />
            {{ plan.schedule }}
          </p>
          <div class="row-actions">
            <span v-if="celebratingPlanId === plan.planEventId" class="heart-burst" aria-hidden="true">
              <i style="--hx: -14px">♥</i><i style="--hx: 8px">♥</i><i style="--hx: 20px">♥</i>
            </span>
            <button
              type="button"
              class="btn btn-primary btn-small"
              :disabled="busyPlanId === plan.planEventId"
              @click="openAction(plan, 'confirm')"
            >
              确认服药
            </button>
            <button
              type="button"
              class="btn btn-ghost btn-small"
              :disabled="busyPlanId === plan.planEventId"
              @click="openAction(plan, 'defer')"
            >
              延期提醒
            </button>
            <button
              type="button"
              class="btn btn-danger btn-small"
              :disabled="busyPlanId === plan.planEventId"
              @click="openAction(plan, 'skip')"
            >
              跳过
            </button>
          </div>

          <form
            v-if="actionDraft.planEventId === plan.planEventId"
            class="section-stack"
            style="border-top: 1px dashed var(--line); padding-top: 12px"
            @submit.prevent="submitAction(plan)"
          >
            <template v-if="actionDraft.action === 'confirm'">
              <p class="card-note" style="margin: 0">确认代表本次已按医嘱服用，会写入健康事件并通知授权照护者。</p>
            </template>
            <template v-else-if="actionDraft.action === 'defer'">
              <label class="field">
                延期小时数（1–168）
                <input v-model.number="actionDraft.delayHours" type="number" min="1" max="168" required />
                <small>延期不改变医嘱内容，只调整本次提醒时间，且必须落在安全时间窗内。</small>
              </label>
            </template>
            <template v-else>
              <label class="field">
                跳过原因（必填）
                <input v-model="actionDraft.skipReason" autocomplete="off" required placeholder="例如 医生建议今日暂停" />
                <small>系统不会替你判断能否停药；连续未响应将升级给照护者。</small>
              </label>
            </template>
            <div class="row-actions">
              <button type="submit" class="btn btn-clay btn-small" :disabled="busyPlanId === plan.planEventId">
                {{ busyPlanId === plan.planEventId ? '正在记录' : '确定' }}
              </button>
            </div>
          </form>
        </li>
      </ul>

      <p class="card-note" style="margin-top: 16px">
        本页不提供新增、停用、替换药物或修改剂量的操作；医嘱变化请通过已确认的健康事件录入。
      </p>
    </section>

    <aside class="side-rail">
      <div class="rail-block">
        <span class="rail-title"><AppIcon name="clock" :size="15" />处理记录</span>
        <span v-if="planActivity.length === 0" class="rail-line text-faint">
          暂无计划处理记录；确认、延期或跳过后，动态会出现在这里。
        </span>
        <ul v-else class="timeline">
          <li v-for="event in planActivity" :key="event.id" class="timeline-row">
            <span class="timeline-dot" :class="activityTone(event.event_type)" />
            <div class="timeline-body">
              <div class="timeline-title-row">
                <span class="timeline-event">{{ eventTypeLabel(event.event_type) }}</span>
              </div>
              <span class="timeline-meta">{{ formatDateTime(event.created_at) }} · 操作人 {{ event.created_by }}</span>
            </div>
          </li>
        </ul>
      </div>

      <hr class="rail-divider" />

      <div class="rail-block">
        <span class="rail-title"><AppIcon name="shield" :size="15" />安全边界</span>
        <span class="rail-line text-faint">
          提醒遵守最小间隔与宽限期；连续未响应会升级照护等级。系统不提供修改剂量的快捷按钮。
        </span>
      </div>
    </aside>
  </div>
</template>
