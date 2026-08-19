<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { apiClient } from '../api/client'
import type {
  HealthEvent,
  MemberState,
  ReviewTask,
  RiskListResponse,
  WeatherResponse,
} from '../api/types'
import emptyCorner from '../assets/empty-corner.jpg'
import AppIcon from '../components/AppIcon.vue'
import CountUp from '../components/CountUp.vue'
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
  greetingByHour,
  relativeTime,
  summarizeEventPayload,
} from '../ui/labels'

const timeline = ref<HealthEvent[]>([])
const memberState = ref<MemberState | null>(null)
const risks = ref<RiskListResponse | null>(null)
const reviewTasks = ref<ReviewTask[]>([])
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
  if (!householdId || !memberId) return

  loading.value = true
  loadError.value = ''
  try {
    const [timelineResult, stateResult, riskResult, reviewResult] =
      await Promise.allSettled([
        apiClient.listMemberTimeline(householdId, memberId, requestOptions.value),
        apiClient.getMemberState(householdId, memberId, requestOptions.value),
        apiClient.listMemberRisks(householdId, memberId, requestOptions.value),
        apiClient.listReviewTasks(householdId, memberId, requestOptions.value),
      ])

    // 新成员还没有状态投影/风险数据属于正常情况（404），
    // 页面按"暂无数据"展示，不把它当作故障告警。
    timeline.value = timelineResult.status === 'fulfilled' ? timelineResult.value : []
    memberState.value = stateResult.status === 'fulfilled' ? stateResult.value : null
    risks.value = riskResult.status === 'fulfilled' ? riskResult.value : null
    reviewTasks.value = reviewResult.status === 'fulfilled' ? reviewResult.value : []
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
          <h2 class="hero-greeting"><span class="gradient-text">{{ greeting }}</span>，{{ session.actorId }}</h2>
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

  <WeatherActionPanel
    :weather="weather"
    :loading="weatherLoading"
    @refresh="loadWeather"
  />

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
