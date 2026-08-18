<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { apiClient } from '../api/client'
import type { WeatherResponse } from '../api/types'
import AppIcon from '../components/AppIcon.vue'
import CountUp from '../components/CountUp.vue'
import { requestOptions, session } from '../store'
import { presentWeather } from '../weather/weatherView'

interface DayPoint {
  label: string
  count: number
}

const now = ref(new Date())
const loading = ref(false)
const eventsToday = ref(0)
const eventsTotal = ref(0)
const severeCount = ref(0)
const warningCount = ref(0)
const infoCount = ref(0)
const pendingReviews = ref(0)
const pendingOutbox = ref(0)
const weekSeries = ref<DayPoint[]>([])
const weather = ref<WeatherResponse | null>(null)
const lastUpdated = ref<Date | null>(null)
const weatherView = computed(() => presentWeather(weather.value))

let clockTimer: ReturnType<typeof setInterval> | null = null
let refreshTimer: ReturnType<typeof setInterval> | null = null

const clockTime = computed(() =>
  now.value.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
)
const clockDate = computed(() =>
  now.value.toLocaleDateString('zh-CN', { month: 'long', day: 'numeric', weekday: 'long' }),
)

const ALERT_BUDGET_PER_MEMBER = 10
const budgetLeft = computed(() => {
  const budget = ALERT_BUDGET_PER_MEMBER * Math.max(session.members.length, 1)
  return Math.max(budget - warningCount.value - infoCount.value, 0)
})

const tickerText = computed(() => {
  const parts = [
    '家庭健康数据默认不出网，全部保存在本地可信域',
    '识别结果仅为候选，确认后才进入健康记录',
    '普通提醒已合并展示，严重事项仍会单独通知',
  ]
  for (const card of weather.value?.action_cards ?? []) {
    parts.push(card.message)
  }
  if (severeCount.value > 0) parts.push(`当前有 ${severeCount.value} 条严重风险信号待确认，请尽快查看依据`)
  parts.push('教学演示系统 · 不提供诊断、处方或用药决策')
  return parts.join('　　·　　')
})

const sparkPath = computed(() => {
  const points = weekSeries.value
  if (points.length === 0) return { line: '', area: '', dots: [] as Array<{ x: number; y: number }> }
  const width = 560
  const height = 120
  const maxCount = Math.max(...points.map(point => point.count), 1)
  const stepX = width / (points.length - 1 || 1)
  const coords = points.map((point, index) => ({
    x: index * stepX + 20,
    y: 20 + (height - 40) * (1 - point.count / maxCount),
  }))
  const line = coords.map((c, i) => `${i === 0 ? 'M' : 'L'} ${c.x.toFixed(1)} ${c.y.toFixed(1)}`).join(' ')
  const area = `${line} L ${coords[coords.length - 1]!.x.toFixed(1)} ${height} L ${coords[0]!.x.toFixed(1)} ${height} Z`
  return { line, area, dots: coords }
})

async function loadAggregates(): Promise<void> {
  const householdId = session.selectedHouseholdId
  if (!householdId || session.members.length === 0) return

  loading.value = true
  try {
    const memberIds = session.members.map(member => member.id)
    const [timelines, risks, reviews, outbox, weatherResult] = await Promise.all([
      Promise.allSettled(
        memberIds.map(id => apiClient.listMemberTimeline(householdId, id, requestOptions.value)),
      ),
      Promise.allSettled(
        memberIds.map(id => apiClient.listMemberRisks(householdId, id, requestOptions.value)),
      ),
      Promise.allSettled(
        memberIds.map(id => apiClient.listReviewTasks(householdId, id, requestOptions.value)),
      ),
      apiClient.listOutboxMessages(householdId, requestOptions.value).catch(() => []),
      apiClient.getWeatherActionCards(undefined, undefined, requestOptions.value).catch(() => null),
    ])

    const allEvents = timelines
      .filter((r): r is PromiseFulfilledResult<Awaited<ReturnType<typeof apiClient.listMemberTimeline>>> => r.status === 'fulfilled')
      .flatMap(r => r.value)
    eventsTotal.value = allEvents.length

    const today = new Date()
    today.setHours(0, 0, 0, 0)
    eventsToday.value = allEvents.filter(event => new Date(event.created_at) >= today).length

    const days: DayPoint[] = []
    for (let offset = 6; offset >= 0; offset -= 1) {
      const dayStart = new Date(today)
      dayStart.setDate(today.getDate() - offset)
      const dayEnd = new Date(dayStart)
      dayEnd.setDate(dayStart.getDate() + 1)
      days.push({
        label: offset === 0 ? '今天' : dayStart.toLocaleDateString('zh-CN', { weekday: 'short' }),
        count: allEvents.filter(event => {
          const created = new Date(event.created_at)
          return created >= dayStart && created < dayEnd
        }).length,
      })
    }
    weekSeries.value = days

    let severe = 0
    let warning = 0
    let info = 0
    for (const result of risks) {
      if (result.status !== 'fulfilled') continue
      severe += result.value.severe_count
      warning += result.value.warning_count
      info += result.value.total - result.value.severe_count - result.value.warning_count
    }
    severeCount.value = severe
    warningCount.value = warning
    infoCount.value = info

    pendingReviews.value = reviews
      .filter((r): r is PromiseFulfilledResult<Awaited<ReturnType<typeof apiClient.listReviewTasks>>> => r.status === 'fulfilled')
      .flatMap(r => r.value)
      .filter(task => task.status === 'PENDING_REVIEW').length

    pendingOutbox.value = outbox.filter(message => message.status === 'PENDING' || message.status === 'FAILED').length
    weather.value = weatherResult
    lastUpdated.value = new Date()
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void loadAggregates()
  clockTimer = setInterval(() => { now.value = new Date() }, 1000)
  refreshTimer = setInterval(() => void loadAggregates(), 30_000)
})

