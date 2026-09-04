<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'

import AppIcon from '@/components/AppIcon.vue'
import BrandLogo from '@/components/BrandLogo.vue'
import ConfettiBurst from '@/components/ConfettiBurst.vue'
import ErrorNotice from '@/components/ErrorNotice.vue'
import EmptyState from '@/components/EmptyState.vue'
import EnvironmentActionCard from '@/components/EnvironmentActionCard.vue'
import ListLoadingState from '@/components/ListLoadingState.vue'
import ListStatusAnnouncer from '@/components/ListStatusAnnouncer.vue'
import ReminderStatusCard from '@/components/ReminderStatusCard.vue'
import LevelTag from '@/components/LevelTag.vue'
import PrivacyBadge from '@/components/PrivacyBadge.vue'
import ProgressRing from '@/components/ProgressRing.vue'
import TaskCard from '@/components/TaskCard.vue'
import TrendChart from '@/components/TrendChart.vue'
import { useCountUp } from '@/composables/useCountUp'
import { usePullToRefresh } from '@/composables/usePullToRefresh'
import { showToast } from '@/composables/useToast'
import { presentApiError, presentListApiError, type ErrorPresentation } from '@/api/errors'
import { activeProvider } from '@/data'
import { eventStatusLabel, riskLevelTone, taskLevelLabel, taskStatusLabel } from '@/data/labels'
import type {
  CareTask,
  MemberSummary,
  TaskAction,
  TaskActionHistoryEntry,
  TaskActionPayload,
  TodaySnapshot,
  TrendPoint,
} from '@/data/types'
import { cancelScheduledReminders, reminderState, synchronizeReminders } from '@/notifications/reminderService'
import { sessionContextKey, useSession } from '@/stores/session'
import { tapFeedback } from '@/utils/haptics'
import { formatDateTime, greetingByHour } from '@/utils/format'

const WEEKDAYS = ['日', '一', '二', '三', '四', '五', '六']

const { session, updateSession } = useSession()

const members = ref<MemberSummary[]>([])
const snapshot = ref<TodaySnapshot | null>(null)
const trend = ref<TrendPoint[]>([])
const loading = ref(true)
const error = ref<ErrorPresentation | null>(null)
const partialError = ref<ErrorPresentation | null>(null)
const actionError = ref<ErrorPresentation | null>(null)
const busyTaskId = ref('')
const failedAction = ref<{ taskId: string; action: TaskAction; payload: TaskActionPayload } | null>(null)
const confetti = ref<InstanceType<typeof ConfettiBurst> | null>(null)
const sessionKey = computed(() => sessionContextKey(session))
let reloadGeneration = 0
let reloadInFlight = false
let reloadQueued = false

/** MOB-135：任务操作历史。服务端条目按需加载；本地待确认/失败条目只存内存。 */
const historyOpen = ref(false)
const historyLoading = ref(false)
const historyError = ref<ErrorPresentation | null>(null)
const serverHistory = ref<TaskActionHistoryEntry[]>([])
const localHistory = ref<TaskActionHistoryEntry[]>([])
let localHistorySeq = 0
const historyEntries = computed(() => [...localHistory.value, ...serverHistory.value])

const RECEIPT_LABELS: Record<TaskActionHistoryEntry['receipt'], string> = {
  RECEIPTED: '有效回执',
  SUPERSEDED: '已被覆盖',
  LOCAL_PENDING: '本地待确认',
  LOCAL_FAILED: '未获回执',
}
const RECEIPT_TONES: Record<TaskActionHistoryEntry['receipt'], 'calm' | 'neutral' | 'warn' | 'danger'> = {
  RECEIPTED: 'calm',
  SUPERSEDED: 'neutral',
  LOCAL_PENDING: 'warn',
  LOCAL_FAILED: 'danger',
}

