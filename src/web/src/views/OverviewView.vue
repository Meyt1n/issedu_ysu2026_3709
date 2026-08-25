<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { apiClient } from '../api/client'
import type {
  HealthEvent,
  MemberState,
  PlanWorkbenchItem,
  PlanWorkbenchResponse,
  ReviewTask,
  RiskListResponse,
  WeatherResponse,
} from '../api/types'
import emptyCorner from '../assets/empty-corner.jpg'
import AppIcon from '../components/AppIcon.vue'
import CountUp from '../components/CountUp.vue'
import HealthNewsPanel from '../components/HealthNewsPanel.vue'
import SkeletonList from '../components/SkeletonList.vue'
import WeatherActionPanel from '../components/WeatherActionPanel.vue'
import { vTilt } from '../ui/tilt'
import {
  formatError,
  onHealthDataRefresh,
  requestOptions,
  selectMember,
  selectedMember,
  session,
  setView,
} from '../store'
import {
  confirmationLabel,
  eventTone,
  eventTypeLabel,
  formatDateTime,
  fusionStatusLabel,
  greetingByHour,
  memberRoleLabel,
  relativeTime,
  reviewStatusLabel,
  summarizeEventPayload,
} from '../ui/labels'
import { isSameLocalDay, memberEventCount, reviewDrugCandidate } from '../overview/overviewView'

const timeline = ref<HealthEvent[]>([])
const memberState = ref<MemberState | null>(null)
const risks = ref<RiskListResponse | null>(null)
const reviewTasks = ref<ReviewTask[]>([])
const planWorkbench = ref<PlanWorkbenchResponse | null>(null)
const memberStates = ref<Record<string, MemberState | null>>({})
const weather = ref<WeatherResponse | null>(null)
const weatherLoading = ref(false)
const loading = ref(false)
const loadError = ref('')
let removeHealthRefreshListener: (() => void) | null = null

const greeting = computed(() => greetingByHour())
const recentEvents = computed(() => [...timeline.value].reverse().slice(0, 6))
const eventsCount = computed(() => {
  const value = memberState.value?.state?.events_count
  return typeof value === 'number' ? value : timeline.value.length
})
const pendingReviews = computed(
  () => reviewTasks.value.filter(task => task.status === 'PENDING_REVIEW').length,
)

type DashboardView = 'review' | 'risks' | 'plans'

interface PendingOverviewItem {
  id: string
  label: string
  detail: string
  tone: 'clay' | 'gold' | 'rose'
  view: DashboardView
}

const orderedPlans = computed(() =>
  [...(planWorkbench.value?.plans ?? [])].sort(
    (left, right) => Date.parse(left.next_action_at) - Date.parse(right.next_action_at),
  ),
)

const todayPlans = computed(() => {
  const today = orderedPlans.value.filter(plan => isSameLocalDay(plan.next_action_at))
  return (today.length > 0 ? today : orderedPlans.value).slice(0, 4)
})

const hasTodayPlans = computed(() => orderedPlans.value.some(plan => isSameLocalDay(plan.next_action_at)))

const pendingOverviewItems = computed<PendingOverviewItem[]>(() => {
  const items: PendingOverviewItem[] = []

  for (const task of reviewTasks.value.filter(item => item.status === 'PENDING_REVIEW').slice(0, 4)) {
    items.push({
      id: `review-${task.id}`,
      label: '识别待复核',
      detail: `${reviewDrugCandidate(task)} · 识别候选，不是健康事实`,
      tone: 'clay',
      view: 'review',
    })
  }

  for (const alert of (risks.value?.alerts ?? []).filter(item => !item.acknowledgement).slice(0, 4)) {
    items.push({
      id: `risk-${alert.risk_fingerprint}`,
      label: '风险待知晓',
      detail: `${alert.message} · ${alert.rule_id}`,
      tone: alert.level === 'SEVERE' ? 'rose' : 'gold',
      view: 'risks',
    })
  }

  for (const plan of orderedPlans.value.filter(item => item.status !== 'NORMAL').slice(0, 4)) {
    items.push({
      id: `plan-${plan.plan_event_id}`,
      label: plan.status === 'ESCALATED' ? '用药需关注' : '用药提醒',
      detail: `${plan.drug} · ${plan.schedule}`,
      tone: plan.status === 'ESCALATED' ? 'rose' : 'gold',
      view: 'plans',
    })
  }

  return items.slice(0, 6)
})

