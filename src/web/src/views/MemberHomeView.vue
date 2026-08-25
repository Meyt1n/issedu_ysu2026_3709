<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { apiClient } from '../api/client'
import type { HealthEvent, PlanWorkbenchResponse, RiskListResponse } from '../api/types'
import AppIcon from '../components/AppIcon.vue'
import HealthNewsPanel from '../components/HealthNewsPanel.vue'
import {
  formatError,
  onHealthDataRefresh,
  requestOptions,
  selectedMember,
  session,
  setView,
} from '../store'
import { eventTypeLabel, formatDateTime, summarizeEventPayload } from '../ui/labels'
import { memberRiskLevelLabel, memberRiskMessage } from '../ui/memberRisk'
import { useMemberVisionTracking } from '../ui/useMemberVisionTracking'

const plans = ref<PlanWorkbenchResponse | null>(null)
const events = ref<HealthEvent[]>([])
const risks = ref<RiskListResponse | null>(null)
const loading = ref(false)
const loadError = ref('')
let removeHealthRefreshListener: (() => void) | null = null

const {
  homePhotoTasks,
  needsRetakeTasks,
  awaitingConfirmationTasks,
  confirmedTaskIds,
  hasActiveTasks,
  taskStatusLabel,
  taskStatusHint,
  taskNeedsRetake,
  refreshTracking,
} = useMemberVisionTracking()

const memberName = computed(() => selectedMember.value?.display_name ?? '家人')
const nextPlans = computed(() => (plans.value?.plans ?? []).slice(0, 3))
const recentEvents = computed(() =>
  events.value.filter(event => event.confirmation_status === 'CONFIRMED').slice(-3).reverse(),
)
const recentMetrics = computed(() =>
  events.value
    .filter(
      event =>
        event.confirmation_status === 'CONFIRMED' && event.event_type === 'metric_recorded',
    )
    .slice(-4)
    .reverse(),
)
const visibleRisks = computed(() =>
  (risks.value?.alerts ?? []).slice(0, 4).map(alert => ({
    key: alert.risk_fingerprint || `${alert.rule_id}:${alert.message}`,
    level: alert.level,
    levelLabel: memberRiskLevelLabel(alert.level),
    message: memberRiskMessage(alert),
  })),
)

const photoBlockTitle = computed(() =>
  needsRetakeTasks.value.length > 0 ? '有照片需要重新拍' : '等待家人确认的照片',
)
const photoBlockCue = computed(() =>
  needsRetakeTasks.value.length > 0
    ? '换个光线好、字清楚的角度再拍一次。'
    : '确认后会出现在「我的记录」。',
)
const photoPrimaryAction = computed(() =>
  needsRetakeTasks.value.length > 0
    ? { label: '去重拍', view: 'member-capture' as const }
    : { label: '看看进度', view: 'member-capture' as const },
)
const captureQuickAction = computed(() => {
  if (needsRetakeTasks.value.length > 0) {
    return { title: '重拍药盒', hint: '刚才没看清，再拍一张', primary: true }
  }
  if (awaitingConfirmationTasks.value.length > 0) {
    return { title: '再拍一张', hint: '上一张还在等家人确认', primary: false }
  }
  return { title: '拍照录药', hint: '拍药盒，交给家人', primary: true }
})

function metricSummary(event: HealthEvent): string {
  const payload = event.payload ?? {}
  if (payload.metric === 'blood_pressure') {
    return `血压 ${payload.systolic ?? '—'}/${payload.diastolic ?? '—'} ${payload.unit ?? 'mmHg'}`
  }
  if (payload.metric === 'blood_glucose') {
    return `血糖 ${payload.value ?? '—'} ${payload.unit ?? 'mmol/L'}${payload.meal_context ? ` · ${payload.meal_context}` : ''}`
  }
  return summarizeEventPayload(event)
}