async function loadHistory(): Promise<void> {
  if (historyLoading.value) return
  const expectedKey = sessionKey.value
  const memberId = session.currentMemberId
  if (!memberId) {
    serverHistory.value = []
    return
  }
  historyLoading.value = true
  historyError.value = null
  try {
    const entries = await activeProvider().listTaskActionHistory(memberId)
    if (expectedKey !== sessionKey.value || memberId !== session.currentMemberId) return
    serverHistory.value = entries
  } catch (cause) {
    if (expectedKey !== sessionKey.value || memberId !== session.currentMemberId) return
    historyError.value = presentListApiError(cause)
  } finally {
    if (expectedKey === sessionKey.value) historyLoading.value = false
  }
}

function toggleHistory(): void {
  historyOpen.value = !historyOpen.value
  if (historyOpen.value) void loadHistory()
}

function pushLocalHistoryEntry(taskId: string, action: TaskAction): string {
  localHistorySeq += 1
  const localId = `local-${localHistorySeq}`
  const task = snapshot.value?.tasks.find(t => t.id === taskId)
  localHistory.value.unshift({
    eventId: localId,
    action,
    actionLabel: action === 'confirm' ? '确认' : action === 'defer' ? '延期' : '跳过',
    taskTitle: task?.title ?? '任务',
    memberName: currentMember.value?.name ?? '当前成员',
    memberId: session.currentMemberId,
    serverTime: new Date().toISOString(),
    finalStatus: '待回执',
    receipt: 'LOCAL_PENDING',
    note: '已提交，等待服务端回执；未获回执前不当作成功。',
  })
  return localId
}

function settleLocalHistoryEntry(localId: string, receipt: 'LOCAL_PENDING' | 'LOCAL_FAILED', note?: string): void {
  const index = localHistory.value.findIndex(entry => entry.eventId === localId)
  if (index === -1) return
  if (receipt === 'LOCAL_PENDING') {
    // 成功：本地条目退场，由服务端事件回执接管展示
    localHistory.value.splice(index, 1)
    if (historyOpen.value) void loadHistory()
    return
  }
  localHistory.value[index] = {
    ...localHistory.value[index]!,
    receipt,
    finalStatus: '未确认',
    note: note ?? '未获服务端回执（网络失败或请求被拒），不当作成功；可安全重试，服务端幂等不会重复记录。',
  }
}

function clearHistory(): void {
  serverHistory.value = []
  localHistory.value = []
  historyError.value = null
}

const KNOWN_FINAL_STATUSES = new Set(['PENDING', 'CONFIRMED', 'DEFERRED', 'SKIPPED', 'ESCALATED'])
function historyFinalStatusLabel(status: string): string {
  return KNOWN_FINAL_STATUSES.has(status)
    ? taskStatusLabel(status as CareTask['status'])
    : status
}

const greeting = computed(() => greetingByHour(new Date().getHours()))
const dateLine = computed(() => {
  const now = new Date()
  return `${now.getMonth() + 1}月${now.getDate()}日 星期${WEEKDAYS[now.getDay()]}`
})
const daypart = computed(() => {
  const hour = new Date().getHours()
  if (hour >= 5 && hour < 10) return 'morning'
  if (hour >= 10 && hour < 16) return 'day'
  if (hour >= 16 && hour < 19) return 'evening'
  return 'night'
})
const currentMember = computed(() => members.value.find(m => m.id === session.currentMemberId) ?? null)

/**
 * 成员下拉必须经过 `updateSession` 写入，不能直接改 store 状态：
 * 只有走 `updateSession` 才会触发会话上下文清理（丢弃上一位成员的查询、上传草稿和缓存）。
 */
const memberSelection = computed<string>({
  get: () => session.currentMemberId,
  set: value => updateSession({ currentMemberId: value }),
})

