<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'

import { apiClient } from '../api/client'
import type { HealthEvent, ProjectionReplayResult } from '../api/types'
import emptyCorner from '../assets/empty-corner.jpg'
import AppIcon from '../components/AppIcon.vue'
import SkeletonList from '../components/SkeletonList.vue'
import { vReveal } from '../ui/motion'
import {
  createIdempotencyKey,
  formatError,
  pushToast,
  requestOptions,
  selectMember,
  selectedMember,
  session,
} from '../store'
import {
  confirmationLabel,
  eventTone,
  eventTypeLabel,
  formatDateTime,
  memberRoleLabel,
  summarizeEventPayload,
} from '../ui/labels'
import { buildFactsFromTimeline } from '../ui/projection'

interface EventTypeOption {
  value: string
  label: string
  fields: Array<{ key: string; label: string; type: 'text' | 'date' | 'number'; required?: boolean; placeholder?: string }>
}

const EVENT_TYPE_OPTIONS: EventTypeOption[] = [
  {
    value: 'medication_added',
    label: '新增药品',
    fields: [
      { key: 'drug', label: '药品名称', type: 'text', required: true, placeholder: '例如 阿莫西林胶囊' },
      { key: 'ingredient', label: '主要成分', type: 'text', placeholder: '例如 阿莫西林' },
      { key: 'expiry_date', label: '有效期至', type: 'date' },
      { key: 'stock', label: '当前库存（片/粒）', type: 'number' },
    ],
  },
  {
    value: 'allergy_added',
    label: '新增过敏史',
    fields: [{ key: 'allergy', label: '过敏原', type: 'text', required: true, placeholder: '例如 青霉素' }],
  },
  {
    value: 'allergy_removed',
    label: '移除过敏史',
    fields: [{ key: 'allergy', label: '过敏原', type: 'text', required: true }],
  },
  {
    value: 'disease_added',
    label: '新增疾病记录',
    fields: [{ key: 'disease', label: '疾病名称', type: 'text', required: true, placeholder: '例如 高血压' }],
  },
  {
    value: 'disease_resolved',
    label: '疾病痊愈',
    fields: [{ key: 'disease', label: '疾病名称', type: 'text', required: true }],
  },
  {
    value: 'plan_created',
    label: '创建用药计划',
    fields: [
      { key: 'drug', label: '药品名称', type: 'text', required: true },
      { key: 'schedule', label: '服药安排', type: 'text', required: true, placeholder: '例如 每日两次，早晚饭后' },
    ],
  },
  {
    value: 'note_added',
    label: '照护备注',
    fields: [{ key: 'text', label: '备注内容', type: 'text', required: true, placeholder: '例如 今天散步三十分钟' }],
  },
]

const timeline = ref<HealthEvent[]>([])
const loading = ref(false)
const loadError = ref('')
const submitting = ref(false)
const formError = ref('')
const compensatingId = ref<string | null>(null)
const compensationReason = ref('')
const compensationNote = ref('')
const compensationBusy = ref(false)
const replayResult = ref<ProjectionReplayResult | null>(null)
const replaying = ref(false)

const entryDraft = reactive({
  eventType: EVENT_TYPE_OPTIONS[0]!.value,
  values: {} as Record<string, string>,
})

const currentOption = computed(
  () => EVENT_TYPE_OPTIONS.find(option => option.value === entryDraft.eventType) ?? EVENT_TYPE_OPTIONS[0]!,
)

const stateFacts = computed(() => buildFactsFromTimeline(timeline.value))

const orderedTimeline = computed(() => [...timeline.value].reverse())

const TIMELINE_PREVIEW = 8
const showAllTimeline = ref(false)
const visibleTimeline = computed(() =>
  showAllTimeline.value ? orderedTimeline.value : orderedTimeline.value.slice(0, TIMELINE_PREVIEW),
)

const canSubmitEntry = computed(() => {
  if (!session.selectedMemberId || submitting.value) return false
  return currentOption.value.fields
    .filter(field => field.required)
    .every(field => (entryDraft.values[field.key] ?? '').trim().length > 0)
})

async function loadProfile(): Promise<void> {
  const householdId = session.selectedHouseholdId
  const memberId = session.selectedMemberId
  if (!householdId || !memberId) return

  loading.value = true
  loadError.value = ''
  compensatingId.value = null
  replayResult.value = null
  try {
    timeline.value = await apiClient.listMemberTimeline(householdId, memberId, requestOptions.value)
  } catch (cause) {
    timeline.value = []
    loadError.value = formatError(cause)
  } finally {
    loading.value = false
  }
}

