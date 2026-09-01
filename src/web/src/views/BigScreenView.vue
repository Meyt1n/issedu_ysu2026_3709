<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { apiClient } from '../api/client'
import type {
  PlanWorkbenchItem,
  ReviewTask,
  RiskAlert,
  WeatherResponse,
} from '../api/types'
import AppIcon from '../components/AppIcon.vue'
import CountUp from '../components/CountUp.vue'
import { requestOptions, session } from '../store'
import { isSameLocalDay, reviewDrugCandidate } from '../overview/overviewView'
import { formatDateTime, memberRoleLabel } from '../ui/labels'
import { familyRuntimeLines } from '../ui/runtimeStatus'
import { presentWeather } from '../weather/weatherView'

interface DayPoint {
  label: string
  count: number
}

interface PlanRow {
  id: string
  memberName: string
  drug: string
  schedule: string
  nextAt: string
  today: boolean
}

interface ReviewRow {
  id: string
  memberName: string
  drug: string
}

interface RiskRow {
  key: string
  memberName: string
  level: string
  levelLabel: string
  message: string
}

const now = ref(new Date())
const loading = ref(false)
const eventsToday = ref(0)
const eventsTotal = ref(0)
const memberCount = ref(0)
const severeCount = ref(0)
const warningCount = ref(0)
const infoCount = ref(0)
const pendingReviews = ref(0)
const pendingOutbox = ref(0)
const weekSeries = ref<DayPoint[]>([])
const weather = ref<WeatherResponse | null>(null)
const planRows = ref<PlanRow[]>([])
const reviewRows = ref<ReviewRow[]>([])
const riskRows = ref<RiskRow[]>([])
const lastUpdated = ref<Date | null>(null)
const weatherView = computed(() => presentWeather(weather.value))
const runtimeLines = computed(() => familyRuntimeLines(session.capabilities))

let clockTimer: ReturnType<typeof setInterval> | null = null
let refreshTimer: ReturnType<typeof setInterval> | null = null

const clockTime = computed(() =>
  now.value.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
)
const clockDate = computed(() =>
  now.value.toLocaleDateString('zh-CN', { month: 'long', day: 'numeric', weekday: 'long' }),
)

const householdName = computed(
  () => session.households.find(h => h.id === session.selectedHouseholdId)?.name ?? '家庭',
)

const ALERT_BUDGET_PER_MEMBER = 10
const budgetLeft = computed(() => {
  const budget = ALERT_BUDGET_PER_MEMBER * Math.max(memberCount.value || session.members.length, 1)
  return Math.max(budget - warningCount.value - infoCount.value, 0)
})

const ordinaryAlertCount = computed(() => warningCount.value + infoCount.value)

const memberTiles = computed(() =>
  session.members.map(member => ({
    id: member.id,
    name: member.display_name,
    role: memberRoleLabel(member.role),
    planCount: planRows.value.filter(row => row.memberName === member.display_name).length,
    reviewCount: reviewRows.value.filter(row => row.memberName === member.display_name).length,
    riskCount: riskRows.value.filter(row => row.memberName === member.display_name).length,
  })),
)

const weatherCards = computed(() => (weather.value?.action_cards ?? []).slice(0, 3))