const pendingTasks = computed(
  () => snapshot.value?.tasks.filter(t => t.status === 'PENDING' || t.status === 'DEFERRED') ?? [],
)
const escalatedTasks = computed(
  () => snapshot.value?.tasks.filter(t => t.status === 'ESCALATED') ?? [],
)
const doneTasks = computed(
  () => snapshot.value?.tasks.filter(t => t.status !== 'PENDING' && t.status !== 'DEFERRED' && t.status !== 'ESCALATED') ?? [],
)
const topRisks = computed(() => (snapshot.value?.risks ?? []).slice(0, 3))

const pendingCount = useCountUp(() => pendingTasks.value.length)
const riskCount = useCountUp(() => snapshot.value?.risks.length ?? 0)
const recentCount = useCountUp(() => snapshot.value?.recentEvents.length ?? 0)

const listStatusMessage = computed(() => {
  if (loading.value || error.value) return ''
  if (!members.value.length) return '当前没有可用的家庭成员。'
  if (!snapshot.value) return '今日照护数据暂不可用。'
  const pending = pendingTasks.value.length
  const risks = snapshot.value.risks.length
  return `已加载今日照护数据，${pending} 项待处理任务，${risks} 条风险提醒。`
})

async function loadMembers(expectedKey: string, generation: number): Promise<boolean> {
  const nextMembers = await activeProvider().listMembers()
  if (expectedKey !== sessionKey.value || generation !== reloadGeneration) return false
  if (session.mobileRole === 'member') {
    // 成员端只保留自己的成员卡片；当前成员无效时优先使用 SELF，
    // 再退回服务端实际返回的第一位授权成员，绝不把全家列表展示给成员。
    const preferred = nextMembers.find(m => m.id === session.currentMemberId)
      ?? nextMembers.find(m => m.role === 'SELF')
      ?? nextMembers[0]
    members.value = preferred ? [preferred] : []
    if (session.currentMemberId !== (preferred?.id ?? '')) {
      updateSession({ currentMemberId: preferred?.id ?? '' })
    }
    return true
  }

  members.value = nextMembers
  const exists = nextMembers.some(m => m.id === session.currentMemberId)
  if (!exists) {
    const preferred = nextMembers.find(m => m.role === 'DEPENDENT') ?? nextMembers[0]
    updateSession({ currentMemberId: preferred?.id ?? '' })
  }
  return true
}

async function loadSnapshot(expectedKey = sessionKey.value, generation = reloadGeneration): Promise<boolean> {
  if (!session.currentMemberId) {
    snapshot.value = null
    trend.value = []
    return true
  }
  const memberId = session.currentMemberId
  const [snapshotResult, trendResult] = await Promise.allSettled([
    activeProvider().getTodaySnapshot(memberId),
    activeProvider().getWeeklyTrend(memberId),
  ])
  if (snapshotResult.status === 'rejected') throw snapshotResult.reason
  if (expectedKey !== sessionKey.value || generation !== reloadGeneration) return false
  // 任务、趋势和时间线来自同一轮刷新，避免操作后显示不同步的旧数据。
  snapshot.value = snapshotResult.value
  if (trendResult.status === 'fulfilled') {
    trend.value = trendResult.value
  } else {
    trend.value = []
    partialError.value = presentListApiError(trendResult.reason, { partial: true })
  }
  void synchronizeReminders(snapshotResult.value.tasks)
  return true
}

async function reload(options: { preserveSnapshot?: boolean } = {}): Promise<void> {
  if (reloadInFlight) {
    reloadQueued = true
    return
  }
  reloadInFlight = true
  const generation = ++reloadGeneration
  const expectedKey = sessionKey.value
  loading.value = true
  error.value = null
  partialError.value = null
  if (!options.preserveSnapshot) {
    members.value = []
    snapshot.value = null
    trend.value = []
  }
  try {
    if (!(await loadMembers(expectedKey, generation))) return
    await loadSnapshot(expectedKey, generation)
  } catch (cause) {
    if (expectedKey !== sessionKey.value || generation !== reloadGeneration) return
    error.value = presentListApiError(cause)
    if (!options.preserveSnapshot) snapshot.value = null
  } finally {
    if (generation === reloadGeneration) loading.value = false
    reloadInFlight = false
    if (reloadQueued) {
      reloadQueued = false
      void reload()
    }
  }
}

