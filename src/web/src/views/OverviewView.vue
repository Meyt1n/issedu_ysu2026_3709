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
  return orderedPlans.value.filter(plan => isSameLocalDay(plan.next_action_at)).slice(0, 4)
})

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
      // 状态签：区分「有记录 / 无记录 / 投影不可见」三态。
      // 事件数为 0 与「当前身份看不到状态」含义不同，必须让用户分得清。
      status: state ? (eventCount > 0 ? '有已同步记录' : '暂无已同步记录') : '状态暂未记录',
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

    <section class="home-dashboard-card overview-section overview-section--pending" aria-labelledby="pending-overview-title">
      <div class="sec-head">
        <span class="sec-no">01</span>
        <span class="overview-sec-icon" aria-hidden="true"><AppIcon name="review" :size="15" /></span>
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
      <div v-else class="pending-empty-state">
        <span class="pending-empty-visual" aria-hidden="true">
          <span class="pending-empty-orbit" />
          <AppIcon name="check" :size="24" />
        </span>
        <span class="pending-empty-copy">
          <strong>今天的照护节奏很平稳</strong>
          <span>没有待复核、待知晓或升级事项，继续保持。</span>
        </span>
        <span class="pill sage">已巡检</span>
      </div>
    </section>
  </section>

  <section class="home-dashboard-grid home-dashboard-secondary" aria-label="家庭健康动态">
    <section class="home-dashboard-card overview-section overview-section--medication" aria-labelledby="medication-overview-title">
      <div class="sec-head">
        <span class="sec-no">02</span>
        <span class="overview-sec-icon" aria-hidden="true"><AppIcon name="plan" :size="15" /></span>
        <h3 id="medication-overview-title">今日用药</h3>
        <span class="sec-line" />
        <button type="button" class="btn btn-ghost btn-small" @click="setView('plans')">
          用药计划
          <AppIcon name="arrow-right" :size="14" />
        </button>
      </div>
      <SkeletonList v-if="loading" :rows="3" />
      <div v-else-if="todayPlans.length === 0" class="medication-empty-state">
        <span class="medication-empty-ambient" aria-hidden="true">
          <i /><i /><i /><i />
        </span>
        <span class="medication-empty-visual" aria-hidden="true">
          <span class="medication-empty-orbit" />
          <span class="medication-bottle">
            <span class="medication-bottle-cap" />
            <span class="medication-bottle-label"><AppIcon name="pill" :size="19" /></span>
          </span>
          <span class="medication-calendar">
            <AppIcon name="plan" :size="44" />
          </span>
          <AppIcon class="medication-leaf medication-leaf--left" name="leaf" :size="34" />
          <AppIcon class="medication-leaf medication-leaf--right" name="leaf" :size="34" />
        </span>
        <span class="medication-empty-copy">
          <strong>今天先轻轻休息一下</strong>
          <span>新的确认计划会在这里亮起。</span>
        </span>
        <span class="pill sage">保持从容</span>
      </div>
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

    <section class="home-dashboard-card overview-section overview-section--scan" aria-labelledby="recent-scan-overview-title">
      <div class="sec-head">
        <span class="sec-no">03</span>
        <span class="overview-sec-icon" aria-hidden="true"><AppIcon name="scan" :size="15" /></span>
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

  <section class="home-dashboard-card home-dashboard-members overview-section overview-section--members" aria-labelledby="member-overview-title">
    <div class="sec-head">
      <span class="sec-no">04</span>
      <span class="overview-sec-icon" aria-hidden="true"><AppIcon name="members" :size="15" /></span>
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

  <div class="grid-main-side overview-lower-grid" style="gap: 34px">
    <section class="home-dashboard-card overview-section overview-section--changes" aria-label="近期变化">
      <div class="sec-head">
        <!-- 编号沿视觉阅读顺序递增：01 待确认 → 02 用药 → 03 识别 → 04 成员 → 05 近期变化。 -->
        <span class="sec-no">05</span>
        <span class="overview-sec-icon" aria-hidden="true"><AppIcon name="timeline" :size="15" /></span>
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

  </div>

  <HealthNewsPanel />
</template>

<style scoped>
.home-dashboard-grid {
  display: grid;
  gap: 20px;
  margin-top: 22px;
}

