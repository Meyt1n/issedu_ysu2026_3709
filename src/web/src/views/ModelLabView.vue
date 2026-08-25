<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'

import { apiClient } from '../api/client'
import type {
  ActiveModelVersion,
  CorrectionDiff,
  HardSample,
  HealthEvent,
  ModelBindingComparison,
  ModelVersionBinding,
} from '../api/types'
import AppIcon from '../components/AppIcon.vue'
import {
  createIdempotencyKey,
  formatError,
  memberNames,
  pushToast,
  requestOptions,
  session,
} from '../store'
import { eventTypeLabel, formatDateTime, summarizeEventPayload } from '../ui/labels'
import { vReveal } from '../ui/motion'

const HARD_SAMPLE_CATEGORIES = [
  { value: 'hard_font', label: '疑难字体' },
  { value: 'hard_layout', label: '复杂版面' },
  { value: 'hard_condition', label: '恶劣拍摄条件' },
  { value: 'hard_similar', label: '易混淆包装' },
  { value: 'hard_foreign', label: '外文包装' },
]

const activeVersion = ref<ActiveModelVersion | null>(null)
const bindings = ref<ModelVersionBinding[]>([])
const samples = ref<HardSample[]>([])
const diffs = ref<CorrectionDiff[]>([])
const memberEvents = ref<HealthEvent[]>([])
const consentBySample = ref<Record<string, string>>({})
const comparisons = ref<Record<string, ModelBindingComparison>>({})
const expandedComparison = ref<string | null>(null)
const loading = ref(false)
const busyId = ref<string | null>(null)
const rollbackReasonById = reactive<Record<string, string>>({})

const bindingDraft = reactive({
  modelId: 'yolo11n-hct203',
  datasetVersion: '',
  fixedSetHash: '',
  comparisonReportHash: '',
})

const sampleDraft = reactive({
  memberId: '',
  sourceEventId: '',
  category: 'hard_similar',
  note: '',
})

const BINDING_PREVIEW = 4
const showAllBindings = ref(false)
const visibleBindings = computed(() =>
  showAllBindings.value ? bindings.value : bindings.value.slice(0, BINDING_PREVIEW),
)

const SAMPLE_PREVIEW = 5
const showAllSamples = ref(false)
const visibleSamples = computed(() =>
  showAllSamples.value ? samples.value : samples.value.slice(0, SAMPLE_PREVIEW),
)

const canCreateBinding = computed(
  () =>
    bindingDraft.modelId.trim().length > 0 &&
    bindingDraft.datasetVersion.trim().length > 0 &&
    bindingDraft.fixedSetHash.trim().length > 0 &&
    !busyId.value,
)

const canCreateSample = computed(
  () => sampleDraft.memberId && sampleDraft.sourceEventId && sampleDraft.category && !busyId.value,
)

const statusTone: Record<string, string> = {
  active: 'pine',
  inactive: 'plain',
  revoked: 'rose',
  pending: 'gold',
  approved: 'pine',
  rejected: 'rose',
}

const statusLabel: Record<string, string> = {
  active: '已发布',
  inactive: '候选',
  revoked: '已回滚',
  pending: '待审核',
  approved: '已入池',
  rejected: '已拒绝',
}

async function loadLab(): Promise<void> {
  loading.value = true
  try {
    const [versionResult, bindingResult, sampleResult, diffResult] = await Promise.allSettled([
      apiClient.getActiveModelVersion(requestOptions.value),
      apiClient.listModelBindings(requestOptions.value),
      apiClient.listHardSamples(session.selectedHouseholdId, requestOptions.value),
      apiClient.listCorrectionDiffs(session.selectedHouseholdId, undefined, requestOptions.value),
    ])
    activeVersion.value = versionResult.status === 'fulfilled' ? versionResult.value : null
    bindings.value = bindingResult.status === 'fulfilled' ? bindingResult.value : []
    samples.value = sampleResult.status === 'fulfilled' ? sampleResult.value : []
    diffs.value = diffResult.status === 'fulfilled' ? diffResult.value : []
    await loadConsents()
  } finally {
    loading.value = false
  }
}

async function loadConsents(): Promise<void> {
  const approved = samples.value.filter(sample => sample.status === 'approved')
  const results = await Promise.allSettled(
    approved.map(sample =>
      apiClient.getTrainingConsent(session.selectedHouseholdId, sample.id, requestOptions.value),
    ),
  )
  const map: Record<string, string> = {}
  approved.forEach((sample, index) => {
    const result = results[index]
    if (result?.status === 'fulfilled' && result.value) {
      map[sample.id] = result.value.status
    }
  })
  consentBySample.value = map
}