async function onMemberChange(): Promise<void> {
  // 选中值已由 memberSelection 的 setter 经 updateSession 写入并触发上下文清理。
  loading.value = true
  error.value = null
  partialError.value = null
  actionError.value = null
  failedAction.value = null
  snapshot.value = null
  trend.value = []
  const generation = ++reloadGeneration
  const expectedKey = sessionKey.value
  try {
    await loadSnapshot(expectedKey, generation)
  } catch (cause) {
    error.value = presentApiError(cause)
  } finally {
    if (generation === reloadGeneration) loading.value = false
  }
}

async function onTaskAction(taskId: string, action: TaskAction, payload: TaskActionPayload): Promise<void> {
  // 同一轮只能有一个写操作；按钮的 disabled 负责视觉反馈，这个守卫负责
  // 覆盖同一事件循环内的重复 click/键盘触发。
  if (busyTaskId.value) return
  const expectedKey = sessionKey.value
  const expectedMemberId = session.currentMemberId
  busyTaskId.value = taskId
  actionError.value = null
  failedAction.value = null
  const hadPending = pendingTasks.value.length
  const localId = pushLocalHistoryEntry(taskId, action)
  let task: CareTask
  try {
    task = await activeProvider().submitTaskAction(taskId, action, payload)
  } catch (cause) {
    actionError.value = presentApiError(cause)
    failedAction.value = { taskId, action, payload }
    settleLocalHistoryEntry(localId, 'LOCAL_FAILED')
    busyTaskId.value = ''
    return
  }

  // 会话或当前成员已切换时，丢弃旧上下文的回执，避免把旧家庭结果写进新页面。
  if (expectedKey !== sessionKey.value || expectedMemberId !== session.currentMemberId) {
    settleLocalHistoryEntry(localId, 'LOCAL_FAILED', '提交期间切换了成员或会话，本次回执已按旧上下文丢弃；请在新上下文中重试。')
    busyTaskId.value = ''
    return
  }

  settleLocalHistoryEntry(localId, 'LOCAL_PENDING')

  const label = action === 'confirm' ? '已确认' : action === 'defer' ? '已延期' : '已记录跳过'
  tapFeedback(action === 'confirm' ? [12, 60, 18] : 12)
  showToast(`${label}：${task.title}`, 'success')

  // 先应用服务端回执，随后做统一整页刷新。刷新失败不再重提写操作，
  // 页面保留已收到的回执并只提供刷新重试。
  if (snapshot.value?.memberId === task.memberId) {
    snapshot.value = {
      ...snapshot.value,
      tasks: snapshot.value.tasks.map(item => item.id === task.id ? task : item),
    }
  }
  await cancelScheduledReminders()
  await reload({ preserveSnapshot: true })
  // 最后一项任务处理完：彩带庆祝。
  if (hadPending === 1 && pendingTasks.value.length === 0 && doneTasks.value.length > 0) {
    confetti.value?.fire()
  }
  busyTaskId.value = ''
}

async function retryTaskAction(): Promise<void> {
  const failed = failedAction.value
  if (!failed) return
  await onTaskAction(failed.taskId, failed.action, failed.payload)
}

watch(
  () => sessionKey.value,
  () => {
    actionError.value = null
    failedAction.value = null
    // 会话/成员/数据源切换：旧上下文的历史（含本地待确认条目）立即清空
    clearHistory()
    void reload()
  },
)

const { pull, refreshing, triggerThreshold } = usePullToRefresh(async () => {
  tapFeedback(10)
  await reload()
  showToast('已刷新', 'info', 1400)
})

onMounted(reload)
</script>