function resetEntryValues(): void {
  entryDraft.values = {}
  formError.value = ''
}

async function submitEntry(): Promise<void> {
  const householdId = session.selectedHouseholdId
  const memberId = session.selectedMemberId
  if (!householdId || !memberId || !canSubmitEntry.value) return

  const payload: Record<string, unknown> = {}
  for (const field of currentOption.value.fields) {
    const raw = (entryDraft.values[field.key] ?? '').trim()
    if (!raw) continue
    payload[field.key] = field.type === 'number' ? Number(raw) : raw
  }

  submitting.value = true
  formError.value = ''
  try {
    await apiClient.appendHealthEvent(
      householdId,
      {
        member_id: memberId,
        event_type: entryDraft.eventType,
        confirmation_status: 'CONFIRMED',
        payload,
        evidence: { entry_channel: 'web-manual' },
      },
      { ...requestOptions.value, idempotencyKey: createIdempotencyKey() },
    )
    pushToast('success', `已记录「${currentOption.value.label}」。`)
    resetEntryValues()
    await loadProfile()
  } catch (cause) {
    formError.value = formatError(cause)
  } finally {
    submitting.value = false
  }
}

function startCompensation(event: HealthEvent): void {
  compensatingId.value = compensatingId.value === event.id ? null : event.id
  compensationReason.value = ''
  compensationNote.value = ''
}

async function submitCompensation(event: HealthEvent): Promise<void> {
  const householdId = session.selectedHouseholdId
  const reason = compensationReason.value.trim()
  if (!householdId || !reason || compensationBusy.value) return

  compensationBusy.value = true
  try {
    await apiClient.compensateHealthEvent(
      householdId,
      event.id,
      {
        event_type: 'COMPENSATION',
        payload: {
          original_event_type: event.event_type,
          note: compensationNote.value.trim() || reason,
        },
        reason,
      },
      { ...requestOptions.value, idempotencyKey: createIdempotencyKey() },
    )
    pushToast('success', '补偿更正已记录，原事实保留在历史中。')
    compensatingId.value = null
    await loadProfile()
  } catch (cause) {
    pushToast('error', formatError(cause))
  } finally {
    compensationBusy.value = false
  }
}

async function runReplayCheck(): Promise<void> {
  const householdId = session.selectedHouseholdId
  const memberId = session.selectedMemberId
  if (!householdId || !memberId || replaying.value) return

  replaying.value = true
  try {
    replayResult.value = await apiClient.replayMemberState(
      householdId,
      memberId,
      undefined,
      { ...requestOptions.value, idempotencyKey: createIdempotencyKey() },
    )
    pushToast(
      replayResult.value.consistent_with_online ? 'success' : 'error',
      replayResult.value.consistent_with_online
        ? '重放校验通过：离线重建与在线投影一致。'
        : '重放结果与在线投影不一致，请联系维护者检查事件链。',
    )
  } catch (cause) {
    pushToast('error', formatError(cause))
  } finally {
    replaying.value = false
  }
}

function onMemberChange(event: Event): void {
  selectMember((event.target as HTMLSelectElement).value)
}

watch(
  () => [session.selectedHouseholdId, session.selectedMemberId],
  () => void loadProfile(),
)
watch(() => entryDraft.eventType, resetEntryValues)

onMounted(() => void loadProfile())
</script>

