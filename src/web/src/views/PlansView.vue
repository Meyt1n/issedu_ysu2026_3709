<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'

import { apiClient } from '../api/client'
import type { PlanWorkbenchItem, PlanWorkbenchResponse } from '../api/types'
import AppIcon from '../components/AppIcon.vue'
import {
  createIdempotencyKey,
  formatError,
  onHealthDataRefresh,
  pushToast,
  requestOptions,
  selectMember,
  selectedMember,
  session,
} from '../store'
import { formatDateTime } from '../ui/labels'

const workbench = ref<PlanWorkbenchResponse | null>(null)
const loading = ref(false)
const loadError = ref('')
const busyPlanId = ref<string | null>(null)
const celebratingPlanId = ref<string | null>(null)
let removeHealthRefreshListener: (() => void) | null = null

const actionDraft = reactive({
  planEventId: '',
  action: 'confirm' as 'confirm' | 'defer' | 'skip' | 'miss',
  delayHours: 1,
  skipReason: '',
})

const plans = computed(() => workbench.value?.plans ?? [])

const planActivity = computed(() =>
  plans.value
    .filter((plan): plan is PlanWorkbenchItem & { last_action: NonNullable<PlanWorkbenchItem['last_action']> } =>
      plan.last_action !== null,
    )
    .sort((left, right) => Date.parse(right.last_action.recorded_at) - Date.parse(left.last_action.recorded_at))
    .slice(0, 8),
)

async function loadPlans(): Promise<void> {
  const householdId = session.selectedHouseholdId
  const memberId = session.selectedMemberId
  if (!householdId || !memberId) return

  loading.value = true
  loadError.value = ''
  try {
    const result = await apiClient.getPlanWorkbench(householdId, memberId, requestOptions.value)
    // Older local API/demo fixtures may omit optional display arrays.  Keep
    // the admin workbench readable while the server rolls forward its schema.
    workbench.value = {
      ...result,
      plans: result.plans.map(plan => ({
        ...plan,
        times: plan.times ?? [],
        action_history: plan.action_history ?? [],
      })),
    }
  } catch (cause) {
    workbench.value = null
    loadError.value = formatError(cause)
  } finally {
    loading.value = false
  }
}

function openAction(plan: PlanWorkbenchItem, action: 'confirm' | 'defer' | 'skip' | 'miss'): void {
  if (actionDraft.planEventId === plan.plan_event_id && actionDraft.action === action) {
    actionDraft.planEventId = ''
    return
  }
  actionDraft.planEventId = plan.plan_event_id
  actionDraft.action = action
  actionDraft.delayHours = 1
  actionDraft.skipReason = ''
}

async function submitAction(plan: PlanWorkbenchItem): Promise<void> {
  const householdId = session.selectedHouseholdId
  const memberId = session.selectedMemberId
  if (!householdId || !memberId || busyPlanId.value) return
  if ((actionDraft.action === 'skip' || actionDraft.action === 'miss') && !actionDraft.skipReason.trim()) {
    pushToast('error', actionDraft.action === 'miss' ? '记录漏服前请填写原因。' : '跳过服药前请填写原因，方便家人了解情况。')
    return
  }

  busyPlanId.value = plan.plan_event_id
  const options = { ...requestOptions.value, idempotencyKey: createIdempotencyKey() }
  try {
    if (actionDraft.action === 'confirm') {
      await apiClient.confirmCarePlan(householdId, memberId, plan.plan_event_id, options)
      pushToast('success', `已确认「${plan.drug}」按计划服用。`)
      celebratingPlanId.value = plan.plan_event_id
      setTimeout(() => {
        if (celebratingPlanId.value === plan.plan_event_id) celebratingPlanId.value = null
      }, 1400)
    } else if (actionDraft.action === 'defer') {
      await apiClient.deferCarePlan(householdId, memberId, plan.plan_event_id, actionDraft.delayHours, options)
      pushToast('success', `「${plan.drug}」已延期 ${actionDraft.delayHours} 小时提醒。`)
    } else if (actionDraft.action === 'skip') {
      await apiClient.skipCarePlan(householdId, memberId, plan.plan_event_id, actionDraft.skipReason.trim(), options)
      pushToast('info', `已记录跳过「${plan.drug}」及原因。`)
    } else {
      await apiClient.missCarePlan(householdId, memberId, plan.plan_event_id, actionDraft.skipReason.trim(), options)
      pushToast('error', `已记录「${plan.drug}」本次漏服，后续提醒仍会保留。`)
    }
    actionDraft.planEventId = ''
    await loadPlans()
  } catch (cause) {
    pushToast('error', formatError(cause))
  } finally {
    busyPlanId.value = null
  }
}

function activityTone(action: string): string {
  if (action === 'CONFIRM') return 'pine'
  if (action === 'DEFER') return 'gold'
  return 'rose'
}

function actionLabel(action: string): string {
  if (action === 'CONFIRM') return '确认服药'
  if (action === 'DEFER') return '延期提醒'
  if (action === 'MISS') return '记录漏服'
  return '跳过'
}

function onMemberChange(event: Event): void {
  selectMember((event.target as HTMLSelectElement).value)
}

watch(
  () => [session.selectedHouseholdId, session.selectedMemberId],
  () => void loadPlans(),
)

onMounted(() => {
  void loadPlans()
  removeHealthRefreshListener = onHealthDataRefresh(() => void loadPlans())
})