<template>
  <main id="main" class="screen">
    <div
      v-if="pull > 0 || refreshing"
      class="pull-indicator"
      :style="{ height: `${refreshing ? triggerThreshold : pull}px` }"
      aria-live="polite"
    >
      <AppIcon name="refresh" :size="18" :class="{ 'pull-spin': refreshing }" />
      {{ refreshing ? '正在刷新…' : pull >= triggerThreshold ? '松开刷新' : '下拉刷新' }}
    </div>

    <section class="hero" :data-daypart="daypart" aria-label="今日概览">
      <div class="hero-top">
        <div class="hero-text">
          <div class="hero-brand">
            <BrandLogo :size="34" />
            <p class="hero-eyebrow">家健镜 · 随身照护</p>
          </div>
          <h1>{{ greeting }}{{ currentMember ? `，${currentMember.name.replace(/（.*?）/g, '')}` : '' }}</h1>
          <p class="hero-sub">{{ dateLine }}</p>
        </div>
        <ProgressRing :done="doneTasks.length" :total="snapshot?.tasks.length ?? 0" />
      </div>
      <div class="hero-stats">
        <div class="hero-stat">
          <strong>{{ pendingCount }}</strong>
          <span><AppIcon name="pill" :size="13" /> 待处理任务</span>
        </div>
        <div class="hero-stat">
          <strong>{{ riskCount }}</strong>
          <span><AppIcon name="alert" :size="13" /> 待关注风险</span>
        </div>
        <div class="hero-stat">
          <strong>{{ recentCount }}</strong>
          <span><AppIcon name="clock" :size="13" /> 最近变化</span>
        </div>
      </div>
    </section>

    <PrivacyBadge />

    <label v-if="session.mobileRole === 'admin'" class="field">
      当前成员
      <select v-model="memberSelection" :disabled="loading" @change="onMemberChange">
        <option v-for="member in members" :key="member.id" :value="member.id">
          {{ member.name }}（{{ member.relation }}）
        </option>
      </select>
    </label>
    <ErrorNotice v-if="error" :error="error" :busy="loading" @retry="reload" />
    <ErrorNotice
      v-if="partialError"
      :error="partialError"
      :busy="loading"
      title="部分数据未加载"
      tone="warn"
      @retry="reload"
    />
    <ErrorNotice v-if="actionError" :error="actionError" :busy="Boolean(busyTaskId)" @retry="retryTaskAction" />

    <ListLoadingState v-if="loading" label="正在加载家庭和成员数据…" :count="3" />

    <template v-else-if="members.length === 0">
      <EmptyState
        icon="family"
        title="当前身份没有可用家庭成员"
      />
    </template>

    <template v-else-if="snapshot">
      <ReminderStatusCard :state="reminderState" />
      <EnvironmentActionCard :state="snapshot.environmentAction" />

      <section aria-labelledby="tasks-title">
        <div class="section-heading">
          <h2 id="tasks-title"><span class="heading-dot" aria-hidden="true"></span>今日照护任务</h2>
          <span class="meta-line">
            {{ pendingTasks.length }} 项待处理
            <template v-if="escalatedTasks.length > 0"> · {{ escalatedTasks.length }} 项需关注</template>
          </span>
        </div>
        <div class="plain-list" style="margin-top: 10px">
          <EmptyState
            v-if="pendingTasks.length === 0 && escalatedTasks.length === 0"
            icon="check"
            title="今日任务都处理完了"
          />
          <TaskCard
            v-for="task in [...pendingTasks, ...escalatedTasks]"
            :key="task.id"
            :task="task"
            :busy="Boolean(busyTaskId)"
            @action="(action, payload) => onTaskAction(task.id, action, payload)"
          />
        </div>
        <details v-if="doneTasks.length > 0" class="done-tasks">
          <summary>已处理（{{ doneTasks.length }}）</summary>
          <ul class="card divided-list">
            <li v-for="task in doneTasks" :key="task.id">
              <div class="card-title-row">
                <strong>{{ task.title }}</strong>
                <LevelTag kind="taskStatus" :value="task.status" />
              </div>
              <span class="meta-line">提醒等级：{{ taskLevelLabel(task.level) }}</span>
            </li>
          </ul>
        </details>
      </section>

      <section v-if="session.mobileRole === 'admin'" aria-labelledby="history-title">
        <div class="section-heading">
          <h2 id="history-title"><span class="heading-dot" data-tone="info" aria-hidden="true"></span>任务操作历史</h2>
          <button type="button" class="section-link" @click="toggleHistory">
            {{ historyOpen ? '收起' : '查看' }}
          </button>
        </div>
        <div v-if="historyOpen" class="card" style="margin-top: 10px">
          <p v-if="historyLoading" class="meta-line" role="status">正在加载服务端操作历史…</p>
          <ErrorNotice v-else-if="historyError" :error="historyError" :busy="historyLoading" @retry="loadHistory" />
          <template v-else>
            <p
              v-if="historyEntries.length === 0"
              class="meta-line"
              role="status"
            >
              当前成员还没有确认、延期或跳过的操作记录；确认、延期、跳过后会在这里显示服务端回执。
            </p>
            <ul v-else class="divided-list">
              <li v-for="entry in historyEntries" :key="entry.eventId">
                <div class="card-title-row">
                  <strong>{{ entry.actionLabel }}：{{ entry.taskTitle }}</strong>
                  <span class="tag" :data-tone="RECEIPT_TONES[entry.receipt]">{{ RECEIPT_LABELS[entry.receipt] }}</span>
                </div>
                <span class="meta-line">{{ entry.memberName }} · {{ entry.serverTime ? `服务端时间 ${formatDateTime(entry.serverTime)}` : '本机提交时间未知' }}</span>
                <span class="meta-line">最终状态：{{ historyFinalStatusLabel(entry.finalStatus) }}</span>
                <span class="meta-line">回执标识：{{ entry.eventId }}</span>
                <p v-if="entry.note" class="meta-line">{{ entry.note }}</p>
                <button
                  v-if="entry.receipt === 'LOCAL_FAILED'"
                  type="button"
                  class="btn btn-quiet"
                  @click="retryTaskAction"
                >
                  安全重试（服务端幂等，不会重复记录）
                </button>
              </li>
            </ul>
            <p class="meta-line">
              历史来自家庭服务器的事件时间线（脱敏摘要）；本地待确认条目只在本机内存中展示，不会写入存储。
            </p>
          </template>
        </div>
      </section>

      <section v-if="session.mobileRole === 'admin'" aria-labelledby="trend-title">
        <div class="section-heading">
          <h2 id="trend-title"><span class="heading-dot" data-tone="accent" aria-hidden="true"></span>近 7 天完成情况</h2>
        </div>
        <div class="card" style="margin-top: 10px">
          <p v-if="trend.length === 0" class="meta-line" role="status">
            趋势当前不可用或没有可复核的计划数据；应用不会用零值代替未知结果。
          </p>
          <template v-else>
            <TrendChart :points="trend" />
            <p class="meta-line">按家庭服务端时区分日；同一计划的更新会折叠，且仅最终确认为完成。</p>
          </template>
        </div>
      </section>

      <section v-if="session.mobileRole === 'admin'" aria-labelledby="risks-title">
        <div class="section-heading">
          <h2 id="risks-title"><span class="heading-dot" data-tone="warn" aria-hidden="true"></span>待关注风险</h2>
          <RouterLink class="section-link" to="/alerts">查看全部</RouterLink>
        </div>
        <div class="plain-list" style="margin-top: 10px">
          <EmptyState
            v-if="topRisks.length === 0"
            icon="shield"
            title="暂无待关注的风险提醒"
            hint="规则重新计算后结果会更新"
          />
          <RouterLink
            v-for="risk in topRisks"
            :key="risk.ruleId"
            class="card risk-link"
            :to="`/alerts/${risk.memberId}/${encodeURIComponent(risk.ruleId)}`"
          >
            <div class="risk-row">
              <span class="icon-disc" :data-tone="riskLevelTone(risk.level)" aria-hidden="true">
                <AppIcon name="alert" :size="21" />
              </span>
              <div class="risk-body">
                <p class="risk-message">{{ risk.message }}</p>
                <span class="meta-line">
                  <LevelTag kind="risk" :value="risk.level" />
                  证据 {{ risk.sourceCount }} 条
                </span>
              </div>
              <AppIcon name="chevron-right" :size="17" />
            </div>
          </RouterLink>
        </div>
      </section>

      <section v-else aria-labelledby="member-risks-title">
        <div class="section-heading">
          <h2 id="member-risks-title"><span class="heading-dot" data-tone="warn" aria-hidden="true"></span>需要留意</h2>
        </div>
        <div class="plain-list" style="margin-top: 10px">
          <EmptyState
            v-if="topRisks.length === 0"
            icon="shield"
            title="暂无需要留意的情况"
          />
          <article v-for="risk in topRisks" :key="risk.ruleId" class="card member-risk-row">
            <div class="risk-row">
              <span class="icon-disc" :data-tone="riskLevelTone(risk.level)" aria-hidden="true">
                <AppIcon name="alert" :size="19" />
              </span>
              <div class="risk-body">
                <p class="risk-message">{{ risk.message }}</p>
                <span class="meta-line"><LevelTag kind="risk" :value="risk.level" /></span>
              </div>
            </div>
          </article>
        </div>
      </section>

      <section aria-labelledby="recent-title">
        <div class="section-heading">
          <h2 id="recent-title"><span class="heading-dot" data-tone="info" aria-hidden="true"></span>最近变化</h2>
        </div>
        <ul class="card divided-list event-timeline" style="margin-top: 10px">
          <li v-if="snapshot.recentEvents.length === 0">
            <span class="meta-line">暂无记录</span>
          </li>
          <li
            v-for="event in snapshot.recentEvents"
            :key="event.id"
            :data-unconfirmed="event.confirmationStatus !== 'CONFIRMED'"
          >
            <strong>{{ event.title }}</strong>
            <span class="meta-line">
              {{ eventStatusLabel(event.confirmationStatus) }} · {{ formatDateTime(event.occurredAt) }}
            </span>
          </li>
        </ul>
      </section>
    </template>

    <ListStatusAnnouncer :message="listStatusMessage" />

    <footer class="disclaimer">仅作健康记录与提醒；紧急情况请联系医生或急救服务。</footer>

    <ConfettiBurst ref="confetti" />
  </main>
