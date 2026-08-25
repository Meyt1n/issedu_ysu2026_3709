<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { apiClient } from '../api/client'
import type { HealthEvent, PlanWorkbenchResponse, RiskListResponse } from '../api/types'
import AppIcon from '../components/AppIcon.vue'
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

const plans = ref<PlanWorkbenchResponse | null>(null)
const events = ref<HealthEvent[]>([])
const risks = ref<RiskListResponse | null>(null)
const loading = ref(false)
const loadError = ref('')
let removeHealthRefreshListener: (() => void) | null = null

const memberName = computed(() => selectedMember.value?.display_name ?? '家人')
const nextPlans = computed(() => (plans.value?.plans ?? []).slice(0, 3))
const recentEvents = computed(() =>
  events.value.filter(event => event.confirmation_status === 'CONFIRMED').slice(-3).reverse(),
)
const visibleRisks = computed(() =>
  (risks.value?.alerts ?? []).slice(0, 4).map(alert => ({
    key: alert.risk_fingerprint || `${alert.rule_id}:${alert.message}`,
    level: alert.level,
    levelLabel: memberRiskLevelLabel(alert.level),
    message: memberRiskMessage(alert),
  })),
)

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
  removeHealthRefreshListener = onHealthDataRefresh(() => void loadHome())
})
onBeforeUnmount(() => removeHealthRefreshListener?.())
</script>

<template>
  <section class="page-hero member-portal-hero">
    <p class="eyebrow">我的家庭</p>
    <h2 class="hero-greeting">你好，{{ memberName }}</h2>
    <p class="hero-sub">这里可以拍照录入药品，也可以查看家人确认过的记录和今天的提醒。</p>
  </section>

  <p v-if="loadError" class="notice warn" role="status">
    <AppIcon name="info" :size="16" />
    暂时没有读取到最新记录，拍照录药仍然可以使用。
  </p>

  <section class="member-quick-grid" aria-label="常用功能">
    <button type="button" class="member-action-card member-action-primary" @click="setView('member-capture')">
      <span class="member-action-icon"><AppIcon name="scan" :size="27" /></span>
      <span><strong>拍照录药</strong><small>拍下药盒，交给家庭管理员确认</small></span>
      <AppIcon name="arrow-right" :size="18" />
    </button>
    <button type="button" class="member-action-card" @click="setView('member-plans')">
      <span class="member-action-icon"><AppIcon name="plan" :size="25" /></span>
      <span><strong>服药提醒</strong><small>{{ nextPlans.length ? `有 ${nextPlans.length} 条近期提醒` : '暂时没有待处理提醒' }}</small></span>
      <AppIcon name="arrow-right" :size="18" />
    </button>
    <button type="button" class="member-action-card" @click="setView('member-records')">
      <span class="member-action-icon"><AppIcon name="compass" :size="25" /></span>
      <span><strong>我的记录</strong><small>只显示家庭已确认的信息</small></span>
      <AppIcon name="arrow-right" :size="18" />
    </button>
  </section>

  <section class="grid-two member-summary-grid">
    <article class="card">
      <div class="card-heading"><div><p class="eyebrow">接下来</p><h3 class="card-title">近期提醒</h3></div></div>
      <div v-if="loading" class="inline-loading">正在读取提醒</div>
      <div v-else-if="nextPlans.length === 0" class="empty-state member-empty"><AppIcon name="plan" :size="30" /><strong>暂时没有提醒</strong><p>家庭管理员设置提醒后，会显示在这里。</p></div>
      <ul v-else class="list-plain member-list">
        <li v-for="plan in nextPlans" :key="plan.plan_event_id" class="row-card">
          <strong><AppIcon name="pill" :size="16" />{{ plan.drug }}</strong>
          <span>{{ plan.schedule }}<span v-if="plan.dose"> · 每次 {{ plan.dose }}</span></span>
        </li>
      </ul>
    </article>
    <article class="card">
      <div class="card-heading"><div><p class="eyebrow">已确认</p><h3 class="card-title">最近记录</h3></div></div>
      <div v-if="recentEvents.length === 0" class="empty-state member-empty"><AppIcon name="compass" :size="30" /><strong>还没有已确认记录</strong><p>管理员确认药品或家人操作后，会显示在这里。</p></div>
      <ul v-else class="list-plain member-list">
        <li v-for="event in recentEvents" :key="event.id" class="row-card">
          <strong>{{ eventTypeLabel(event.event_type) }}</strong>
          <span>{{ summarizeEventPayload(event) || '已记录' }} · {{ formatDateTime(event.occurred_at) }}</span>
        </li>
      </ul>
    </article>
  </section>

  <section v-if="visibleRisks.length" class="card member-risk-card" aria-label="需要留意的情况">
    <div class="card-heading">
      <div>
        <p class="eyebrow">管理员已确认</p>
        <h3 class="card-title">需要留意的情况</h3>
      </div>
      <span class="member-risk-count">{{ risks?.total }} 条</span>
    </div>
    <p class="member-risk-intro">这些提醒来自家庭管理员确认过的记录。如果不确定怎么处理，请先问家人或医生。</p>
    <ul class="list-plain member-risk-list">
      <li v-for="alert in visibleRisks" :key="alert.key" class="member-risk-row" :class="alert.level">
        <span class="member-risk-level">{{ alert.levelLabel }}</span>
        <span>{{ alert.message }}</span>
      </li>
    </ul>
  </section>
</template>