onBeforeUnmount(() => removeHealthRefreshListener?.())
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
        正在读取服务端待办
      </div>
      <div v-else-if="plans.length === 0" class="empty-state">
        <AppIcon class="empty-art" name="plan" :size="40" />
        <strong>还没有已确认的用药计划</strong>
        <p>请先在「成员档案」录入一条「创建用药计划」事实，计划将出现在这里。</p>
      </div>
      <ul v-else class="list-plain">
        <li v-for="plan in plans" :key="plan.plan_event_id" class="row-card">
          <div class="row-top">
            <span class="row-title">
              <AppIcon name="pill" :size="18" style="color: var(--pine)" />
              {{ plan.drug }}
            </span>
            <span
              v-if="plan.last_action"
              class="pill"
              :class="activityTone(plan.last_action.action)"
            >
              {{ actionLabel(plan.last_action.action) }} ·
              {{ formatDateTime(plan.last_action.recorded_at) }}
            </span>
          </div>
          <p class="row-meta" style="margin: 0">
            <AppIcon name="clock" :size="14" style="vertical-align: -2px" />
            {{ plan.schedule }}
            <span v-if="plan.dose"> · 每次 {{ plan.dose }}</span>
            <span v-if="plan.times.length > 0"> · {{ plan.times.join('、') }}</span>
            · 下次处理 {{ formatDateTime(plan.next_action_at) }}
            <span class="pill" :class="plan.status === 'ESCALATED' ? 'rose' : plan.status === 'REMINDER' ? 'gold' : 'pine'">
              {{ plan.status === 'ESCALATED' ? '已升级' : plan.status === 'REMINDER' ? '待提醒' : '时间窗内' }}
            </span>
          </p>
          <p v-if="plan.start_date || plan.end_date" class="row-meta" style="margin: 0">
            疗程：{{ plan.start_date ?? '未设开始日期' }} 至 {{ plan.end_date ?? '未设结束日期' }}
          </p>
          <div class="row-actions">
            <span v-if="celebratingPlanId === plan.plan_event_id" class="heart-burst" aria-hidden="true">
              <i style="--hx: -14px">♥</i><i style="--hx: 8px">♥</i><i style="--hx: 20px">♥</i>
            </span>
            <button
              type="button"
              class="btn btn-primary btn-small"
              :disabled="busyPlanId === plan.plan_event_id || !plan.allowed_actions.includes('CONFIRM')"
              @click="openAction(plan, 'confirm')"
            >
              确认服药
            </button>
            <button
              type="button"
              class="btn btn-ghost btn-small"
              :disabled="busyPlanId === plan.plan_event_id || !plan.allowed_actions.includes('DEFER')"
              @click="openAction(plan, 'defer')"
            >
              延期提醒
            </button>
            <button
              type="button"
              class="btn btn-danger btn-small"
              :disabled="busyPlanId === plan.plan_event_id || !plan.allowed_actions.includes('SKIP')"
              @click="openAction(plan, 'skip')"
            >
              跳过
            </button>
            <button
              type="button"
              class="btn btn-danger btn-small"
              :disabled="busyPlanId === plan.plan_event_id || !plan.allowed_actions.includes('MISS')"
              @click="openAction(plan, 'miss')"
            >
              记录漏服
            </button>
          </div>

          <form
            v-if="actionDraft.planEventId === plan.plan_event_id"
            class="section-stack"
            style="border-top: 1px dashed var(--line); padding-top: 12px"
            @submit.prevent="submitAction(plan)"
          >
            <template v-if="actionDraft.action === 'confirm'">
              <p class="card-note" style="margin: 0">确认代表本次已按医嘱服用，会写入健康事件并通知授权照护者。</p>
            </template>
            <template v-else-if="actionDraft.action === 'defer'">
              <label class="field">
                延期小时数（1–2）
                <input v-model.number="actionDraft.delayHours" type="number" min="1" max="2" required />
                <small>仅推迟本次提醒，最长 2 小时；不改变医嘱剂量与频次。</small>
              </label>
            </template>
            <template v-else>
              <label class="field">
                {{ actionDraft.action === 'miss' ? '漏服原因（必填）' : '跳过原因（必填）' }}
                <input v-model="actionDraft.skipReason" autocomplete="off" required :placeholder="actionDraft.action === 'miss' ? '例如 忘记服用或外出未携带' : '例如 医生建议今日暂停'" />
                <small v-if="actionDraft.action === 'miss'">漏服只记录事实，不会自动补服或修改剂量；后续提醒仍由计划决定。</small>
                <small v-else>系统不会替你判断能否停药；连续未响应将升级给照护者。</small>
              </label>
            </template>
            <div class="row-actions">
              <button type="submit" class="btn btn-clay btn-small" :disabled="busyPlanId === plan.plan_event_id">
                {{ busyPlanId === plan.planEventId ? '正在记录' : '确定' }}
              </button>
            </div>
          </form>
          <div v-if="plan.action_history.length > 0" class="capability-chips" style="margin-top: 8px">
            <span v-for="(action, index) in plan.action_history" :key="`${plan.plan_event_id}-${index}`" class="pill" :class="activityTone(action.action)">
              {{ actionLabel(action.action) }} · {{ formatDateTime(action.recorded_at) }}
            </span>
          </div>
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
          <li v-for="plan in planActivity" :key="plan.plan_event_id" class="timeline-row">
            <span class="timeline-dot" :class="activityTone(plan.last_action.action)" />
            <div class="timeline-body">
              <div class="timeline-title-row">
                <span class="timeline-event">{{ plan.drug }} · {{ actionLabel(plan.last_action.action) }}</span>
              </div>
              <span class="timeline-meta">{{ formatDateTime(plan.last_action.recorded_at) }} · 服务端处理记录</span>
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