<template>
  <section class="page-hero">
    <div class="card-heading" style="margin-bottom: 0">
      <div>
        <h2 class="hero-greeting">{{ selectedMember?.display_name ?? '成员' }}的健康档案</h2>
        <p class="hero-sub">
          {{ selectedMember ? memberRoleLabel(selectedMember.role) : '' }} ·
          每一条记录都来自已确认的健康事件，字段未授权时不会显示。
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

  <p v-if="loadError" class="notice error" role="alert">
    <AppIcon name="alert" :size="16" />
    {{ loadError }}
  </p>

  <section class="fact-ribbon" aria-label="当前健康事实">
    <div class="fact-group">
      <span class="fact-label"><AppIcon name="pill" :size="14" style="color: var(--pine)" />在用药品</span>
      <template v-if="stateFacts.drugs.length > 0">
        <span v-for="drug in stateFacts.drugs" :key="drug.addedBy" class="pill pine">{{ drug.name }}</span>
      </template>
      <span v-else class="fact-empty">暂无记录</span>
    </div>
    <div class="fact-group">
      <span class="fact-label"><AppIcon name="alert" :size="14" style="color: var(--rose)" />过敏史</span>
      <template v-if="stateFacts.allergies.length > 0">
        <span v-for="item in stateFacts.allergies" :key="item.addedBy" class="pill rose">{{ item.name }}</span>
      </template>
      <span v-else class="fact-empty">暂无记录</span>
    </div>
    <div class="fact-group">
      <span class="fact-label"><AppIcon name="heart" :size="14" style="color: var(--gold)" />关注疾病</span>
      <template v-if="stateFacts.diseases.length > 0">
        <span v-for="item in stateFacts.diseases" :key="item.addedBy" class="pill gold">{{ item.name }}</span>
      </template>
      <span v-else class="fact-empty">暂无记录</span>
    </div>
    <div class="fact-group">
      <span class="fact-label"><AppIcon name="plan" :size="14" style="color: var(--sky)" />用药计划</span>
      <template v-if="stateFacts.plans.length > 0">
        <span v-for="plan in stateFacts.plans" :key="plan.addedBy" class="pill sky">{{ plan.drug }}</span>
      </template>
      <span v-else class="fact-empty">暂无计划</span>
    </div>
  </section>

  <div class="grid-main-side" style="gap: 34px">
    <section aria-label="事件时间线">
      <div class="sec-head">
        <span class="sec-no">01</span>
        <h3>事件时间线</h3>
        <span class="sec-line" />
        <span class="sec-hint">{{ timeline.length }} 条已确认记录</span>
      </div>

      <SkeletonList v-if="loading" :rows="6" />
      <div v-else-if="orderedTimeline.length === 0" class="empty-state">
        <img class="empty-illustration" :src="emptyCorner" alt="" aria-hidden="true" />
        <strong>尚无已确认健康事件</strong>
        <p>可以在右侧手工录入一条事实，或到「视觉扫描」拍摄药盒开始识别。</p>
      </div>
      <ul v-else v-reveal class="timeline">
        <li v-for="event in visibleTimeline" :key="event.id" class="timeline-row">
          <span class="timeline-dot" :class="eventTone(event.event_type)" />
          <div class="timeline-body">
            <div class="timeline-title-row">
              <span class="timeline-event">{{ eventTypeLabel(event.event_type) }}</span>
              <span class="pill" :class="event.confirmation_status === 'CONFIRMED' ? 'pine' : 'gold'">
                {{ confirmationLabel(event.confirmation_status) }}
              </span>
              <span v-if="event.compensates_event_id" class="pill gold">更正记录</span>
            </div>
            <span v-if="summarizeEventPayload(event)" class="timeline-payload">{{ summarizeEventPayload(event) }}</span>
            <span class="timeline-meta">
              {{ formatDateTime(event.created_at) }} · 序号 {{ event.sequence_no }} · 记录人 {{ event.created_by }}
            </span>
            <div v-if="event.event_type !== 'COMPENSATION'" class="row-actions" style="margin-top: 4px">
              <button type="button" class="btn btn-ghost btn-small" @click="startCompensation(event)">
                {{ compensatingId === event.id ? '收起' : '补偿更正' }}
              </button>
            </div>
            <form
              v-if="compensatingId === event.id"
              class="section-stack"
              style="background: var(--glass-card-strong); border: 1px solid var(--glass-border); border-radius: 10px; margin-top: 8px; padding: 13px 14px"
              @submit.prevent="submitCompensation(event)"
            >
              <p class="card-note" style="margin: 0">
                补偿不会删除原记录：系统会追加一条更正事件，并在状态投影中抵销这条事实。
              </p>
              <label class="field">
                更正原因（必填）
                <input v-model="compensationReason" autocomplete="off" required placeholder="例如 录入时药品名称写错" />
              </label>
              <label class="field">
                补充说明（可选）
                <input v-model="compensationNote" autocomplete="off" placeholder="正确内容或其它说明" />
              </label>
              <div class="row-actions">
                <button type="submit" class="btn btn-clay btn-small" :disabled="!compensationReason.trim() || compensationBusy">
                  {{ compensationBusy ? '正在记录' : '确认更正' }}
                </button>
              </div>
            </form>
          </div>
        </li>
      </ul>
      <div v-if="orderedTimeline.length > TIMELINE_PREVIEW" class="more-wrap">
        <button type="button" class="more-btn" :class="{ open: showAllTimeline }" @click="showAllTimeline = !showAllTimeline">
          <AppIcon name="arrow-right" :size="13" />
          {{ showAllTimeline ? '收起时间线' : `展开更早的 ${orderedTimeline.length - TIMELINE_PREVIEW} 条记录` }}
        </button>
      </div>
    </section>

    <div class="section-stack">
      <section class="card">
        <div class="card-heading">
          <div>
            <p class="eyebrow">手工录入</p>
            <h3 class="card-title">补一条健康事实</h3>
          </div>
          <AppIcon name="plus" :size="20" style="color: var(--clay)" />
        </div>
        <form class="section-stack" @submit.prevent="submitEntry">
          <label class="field">
            事实类型
            <select v-model="entryDraft.eventType">
              <option v-for="option in EVENT_TYPE_OPTIONS" :key="option.value" :value="option.value">
                {{ option.label }}
              </option>
            </select>
          </label>
          <label v-for="field in currentOption.fields" :key="field.key" class="field">
            {{ field.label }}{{ field.required ? '' : '（可选）' }}
            <input
              v-model="entryDraft.values[field.key]"
              :type="field.type"
              :required="field.required"
              :placeholder="field.placeholder"
              autocomplete="off"
            />
          </label>
          <p v-if="formError" class="notice error" role="alert">
            <AppIcon name="alert" :size="16" />
            {{ formError }}
          </p>
          <button type="submit" class="btn btn-primary" :disabled="!canSubmitEntry">
            {{ submitting ? '正在记录' : '确认并记录' }}
          </button>
          <p class="text-faint" style="font-size: 12px; line-height: 1.6; margin: 0">
            手工录入的事实以你的身份确认后立即生效，写入不可覆盖的事件链，随时可通过补偿更正。
          </p>
        </form>
      </section>

      <section v-if="stateFacts.plans.length > 0" class="card">
        <div class="card-heading">
          <div>
            <p class="eyebrow">医嘱事实</p>
            <h3 class="card-title">当前用药计划</h3>
          </div>
        </div>
        <ul class="list-plain">
          <li v-for="(plan, index) in stateFacts.plans" :key="index" class="row-card">
            <div class="row-title">
              <AppIcon name="pill" :size="17" style="color: var(--pine)" />
              {{ plan.drug ?? '未命名药品' }}
            </div>
            <p class="row-meta" style="margin: 0">{{ plan.schedule ?? '未填写安排' }}</p>
          </li>
        </ul>
        <p class="card-note">计划内容只读，来自已确认医嘱事实；提醒确认、延期与跳过请到「健康计划」页操作。</p>
      </section>

      <section v-if="stateFacts.caregivers.length > 0" class="card">
        <div class="card-heading">
          <div>
            <p class="eyebrow">照护关系</p>
            <h3 class="card-title">谁在照护</h3>
          </div>
        </div>
        <div class="capability-chips">
          <span v-for="caregiver in stateFacts.caregivers" :key="caregiver" class="pill sky">{{ caregiver }}</span>
        </div>
      </section>

      <section class="card">
        <div class="card-heading">
          <div>
            <p class="eyebrow">数据可靠性</p>
            <h3 class="card-title">状态重放校验</h3>
          </div>
          <AppIcon name="refresh" :size="19" style="color: var(--sky)" />
        </div>
        <p class="card-note" style="margin: -6px 0 12px">
          从不可覆盖的事件链离线重建成员状态，并与在线投影比对哈希，验证「事件是唯一事实源」。
        </p>
        <button type="button" class="btn btn-ghost btn-small" :disabled="replaying" @click="runReplayCheck">
          {{ replaying ? '正在重放' : '运行重放校验' }}
        </button>
        <div v-if="replayResult" class="section-stack" style="gap: 6px; margin-top: 12px">
          <p
            class="notice"
            :class="replayResult.consistent_with_online ? 'ok' : 'error'"
            style="margin: 0"
          >
            <AppIcon :name="replayResult.consistent_with_online ? 'check' : 'alert'" :size="15" />
            {{ replayResult.consistent_with_online ? '重建结果与在线投影一致' : '重建结果与在线投影不一致' }}
          </p>
          <dl class="kv-pairs">
            <div><dt>重放事件数</dt><dd>{{ replayResult.events_replayed }}</dd></div>
            <div><dt>最终序号</dt><dd>{{ replayResult.last_sequence }}</dd></div>
            <div><dt>状态哈希</dt><dd class="mono">{{ replayResult.rebuilt_state_hash.slice(0, 16) }}…</dd></div>
          </dl>
        </div>
      </section>
    </div>
  </div>
</template>