const tickerText = computed(() => {
  const parts = [
    '家庭健康数据默认不出网，全部保存在本地可信域',
    '识别结果仅为候选，确认后才进入健康记录',
    '普通提醒已合并展示，严重事项仍会单独通知',
  ]
  for (const card of weatherCards.value) {
    parts.push(card.message)
  }
  if (severeCount.value > 0) {
    parts.push(`当前有 ${severeCount.value} 条严重风险信号待确认，请尽快查看依据`)
  }
  if (pendingReviews.value > 0) {
    parts.push(`还有 ${pendingReviews.value} 条识别候选等待人工复核`)
  }
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

function riskLevelLabel(level: string): string {
  if (level === 'SEVERE') return '严重'
  if (level === 'WARNING') return '提醒'
  if (level === 'INFO' || level === 'TIP') return '提示'
  return '留意'
}

function riskTone(level: string): string {
  if (level === 'SEVERE') return 'rose'
  if (level === 'WARNING') return 'gold'
  return 'plain'
}

async function loadMemberPanels(householdId: string): Promise<void> {
  const members = session.members
  if (members.length === 0) {
    planRows.value = []
    reviewRows.value = []
    riskRows.value = []
    return
  }

  const results = await Promise.all(
    members.map(async member => {
      const [plans, reviews, risks] = await Promise.all([
        apiClient.getPlanWorkbench(householdId, member.id, requestOptions.value).catch(() => null),
        apiClient.listReviewTasks(householdId, member.id, requestOptions.value).catch(() => [] as ReviewTask[]),
        apiClient.listMemberRisks(householdId, member.id, requestOptions.value).catch(() => null),
      ])
      return { member, plans, reviews, risks }
    }),
  )

  const nextPlans: PlanRow[] = []
  const nextReviews: ReviewRow[] = []
  const nextRisks: RiskRow[] = []

  for (const { member, plans, reviews, risks } of results) {
    const ordered = [...(plans?.plans ?? [])].sort(
      (left, right) => Date.parse(left.next_action_at) - Date.parse(right.next_action_at),
    )
    const today = ordered.filter(plan => isSameLocalDay(plan.next_action_at))
    const chosen = (today.length > 0 ? today : ordered).slice(0, 3)
    for (const plan of chosen) {
      nextPlans.push(planRow(member.display_name, plan))
    }

    for (const task of reviews.filter(item => item.status === 'PENDING_REVIEW').slice(0, 3)) {
      nextReviews.push({
        id: task.id,
        memberName: member.display_name,
        drug: reviewDrugCandidate(task),
      })
    }

    const alerts = (risks?.alerts ?? []) as RiskAlert[]
    const ranked = [...alerts].sort((left, right) => {
      const rank = (level: string) => (level === 'SEVERE' ? 0 : level === 'WARNING' ? 1 : 2)
      return rank(left.level) - rank(right.level)
    })
    for (const alert of ranked.slice(0, 3)) {
      nextRisks.push({
        key: alert.risk_fingerprint || `${member.id}:${alert.rule_id}:${alert.message}`,
        memberName: member.display_name,
        level: alert.level,
        levelLabel: riskLevelLabel(alert.level),
        message: alert.message,
      })
    }
  }

  planRows.value = nextPlans
    .sort((left, right) => Number(right.today) - Number(left.today) || Date.parse(left.nextAt) - Date.parse(right.nextAt))
    .slice(0, 6)
  reviewRows.value = nextReviews.slice(0, 5)
  riskRows.value = nextRisks
    .sort((left, right) => {
      const rank = (level: string) => (level === 'SEVERE' ? 0 : level === 'WARNING' ? 1 : 2)
      return rank(left.level) - rank(right.level)
    })
    .slice(0, 5)
}

function planRow(memberName: string, plan: PlanWorkbenchItem): PlanRow {
  return {
    id: plan.plan_event_id,
    memberName,
    drug: plan.drug,
    schedule: plan.schedule,
    nextAt: plan.next_action_at,
    today: isSameLocalDay(plan.next_action_at),
  }
}

async function loadAggregates(): Promise<void> {
  const householdId = session.selectedHouseholdId
  if (!householdId) return

  loading.value = true
  try {
    const [summaryResult, weatherResult] = await Promise.all([
      apiClient.getDashboardSummary(householdId, requestOptions.value),
      apiClient.getWeatherActionCards(undefined, undefined, requestOptions.value).catch(() => null),
    ])
    memberCount.value = summaryResult.member_count
    eventsTotal.value = summaryResult.events_total
    eventsToday.value = summaryResult.events_today
    severeCount.value = summaryResult.severe_count
    warningCount.value = summaryResult.warning_count
    infoCount.value = summaryResult.info_count
    pendingReviews.value = summaryResult.pending_reviews
    pendingOutbox.value = summaryResult.pending_outbox
    weekSeries.value = summaryResult.week_series.map(point => {
      const date = new Date(`${point.day}T00:00:00`)
      return {
        label: point.day === new Date().toISOString().slice(0, 10)
          ? '今天'
          : date.toLocaleDateString('zh-CN', { weekday: 'short' }),
        count: point.count,
      }
    })
    weather.value = weatherResult
    lastUpdated.value = new Date(summaryResult.generated_at)
    await loadMemberPanels(householdId)
  } finally {
    loading.value = false
  }
}

watch(
  () => [session.selectedHouseholdId, session.members.map(member => member.id).join(',')],
  () => void loadAggregates(),
)

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
  <div class="bigscreen" aria-label="家庭健康大屏">
    <div class="bigscreen-top">
      <div>
        <p class="bs-kicker">家庭值守大屏</p>
        <h2 class="bigscreen-title">{{ householdName }} · 健康值守</h2>
        <span class="bs-hint">非敏感聚合视图 · 病史、报告与对话正文不会投放到公共大屏</span>
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
        <span class="bs-value mint"><CountUp :value="memberCount || session.members.length" /></span>
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
        <span class="bs-value gold"><CountUp :value="ordinaryAlertCount" /></span>
        <span class="bs-hint">警告 {{ warningCount }} · 提示 {{ infoCount }} · 预算剩 {{ budgetLeft }}</span>
      </div>
      <div class="bs-tile">
        <span class="bs-label">待人工处理</span>
        <span class="bs-value mint"><CountUp :value="pendingReviews" /></span>
        <span class="bs-hint">复核候选，确认后方可入档</span>
      </div>
      <div class="bs-tile">
        <span class="bs-label">今日用药提醒</span>
        <span class="bs-value warm"><CountUp :value="planRows.filter(row => row.today).length || planRows.length" /></span>
        <span class="bs-hint">{{ planRows.some(row => row.today) ? '按已确认计划展示' : planRows.length ? '展示最近计划' : '暂无计划' }}</span>
      </div>
    </div>

    <div class="bs-member-strip" aria-label="家庭成员概览">
      <div v-for="member in memberTiles" :key="member.id" class="bs-member-chip">
        <strong>{{ member.name }}</strong>
        <span>{{ member.role }}</span>
        <small>
          提醒 {{ member.planCount }} · 复核 {{ member.reviewCount }} · 风险 {{ member.riskCount }}
        </small>
      </div>
      <div v-if="memberTiles.length === 0" class="bs-empty-inline">当前身份下没有可展示的家庭成员</div>
    </div>

    <div class="bs-columns bs-columns-main">
      <div class="bs-panel">
        <h3>近七日已确认事件</h3>
        <svg class="bs-spark" viewBox="0 0 600 150" role="img" aria-label="近七日已确认事件趋势">
          <defs>
            <linearGradient id="sparkFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stop-color="var(--pine)" stop-opacity="0.35" />
              <stop offset="100%" stop-color="var(--pine)" stop-opacity="0" />
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
        <div
          v-for="line in runtimeLines"
          :key="line.label"
          class="bs-light-row"
        >
          <span class="bs-light" :class="line.on ? 'on' : 'off'" />
          <span>{{ line.label }}</span>
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

    <div class="bs-columns bs-columns-detail">
      <div class="bs-panel">
        <h3>今日环境提醒</h3>
        <template v-if="weatherView.available">
          <div class="bs-weather-hero">
            <strong>
              {{ weather?.temperature != null ? `${weather.temperature}°` : '—' }}
            </strong>
            <div>
              <span>{{ weather?.condition || weatherView.statusLabel }}</span>
              <small>{{ weatherView.scopeLabel }} · {{ weatherView.sourceLabel }}</small>
            </div>
          </div>
          <ul v-if="weatherCards.length" class="bs-list">
            <li v-for="card in weatherCards" :key="card.rule_id" class="bs-list-row">
              <span class="pill" :class="card.level === 'warning' ? 'gold' : 'plain'">
                {{ card.level === 'warning' ? '留意' : '提示' }}
              </span>
              <span>{{ card.message }}</span>
            </li>
          </ul>
          <p v-else class="bs-empty">暂无环境行动建议</p>
        </template>
        <p v-else class="bs-empty">{{ weatherView.statusLabel }} · 不影响家庭健康记录</p>
      </div>

      <div class="bs-panel">
        <h3>近期用药提醒</h3>
        <ul v-if="planRows.length" class="bs-list">
          <li v-for="plan in planRows" :key="plan.id" class="bs-list-row">
            <div>
              <strong>{{ plan.drug }}</strong>
              <small>{{ plan.memberName }} · {{ plan.schedule }}</small>
            </div>
            <span class="pill" :class="plan.today ? 'pine' : 'plain'">
              {{ plan.today ? '今日' : formatDateTime(plan.nextAt) }}
            </span>
          </li>
        </ul>
        <p v-else class="bs-empty">暂无已确认用药计划</p>
      </div>

      <div class="bs-panel">
        <h3>待复核识别候选</h3>
        <ul v-if="reviewRows.length" class="bs-list">
          <li v-for="row in reviewRows" :key="row.id" class="bs-list-row">
            <div>
              <strong>{{ row.drug }}</strong>
              <small>{{ row.memberName }} · 仅候选，未入档</small>
            </div>
            <span class="pill clay">待复核</span>
          </li>
        </ul>
        <p v-else class="bs-empty">当前没有待复核候选</p>
      </div>

      <div class="bs-panel">
        <h3>需要留意的风险</h3>
        <ul v-if="riskRows.length" class="bs-list">
          <li v-for="row in riskRows" :key="row.key" class="bs-list-row">
            <div>
              <strong>{{ row.memberName }}</strong>
              <small>{{ row.message }}</small>
            </div>
            <span class="pill" :class="riskTone(row.level)">{{ row.levelLabel }}</span>
          </li>
        </ul>
        <p v-else class="bs-empty">当前没有脱敏风险摘要</p>
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
    大屏跟随当前主题配色；只展示数量、趋势、运行状态与脱敏摘要。
  </p>
</template>