async function loadHome(): Promise<void> {
  const householdId = session.selectedHouseholdId
  const memberId = session.selectedMemberId
  if (!householdId || !memberId) return
  loading.value = true
  loadError.value = ''
  const [planResult, eventResult, riskResult] = await Promise.allSettled([
    apiClient.getPlanWorkbench(householdId, memberId, requestOptions.value),
    apiClient.listMemberTimeline(householdId, memberId, requestOptions.value),
    apiClient.listMemberRisks(householdId, memberId, requestOptions.value),
  ])
  plans.value = planResult.status === 'fulfilled' ? planResult.value : null
  events.value = eventResult.status === 'fulfilled' ? eventResult.value : []
  risks.value = riskResult.status === 'fulfilled' ? riskResult.value : null
  if (
    planResult.status === 'rejected' &&
    eventResult.status === 'rejected' &&
    riskResult.status === 'rejected'
  ) {
    loadError.value = formatError(planResult.reason)
  }
  loading.value = false
}

watch(() => [session.selectedHouseholdId, session.selectedMemberId], () => void loadHome())
onMounted(() => {
  void loadHome()
  removeHealthRefreshListener = onHealthDataRefresh(() => {
    void loadHome()
    void refreshTracking()
  })
})
onBeforeUnmount(() => removeHealthRefreshListener?.())
</script>