onBeforeUnmount(() => {
  if (clockTimer) clearInterval(clockTimer)
  if (refreshTimer) clearInterval(refreshTimer)
})
</script>

<template>
  <div class="bigscreen">
    <div class="bigscreen-top">
      <div>
        <h2 class="bigscreen-title">
          {{ session.households.find(h => h.id === session.selectedHouseholdId)?.name ?? '家庭' }} · 健康值守
        </h2>
        <span class="bs-hint">非敏感聚合视图 · 成员详情需授权后进入成员视图查看</span>
      </div>
      <div class="clock-ring">
        <div class="bigscreen-clock">
          {{ clockTime }}
          <small>{{ clockDate }}</small>
        </div>
      </div>
    </div>

    <div class="bigscreen-grid">
      <div class="bs-tile">
        <span class="bs-label">家庭成员</span>
        <span class="bs-value mint"><CountUp :value="session.members.length" /></span>
        <span class="bs-hint">全部在本地可信域内</span>
      </div>
      <div class="bs-tile">
        <span class="bs-label">今日新增事件</span>
        <span class="bs-value warm"><CountUp :value="eventsToday" /></span>
        <span class="bs-hint">累计 {{ eventsTotal }} 条已确认事实</span>
      </div>
      <div class="bs-tile">
        <span class="bs-label">严重风险</span>
        <span class="bs-value rose" :class="{ alarm: severeCount > 0 }"><CountUp :value="severeCount" /></span>
        <span class="bs-hint">严重信号不受预算压制</span>
      </div>
      <div class="bs-tile">
        <span class="bs-label">普通提醒</span>
        <span class="bs-value gold"><CountUp :value="warningCount + infoCount" /></span>
        <span class="bs-hint">今日预算剩余 {{ budgetLeft }}</span>
      </div>
      <div class="bs-tile">
        <span class="bs-label">待人工处理</span>
        <span class="bs-value mint"><CountUp :value="pendingReviews" /></span>
        <span class="bs-hint">复核候选，确认后方可入档</span>
      </div>
    </div>

    <div class="bs-columns">
      <div class="bs-panel">
        <h3>近七日健康事件</h3>
        <svg class="bs-spark" viewBox="0 0 600 150" role="img" aria-label="近七日已确认事件趋势">
          <defs>
            <linearGradient id="sparkFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stop-color="#9fd8c2" stop-opacity="0.45" />
              <stop offset="100%" stop-color="#9fd8c2" stop-opacity="0" />
            </linearGradient>
          </defs>
          <path v-if="sparkPath.area" class="spark-fill" :d="sparkPath.area" />
          <path v-if="sparkPath.line" class="spark-line" :d="sparkPath.line" />
          <circle
            v-for="(dot, index) in sparkPath.dots"
            :key="index"
            class="spark-dot"
            :cx="dot.x"
            :cy="dot.y"
            r="3.2"
          />
          <text
            v-for="(point, index) in weekSeries"
            :key="point.label + index"
            class="spark-label"
            :x="sparkPath.dots[index]?.x ?? 0"
            y="144"
          >
            {{ point.label }} {{ point.count }}
          </text>
        </svg>
      </div>

      <div class="bs-panel">
        <h3>本地运行状态</h3>
        <div class="bs-light-row">
          <span class="bs-light on" />
          <span>本地 API · 已连接（阶段 {{ session.capabilities?.phase ?? '未知' }}）</span>
        </div>
        <div
          v-for="cap in (session.capabilities?.available ?? []).slice(0, 3)"
          :key="cap"
          class="bs-light-row"
        >
          <span class="bs-light on" />
          <span>{{ cap }}</span>
        </div>
        <div
          v-for="cap in (session.capabilities?.unavailable ?? []).slice(0, 3)"
          :key="cap"
          class="bs-light-row"
        >
          <span class="bs-light off" />
          <span>{{ cap }} · 未启用（不显示虚假状态）</span>
        </div>
        <div class="bs-light-row">
          <span class="bs-light" :class="pendingOutbox === 0 ? 'on' : 'off'" />
          <span>事件出箱 · {{ pendingOutbox === 0 ? '全部送达' : `${pendingOutbox} 条待派发` }}</span>
        </div>
        <div class="bs-light-row">
          <span class="bs-light" :class="weatherView.available && !weatherView.stale ? 'on' : 'off'" />
          <span>天气行动卡 · {{ weatherView.statusLabel }} · {{ weatherView.scopeLabel }}</span>
        </div>
      </div>
    </div>

    <div class="bs-ticker" aria-hidden="true">
      <span>{{ tickerText }}</span>
    </div>

    <div class="bs-footer">
      {{ loading ? '正在刷新聚合数据…' : lastUpdated ? `每 30 秒自动刷新 · 上次更新 ${lastUpdated.toLocaleTimeString('zh-CN')}` : '' }}
      · 教学演示，不用于诊断或治疗
    </div>
  </div>

  <p class="text-faint" style="font-size: 12.5px; margin: 0; text-align: center">
    <AppIcon name="lock" :size="13" style="vertical-align: -2px" />
    大屏默认只展示非敏感聚合：数量、趋势与运行状态；病史、报告与对话正文不会投放到公共大屏。
  </p>
</template>
