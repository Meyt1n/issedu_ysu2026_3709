<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import AppIcon from '@/components/AppIcon.vue'
import ConfettiBurst from '@/components/ConfettiBurst.vue'
import EmptyState from '@/components/EmptyState.vue'
import LevelTag from '@/components/LevelTag.vue'
import PrivacyBadge from '@/components/PrivacyBadge.vue'
import ProgressRing from '@/components/ProgressRing.vue'
import SkeletonCard from '@/components/SkeletonCard.vue'
import TaskCard from '@/components/TaskCard.vue'
import TrendChart from '@/components/TrendChart.vue'
import { useCountUp } from '@/composables/useCountUp'
import { usePullToRefresh } from '@/composables/usePullToRefresh'
import { createSpeaker, useSpeech } from '@/composables/useSpeech'
import { showToast } from '@/composables/useToast'
import { activeProvider } from '@/data'
import { eventStatusLabel, riskLevelLabel, riskLevelTone, taskLevelLabel } from '@/data/labels'
import type { MemberSummary, TaskAction, TaskActionPayload, TodaySnapshot, TrendPoint } from '@/data/types'
import { useA11y } from '@/stores/accessibility'
import { useSession } from '@/stores/session'
import { tapFeedback } from '@/utils/haptics'
import { formatDateTime, greetingByHour } from '@/utils/format'

const WEEKDAYS = ['日', '一', '二', '三', '四', '五', '六']

const { session, updateSession } = useSession()
const { settings } = useA11y()
const speech = useSpeech()
const manualSpeaker = createSpeaker(() => true)

const members = ref<MemberSummary[]>([])
const snapshot = ref<TodaySnapshot | null>(null)
const trend = ref<TrendPoint[]>([])
const loading = ref(true)
const error = ref('')
const actionError = ref('')
const busyTaskId = ref('')
const announced = ref(false)
const confetti = ref<InstanceType<typeof ConfettiBurst> | null>(null)

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

const pendingTasks = computed(
  () => snapshot.value?.tasks.filter(t => t.status === 'PENDING' || t.status === 'DEFERRED') ?? [],
)
const doneTasks = computed(
  () => snapshot.value?.tasks.filter(t => t.status !== 'PENDING' && t.status !== 'DEFERRED') ?? [],
)
const topRisks = computed(() => (snapshot.value?.risks ?? []).slice(0, 3))

const pendingCount = useCountUp(() => pendingTasks.value.length)
const riskCount = useCountUp(() => snapshot.value?.risks.length ?? 0)
const recentCount = useCountUp(() => snapshot.value?.recentEvents.length ?? 0)

function summaryText(): string {
  if (!snapshot.value) return ''
  const name = currentMember.value?.name ?? '当前成员'
  const parts = [`${greeting.value}。${name}今天有 ${pendingTasks.value.length} 项照护任务待处理`]
  const risks = snapshot.value.risks
  if (risks.length > 0) {
    const first = risks[0]!
    parts.push(`${risks.length} 条风险提醒需要关注，最高等级：${riskLevelLabel(first.level)}，${first.message}`)
  } else {
    parts.push('暂无待关注的风险提醒')
  }
  return `${parts.join('；')}。`
}

async function loadMembers(): Promise<void> {
  members.value = await activeProvider().listMembers()
  const exists = members.value.some(m => m.id === session.currentMemberId)
  if (!exists) {
    const preferred = members.value.find(m => m.role === 'DEPENDENT') ?? members.value[0]
    updateSession({ currentMemberId: preferred?.id ?? '' })
  }
}

async function loadSnapshot(): Promise<void> {
  if (!session.currentMemberId) {
    snapshot.value = null
    trend.value = []
    return
  }
  snapshot.value = await activeProvider().getTodaySnapshot(session.currentMemberId)
  activeProvider()
    .getWeeklyTrend(session.currentMemberId)
    .then(points => {
      trend.value = points
    })
    .catch(() => {
      trend.value = []
    })
  if (!announced.value && settings.voiceBroadcast) {
    announced.value = true
    speech.speak(summaryText())
  }
}

async function reload(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    await loadMembers()
    await loadSnapshot()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '加载失败，请稍后重试'
    snapshot.value = null
  } finally {
    loading.value = false
  }
}

