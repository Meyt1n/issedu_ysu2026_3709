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
import AppIcon from '../components/AppIcon.vue'
import CountUp from '../components/CountUp.vue'
import HealthNewsPanel from '../components/HealthNewsPanel.vue'
import SkeletonList from '../components/SkeletonList.vue'
import WeatherActionPanel from '../components/WeatherActionPanel.vue'
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
const householdName = computed(
  () => session.households.find(h => h.id === session.selectedHouseholdId)?.name ?? '家庭',
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
  return (today.length > 0 ? today : orderedPlans.value).slice(0, 5)
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
  <header class="ov-head">
    <div class="ov-head-row">
      <div class="page-hero">
        <h2 class="hero-greeting">{{ greeting }}，{{ selectedMember?.display_name ?? session.actorId }}</h2>
        <p class="hero-sub">
          {{ householdName }} 的健康工作台 · 当前关注 {{ selectedMember?.display_name ?? '家人' }} 的近况。
        </p>
      </div>
      <div class="ov-head-tools">
        <div class="ov-toolbar" role="group" aria-label="常用操作">
          <button type="button" class="btn btn-ghost btn-small" @click="setView('scan')">
            <AppIcon name="scan" :size="15" />
            扫描药盒
          </button>
          <button type="button" class="btn btn-ghost btn-small" @click="setView('members')">
            <AppIcon name="plus" :size="15" />
            记一条事实
          </button>
          <button type="button" class="btn btn-ghost btn-small" @click="setView('risks')">
            <AppIcon name="shield" :size="15" />
            用药安全
          </button>
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
    </div>

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
  </header>

  <p v-if="loadError" class="notice error" role="alert">
    <AppIcon name="alert" :size="16" />
    {{ loadError }}
  </p>

  <div class="ov-columns">
    <section class="ov-panel" aria-labelledby="pending-overview-title">
      <div class="ov-panel-head">
        <h3 id="pending-overview-title">待确认事项</h3>
        <span class="ov-panel-count">{{ pendingOverviewCount }}</span>
        <button type="button" class="ov-panel-link" @click="setView('review')">
          查看
          <AppIcon name="arrow-right" :size="13" />
        </button>
      </div>
      <ul v-if="pendingOverviewItems.length > 0" class="ov-list">
        <li v-for="item in pendingOverviewItems" :key="item.id">
          <button type="button" class="ov-row ov-row-action" @click="setView(item.view)">
            <span class="pill" :class="item.tone">{{ item.label }}</span>
            <span class="ov-row-detail">{{ item.detail }}</span>
            <AppIcon name="arrow-right" :size="13" />
          </button>
        </li>
      </ul>
      <p v-else class="ov-empty">当前没有待复核、待知晓或升级提醒事项。</p>
    </section>

    <section class="ov-panel" aria-labelledby="medication-overview-title">
      <div class="ov-panel-head">
        <h3 id="medication-overview-title">今日用药</h3>
        <button type="button" class="ov-panel-link" @click="setView('plans')">
          用药计划
          <AppIcon name="arrow-right" :size="13" />
        </button>
      </div>
      <p class="ov-caption">
        {{ selectedMember?.display_name ?? '当前成员' }} ·
        {{ hasTodayPlans ? '今日已确认计划' : '今日暂无计划，展示近期已确认计划' }}
      </p>
      <SkeletonList v-if="loading" :rows="3" />
      <p v-else-if="todayPlans.length === 0" class="ov-empty">
        暂无可展示的已确认用药计划，识别候选不会自动进入这里。
      </p>
      <ul v-else class="ov-list">
        <li v-for="plan in todayPlans" :key="plan.plan_event_id" class="ov-row">
          <div class="ov-row-main">
            <strong>{{ plan.drug }}</strong>
            <span>{{ plan.schedule }} · 下次 {{ formatDateTime(plan.next_action_at) }}</span>
          </div>
          <span class="pill" :class="planStatusTone(plan.status)">{{ planStatusLabel(plan.status) }}</span>
        </li>
      </ul>
    </section>

    <section class="ov-panel" aria-labelledby="recent-overview-title">
      <div class="ov-panel-head">
        <h3 id="recent-overview-title">近期变化</h3>
        <button type="button" class="ov-panel-link" @click="setView('members')">
          完整档案
          <AppIcon name="arrow-right" :size="13" />
        </button>
      </div>
      <SkeletonList v-if="loading" :rows="4" />
      <p v-else-if="recentEvents.length === 0" class="ov-empty">
        还没有已确认的健康事件，可以先到「视觉扫描」拍摄药盒或在「成员档案」手工录入。
      </p>
      <ul v-else class="timeline ov-timeline">
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

  <div class="ov-band" aria-label="环境与资讯">
    <WeatherActionPanel
      :weather="weather"
      :loading="weatherLoading"
      @refresh="loadWeather"
    />
    <HealthNewsPanel />
  </div>

  <div class="ov-columns ov-columns-two">
    <section class="ov-panel" aria-labelledby="member-overview-title">
      <div class="ov-panel-head">
        <h3 id="member-overview-title">家庭成员状态</h3>
        <button type="button" class="ov-panel-link" @click="setView('members')">
          查看档案
          <AppIcon name="arrow-right" :size="13" />
        </button>
      </div>
      <ul v-if="memberOverviewRows.length > 0" class="ov-list">
        <li v-for="member in memberOverviewRows" :key="member.id">
          <button
            type="button"
            class="ov-row ov-row-action ov-member"
            :class="{ selected: member.id === session.selectedMemberId }"
            @click="selectMember(member.id)"
          >
            <span class="ov-row-main">
              <strong>{{ member.name }}</strong>
              <span>{{ member.role }} · {{ member.eventCount }} 条已同步事件 · {{ member.updatedAt ? relativeTime(member.updatedAt) : '等待状态投影' }}</span>
            </span>
            <span class="pill" :class="member.tone">{{ member.status }}</span>
          </button>
        </li>
      </ul>
      <p v-else class="ov-empty">当前身份下没有可展示的家庭成员。</p>
    </section>

    <section class="ov-panel" aria-labelledby="recent-scan-overview-title">
      <div class="ov-panel-head">
        <h3 id="recent-scan-overview-title">最近识别的药品</h3>
        <button type="button" class="ov-panel-link" @click="setView('review')">
          人工复核
          <AppIcon name="arrow-right" :size="13" />
        </button>
      </div>
      <p class="ov-caption">只展示最近识别任务的候选结果，确认后才会成为健康事实。</p>
      <p v-if="recentMedicationCandidates.length === 0" class="ov-empty">
        还没有识别任务，可以先到视觉扫描拍摄药盒。
      </p>
      <ul v-else class="ov-list">
        <li v-for="candidate in recentMedicationCandidates" :key="candidate.id" class="ov-row">
          <div class="ov-row-main">
            <strong>{{ candidate.drugName }}</strong>
            <span>{{ candidate.status }} · {{ candidate.fusionStatus }} · {{ relativeTime(candidate.createdAt) }}</span>
          </div>
          <span class="pill clay">识别候选</span>
        </li>
      </ul>
    </section>
  </div>

  <section class="ov-status" aria-label="本地运行与授权状态">
    <span class="ov-status-item">
      <AppIcon name="lock" :size="14" />
      <strong>{{ session.capabilities ? 'API 已连接' : 'API 状态未知' }}</strong>
      · 阶段 {{ session.capabilities?.phase ?? '未知' }} · 网络出口默认拒绝，天气仅发送城市代码
    </span>
    <span class="ov-status-chips">
      <span v-for="cap in session.capabilities?.available ?? []" :key="cap" class="pill sage">{{ cap }}</span>
      <span
        v-for="cap in session.capabilities?.unavailable ?? []"
        :key="cap"
        class="pill plain"
        :title="'能力未启用：' + cap"
      >
        {{ cap }} · 未启用
      </span>
    </span>
    <span class="ov-status-item">
      <AppIcon name="key" :size="14" />
      {{ session.isOwnerView
        ? '你是家庭管理员，可以配置字段级授权并随时撤回。'
        : '你是授权照护者，仅能看到授权范围内的成员与字段。' }}
    </span>
    <button
      v-if="session.isOwnerView"
      type="button"
      class="ov-panel-link"
      @click="setView('authorizations')"
    >
      管理授权
      <AppIcon name="arrow-right" :size="13" />
    </button>
  </section>
</template>

<style scoped>
/* 总览工作台：等权分栏、细线分区，不叠卡片。 */
.ov-head {
  display: grid;
  gap: 16px;
}

.ov-head-row {
  align-items: flex-end;
  display: flex;
  flex-wrap: wrap;
  gap: 12px 18px;
  justify-content: space-between;
}

.ov-head-tools {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.ov-toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.ov-columns {
  align-items: stretch;
  display: grid;
  gap: 16px;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.ov-columns-two {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.ov-band {
  align-items: stretch;
  display: grid;
  gap: 16px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.ov-panel {
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  display: flex;
  flex-direction: column;
  min-width: 0;
  padding: 16px 18px;
}

.ov-panel-head {
  align-items: center;
  border-bottom: 1px solid var(--line-soft);
  display: flex;
  gap: 10px;
  margin-bottom: 12px;
  padding-bottom: 10px;
}

.ov-panel-head h3 {
  font-size: 15px;
  letter-spacing: 0.3px;
  margin: 0;
}

.ov-panel-count {
  color: var(--clay-deep);
  font-family: var(--font-numeric);
  font-size: 18px;
  font-variant-numeric: tabular-nums;
  font-weight: 700;
  line-height: 1;
}

.ov-panel-link {
  align-items: center;
  background: transparent;
  border: 0;
  border-radius: 7px;
  color: var(--pine-deep);
  cursor: pointer;
  display: inline-flex;
  font-size: 12.5px;
  font-weight: 650;
  gap: 4px;
  margin-left: auto;
  padding: 4px 7px;
}

.ov-panel-link:hover { background: var(--pine-tint); }

.ov-caption {
  color: var(--ink-soft);
  font-size: 12.5px;
  line-height: 1.55;
  margin: 0 0 10px;
}

.ov-list {
  display: grid;
  gap: 6px;
  list-style: none;
  margin: 0;
  padding: 0;
}

.ov-row {
  align-items: center;
  border-bottom: 1px solid var(--line-soft);
  display: flex;
  gap: 10px;
  min-width: 0;
  padding: 8px 2px;
  width: 100%;
}

.ov-list > li:last-child .ov-row,
.ov-list > li:last-child.ov-row { border-bottom: 0; }

.ov-row-action {
  background: transparent;
  border-left: 0;
  border-right: 0;
  border-top: 0;
  border-radius: 6px;
  color: inherit;
  cursor: pointer;
  text-align: left;
  transition: background 0.16s ease;
}

.ov-row-action:hover { background: var(--paper-deep); }

.ov-member.selected { background: var(--pine-tint); }

.ov-row-detail {
  color: var(--ink-soft);
  flex: 1;
  font-size: 13px;
  line-height: 1.45;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ov-row-main {
  display: grid;
  flex: 1;
  gap: 2px;
  min-width: 0;
}

.ov-row-main strong {
  font-size: 13.5px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ov-row-main span:not(.pill) {
  color: var(--ink-soft);
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ov-row > .app-icon { color: var(--ink-faint); flex: 0 0 auto; }
.ov-row .pill { flex: 0 0 auto; }

.ov-empty {
  color: var(--ink-soft);
  font-size: 13px;
  line-height: 1.6;
  margin: 4px 0 0;
}

.ov-timeline .timeline-body { padding-bottom: 12px; }

/* 本地/授权状态：细长状态条，不再是孤立右栏。 */
.ov-status {
  align-items: center;
  border-top: 1px solid var(--line);
  color: var(--ink-soft);
  display: flex;
  flex-wrap: wrap;
  font-size: 12.5px;
  gap: 8px 18px;
  line-height: 1.5;
  padding: 12px 2px 0;
}

.ov-status-item {
  align-items: center;
  display: inline-flex;
  gap: 6px;
}

.ov-status-item .app-icon { color: var(--clay); flex: 0 0 auto; }
.ov-status-item strong { color: var(--ink); }

.ov-status-chips {
  align-items: center;
  display: inline-flex;
  flex-wrap: wrap;
  gap: 6px;
}

/* 状态胶囊加深文字颜色以满足 WCAG AA 对比度（axe 验收路径）。 */
.ov-panel .pill.pine { background: var(--pine-tint); color: #244d40; }
.ov-panel .pill.clay { background: var(--clay-tint); color: #7f3925; }
.ov-panel .pill.gold { background: var(--gold-tint); color: #6f4e08; }
.ov-panel .pill.rose { background: var(--rose-tint); color: #7e2330; }
.ov-panel .pill.plain { background: var(--paper-deep); color: #4f493f; }
.ov-status .pill.sage { background: var(--sage-tint); color: #3c5241; }
.ov-status .pill.plain { background: var(--paper-deep); color: #4f493f; }

@media (max-width: 1180px) {
  .ov-columns { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

@media (max-width: 900px) {
  .ov-band { grid-template-columns: 1fr; }
}

@media (max-width: 760px) {
  .ov-columns, .ov-columns-two { grid-template-columns: 1fr; }
  .ov-row-detail, .ov-row-main span:not(.pill) { white-space: normal; }
}
</style>