const pendingOverviewCount = computed(
  () =>
    reviewTasks.value.filter(task => task.status === 'PENDING_REVIEW').length +
    (risks.value?.alerts ?? []).filter(alert => !alert.acknowledgement).length +
    orderedPlans.value.filter(plan => plan.status !== 'NORMAL').length,
)

const recentMedicationCandidates = computed(() =>
  [...reviewTasks.value]
    .sort(
      (left, right) =>
        Date.parse(right.updated_at || right.created_at) - Date.parse(left.updated_at || left.created_at),
    )
    .slice(0, 5)
    .map(task => ({
      id: task.id,
      drugName: reviewDrugCandidate(task),
      status: reviewStatusLabel(task.status),
      fusionStatus: fusionStatusLabel(task.fusion_status),
      createdAt: task.updated_at || task.created_at,
    })),
)

const memberOverviewRows = computed(() =>
  session.members.map(member => {
    const state = memberStates.value[member.id]
    const eventCount = memberEventCount(state)
    return {
      id: member.id,
      name: member.display_name,
      role: memberRoleLabel(member.role),
      eventCount,
      updatedAt: state?.updated_at ?? null,
      status: state ? (eventCount > 0 ? '有已同步记录' : '暂无已同步记录') : '状态暂不可见',
      tone: state ? (eventCount > 0 ? 'pine' : 'gold') : 'plain',
    }
  }),
)

function planStatusLabel(status: PlanWorkbenchItem['status']): string {
  if (status === 'ESCALATED') return '需关注'
  if (status === 'REMINDER') return '待提醒'
  return '计划内'
}

function planStatusTone(status: PlanWorkbenchItem['status']): string {
  if (status === 'ESCALATED') return 'rose'
  if (status === 'REMINDER') return 'gold'
  return 'pine'
}

async function loadWeather(): Promise<void> {
  weatherLoading.value = true
  try {
    weather.value = await apiClient.getWeatherActionCards(
      undefined,
      undefined,
      requestOptions.value,
    )
  } catch {
    weather.value = {
      status: 'provider_unavailable',
      degraded_reason: 'provider_unavailable',
      action_cards: [],
    }
  } finally {
    weatherLoading.value = false
  }
}

async function loadOverview(): Promise<void> {
  const householdId = session.selectedHouseholdId
  const memberId = session.selectedMemberId
  if (!householdId || !memberId) {
    timeline.value = []
    memberState.value = null
    risks.value = null
    reviewTasks.value = []
    planWorkbench.value = null
    memberStates.value = {}
    return
  }

  loading.value = true
  loadError.value = ''
  try {
    const [timelineResult, stateResult, riskResult, reviewResult, planResult] =
      await Promise.allSettled([
        apiClient.listMemberTimeline(householdId, memberId, requestOptions.value),
        apiClient.getMemberState(householdId, memberId, requestOptions.value),
        apiClient.listMemberRisks(householdId, memberId, requestOptions.value),
        apiClient.listReviewTasks(householdId, memberId, requestOptions.value),
        apiClient.getPlanWorkbench(householdId, memberId, requestOptions.value),
      ])

    // 新成员还没有状态投影/风险数据属于正常情况（404），
    // 页面按"暂无数据"展示，不把它当作故障告警。
    timeline.value = timelineResult.status === 'fulfilled' ? timelineResult.value : []
    memberState.value = stateResult.status === 'fulfilled' ? stateResult.value : null
    risks.value = riskResult.status === 'fulfilled' ? riskResult.value : null
    reviewTasks.value = reviewResult.status === 'fulfilled' ? reviewResult.value : []
    planWorkbench.value = planResult.status === 'fulfilled' ? planResult.value : null

    const stateResults = await Promise.allSettled(
      session.members.map(member =>
        apiClient.getMemberState(householdId, member.id, requestOptions.value),
      ),
    )
    memberStates.value = Object.fromEntries(
      session.members.map((member, index) => [
        member.id,
        stateResults[index]?.status === 'fulfilled' ? stateResults[index].value : null,
      ]),
    )
  } catch (cause) {
    loadError.value = formatError(cause)
  } finally {
    loading.value = false
  }
}

function onMemberChange(event: Event): void {
  selectMember((event.target as HTMLSelectElement).value)
}

watch(
  () => [session.selectedHouseholdId, session.selectedMemberId],
  () => void loadOverview(),
)