.home-dashboard-primary {
  align-items: stretch;
  grid-template-columns: 1fr;
}

.home-dashboard-secondary {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.overview-lower-grid {
  grid-template-columns: 1fr;
}

.overview-lower-grid .side-rail {
  border-left: 0;
  border-top: 1px solid var(--line);
  padding-left: 0;
  padding-top: 18px;
  position: static;
}

.home-dashboard-weather {
  align-self: start;
  display: grid;
  min-width: 0;
}

/* 天气卡按内容收紧，避免为了配齐右列高度制造大块空白。 */
.home-dashboard-weather > .weather-action-panel {
  align-content: start;
  grid-template-rows: none;
  height: auto;
}

.home-dashboard-weather .weather-action-body {
  align-content: start;
}

/* 天气与 01 待确认各自占满一行；宽屏下待确认内容横向铺开，减少空白。 */
.overview-section--pending .home-dashboard-list {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.overview-section--pending .home-dashboard-list-row {
  min-height: 54px;
}

.pending-empty-state {
  align-items: center;
  background: color-mix(in srgb, var(--clay-tint) 28%, transparent);
  border: 1px solid color-mix(in srgb, var(--clay) 18%, var(--line-soft));
  border-radius: 16px;
  display: flex;
  gap: 14px;
  min-height: 96px;
  padding: 14px 18px;
}

.pending-empty-visual {
  align-items: center;
  background: color-mix(in srgb, var(--card) 84%, transparent);
  border: 1px solid color-mix(in srgb, var(--clay) 24%, transparent);
  border-radius: 50%;
  color: var(--clay-deep);
  display: inline-flex;
  flex: 0 0 auto;
  height: 52px;
  justify-content: center;
  position: relative;
  width: 52px;
}

.pending-empty-orbit {
  border: 1px dashed color-mix(in srgb, var(--clay) 42%, transparent);
  border-radius: 50%;
  inset: -5px;
  position: absolute;
  animation: pending-orbit 5s linear infinite reverse;
}

@keyframes pending-orbit {
  to { transform: rotate(360deg); }
}

.pending-empty-copy {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.pending-empty-copy strong { color: var(--clay-deep); font-size: 15px; }
.pending-empty-copy span { color: var(--ink-soft); font-size: 12.5px; }

.home-dashboard-card {
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
  padding: 22px;
  border: 1px solid rgba(190, 167, 125, 0.28);
  border-radius: 22px;
  /* 纸色晕染全覆盖（HCT-533）：底色即带 accent 淡彩，四角呼吸渐变直达边缘，边缘不再发白。 */
  background:
    var(--card-texture, none),
    linear-gradient(
      150deg,
      color-mix(in srgb, var(--overview-accent, var(--pine)) 8%, var(--card)),
      var(--card) 46%,
      color-mix(in srgb, var(--overview-accent, var(--pine)) 5%, var(--card))
    );
  box-shadow: 0 14px 34px rgba(94, 71, 42, 0.06);
}

.overview-section {
  isolation: isolate;
  overflow: hidden;
  position: relative;
}

.overview-section::after {
  border: 1px solid var(--overview-accent);
  border-radius: 50%;
  content: "";
  height: 82px;
  opacity: 0.08;
  pointer-events: none;
  position: absolute;
  right: -32px;
  top: -34px;
  width: 82px;
  z-index: 1;
}

.overview-section--pending { --overview-accent: var(--clay-deep); --card-pattern: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='132' height='132' viewBox='0 0 132 132'%3E%3Cg fill='none' stroke='%23b06a45' stroke-opacity='.17' stroke-width='1.2' stroke-linejoin='round'%3E%3Cpath d='M30 26l8 8-8 8-8-8z'/%3E%3Cpath d='M98 92l8 8-8 8-8-8z'/%3E%3C/g%3E%3Cg stroke='%23b06a45' stroke-opacity='.12' stroke-width='1.4' stroke-linecap='round'%3E%3Cpath d='M92 24v12M86 30h12'/%3E%3C/g%3E%3C/svg%3E"); }
.overview-section--medication { --overview-accent: var(--pine-deep); --card-pattern: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='132' height='132' viewBox='0 0 132 132'%3E%3Cg stroke='%234d7c6b' stroke-opacity='.18' stroke-width='2.6' stroke-linecap='round'%3E%3Cpath d='M36 28v14M29 35h14'/%3E%3Cpath d='M96 96v14M89 103h14'/%3E%3C/g%3E%3Cg fill='%234d7c6b' fill-opacity='.12'%3E%3Crect x='88' y='22' width='16' height='8' rx='4' transform='rotate(-24 96 26)'/%3E%3C/g%3E%3C/svg%3E"); }
.overview-section--scan { --overview-accent: var(--sky); --card-pattern: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='132' height='132' viewBox='0 0 132 132'%3E%3Cg fill='none' stroke='%2355809c' stroke-opacity='.16' stroke-width='1.2'%3E%3Ccircle cx='34' cy='32' r='6'/%3E%3Ccircle cx='34' cy='32' r='11' stroke-dasharray='3 4'/%3E%3Ccircle cx='98' cy='98' r='5'/%3E%3Ccircle cx='98' cy='98' r='9' stroke-dasharray='2 4'/%3E%3C/g%3E%3Ccircle cx='34' cy='32' r='1.7' fill='%2355809c' fill-opacity='.3'/%3E%3C/svg%3E"); }
.overview-section--members { --overview-accent: var(--gold); --card-pattern: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='132' height='132' viewBox='0 0 132 132'%3E%3Cg fill='%23b08a2e' fill-opacity='.16'%3E%3Cpath d='M34 36c-3.2-2.8-6.4-5.5-6.4-8.7 0-2.1 1.7-3.8 3.7-3.8 1 0 2 .5 2.7 1.4a3.4 3.4 0 0 1 2.7-1.4c2 0 3.7 1.7 3.7 3.8 0 3.2-3.2 5.9-6.4 8.7z'/%3E%3Cpath d='M98 104c-2.6-2.3-5.2-4.5-5.2-7.1 0-1.7 1.4-3.1 3-3.1.9 0 1.7.4 2.2 1.1a2.8 2.8 0 0 1 2.2-1.1c1.6 0 3 1.4 3 3.1 0 2.6-2.6 4.8-5.2 7.1z'/%3E%3C/g%3E%3C/svg%3E"); }
.overview-section--changes { --overview-accent: var(--rose); --card-pattern: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='132' height='132' viewBox='0 0 132 132'%3E%3Cg fill='none' stroke='%23b2596b' stroke-opacity='.16' stroke-width='1.5' stroke-linecap='round'%3E%3Cpath d='M24 36c4-5 8-5 12 0s8 5 12 0'/%3E%3Cpath d='M84 100c4-5 8-5 12 0s8 5 12 0'/%3E%3Cpath d='M96 30c3-4 6-4 9 0'/%3E%3C/g%3E%3C/svg%3E"); }
.overview-section--calendar { --overview-accent: var(--sage, #6e8a74); --card-pattern: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='132' height='132' viewBox='0 0 132 132'%3E%3Cg fill='%236e8a74' fill-opacity='.18'%3E%3Ccircle cx='32' cy='32' r='1.8'/%3E%3Ccircle cx='42' cy='32' r='1.8'/%3E%3Ccircle cx='32' cy='42' r='1.8'/%3E%3Ccircle cx='42' cy='42' r='1.8'/%3E%3Ccircle cx='96' cy='96' r='1.8'/%3E%3Ccircle cx='106' cy='96' r='1.8'/%3E%3Ccircle cx='96' cy='106' r='1.8'/%3E%3Ccircle cx='106' cy='106' r='1.8'/%3E%3C/g%3E%3C/svg%3E"); }

.calendar-head-note {
  align-items: center;
  color: var(--ink-faint);
  display: inline-flex;
  font-size: 11.5px;
  gap: 6px;
  white-space: nowrap;
}

.calendar-head-note i {
  background: var(--sage, #6e8a74);
  border-radius: 50%;
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--sage, #6e8a74) 13%, transparent);
  display: inline-block;
  height: 7px;
  width: 7px;
}

/* 日历卡与相邻卡片保持呼吸距离。 */
/*
 * 与成员卡同理（图三修复）：本卡是 .view-container（定高 grid）的直接子项，
 * overflow:hidden 会清零 grid 自动最小尺寸，整卡被压成只剩标题的一条。
 * 月历内容较高，必须恢复 min-content 参与行高计算，让页面自然下滚。
 */
.overview-section--calendar {
  margin-top: 22px;
  overflow: visible;
}

.overview-section > * { position: relative; z-index: 2; }

/* 新闻卡收在首页最底部，与月历卡保持同一段呼吸距离。 */
.health-news-panel {
  margin-top: 22px;
}

.overview-section .sec-head { color: var(--ink); }

.overview-sec-icon {
  align-items: center;
  background: color-mix(in srgb, var(--overview-accent) 14%, transparent);
  border: 1px solid color-mix(in srgb, var(--overview-accent) 24%, transparent);
  border-radius: 9px;
  color: var(--overview-accent);
  display: inline-flex;
  flex: 0 0 auto;
  height: 27px;
  justify-content: center;
  margin-left: -5px;
  transform: translateY(-1px);
  width: 27px;
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

/* 列表在卡片内部滚动，避免行内容溢出卡片下边缘（图一修复）。
   grid 隐式列会取 max-content：行内 nowrap 的长药名会把轨道撑到千余像素，
   卡片里因此多出一条横向滚动条。minmax(0, 1fr) 把轨道锁在容器宽度内。
   高度不再写死 340px：同行卡片等高对齐时，写死高度会在卡片底部留出
   近百像素空洞。改为 flex 撑满剩余空间，超出部分仍在列表内滚动。 */
.home-dashboard-list {
  display: grid;
  align-content: start;
  flex: 1 1 auto;
  gap: 9px;
  grid-template-columns: minmax(0, 1fr);
  margin: 0;
  padding: 0 2px 2px 0;
  list-style: none;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
}

.home-dashboard-list > li {
  min-width: 0;
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

/* 长药名与风险原文允许折到两行再省略：单行 nowrap 会把 200–800px 的正文
   直接裁掉，用户在首页看不到自己要判断的关键信息。 */
.home-dashboard-list-detail {
  min-width: 0;
  flex: 1;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  overflow: hidden;
  color: var(--ink-soft, #6d6659);
  font-size: 13px;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.home-dashboard-plan-row {
  justify-content: space-between;
}

.home-dashboard-plan-row > div {
  display: grid;
  min-width: 0;
  gap: 4px;
}

/* 药名与安排同样允许折两行：窄栏（1024px 两列）下单行会裁掉过半药名。 */
.home-dashboard-plan-row strong,
.home-dashboard-plan-row span:not(.pill) {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  overflow: hidden;
  overflow-wrap: anywhere;
}

.medication-empty-state {
  align-items: center;
  background: color-mix(in srgb, var(--pine-tint) 58%, transparent);
  border: 1px solid color-mix(in srgb, var(--pine) 20%, var(--line-soft));
  border-radius: 16px;
  display: flex;
  flex-direction: column;
  gap: 13px;
  justify-content: center;
  margin-top: 16px;
  min-height: 270px;
  overflow: hidden;
  padding: 14px 16px;
  position: relative;
}

.medication-empty-state > * {
  position: relative;
  z-index: 1;
}

.medication-empty-state::before,
.medication-empty-state::after {
  border: 1px solid color-mix(in srgb, var(--pine) 14%, transparent);
  border-radius: 50%;
  content: "";
  height: 210px;
  left: 50%;
  pointer-events: none;
  position: absolute;
  top: 50%;
  transform: translate(-50%, -50%);
  width: 210px;
}

.medication-empty-state::after {
  border-style: dashed;
  height: 270px;
  opacity: 0.7;
  transform: translate(-50%, -50%) rotate(25deg);
  width: 270px;
}

.medication-empty-ambient {
  inset: 0;
  pointer-events: none;
  position: absolute !important;
}

.medication-empty-ambient i {
  background: var(--pine);
  border-radius: 50%;
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--pine) 10%, transparent);
  height: 5px;
  opacity: 0.45;
  position: absolute;
  width: 5px;
}

.medication-empty-ambient i:nth-child(1) { left: 18%; top: 26%; }
.medication-empty-ambient i:nth-child(2) { right: 23%; top: 21%; }
.medication-empty-ambient i:nth-child(3) { bottom: 22%; left: 27%; }
.medication-empty-ambient i:nth-child(4) { bottom: 26%; right: 15%; }

.medication-empty-visual {
  align-items: center;
  color: var(--pine-deep);
  display: inline-flex;
  height: 142px;
  justify-content: center;
  position: relative;
  width: 250px;
}

.medication-empty-orbit {
  background: radial-gradient(circle, color-mix(in srgb, var(--gold) 18%, transparent), transparent 68%);
  border-radius: 50%;
  height: 142px;
  position: absolute;
  left: 50%;
  top: 0;
  transform: translateX(-50%);
  width: 190px;
}

.medication-bottle,
.medication-calendar {
  align-items: center;
  background: color-mix(in srgb, var(--card) 86%, transparent);
  border: 2px solid color-mix(in srgb, var(--pine) 58%, var(--line));
  box-shadow: 0 8px 18px rgba(66, 93, 76, .1);
  display: inline-flex;
  justify-content: center;
  position: absolute;
}

.medication-bottle {
  border-radius: 16px 16px 14px 14px;
  height: 88px;
  left: 50px;
  top: 35px;
  transform: rotate(-1deg);
  width: 58px;
}

.medication-bottle-cap {
  background: color-mix(in srgb, var(--pine) 22%, var(--card));
  border: 2px solid color-mix(in srgb, var(--pine) 58%, var(--line));
  border-bottom: 0;
  border-radius: 8px 8px 4px 4px;
  height: 16px;
  left: 8px;
  position: absolute;
  top: -17px;
  width: 38px;
}

.medication-bottle-label {
  align-items: center;
  background: color-mix(in srgb, var(--card) 94%, transparent);
  border-radius: 9px;
  color: var(--clay);
  display: inline-flex;
  height: 39px;
  justify-content: center;
  width: 44px;
}

.medication-calendar {
  background: color-mix(in srgb, var(--card) 90%, var(--sky-tint));
  border-radius: 15px;
  color: var(--pine);
  height: 82px;
  left: 105px;
  top: 48px;
  transform: rotate(3deg);
  width: 82px;
}

.medication-leaf {
  color: color-mix(in srgb, var(--pine) 68%, var(--sage));
  position: absolute;
  top: 75px;
}

.medication-leaf--left {
  left: 23px;
  transform: rotate(-22deg);
}

.medication-leaf--right {
  right: 23px;
  transform: scaleX(-1) rotate(-22deg);
}

.medication-empty-copy {
  display: grid;
  gap: 4px;
  min-width: 0;
  text-align: center;
}

.medication-empty-copy strong { color: var(--pine-deep); font-size: 15px; }
.medication-empty-copy span { color: var(--ink-soft); font-size: 12.5px; }

@media (prefers-reduced-motion: reduce) {
  .pending-empty-orbit { animation: none; }
}

.home-dashboard-plan-row strong {
  color: var(--ink, #3f3a31);
}

.home-dashboard-plan-row span:not(.pill) {
  color: var(--ink-soft, #6d6659);
  font-size: 12px;
}

.home-dashboard-members {
  margin-top: 22px;
  /*
   * 图三修复：本卡是 .view-container（定高 grid）的直接子项。overflow:hidden
   * 会把 grid 自动最小尺寸清零，视口不够高时整张卡被压成一条只剩标题的白条。
   * 恢复 min-content 参与行高计算，成员格子才能完整渲染。
   */
  overflow: visible;
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
  flex-wrap: wrap;
  gap: 8px;
}

/* 姓名可截断、状态签不收缩：窄格子里先压姓名，别把签压变形。 */
.home-dashboard-member-head strong {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.home-dashboard-member-head .pill { flex: 0 0 auto; }

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

  .overview-section--pending .home-dashboard-list {
    grid-template-columns: 1fr;
  }

  .pending-empty-state {
    align-items: flex-start;
    flex-wrap: wrap;
  }

  /* 单列后横向空间充裕，正文放开到三行。 */
  .home-dashboard-list-detail {
    -webkit-line-clamp: 3;
    line-clamp: 3;
  }
}
</style>