async function loadMemberEvents(): Promise<void> {
  if (!sampleDraft.memberId) {
    memberEvents.value = []
    return
  }
  try {
    memberEvents.value = await apiClient.listMemberTimeline(
      session.selectedHouseholdId,
      sampleDraft.memberId,
      requestOptions.value,
    )
  } catch {
    memberEvents.value = []
  }
}

async function createBinding(): Promise<void> {
  if (!canCreateBinding.value) return
  busyId.value = 'create-binding'
  try {
    await apiClient.createModelBinding(
      {
        model_id: bindingDraft.modelId.trim(),
        dataset_version: bindingDraft.datasetVersion.trim(),
        fixed_set_hash: bindingDraft.fixedSetHash.trim(),
        comparison_report_hash: bindingDraft.comparisonReportHash.trim() || undefined,
      },
      { ...requestOptions.value, idempotencyKey: createIdempotencyKey() },
    )
    pushToast('success', '模型版本绑定已登记，当前为候选状态。')
    bindingDraft.datasetVersion = ''
    bindingDraft.fixedSetHash = ''
    bindingDraft.comparisonReportHash = ''
    await loadLab()
  } catch (cause) {
    pushToast('error', formatError(cause))
  } finally {
    busyId.value = null
  }
}

async function activateBinding(binding: ModelVersionBinding): Promise<void> {
  busyId.value = binding.id
  try {
    await apiClient.activateModelBinding(binding.id, session.actorId, requestOptions.value)
    pushToast('success', `模型 ${binding.model_id} 已发布，同模型旧版本自动转为候选。`)
    await loadLab()
  } catch (cause) {
    pushToast('error', formatError(cause))
  } finally {
    busyId.value = null
  }
}

async function rollbackBinding(binding: ModelVersionBinding): Promise<void> {
  const reason = (rollbackReasonById[binding.id] ?? '').trim()
  if (!reason) {
    pushToast('error', '回滚前请填写原因，方便审计追溯。')
    return
  }
  busyId.value = binding.id
  try {
    await apiClient.rollbackModelBinding(binding.id, reason, undefined, requestOptions.value)
    pushToast('info', '已回滚；系统尝试自动恢复上一个候选版本。')
    rollbackReasonById[binding.id] = ''
    await loadLab()
  } catch (cause) {
    pushToast('error', formatError(cause))
  } finally {
    busyId.value = null
  }
}

async function toggleComparison(binding: ModelVersionBinding): Promise<void> {
  if (expandedComparison.value === binding.id) {
    expandedComparison.value = null
    return
  }
  expandedComparison.value = binding.id
  if (comparisons.value[binding.id]) return
  try {
    const detail = await apiClient.getModelBindingComparison(binding.id, requestOptions.value)
    comparisons.value = { ...comparisons.value, [binding.id]: detail }
  } catch (cause) {
    expandedComparison.value = null
    pushToast('error', formatError(cause))
  }
}

async function createSample(): Promise<void> {
  if (!canCreateSample.value) return
  busyId.value = 'create-sample'
  try {
    await apiClient.createHardSample(
      session.selectedHouseholdId,
      {
        source_event_id: sampleDraft.sourceEventId,
        member_id: sampleDraft.memberId,
        category: sampleDraft.category,
        note: sampleDraft.note.trim(),
      },
      { ...requestOptions.value, idempotencyKey: createIdempotencyKey() },
    )
    pushToast('success', '困难样本已提交，待审核后进入训练候选池。')
    sampleDraft.sourceEventId = ''
    sampleDraft.note = ''
    await loadLab()
  } catch (cause) {
    pushToast('error', formatError(cause))
  } finally {
    busyId.value = null
  }
}

async function reviewSample(sample: HardSample, status: 'approved' | 'rejected'): Promise<void> {
  busyId.value = sample.id
  try {
    await apiClient.updateHardSample(
      session.selectedHouseholdId,
      sample.id,
      status,
      undefined,
      requestOptions.value,
    )
    pushToast('success', status === 'approved' ? '样本已入池。' : '样本已拒绝。')
    await loadLab()
  } catch (cause) {
    pushToast('error', formatError(cause))
  } finally {
    busyId.value = null
  }
}

