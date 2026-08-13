<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import { apiClient } from '../api/client'
import type { RiskAlert, RiskDetailResponse, RiskListResponse } from '../api/types'
import AppIcon from '../components/AppIcon.vue'
import SkeletonList from '../components/SkeletonList.vue'
import { riskLevelLabel } from '../risk/riskView'
import {
  createIdempotencyKey,
  formatError,
  pushToast,
  requestOptions,
  selectMember,
  selectedMember,
  session,
} from '../store'
import { confirmationLabel, eventTypeLabel, formatDateTime } from '../ui/labels'

const riskList = ref<RiskListResponse | null>(null)
const riskDetails = ref<Record<string, RiskDetailResponse>>({})
const expandedRuleKey = ref<string | null>(null)
const loading = ref(false)
const evaluating = ref(false)
const loadError = ref('')

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

function onMemberChange(event: Event): void {
  selectMember((event.target as HTMLSelectElement).value)
}

watch(
  () => [session.selectedHouseholdId, session.selectedMemberId],
  () => void loadRisks(),
)

onMounted(() => void loadRisks())
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
            </li>
          </ul>
        </div>
      </div>
    </div>
  </section>
</template>
