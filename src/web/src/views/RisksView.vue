<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { ApiClientError, apiClient } from '../api/client'
import type { RiskAlert, RiskDetailResponse, RiskListResponse } from '../api/types'
import AppIcon from '../components/AppIcon.vue'
import SkeletonList from '../components/SkeletonList.vue'
import { riskLevelLabel } from '../risk/riskView'
import {
  createIdempotencyKey,
  formatError,
  onHealthDataRefresh,
  pushToast,
  requestOptions,
  selectMember,
  selectedMember,
  session,
  setView,
} from '../store'
import { confirmationLabel, eventTypeLabel, formatDateTime } from '../ui/labels'

const riskList = ref<RiskListResponse | null>(null)
const riskDetails = ref<Record<string, RiskDetailResponse>>({})
const expandedRuleKey = ref<string | null>(null)
const loading = ref(false)
const evaluating = ref(false)
const loadError = ref('')
const acknowledgementStatus = ref<Record<string, 'idle' | 'saving' | 'success' | 'offline' | 'unauthorized' | 'conflict' | 'error'>>({})
let removeHealthRefreshListener: (() => void) | null = null

const levelTone: Record<string, string> = {
  SEVERE: 'rose',
  WARNING: 'gold',
  INFO: 'sky',
  TIP: 'sage',
}

const groupedAlerts = computed(() => {
  const alerts = riskList.value?.alerts ?? []
  const order = ['SEVERE', 'WARNING', 'INFO', 'TIP']
  return [...alerts].sort(
    (a, b) => (order.indexOf(a.level) === -1 ? 99 : order.indexOf(a.level)) -
      (order.indexOf(b.level) === -1 ? 99 : order.indexOf(b.level)),
  )
})

function alertKey(alert: RiskAlert, index: number): string {
  return `${alert.rule_id}:${index}`
}

function acknowledgementKey(alert: RiskAlert): string {
  return `${alert.rule_id}:${alert.risk_fingerprint}`
}

function acknowledgementLabel(alert: RiskAlert): string {
  const status = acknowledgementStatus.value[acknowledgementKey(alert)]
  if (alert.acknowledgement || status === 'success') return '已知晓'
  if (status === 'saving') return '正在回写…'
  if (status === 'offline') return '离线，未回写'
  if (status === 'unauthorized') return '未授权，未回写'
  if (status === 'conflict') return '风险已变化，请刷新'
  if (status === 'error') return '回写失败，可重试'
  return '我已知晓'
}

function acknowledgementHint(alert: RiskAlert): string {
  if (alert.acknowledgement) {
    return `${alert.acknowledgement.actor_id} · ${formatDateTime(alert.acknowledgement.acknowledged_at)}`
  }
  const status = acknowledgementStatus.value[acknowledgementKey(alert)]
  if (status === 'offline') return '本地 API 不可用，页面没有把本地状态冒充为成功。'
  if (status === 'unauthorized') return '当前身份没有确认该成员风险的授权。'
  if (status === 'conflict') return '规则版本或风险指纹已变化，请刷新后重新查看。'
  if (status === 'error') return '服务端没有确认这次回写，请稍后重试。'
  return '服务端会记录操作者、时间、规则版本和风险指纹。'
}

function jumpToSourceEvent(source: { id?: string }): void {
  if (!source?.id) return
  try {
    sessionStorage.setItem('hct:focus-event-id', source.id)
  } catch {
    /* ignore */
  }
  setView('members')
  pushToast('已打开成员档案；请在时间线中定位来源事件', 'info')
}

async function loadRisks(): Promise<void> {
  const householdId = session.selectedHouseholdId
  const memberId = session.selectedMemberId
  if (!householdId || !memberId) return

  loading.value = true
  loadError.value = ''
  expandedRuleKey.value = null
  try {
    riskList.value = await apiClient.listMemberRisks(householdId, memberId, requestOptions.value)
    riskDetails.value = {}
  } catch (cause) {
    riskList.value = null
    loadError.value = formatError(cause)
  } finally {
    loading.value = false
  }
}