async function toggleConsent(sample: HardSample): Promise<void> {
  busyId.value = sample.id
  const granted = consentBySample.value[sample.id] === 'granted'
  try {
    if (granted) {
      await apiClient.revokeTrainingConsent(
        session.selectedHouseholdId,
        sample.id,
        '家庭撤回训练同意',
        requestOptions.value,
      )
      pushToast('info', '训练同意已撤回，该样本不再进入训练导出。')
    } else {
      await apiClient.grantTrainingConsent(
        session.selectedHouseholdId,
        sample.id,
        'internal',
        requestOptions.value,
      )
      pushToast('success', '已单独授予训练同意（与健康事实确认相互独立）。')
    }
    await loadConsents()
  } catch (cause) {
    pushToast('error', formatError(cause))
  } finally {
    busyId.value = null
  }
}

watch(() => sampleDraft.memberId, () => void loadMemberEvents())
watch(
  () => session.selectedHouseholdId,
  () => {
    sampleDraft.memberId = session.members[0]?.id ?? ''
    void loadLab()
  },
)

onMounted(() => {
  sampleDraft.memberId = session.members[0]?.id ?? ''
  void loadLab()
  void loadMemberEvents()
})
</script>

<template>
  <section class="page-hero">
    <div class="card-heading" style="margin-bottom: 0">
      <div>
        <h2 class="hero-greeting gradient-text">模型实验室</h2>
        <p class="hero-sub">
          面向管理员与研发：版本绑定、固定集对照、发布与回滚、困难样本池与训练同意。此页不展示任何家庭健康正文。
        </p>
      </div>
      <span class="pill plain">仅研发用途</span>
    </div>
  </section>

  <div class="release-band">
    <div style="display: grid; gap: 3px">
      <span class="eyebrow" style="margin: 0">当前生效的视觉模型</span>
      <strong style="font-size: 19px">{{ activeVersion?.active_model_version ?? '未知' }}</strong>
    </div>
    <span class="pill" :class="activeVersion?.source === 'binding' ? 'pine' : 'gold'">
      {{ activeVersion?.source === 'binding' ? '来自已发布绑定' : '来自配置回退（无已发布绑定）' }}
    </span>
  </div>

  <div class="grid-main-side">
    <section class="card">
      <div class="card-heading">
        <div>
          <p class="eyebrow">发布管理</p>
          <h3 class="card-title">模型版本绑定</h3>
        </div>
        <button type="button" class="btn btn-ghost btn-small" :disabled="loading" @click="loadLab">
          <AppIcon name="refresh" :size="15" />
          刷新
        </button>
      </div>

      <div v-if="loading" class="inline-loading">
        <span class="loading-dots"><span /><span /><span /></span>
        正在读取版本登记
      </div>
      <div v-else-if="bindings.length === 0" class="empty-state">
        <AppIcon class="empty-art" name="sparkle" :size="38" />
        <strong>暂无已登记的模型版本</strong>
        <p>在右侧登记一个版本绑定：模型、数据集与固定评估集三者绑定后才能发布。</p>
      </div>
      <ul v-else v-reveal class="list-plain">
        <li v-for="binding in visibleBindings" :key="binding.id" class="row-card">
          <div class="row-top">
            <span class="row-title">
              {{ binding.model_id }}
              <span class="pill" :class="statusTone[binding.release_status] ?? 'plain'">
                {{ statusLabel[binding.release_status] ?? binding.release_status }}
              </span>
            </span>
            <span class="text-faint" style="font-size: 12.5px">{{ formatDateTime(binding.created_at) }}</span>
          </div>
          <p class="row-meta mono" style="margin: 0">
            数据集 {{ binding.dataset_version }} · 固定集 {{ binding.fixed_set_hash.slice(0, 12) }}…
            {{ binding.comparison_report_hash ? ` · 对照报告 ${binding.comparison_report_hash.slice(0, 12)}…` : ' · 缺少对照报告' }}
          </p>
          <p v-if="binding.approved_by" class="row-meta" style="margin: 0">
            发布人 {{ binding.approved_by }} · {{ formatDateTime(binding.approved_at) }}
            {{ binding.revoked_by ? ` · 回滚人 ${binding.revoked_by}` : '' }}
          </p>
          <div class="row-actions">
            <button
              v-if="binding.release_status === 'inactive'"
              type="button"
              class="btn btn-primary btn-small"
              :disabled="busyId === binding.id"
              @click="activateBinding(binding)"
            >
              发布此版本
            </button>
            <button type="button" class="btn btn-ghost btn-small" @click="toggleComparison(binding)">
              {{ expandedComparison === binding.id ? '收起对照' : '固定集对照' }}
            </button>
          </div>
          <div
            v-if="binding.release_status === 'active'"
            class="row-actions"
            style="align-items: flex-end"
          >
            <label class="field" style="flex: 1">
              回滚原因
              <input
                v-model="rollbackReasonById[binding.id]"
                autocomplete="off"
                placeholder="例如 固定集回归超过安全阈值"
              />
            </label>
            <button
              type="button"
              class="btn btn-danger btn-small"
              :disabled="busyId === binding.id"
              @click="rollbackBinding(binding)"
            >
              回滚
            </button>
          </div>
          <div
            v-if="expandedComparison === binding.id && comparisons[binding.id]"
            class="section-stack"
            style="border-top: 1px dashed var(--line); gap: 6px; padding-top: 10px"
          >
            <dl class="kv-pairs">
              <div><dt>模型</dt><dd class="mono">{{ comparisons[binding.id]!.model_id }}</dd></div>
              <div><dt>数据集版本</dt><dd class="mono">{{ comparisons[binding.id]!.dataset_version }}</dd></div>
              <div><dt>固定集哈希</dt><dd class="mono">{{ comparisons[binding.id]!.fixed_set_hash }}</dd></div>
              <div><dt>对照报告</dt><dd class="mono">{{ comparisons[binding.id]!.comparison_report_hash ?? '未登记' }}</dd></div>
              <div><dt>安全阈值</dt><dd class="mono">{{ JSON.stringify(comparisons[binding.id]!.safety_thresholds) }}</dd></div>
            </dl>
          </div>
        </li>
      </ul>
      <div v-if="bindings.length > BINDING_PREVIEW" class="more-wrap">
        <button type="button" class="more-btn" :class="{ open: showAllBindings }" @click="showAllBindings = !showAllBindings">
          <AppIcon name="arrow-right" :size="13" />
          {{ showAllBindings ? '收起版本' : `展开更早的 ${bindings.length - BINDING_PREVIEW} 个版本` }}
        </button>
      </div>
    </section>

    <section class="card" style="align-self: start">
      <div class="card-heading">
        <div>
          <p class="eyebrow">登记新版本</p>
          <h3 class="card-title">创建版本绑定</h3>
        </div>
      </div>
      <form class="section-stack" @submit.prevent="createBinding">
        <label class="field">
          模型标识
          <input v-model="bindingDraft.modelId" autocomplete="off" required placeholder="例如 yolo11n-hct203-v2" />
        </label>
        <label class="field">
          数据集版本
          <input v-model="bindingDraft.datasetVersion" autocomplete="off" required placeholder="例如 hct-201-dataset-v2" />
        </label>
        <label class="field">
          固定评估集哈希
          <input v-model="bindingDraft.fixedSetHash" autocomplete="off" required placeholder="固定集 SHA-256" class="mono" />
        </label>
        <label class="field">
          对照报告哈希（发布前必填）
          <input v-model="bindingDraft.comparisonReportHash" autocomplete="off" placeholder="V1/V2 对照报告 SHA-256" class="mono" />
          <small>没有对照报告的版本可以登记为候选，但默认安全阈值会阻止其发布。</small>
        </label>
        <button type="submit" class="btn btn-clay" :disabled="!canCreateBinding">
          {{ busyId === 'create-binding' ? '正在登记' : '登记为候选版本' }}
        </button>
      </form>
    </section>
  </div>

  <section class="card">
    <div class="card-heading">
      <div>
        <p class="eyebrow">数据改进</p>
        <h3 class="card-title">困难样本池与训练同意</h3>
      </div>
      <span class="pill clay">{{ samples.filter(s => s.status === 'pending').length }} 个待审核</span>
    </div>

    <div class="grid-main-side" style="gap: 18px">
      <div class="section-stack">
        <div v-if="samples.length === 0" class="empty-state">
          <AppIcon class="empty-art" name="pill" :size="36" />
          <strong>困难样本池为空</strong>
          <p>把识别困难的事件标注为困难样本，审核入池并单独获得训练同意后，才能进入 V2 训练导出。</p>
        </div>
        <ul v-else class="list-plain">
          <li v-for="sample in visibleSamples" :key="sample.id" class="row-card">
            <div class="row-top">
              <span class="row-title">
                {{ HARD_SAMPLE_CATEGORIES.find(c => c.value === sample.category)?.label ?? sample.category }}
                <span class="pill" :class="statusTone[sample.status] ?? 'plain'">
                  {{ statusLabel[sample.status] ?? sample.status }}
                </span>
                <span
                  v-if="sample.status === 'approved'"
                  class="pill"
                  :class="consentBySample[sample.id] === 'granted' ? 'pine' : 'plain'"
                >
                  {{ consentBySample[sample.id] === 'granted' ? '已同意训练' : '未同意训练' }}
                </span>
              </span>
              <span class="text-faint" style="font-size: 12.5px">{{ formatDateTime(sample.created_at) }}</span>
            </div>
            <p class="row-meta" style="margin: 0">
              成员 {{ memberNames.get(sample.member_id) ?? sample.member_id.slice(0, 8) }} ·
              来源事件 {{ sample.source_event_id.slice(0, 8) }}…
              {{ sample.note ? ` · ${sample.note}` : '' }}
            </p>
            <div class="row-actions">
              <template v-if="sample.status === 'pending'">
                <button type="button" class="btn btn-primary btn-small" :disabled="busyId === sample.id" @click="reviewSample(sample, 'approved')">
                  审核入池
                </button>
                <button type="button" class="btn btn-danger btn-small" :disabled="busyId === sample.id" @click="reviewSample(sample, 'rejected')">
                  拒绝
                </button>
              </template>
              <button
                v-else-if="sample.status === 'approved'"
                type="button"
                class="btn btn-ghost btn-small"
                :disabled="busyId === sample.id"
                @click="toggleConsent(sample)"
              >
                {{ consentBySample[sample.id] === 'granted' ? '撤回训练同意' : '授予训练同意' }}
              </button>
            </div>
          </li>
        </ul>
        <div v-if="samples.length > SAMPLE_PREVIEW" class="more-wrap">
          <button type="button" class="more-btn" :class="{ open: showAllSamples }" @click="showAllSamples = !showAllSamples">
            <AppIcon name="arrow-right" :size="13" />
            {{ showAllSamples ? '收起样本' : `展开更多 ${samples.length - SAMPLE_PREVIEW} 个样本` }}
          </button>
        </div>
      </div>

      <form class="section-stack" style="align-self: start" @submit.prevent="createSample">
        <p class="eyebrow" style="margin: 0">标注新困难样本</p>
        <label class="field">
          成员
          <select v-model="sampleDraft.memberId" required>
            <option v-for="member in session.members" :key="member.id" :value="member.id">
              {{ member.display_name }}
            </option>
          </select>
        </label>
        <label class="field">
          来源事件
          <select v-model="sampleDraft.sourceEventId" required>
            <option value="" disabled>选择一条已确认事件</option>
            <option v-for="event in memberEvents" :key="event.id" :value="event.id">
              {{ eventTypeLabel(event.event_type) }} · {{ summarizeEventPayload(event).slice(0, 24) || event.id.slice(0, 8) }}
            </option>
          </select>
        </label>
        <label class="field">
          困难类别
          <select v-model="sampleDraft.category" required>
            <option v-for="category in HARD_SAMPLE_CATEGORIES" :key="category.value" :value="category.value">
              {{ category.label }}
            </option>
          </select>
        </label>
        <label class="field">
          备注（可选）
          <input v-model="sampleDraft.note" autocomplete="off" placeholder="例如 反光导致批号无法识别" />
        </label>
        <button type="submit" class="btn btn-clay btn-small" :disabled="!canCreateSample">
          {{ busyId === 'create-sample' ? '正在提交' : '提交待审核' }}
        </button>
        <p class="text-faint" style="font-size: 12px; line-height: 1.6; margin: 0">
          训练同意与健康事实确认相互独立、可单独撤回；撤回后样本不再出现在新的训练导出中。
        </p>
      </form>
    </div>
  </section>

  <section v-if="diffs.length > 0" class="card">
    <div class="card-heading">
      <div>
        <p class="eyebrow">修正档案</p>
        <h3 class="card-title">字段级修正差异（before → after）</h3>
      </div>
      <span class="pill plain">{{ diffs.length }} 条</span>
    </div>
    <ul class="list-plain">
      <li v-for="diff in diffs.slice(0, 10)" :key="diff.id" class="row-card">
        <div class="row-top">
          <span class="row-title mono">{{ diff.field_path }}</span>
          <span class="text-faint" style="font-size: 12.5px">{{ formatDateTime(diff.created_at) }}</span>
        </div>
        <p class="row-meta" style="margin: 0">
          <span class="mono" style="text-decoration: line-through">{{ JSON.stringify(diff.before_value) }}</span>
          →
          <strong class="mono">{{ JSON.stringify(diff.after_value) }}</strong>
        </p>
        <p class="row-meta" style="margin: 0">原因：{{ diff.reason }} · 操作人 {{ diff.operator_actor_id }}</p>
      </li>
    </ul>
  </section>
</template>