async function onMemberChange(): Promise<void> {
  updateSession({ currentMemberId: session.currentMemberId })
  loading.value = true
  error.value = ''
  actionError.value = ''
  try {
    await loadSnapshot()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '加载失败，请稍后重试'
  } finally {
    loading.value = false
  }
}

async function onTaskAction(taskId: string, action: TaskAction, payload: TaskActionPayload): Promise<void> {
  busyTaskId.value = taskId
  actionError.value = ''
  const hadPending = pendingTasks.value.length
  try {
    const task = await activeProvider().submitTaskAction(taskId, action, payload)
    const label = action === 'confirm' ? '已确认' : action === 'defer' ? '已延期' : '已记录跳过'
    tapFeedback(action === 'confirm' ? [12, 60, 18] : 12)
    showToast(`${label}：${task.title}`, 'success')
    speech.speak(`${label}：${task.title}`)
    await loadSnapshot()
    // 最后一项任务处理完：彩带庆祝 + 语音鼓励。
    if (hadPending === 1 && pendingTasks.value.length === 0 && doneTasks.value.length > 0) {
      confetti.value?.fire()
      speech.speak('今日照护任务全部完成，辛苦了！')
    }
  } catch (cause) {
    actionError.value = cause instanceof Error ? cause.message : '操作失败，请稍后重试'
  } finally {
    busyTaskId.value = ''
  }
}

function speakSummary(): void {
  manualSpeaker.speak(summaryText())
}

watch(
  () => session.dataMode,
  () => {
    announced.value = true
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
          <p class="hero-eyebrow">家健镜 · 随身照护</p>
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
      <button type="button" class="btn btn-ghost" @click="speakSummary">
        <AppIcon name="sound" :size="18" />
        听一遍今日安排
      </button>
    </section>

    <PrivacyBadge />

    <label class="field">
      当前成员
      <select v-model="session.currentMemberId" :disabled="loading" @change="onMemberChange">
        <option v-for="member in members" :key="member.id" :value="member.id">
          {{ member.name }}（{{ member.relation }}）
        </option>
      </select>
    </label>

    <p v-if="error" class="notice" data-tone="error" role="alert">{{ error }}</p>
    <p v-if="actionError" class="notice" data-tone="error" role="alert">{{ actionError }}</p>

    <div v-if="loading" class="plain-list" aria-label="正在加载" aria-live="polite">
      <SkeletonCard />
      <SkeletonCard />
      <SkeletonCard :disc="false" />
    </div>

    <template v-else-if="snapshot">
      <section aria-labelledby="tasks-title">
        <div class="section-heading">
          <h2 id="tasks-title"><span class="heading-dot" aria-hidden="true"></span>今日照护任务</h2>
          <span class="meta-line">{{ pendingTasks.length }} 项待处理</span>
        </div>
        <div class="plain-list" style="margin-top: 10px">
          <EmptyState
            v-if="pendingTasks.length === 0"
            icon="check"
            title="今日任务都处理完了"
            hint="新的提醒会按等级出现在这里"
          />
          <TaskCard
            v-for="task in pendingTasks"
            :key="task.id"
            :task="task"
            :busy="busyTaskId === task.id"
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

      <section v-if="trend.length > 0" aria-labelledby="trend-title">
        <div class="section-heading">
          <h2 id="trend-title"><span class="heading-dot" data-tone="accent" aria-hidden="true"></span>近 7 天完成情况</h2>
        </div>
        <div class="card" style="margin-top: 10px">
          <TrendChart :points="trend" />
          <p class="meta-line">柱高为当日完成比例；琥珀色为今天。数据来自计划确认事件。</p>
        </div>
      </section>

      <section aria-labelledby="risks-title">
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

      <section aria-labelledby="recent-title">
        <div class="section-heading">
          <h2 id="recent-title"><span class="heading-dot" data-tone="info" aria-hidden="true"></span>最近变化</h2>
        </div>
        <ul class="card divided-list event-timeline" style="margin-top: 10px">
          <li v-if="snapshot.recentEvents.length === 0">
            <span class="meta-line">尚无已确认健康事件，可拍摄药盒或在网页端手工录入一条事实。</span>
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

    <footer class="disclaimer">
      教学演示，不用于诊断或治疗。系统不改变任何用药决定；紧急情况请联系医生或当地急救服务。
    </footer>

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