<template>
  <section class="page-hero member-portal-hero">
    <p class="eyebrow">我的家庭</p>
    <h2 class="hero-greeting">你好，{{ memberName }}</h2>
    <p class="hero-sub">拍照录药、查看提醒和家人确认过的记录。</p>
  </section>

  <p v-if="loadError" class="notice warn" role="status">
    <AppIcon name="info" :size="16" />
    暂时没有读取到最新记录，拍照录药仍然可以使用。
  </p>

  <section v-if="visibleRisks.length" class="card member-risk-card" aria-label="需要留意的情况">
    <div class="card-heading">
      <div>
        <p class="eyebrow">家人已确认</p>
        <h3 class="card-title">需要留意的情况</h3>
      </div>
      <span class="member-risk-count">{{ risks?.total }} 条</span>
    </div>
    <p class="member-risk-intro">不确定时，请先问家人或医生。</p>
    <ul class="list-plain member-risk-list">
      <li v-for="alert in visibleRisks" :key="alert.key" class="member-risk-row" :class="alert.level">
        <span class="member-risk-level">{{ alert.levelLabel }}</span>
        <span>{{ alert.message }}</span>
      </li>
    </ul>
  </section>

  <section v-if="homePhotoTasks.length" class="card member-pending-card" :aria-label="photoBlockTitle">
    <div class="card-heading">
      <div>
        <p class="eyebrow">{{ needsRetakeTasks.length ? '需要处理' : '等待确认' }}</p>
        <h3 class="card-title">{{ photoBlockTitle }}</h3>
      </div>
      <span v-if="hasActiveTasks" class="pill gold">正在看照片</span>
      <span v-else-if="needsRetakeTasks.length" class="pill clay">{{ needsRetakeTasks.length }} 张待重拍</span>
      <span v-else class="member-pending-count">{{ awaitingConfirmationTasks.length }} 张</span>
    </div>
    <p class="member-pending-intro">{{ photoBlockCue }}</p>
    <div class="member-pending-body">
      <ul class="list-plain member-status-list">
        <li v-for="task in homePhotoTasks" :key="task.id" class="member-status-row">
          <span
            class="member-status-icon"
            :class="confirmedTaskIds.has(task.id) ? 'confirmed' : taskNeedsRetake(task) ? 'failed' : 'pending'"
          >
            <AppIcon
              :name="confirmedTaskIds.has(task.id) ? 'check' : taskNeedsRetake(task) ? 'alert' : 'scan'"
              :size="17"
            />
          </span>
          <span><strong>{{ taskStatusLabel(task) }}</strong><small>{{ taskStatusHint(task) }}</small></span>
        </li>
      </ul>
      <button
        type="button"
        class="btn btn-small member-pending-link"
        :class="needsRetakeTasks.length ? 'btn-clay' : 'btn-ghost'"
        @click="setView(photoPrimaryAction.view)"
      >
        <AppIcon name="scan" :size="15" />
        {{ photoPrimaryAction.label }}
      </button>
    </div>
  </section>

  <section class="member-quick-grid" aria-label="常用功能">
    <button
      type="button"
      class="member-action-card"
      :class="{ 'member-action-primary': captureQuickAction.primary }"
      @click="setView('member-capture')"
    >
      <span class="member-action-icon"><AppIcon name="scan" :size="24" /></span>
      <span><strong>{{ captureQuickAction.title }}</strong><small>{{ captureQuickAction.hint }}</small></span>
      <AppIcon name="arrow-right" :size="16" />
    </button>
    <button type="button" class="member-action-card" @click="setView('member-plans')">
      <span class="member-action-icon"><AppIcon name="plan" :size="22" /></span>
      <span><strong>服药提醒</strong><small>{{ nextPlans.length ? `${nextPlans.length} 条近期提醒` : '暂无提醒' }}</small></span>
      <AppIcon name="arrow-right" :size="16" />
    </button>
    <button type="button" class="member-action-card" @click="setView('member-records')">
      <span class="member-action-icon"><AppIcon name="compass" :size="22" /></span>
      <span><strong>我的记录</strong><small>只看已确认内容</small></span>
      <AppIcon name="arrow-right" :size="16" />
    </button>
  </section>

  <section class="grid-two member-summary-grid">
    <article class="card">
      <div class="card-heading"><div><p class="eyebrow">接下来</p><h3 class="card-title">近期提醒</h3></div></div>
      <div v-if="loading" class="inline-loading">正在读取提醒</div>
      <div v-else-if="nextPlans.length === 0" class="empty-state member-empty"><AppIcon name="plan" :size="26" /><strong>暂时没有提醒</strong><p>家人设置后会出现在这里。</p></div>
      <ul v-else class="list-plain member-list">
        <li v-for="plan in nextPlans" :key="plan.plan_event_id" class="row-card">
          <strong><AppIcon name="pill" :size="16" />{{ plan.drug }}</strong>
          <span>{{ plan.schedule }}<span v-if="plan.dose"> · 每次 {{ plan.dose }}</span></span>
        </li>
      </ul>
    </article>
    <article class="card">
      <div class="card-heading"><div><p class="eyebrow">已确认</p><h3 class="card-title">最近记录</h3></div></div>
      <div v-if="recentEvents.length === 0" class="empty-state member-empty"><AppIcon name="compass" :size="26" /><strong>还没有已确认记录</strong><p>家人确认后会出现在这里。</p></div>
      <ul v-else class="list-plain member-list">
        <li v-for="event in recentEvents" :key="event.id" class="row-card">
          <strong>{{ eventTypeLabel(event.event_type, 'member') }}</strong>
          <span>{{ summarizeEventPayload(event) || '已记录' }} · {{ formatDateTime(event.occurred_at) }}</span>
        </li>
      </ul>
    </article>
  </section>

  <section v-if="recentMetrics.length" class="card" aria-label="最近指标观察">
    <div class="card-heading">
      <div>
        <p class="eyebrow">居家观察</p>
        <h3 class="card-title">最近指标</h3>
      </div>
    </div>
    <p class="member-risk-intro">以下为家人确认过的居家观察记录，仅供参考，不能当作诊断结论。</p>
    <ul class="list-plain member-list">
      <li v-for="event in recentMetrics" :key="event.id" class="row-card">
        <strong>{{ metricSummary(event) }}</strong>
        <span>{{ formatDateTime(String(event.payload?.measured_at || event.occurred_at)) }}</span>
      </li>
    </ul>
  </section>

  <HealthNewsPanel />
</template>