onMounted(() => {
  void loadOverview()
  void loadWeather()
  removeHealthRefreshListener = onHealthDataRefresh(() => void loadOverview())
})

onBeforeUnmount(() => removeHealthRefreshListener?.())
</script>

<template>
  <section class="page-hero">
    <div class="card-heading" style="margin-bottom: 0">
      <div style="align-items: center; display: flex; gap: 18px">
        <span class="seal" aria-hidden="true"><i>家</i><i>的</i><i>温</i><i>度</i></span>
        <div>
          <h2 class="hero-greeting"><span class="gradient-text">{{ greeting }}</span>，{{ selectedMember?.display_name ?? session.actorId }}</h2>
          <svg class="brush-underline" viewBox="0 0 220 12" aria-hidden="true">
            <path d="M4 8 C 46 3, 92 11, 128 6 S 196 4, 216 7" />
          </svg>
          <p class="hero-sub">
            这里是 {{ session.households.find(h => h.id === session.selectedHouseholdId)?.name ?? '家庭' }} 的健康近况，先看看
            {{ selectedMember?.display_name ?? '家人' }} 最近的变化。
          </p>
        </div>
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

  <HealthNewsPanel />

  <section class="stat-strip" aria-label="家庭健康概况">
    <div class="stat-cell pine">
      <span class="cell-cap"><AppIcon name="members" :size="14" />家庭成员</span>
      <span class="cell-num"><CountUp :value="session.members.length" /><small>位</small></span>
      <span class="cell-sub">{{ session.isOwnerView ? '管理员视图，可管理授权' : '仅显示已授权成员' }}</span>
    </div>
    <div class="stat-cell sky">
      <span class="cell-cap"><AppIcon name="timeline" :size="14" />已确认事件</span>
      <span class="cell-num"><CountUp :value="eventsCount" /><small>条</small></span>
      <span class="cell-sub">{{ selectedMember?.display_name ?? '当前成员' }}的事实记录</span>
    </div>
    <div class="stat-cell" :class="(risks?.severe_count ?? 0) > 0 ? 'rose' : 'gold'">
      <span class="cell-cap"><AppIcon name="shield" :size="14" />风险信号</span>
      <span class="cell-num"><CountUp :value="risks?.total ?? 0" /><small>个</small></span>
      <span class="cell-sub">严重 {{ risks?.severe_count ?? 0 }} · 警告 {{ risks?.warning_count ?? 0 }}</span>
    </div>
    <div class="stat-cell clay">
      <span class="cell-cap"><AppIcon name="review" :size="14" />待人工复核</span>
      <span class="cell-num"><CountUp :value="pendingReviews" /><small>项</small></span>
      <span class="cell-sub">识别候选需确认后才入档</span>
    </div>
  </section>

  <section class="quick-actions" aria-label="快捷入口">
    <button v-tilt="4" type="button" class="quick-card clay" @click="setView('scan')">
      <span class="quick-icon"><AppIcon name="scan" :size="22" /></span>
      <span class="quick-text">
        <strong>扫描药盒</strong>
        <span>拍照识别，人工确认后入档</span>
      </span>
      <AppIcon class="quick-arrow" name="arrow-right" :size="17" />
    </button>
    <button v-tilt="4" type="button" class="quick-card pine" @click="setView('members')">
      <span class="quick-icon"><AppIcon name="plus" :size="22" /></span>
      <span class="quick-text">
        <strong>记一条事实</strong>
        <span>用药、过敏、报告手工录入</span>
      </span>
      <AppIcon class="quick-arrow" name="arrow-right" :size="17" />
    </button>
    <button v-tilt="4" type="button" class="quick-card sky" @click="setView('risks')">
      <span class="quick-icon"><AppIcon name="shield" :size="22" /></span>
      <span class="quick-text">
        <strong>查看用药安全</strong>
        <span>规则命中与证据链</span>
      </span>
      <AppIcon class="quick-arrow" name="arrow-right" :size="17" />
    </button>
  </section>

  <section class="home-dashboard-grid home-dashboard-primary" aria-label="今日家庭健康摘要">
    <div class="home-dashboard-weather" aria-label="今日天气">
      <WeatherActionPanel
        :weather="weather"
        :loading="weatherLoading"
        @refresh="loadWeather"
      />
    </div>

    <section class="home-dashboard-card" aria-labelledby="pending-overview-title">
      <div class="sec-head">
        <span class="sec-no">01</span>
        <h3 id="pending-overview-title">待确认事项</h3>
        <span class="sec-line" />
        <button type="button" class="btn btn-ghost btn-small" @click="setView('review')">
          查看
          <AppIcon name="arrow-right" :size="14" />
        </button>
      </div>
      <div class="home-dashboard-count">
        <strong>{{ pendingOverviewCount }}</strong>
        <span>项需要留意</span>
      </div>
      <ul v-if="pendingOverviewItems.length > 0" class="home-dashboard-list">
        <li v-for="item in pendingOverviewItems" :key="item.id">
          <button type="button" class="home-dashboard-list-row" @click="setView(item.view)">
            <span class="pill" :class="item.tone">{{ item.label }}</span>
            <span class="home-dashboard-list-detail">{{ item.detail }}</span>
            <AppIcon name="arrow-right" :size="14" />
          </button>
        </li>
      </ul>
      <p v-else class="home-dashboard-empty">当前没有待复核、待知晓或升级提醒事项。</p>
    </section>
  </section>

  <section class="home-dashboard-grid home-dashboard-secondary" aria-label="家庭健康动态">
    <section class="home-dashboard-card" aria-labelledby="medication-overview-title">
      <div class="sec-head">
        <span class="sec-no">02</span>
        <h3 id="medication-overview-title">今日用药</h3>
        <span class="sec-line" />
        <button type="button" class="btn btn-ghost btn-small" @click="setView('plans')">
          用药计划
          <AppIcon name="arrow-right" :size="14" />
        </button>
      </div>
      <p class="home-dashboard-caption">
        {{ selectedMember?.display_name ?? '当前成员' }} ·
        {{ hasTodayPlans ? '今日已确认计划' : '今日暂无计划，展示近期已确认计划' }}
      </p>
      <SkeletonList v-if="loading" :rows="3" />
      <p v-else-if="todayPlans.length === 0" class="home-dashboard-empty">
        暂无可展示的已确认用药计划，识别候选不会自动进入这里。
      </p>
      <ul v-else class="home-dashboard-list">
        <li v-for="plan in todayPlans" :key="plan.plan_event_id" class="home-dashboard-plan-row">
          <div>
            <strong>{{ plan.drug }}</strong>
            <span>{{ plan.schedule }} · 下次 {{ formatDateTime(plan.next_action_at) }}</span>
          </div>
          <span class="pill" :class="planStatusTone(plan.status)">{{ planStatusLabel(plan.status) }}</span>
        </li>
      </ul>
    </section>

    <section class="home-dashboard-card" aria-labelledby="recent-scan-overview-title">
      <div class="sec-head">
        <span class="sec-no">03</span>
        <h3 id="recent-scan-overview-title">最近识别的药品</h3>
        <span class="sec-line" />
        <button type="button" class="btn btn-ghost btn-small" @click="setView('review')">
          人工复核
          <AppIcon name="arrow-right" :size="14" />
        </button>
      </div>
      <p class="home-dashboard-caption">只展示最近识别任务的候选结果，确认后才会成为健康事实。</p>
      <p v-if="recentMedicationCandidates.length === 0" class="home-dashboard-empty">
        还没有识别任务，可以先到视觉扫描拍摄药盒。
      </p>
      <ul v-else class="home-dashboard-list">
        <li v-for="candidate in recentMedicationCandidates" :key="candidate.id" class="home-dashboard-plan-row">
          <div>
            <strong>{{ candidate.drugName }}</strong>
            <span>{{ candidate.status }} · {{ candidate.fusionStatus }} · {{ relativeTime(candidate.createdAt) }}</span>
          </div>
          <span class="pill clay">识别候选</span>
        </li>
      </ul>
    </section>
  </section>

  <section class="home-dashboard-card home-dashboard-members" aria-labelledby="member-overview-title">
    <div class="sec-head">
      <span class="sec-no">04</span>
      <h3 id="member-overview-title">家庭成员状态</h3>
      <span class="sec-line" />
      <button type="button" class="btn btn-ghost btn-small" @click="setView('members')">
        查看档案
        <AppIcon name="arrow-right" :size="14" />
      </button>
    </div>
    <div v-if="memberOverviewRows.length > 0" class="home-dashboard-member-grid">
      <button
        v-for="member in memberOverviewRows"
        :key="member.id"
        type="button"
        class="home-dashboard-member"
        :class="{ selected: member.id === session.selectedMemberId }"
        @click="selectMember(member.id)"
      >
        <span class="home-dashboard-member-head">
          <strong>{{ member.name }}</strong>
          <span class="pill" :class="member.tone">{{ member.status }}</span>
        </span>
        <span class="home-dashboard-member-role">{{ member.role }}</span>
        <span class="home-dashboard-member-meta">
          {{ member.eventCount }} 条已同步事件 · {{ member.updatedAt ? relativeTime(member.updatedAt) : '等待状态投影' }}
        </span>
      </button>
    </div>
    <p v-else class="home-dashboard-empty">当前身份下没有可展示的家庭成员。</p>
  </section>

  <div class="grid-main-side" style="gap: 34px">
    <section aria-label="近期变化">
      <div class="sec-head">
        <span class="sec-no">01</span>
        <h3>近期变化</h3>
        <span class="sec-line" />
        <button type="button" class="btn btn-ghost btn-small" @click="setView('members')">
          完整档案
          <AppIcon name="arrow-right" :size="14" />
        </button>
      </div>

      <SkeletonList v-if="loading" :rows="4" />
      <div v-else-if="recentEvents.length === 0" class="empty-state">
        <img class="empty-illustration" :src="emptyCorner" alt="" aria-hidden="true" />
        <strong>还没有已确认的健康事件</strong>
        <p>可以先到「视觉扫描」拍摄一个药盒，或在「成员档案」手工录入一条健康事实。</p>
      </div>
      <ul v-else class="timeline">
        <li v-for="event in recentEvents" :key="event.id" class="timeline-row">
          <span class="timeline-dot" :class="eventTone(event.event_type)" />
          <div class="timeline-body">
            <div class="timeline-title-row">
              <span class="timeline-event">{{ eventTypeLabel(event.event_type) }}</span>
              <span class="pill" :class="event.confirmation_status === 'CONFIRMED' ? 'pine' : 'gold'">
                {{ confirmationLabel(event.confirmation_status) }}
              </span>
            </div>
            <span v-if="summarizeEventPayload(event)" class="timeline-payload">{{ summarizeEventPayload(event) }}</span>
            <span class="timeline-meta">{{ relativeTime(event.created_at) }} · 记录人 {{ event.created_by }}</span>
          </div>
        </li>
      </ul>
    </section>

    <aside class="side-rail">
      <div class="rail-block">
        <span class="rail-title"><AppIcon name="lock" :size="15" />本地运行状态</span>
        <span class="rail-line">
          <strong>{{ session.capabilities ? 'API 已连接' : 'API 状态未知' }}</strong>
          · 阶段 {{ session.capabilities?.phase ?? '未知' }}<br />
          网络出口默认拒绝，天气仅发送城市代码。
        </span>
        <div class="capability-chips">
          <span v-for="cap in session.capabilities?.available ?? []" :key="cap" class="pill sage">{{ cap }}</span>
          <span
            v-for="cap in session.capabilities?.unavailable ?? []"
            :key="cap"
            class="pill plain"
            :title="'能力未启用：' + cap"
          >
            {{ cap }} · 未启用
          </span>
        </div>
      </div>

      <div class="rail-block">
        <span class="rail-title"><AppIcon name="key" :size="15" />谁能看到这些数据</span>
        <span class="rail-line">
          {{ session.isOwnerView
            ? '你是家庭管理员，可以为子女或照护者配置字段级授权，并随时撤回。'
            : '你是授权照护者，仅能看到授权范围内的成员与字段，范围与到期时间以授权记录为准。' }}
        </span>
        <button
          v-if="session.isOwnerView"
          type="button"
          class="btn btn-ghost btn-small"
          style="justify-self: start"
          @click="setView('authorizations')"
        >
          管理授权
          <AppIcon name="arrow-right" :size="14" />
        </button>
      </div>
    </aside>
  </div>