async function reevaluate(): Promise<void> {
  const householdId = session.selectedHouseholdId
  const memberId = session.selectedMemberId
  if (!householdId || !memberId) return

  evaluating.value = true
  try {
    await apiClient.runMemberRules(
      householdId,
      memberId,
      { ...requestOptions.value, idempotencyKey: createIdempotencyKey() },
    )
    await loadRisks()
    pushToast('success', '已按当前事实重新计算规则。')
  } catch (cause) {
    pushToast('error', formatError(cause))
  } finally {
    evaluating.value = false
  }
}

async function toggleDetail(alert: RiskAlert, index: number): Promise<void> {
  const key = alertKey(alert, index)
  if (expandedRuleKey.value === key) {
    expandedRuleKey.value = null
    return
  }
  expandedRuleKey.value = key
  if (riskDetails.value[alert.rule_id]) return

  try {
    const detail = await apiClient.getRiskDetail(
      session.selectedHouseholdId,
      session.selectedMemberId,
      alert.rule_id,
      requestOptions.value,
    )
    riskDetails.value = { ...riskDetails.value, [alert.rule_id]: detail }
  } catch (cause) {
    expandedRuleKey.value = null
    pushToast('error', formatError(cause))
  }
}

async function acknowledge(alert: RiskAlert): Promise<void> {
  if (alert.acknowledgement) return
  const key = acknowledgementKey(alert)
  acknowledgementStatus.value = { ...acknowledgementStatus.value, [key]: 'saving' }
  try {
    const receipt = await apiClient.acknowledgeRisk(
      session.selectedHouseholdId,
      session.selectedMemberId,
      alert.rule_id,
      { rule_version: alert.rule_version, risk_fingerprint: alert.risk_fingerprint },
      { ...requestOptions.value, idempotencyKey: createIdempotencyKey() },
    )
    const update = (item: RiskAlert): RiskAlert => (
      item.rule_id === alert.rule_id && item.risk_fingerprint === alert.risk_fingerprint
        ? { ...item, acknowledgement: receipt }
        : item
    )
    if (riskList.value) riskList.value = { ...riskList.value, alerts: riskList.value.alerts.map(update) }
    for (const [ruleId, detail] of Object.entries(riskDetails.value)) {
      riskDetails.value[ruleId] = { ...detail, alert: update(detail.alert) }
    }
    acknowledgementStatus.value = { ...acknowledgementStatus.value, [key]: 'success' }
  } catch (cause) {
    let status: 'offline' | 'unauthorized' | 'conflict' | 'error' = 'error'
    if (
      cause instanceof ApiClientError &&
      (cause.code === 'DEPENDENCY_UNAVAILABLE' || cause.code === 'REQUEST_TIMEOUT')
    ) status = 'offline'
    else if (cause instanceof ApiClientError && cause.status === 404) status = 'unauthorized'
    else if (cause instanceof ApiClientError && cause.status === 409) status = 'conflict'
    acknowledgementStatus.value = { ...acknowledgementStatus.value, [key]: status }
    pushToast('error', acknowledgementHint({ ...alert, acknowledgement: null }))
  }
}

function onMemberChange(event: Event): void {
  selectMember((event.target as HTMLSelectElement).value)
}

watch(
  () => [session.selectedHouseholdId, session.selectedMemberId],
  () => void loadRisks(),
)

onMounted(() => {
  void loadRisks()
  removeHealthRefreshListener = onHealthDataRefresh(() => void loadRisks())
})

onBeforeUnmount(() => removeHealthRefreshListener?.())
</script>