</template>

<style scoped>
.pull-indicator {
  display: flex;
  align-items: flex-end;
  justify-content: center;
  gap: 8px;
  padding-bottom: 6px;
  overflow: hidden;
  color: var(--c-ink-faint);
  font-size: 0.82rem;
  font-weight: 700;
  margin: -12px 0 -6px;
}
.pull-spin { animation: pull-rotate 0.9s linear infinite; }
@keyframes pull-rotate {
  to { transform: rotate(360deg); }
}

.hero-top {
  display: flex;
  align-items: center;
  gap: 14px;
}
.hero-text { flex: 1; display: grid; gap: 5px; min-width: 0; }
.hero-brand { display: flex; align-items: center; gap: 8px; min-width: 0; }
.hero-brand .hero-eyebrow { margin: 0; }
.risk-row { display: flex; align-items: center; gap: 12px; }
.risk-body { flex: 1; min-width: 0; display: grid; gap: 6px; }
.risk-message { font-weight: 700; line-height: 1.4; }
.done-tasks { margin-top: 12px; }
.done-tasks summary {
  cursor: pointer;
  font-weight: 800;
  color: var(--c-ink-soft);
  min-height: var(--tap);
  display: flex;
  align-items: center;
  padding: 0 4px;
}
.done-tasks ul { margin-top: 8px; }

</style>