</template>

<style scoped>
.home-dashboard-grid {
  display: grid;
  gap: 20px;
  margin-top: 22px;
}

.home-dashboard-primary {
  align-items: stretch;
  grid-template-columns: minmax(0, 1.25fr) minmax(360px, 0.75fr);
}

.home-dashboard-secondary {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.home-dashboard-weather {
  min-width: 0;
}

.home-dashboard-card {
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
  padding: 22px;
  border: 1px solid rgba(190, 167, 125, 0.28);
  border-radius: 22px;
  background: rgba(255, 252, 243, 0.76);
  box-shadow: 0 14px 34px rgba(94, 71, 42, 0.06);
}

.home-dashboard-card .sec-head {
  margin-top: 0;
}

.home-dashboard-count {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin: 12px 0 16px;
  color: var(--ink-muted, #877966);
}

.home-dashboard-count strong {
  color: var(--ink, #3f3a31);
  font-family: Georgia, 'Times New Roman', serif;
  font-size: 38px;
  line-height: 1;
}

.home-dashboard-count span {
  color: var(--ink-soft, #6d6659);
}

.home-dashboard-caption,
.home-dashboard-empty {
  margin: 8px 0 16px;
  color: var(--ink-soft, #6d6659);
  font-size: 13px;
  line-height: 1.65;
}

/* 列表在卡片内部滚动，避免行内容溢出卡片下边缘（图一修复）。 */
.home-dashboard-list {
  display: grid;
  align-content: start;
  flex: 1 1 auto;
  gap: 9px;
  margin: 0;
  padding: 0 2px 2px 0;
  list-style: none;
  min-height: 0;
  max-height: 340px;
  overflow-y: auto;
}

.home-dashboard-list-row .pill,
.home-dashboard-list-row > svg {
  flex-shrink: 0;
}

.home-dashboard-list-row,
.home-dashboard-plan-row {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  min-width: 0;
  padding: 11px 12px;
  border: 1px solid rgba(190, 167, 125, 0.2);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.42);
  color: inherit;
  text-align: left;
}

.home-dashboard-list-row {
  cursor: pointer;
  transition: border-color 160ms ease, background 160ms ease, transform 160ms ease;
}

.home-dashboard-list-row:hover,
.home-dashboard-list-row:focus-visible {
  border-color: rgba(52, 104, 88, 0.42);
  background: rgba(238, 247, 239, 0.84);
  outline: none;
  transform: translateY(-1px);
}

.home-dashboard-list-detail {
  min-width: 0;
  flex: 1;
  overflow: hidden;
  color: var(--ink-soft, #6d6659);
  font-size: 13px;
  line-height: 1.45;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.home-dashboard-plan-row {
  justify-content: space-between;
}

.home-dashboard-plan-row > div {
  display: grid;
  min-width: 0;
  gap: 4px;
}

.home-dashboard-plan-row strong {
  overflow: hidden;
  color: var(--ink, #3f3a31);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.home-dashboard-plan-row span:not(.pill) {
  overflow: hidden;
  color: var(--ink-soft, #6d6659);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.home-dashboard-members {
  margin-top: 22px;
}

.home-dashboard-member-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: 12px;
  margin-top: 14px;
}

.home-dashboard-member {
  display: grid;
  gap: 8px;
  padding: 15px;
  border: 1px solid rgba(190, 167, 125, 0.24);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.4);
  color: inherit;
  text-align: left;
  cursor: pointer;
}

.home-dashboard-member:hover,
.home-dashboard-member:focus-visible,
.home-dashboard-member.selected {
  border-color: rgba(52, 104, 88, 0.48);
  background: rgba(238, 247, 239, 0.74);
  outline: none;
}

.home-dashboard-member-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.home-dashboard-member-role,
.home-dashboard-member-meta {
  color: var(--ink-soft, #6d6659);
  font-size: 12px;
}

/* These compact status pills are also used in the keyboard/axe acceptance path. */
.home-dashboard-card .pill.pine { background: var(--pine-tint); color: #244d40; }
.home-dashboard-card .pill.clay { background: var(--clay-tint); color: #7f3925; }
.home-dashboard-card .pill.gold { background: var(--gold-tint); color: #6f4e08; }
.home-dashboard-card .pill.rose { background: var(--rose-tint); color: #7e2330; }
.home-dashboard-card .pill.plain { background: var(--paper-deep); color: #4f493f; }

@media (max-width: 1050px) {
  .home-dashboard-primary {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .home-dashboard-secondary {
    grid-template-columns: 1fr;
  }

  .home-dashboard-card {
    padding: 17px;
    border-radius: 17px;
  }

  .home-dashboard-primary,
  .home-dashboard-secondary {
    gap: 14px;
    margin-top: 14px;
  }

  .home-dashboard-list-detail {
    white-space: normal;
  }
}
</style>