<template>
  <section class="page-hero">
    <div class="card-heading" style="margin-bottom: 0">
      <div>
        <h2 class="hero-greeting">用药安全中心</h2>
        <p class="hero-sub">
          风险由确定性规则基于已确认事实计算；发现规则资料时请查看依据并进一步确认，系统不会替你做用药判断。
        </p>
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

  <section class="stat-strip">
    <div class="stat-cell rose">
      <span class="cell-cap"><AppIcon name="alert" :size="14" />严重信号</span>
      <span class="cell-num">{{ riskList?.severe_count ?? 0 }}<small>个</small></span>
      <span class="cell-sub">严重告警不受预算压制，单独提醒</span>
    </div>
    <div class="stat-cell gold">
      <span class="cell-cap"><AppIcon name="shield" :size="14" />警告信号</span>
      <span class="cell-num">{{ riskList?.warning_count ?? 0 }}<small>个</small></span>
      <span class="cell-sub">普通提醒合并展示，受每日预算约束</span>
    </div>
    <div class="stat-cell sky">
      <span class="cell-cap"><AppIcon name="info" :size="14" />全部信号</span>
      <span class="cell-num">{{ riskList?.total ?? 0 }}<small>个</small></span>
      <span class="cell-sub">{{ selectedMember?.display_name ?? '当前成员' }} · 已去重</span>
    </div>
  </section>

  <p v-if="riskList && (riskList.suppressed_count ?? 0) > 0" class="notice info" role="status">
    <AppIcon name="shield" :size="15" />
    当前规则 {{ riskList.ruleset_version ?? '未知' }}：已展示 {{ riskList.total }} 条信号；{{ riskList.suppressed_count }} 条普通信号受每日预算 {{ riskList.non_severe_budget ?? 10 }} 条限制，严重信号不受压制。
  </p>

  <section aria-label="风险信号与依据">
    <div class="sec-head">
      <span class="sec-no">01</span>
      <h3>风险信号与依据</h3>
      <span class="sec-line" />
      <button type="button" class="btn btn-ghost btn-small" :disabled="loading || evaluating" @click="reevaluate">
        <AppIcon name="refresh" :size="15" />
        {{ evaluating ? '正在重算' : '重新计算规则' }}
      </button>
    </div>

    <SkeletonList v-if="loading" :rows="3" variant="cards" />
    <p v-else-if="loadError" class="notice error" role="alert">
      <AppIcon name="alert" :size="16" />
      {{ loadError }}
    </p>
    <div v-else-if="groupedAlerts.length === 0" class="empty-state">
      <AppIcon class="empty-art" name="shield" :size="40" />
      <strong>当前没有已确认规则命中</strong>
      <p>录入药品、过敏史等事实后，规则引擎会自动计算过期、重复成分、过敏冲突等风险。</p>
    </div>
    <div v-else class="section-stack" style="gap: 12px">
      <div
        v-for="(alert, index) in groupedAlerts"
        :key="alertKey(alert, index)"
        class="risk-card"
        :class="alert.level"
      >
        <button
          type="button"
          class="risk-toggle"
          :aria-expanded="expandedRuleKey === alertKey(alert, index)"
          @click="toggleDetail(alert, index)"
        >
          <span class="pill" :class="levelTone[alert.level] ?? 'plain'">{{ riskLevelLabel(alert.level) }}</span>
          <span class="risk-message">{{ alert.message }}</span>
          <span class="risk-expand">
            {{ alert.source_event_ids.length }} 条来源事件 ·
            {{ expandedRuleKey === alertKey(alert, index) ? '收起' : '查看依据' }}
          </span>
        </button>
        <div class="risk-actions">
          <button
            type="button"
            class="btn btn-ghost btn-small"
            :disabled="Boolean(alert.acknowledgement) || acknowledgementStatus[acknowledgementKey(alert)] === 'saving'"
            @click="acknowledge(alert)"
          >
            <AppIcon name="check" :size="14" />
            {{ acknowledgementLabel(alert) }}
          </button>
          <span class="risk-ack-hint" :class="{ success: Boolean(alert.acknowledgement) }">
            {{ acknowledgementHint(alert) }}
          </span>
        </div>
        <div v-if="expandedRuleKey === alertKey(alert, index)" class="risk-detail">
          <p class="card-note" style="margin: 0">
            证据仅展示 API 的脱敏摘要，规则 {{ alert.rule_id }}。发现已知资料，需要进一步确认；请勿据此自行停药或改量。
          </p>
          <p v-if="(riskDetails[alert.rule_id]?.source_events ?? []).length === 0" class="text-faint" style="font-size: 13px; margin: 0">
            该信号暂无可展示的来源事件。
          </p>
          <ul v-else class="evidence-list">
            <li v-for="source in riskDetails[alert.rule_id]?.source_events ?? []" :key="source.id" class="evidence-item">
              <strong>{{ eventTypeLabel(source.event_type) }}</strong>
              <span>{{ confirmationLabel(source.confirmation_status) }} · {{ formatDateTime(source.created_at) }}</span>
              <button type="button" class="btn btn-ghost btn-small" @click="jumpToSourceEvent(source)">
                查看源事件
              </button>
            </li>
          </ul>
        </div>
      </div>
    </div>
  </section>
</template>
