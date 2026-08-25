<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'

import { apiClient } from '../api/client'
import type { ReviewCandidate, ReviewTask, VisionTask } from '../api/types'
import AppIcon from '../components/AppIcon.vue'
import VisionResultViewer from '../components/VisionResultViewer.vue'
import {
  createIdempotencyKey,
  formatError,
  pushToast,
  refreshPendingReviewCount,
  requestHealthDataRefresh,
  requestOptions,
  selectMember,
  session,
} from '../store'
import {
  formatDateTime,
  fusionStatusLabel,
  reviewStatusLabel,
} from '../ui/labels'
import { vReveal } from '../ui/motion'

type EnrichedReviewTask = ReviewTask & { memberName: string }

const tasks = ref<EnrichedReviewTask[]>([])
const loading = ref(false)
const loadError = ref('')
const busyTaskId = ref<string | null>(null)
const showAllMembers = ref(false)
const expandedMetaId = ref<string | null>(null)

const panel = reactive({
  taskId: '',
  mode: 'confirm' as 'confirm' | 'correct' | 'skip',
  selectedIndex: 0,
  note: '',
  correctDrug: '',
  correctDosage: '',
  correctFrequency: '',
  skipReason: '',
})

const pendingTasks = computed(() => tasks.value.filter(task => task.status === 'PENDING_REVIEW'))
const settledTasks = computed(() => tasks.value.filter(task => task.status !== 'PENDING_REVIEW'))

const SETTLED_PREVIEW = 4
const showAllSettled = ref(false)
const visibleSettled = computed(() =>
  showAllSettled.value ? settledTasks.value : settledTasks.value.slice(0, SETTLED_PREVIEW),
)

function fusionTone(status: string | null): string {
  if (status === 'MATCHED' || status === 'READY_FOR_FUSION') return 'pine'
  if (status === 'CONFLICT') return 'rose'
  if (status === 'UNKNOWN') return 'plain'
  return 'gold'
}

function statusTone(status: string): string {
  if (status === 'CONFIRMED') return 'pine'
  if (status === 'CORRECTED') return 'gold'
  if (status === 'SKIPPED') return 'plain'
  return 'clay'
}

function interactionSummary(candidate: ReviewCandidate): string {
  return (candidate.interaction_warnings ?? []).map(item => item.message).join('；')
}

function primaryDrugName(task: ReviewTask): string {
  return task.candidates[0]?.drug_name?.trim() || '待确认药品'
}

function candidateLine(candidate: ReviewCandidate): string {
  const parts: string[] = []
  if (candidate.dosage) parts.push(`剂量 ${candidate.dosage}`)
  if (candidate.frequency) parts.push(`频次 ${candidate.frequency}`)
  if (candidate.confidence != null) {
    parts.push(`证据置信度 ${(candidate.confidence * 100).toFixed(0)}%（仍需人工确认）`)
  }
  return parts.join(' · ')
}

function settledDrugLabel(task: EnrichedReviewTask): string {
  if (task.status === 'CORRECTED') return task.manual_payload?.drug_name as string ?? '未记录'
  if (task.status === 'CONFIRMED') return task.selected_candidate?.drug_name as string ?? primaryDrugName(task)
  return '已跳过'
}

// 原始证据（原图 + 定位框）缓存，键为 vision_task_id
const evidenceOpenId = ref<string | null>(null)
const visionTasks = ref<Record<string, VisionTask>>({})
const imageUrls = ref<Record<string, string>>({})
const evidenceLoadingId = ref<string | null>(null)

async function loadEvidence(visionTaskId: string): Promise<void> {
  if (!visionTasks.value[visionTaskId]) {
    const vision = await apiClient.getVisionTask(visionTaskId, requestOptions.value)
    visionTasks.value = { ...visionTasks.value, [visionTaskId]: vision }
  }
  if (!imageUrls.value[visionTaskId]) {
    const fileId = visionTasks.value[visionTaskId]?.file_id
    if (fileId) {
      const blob = await apiClient.fetchFileBlob(fileId, requestOptions.value)
      imageUrls.value = { ...imageUrls.value, [visionTaskId]: URL.createObjectURL(blob) }
    }
  }
}

async function preloadEvidence(): Promise<void> {
  const targets = pendingTasks.value.slice(0, 8)
  await Promise.allSettled(targets.map(task => loadEvidence(task.vision_task_id)))
}

async function toggleEvidence(task: ReviewTask): Promise<void> {
  if (evidenceOpenId.value === task.id) {
    evidenceOpenId.value = null
    return
  }
  evidenceOpenId.value = task.id
  evidenceLoadingId.value = task.id
  try {
    await loadEvidence(task.vision_task_id)
  } catch {
    // 原图或识别详情不可用时保持候选列表可操作
  } finally {
    evidenceLoadingId.value = null
  }
}

function toggleMeta(taskId: string): void {
  expandedMetaId.value = expandedMetaId.value === taskId ? null : taskId
}

onBeforeUnmount(() => {
  for (const url of Object.values(imageUrls.value)) URL.revokeObjectURL(url)
})

async function loadTasks(): Promise<void> {
  const householdId = session.selectedHouseholdId
  if (!householdId) return

  loading.value = true
  loadError.value = ''
  panel.taskId = ''
  try {
    if (showAllMembers.value) {
      const results = await Promise.allSettled(
        session.members.map(async member => {
          const memberTasks = await apiClient.listReviewTasks(
            householdId,
            member.id,
            requestOptions.value,
          )
          return memberTasks.map(task => ({ ...task, memberName: member.display_name }))
        }),
      )
      tasks.value = results.flatMap(result =>
        result.status === 'fulfilled' ? result.value : [],
      )
    } else {
      const memberId = session.selectedMemberId
      if (!memberId) {
        tasks.value = []
        return
      }
      const memberName = session.members.find(member => member.id === memberId)?.display_name ?? '成员'
      const memberTasks = await apiClient.listReviewTasks(householdId, memberId, requestOptions.value)
      tasks.value = memberTasks.map(task => ({ ...task, memberName }))
    }
    void preloadEvidence()
  } catch (cause) {
    tasks.value = []
    loadError.value = formatError(cause)
  } finally {
    loading.value = false
  }
}

function openPanel(task: ReviewTask, mode: 'confirm' | 'correct' | 'skip'): void {
  if (panel.taskId === task.id && panel.mode === mode) {
    panel.taskId = ''
    return
  }
  panel.taskId = task.id
  panel.mode = mode
  panel.selectedIndex = 0
  panel.note = ''
  const first = task.candidates[0] ?? {}
  panel.correctDrug = String(first.drug_name ?? '')
  panel.correctDosage = String(first.dosage ?? '')
  panel.correctFrequency = String(first.frequency ?? '')
  panel.skipReason = ''
}

async function submitPanel(task: ReviewTask): Promise<void> {
  const householdId = session.selectedHouseholdId
  if (!householdId || busyTaskId.value) return

  busyTaskId.value = task.id
  const options = { ...requestOptions.value, idempotencyKey: createIdempotencyKey() }
  try {
    if (panel.mode === 'confirm') {
      await apiClient.confirmReviewTask(
        householdId,
        task.id,
        {
          expected_version: task.version,
          selected_index: panel.selectedIndex,
          confirmation_note: panel.note.trim() || null,
        },
        options,
      )
      pushToast('success', `${primaryDrugName(task)} 已确认，健康事件已入档。`)
    } else if (panel.mode === 'correct') {
      if (!panel.correctDrug.trim()) {
        pushToast('error', '请填写修正后的药品名称。')
        return
      }
      await apiClient.correctReviewTask(
        householdId,
        task.id,
        {
          expected_version: task.version,
          manual_payload: {
            drug_name: panel.correctDrug.trim(),
            dosage: panel.correctDosage.trim() || null,
            frequency: panel.correctFrequency.trim() || null,
          },
          correction_note: panel.note.trim() || null,
        },
        options,
      )
      pushToast('success', '人工修正已入档，before/after 已留痕。')
    } else {
      await apiClient.skipReviewTask(
        householdId,
        task.id,
        { expected_version: task.version, reason: panel.skipReason.trim() },
        options,
      )
      pushToast('info', '该药品已跳过，不会写入健康记录。')
    }
    panel.taskId = ''
    await loadTasks()
    requestHealthDataRefresh()
    void refreshPendingReviewCount()
  } catch (cause) {
    pushToast('error', formatError(cause))
  } finally {
    busyTaskId.value = null
  }
}

function onMemberChange(event: Event): void {
  selectMember((event.target as HTMLSelectElement).value)
}

watch(
  () => [session.selectedHouseholdId, session.selectedMemberId, showAllMembers.value],
  () => void loadTasks(),
)

onMounted(() => void loadTasks())
</script>

<template>
  <section class="page-hero">
    <div class="card-heading" style="margin-bottom: 0">
      <div>
        <h2 class="hero-greeting">人工复核中心</h2>
        <p class="hero-sub">
          成员提交的药盒照片在此排队，确认后才写入家庭记录。
        </p>
        <p class="hero-sub review-session-meta">
          登录 <strong>{{ session.actorId }}</strong>
          · 用途 <strong>{{ session.accessPurpose || '未填' }}</strong>
        </p>
      </div>
      <div class="review-hero-actions">
        <label class="context-select">
          成员
          <select
            :value="session.selectedMemberId"
            :disabled="loading || showAllMembers"
            @change="onMemberChange"
          >
            <option v-for="member in session.members" :key="member.id" :value="member.id">
              {{ member.display_name }}
            </option>
          </select>
        </label>
        <label class="check-row review-all-toggle">
          <input v-model="showAllMembers" type="checkbox" :disabled="loading" />
          显示全部成员待复核
        </label>
      </div>
    </div>
  </section>

  <p v-if="loadError" class="notice error" role="alert">
    <AppIcon name="alert" :size="16" />
    {{ loadError }}
  </p>

  <section class="card">
    <div class="card-heading">
      <div>
        <p class="eyebrow">待处理</p>
        <h3 class="card-title">待复核药品</h3>
      </div>
      <div class="heading-actions">
        <span class="pill clay">{{ pendingTasks.length }} 个待复核</span>
        <button type="button" class="btn btn-ghost btn-small" :disabled="loading" @click="loadTasks">
          <AppIcon name="refresh" :size="15" />
          刷新
        </button>
      </div>
    </div>

    <div v-if="loading" class="inline-loading">
      <span class="loading-dots"><span /><span /><span /></span>
      正在读取待复核药品
    </div>
    <div v-else-if="pendingTasks.length === 0" class="empty-state">
      <AppIcon class="empty-art" name="review" :size="40" />
      <strong>当前没有待复核药品</strong>
      <p>成员拍照或管理员扫描后，需要确认的药品会出现在这里。</p>
    </div>
    <ul v-else v-reveal class="list-plain review-task-list">
      <li v-for="task in pendingTasks" :key="task.id" class="row-card review-task-card">
        <div class="review-task-main">
          <button
            v-if="imageUrls[task.vision_task_id]"
            type="button"
            class="review-thumb review-task-thumb"
            title="查看原图与识别定位"
            @click="toggleEvidence(task)"
          >
            <img :src="imageUrls[task.vision_task_id]" alt="药盒原图缩略" />
            <span class="review-thumb-hint">
              <AppIcon name="eye" :size="12" />
              查看原图
            </span>
          </button>
          <div v-else class="review-task-thumb review-task-thumb-empty">
            <AppIcon name="pill" :size="28" />
          </div>

          <div class="review-task-body">
            <div class="row-top">
              <span class="row-title review-task-title">
                {{ primaryDrugName(task) }}
                <span class="pill" :class="fusionTone(task.fusion_status)">
                  {{ fusionStatusLabel(task.fusion_status) }}
                </span>
              </span>
              <span class="text-faint review-task-time">{{ formatDateTime(task.created_at) }}</span>
            </div>
            <p class="row-meta review-task-meta">
              <span v-if="showAllMembers" class="review-task-member">{{ task.memberName }}</span>
              <span v-if="task.candidates.length === 0">没有可用候选，请人工修正或跳过。</span>
              <span v-else-if="task.candidates.length === 1">{{ candidateLine(task.candidates[0]) || '请对照原图确认药品信息。' }}</span>
              <span v-else>{{ task.candidates.length }} 个候选，请选择最符合药盒的一项。</span>
            </p>
          </div>
        </div>

        <VisionResultViewer
          v-if="evidenceOpenId === task.id && visionTasks[task.vision_task_id]"
          :task="visionTasks[task.vision_task_id]"
          :image-url="imageUrls[task.vision_task_id] ?? null"
          :image-loading="evidenceLoadingId === task.id"
        />

        <div v-if="task.candidates.length > 1" class="section-stack review-candidate-stack">
          <label
            v-for="(candidate, index) in task.candidates"
            :key="index"
            class="check-row review-candidate-row"
          >
            <input
              type="radio"
              :name="'candidate-' + task.id"
              :checked="panel.taskId === task.id && panel.selectedIndex === index"
              @change="panel.taskId = task.id; panel.mode = 'confirm'; panel.selectedIndex = index"
            />
            <span class="review-candidate-copy">
              <strong>{{ candidate.drug_name ?? '未命名候选' }}</strong>
              <span v-if="candidateLine(candidate)" class="text-soft">{{ candidateLine(candidate) }}</span>
              <span v-if="candidate.evidence?.length" class="text-faint">
                证据来源：{{ candidate.evidence.join('、') }}
              </span>
              <div v-if="candidate.interaction_warnings?.length" class="text-soft" style="color: var(--clay)">
                组合提醒：{{ interactionSummary(candidate) }}
              </div>
            </span>
          </label>
        </div>
        <p
          v-else-if="task.candidates.length === 1"
          class="review-single-candidate"
        >
          <span v-if="task.candidates[0]?.evidence?.length" class="text-faint">
            证据来源：{{ task.candidates[0].evidence.join('、') }}
          </span>
          <span
            v-if="task.candidates[0]?.interaction_warnings?.length"
            class="text-soft"
            style="color: var(--clay)"
          >
            组合提醒：{{ interactionSummary(task.candidates[0]) }}
          </span>
        </p>
        <p v-else class="notice warn" style="margin: 0">
          <AppIcon name="info" :size="15" />
          没有可用候选，请选择「人工修正」手工填写，或跳过并补拍。
        </p>

        <details class="review-meta-details">
          <summary @click.prevent="toggleMeta(task.id)">
            {{ expandedMetaId === task.id ? '收起版本与追溯' : '版本、任务编号与追溯' }}
          </summary>
          <p v-if="expandedMetaId === task.id" class="text-faint" style="font-size: 12.5px; margin: 8px 0 0; font-family: ui-monospace, monospace">
            视觉任务 {{ task.vision_task_id }} · 复核任务 {{ task.id }} · 成员 {{ task.memberName }}（{{ task.member_id }}）
            <br />
            模型 {{ task.model_version ?? '未登记' }} · 规则 {{ task.rule_version ?? '未登记' }} · 版本 v{{ task.version }}
            <br />
            确认/修正将以当前登录身份 {{ session.actorId }} 写入已确认事件（需相应写权限）。
          </p>
        </details>

        <div class="review-actions">
          <button
            v-if="task.candidates.length > 0"
            type="button"
            class="btn btn-primary btn-small"
            @click="openPanel(task, 'confirm')"
          >
            确认保存
          </button>
          <button type="button" class="btn btn-ghost btn-small" @click="toggleEvidence(task)">
            <AppIcon name="eye" :size="14" />
            {{ evidenceOpenId === task.id ? '收起原图' : '看原图' }}
          </button>
          <div class="review-actions-more">
            <button type="button" class="btn btn-ghost btn-small" @click="openPanel(task, 'correct')">
              人工修正
            </button>
            <button type="button" class="btn btn-danger btn-small" @click="openPanel(task, 'skip')">
              跳过
            </button>
          </div>
        </div>

        <form
          v-if="panel.taskId === task.id"
          class="section-stack review-panel-form"
          @submit.prevent="submitPanel(task)"
        >
          <template v-if="panel.mode === 'confirm'">
            <p class="card-note" style="margin: 0">
              确认后才会以「已确认」状态写入健康事件并参与用药规则。
            </p>
            <label class="field">
              确认备注（可选）
              <input v-model="panel.note" autocomplete="off" placeholder="例如 与药盒实物核对一致" />
            </label>
          </template>
          <template v-else-if="panel.mode === 'correct'">
            <p class="card-note" style="margin: 0">
              本次修正会进入健康事件，before / after 与原因将留痕。
            </p>
            <label class="field">
              修正后药品名称（必填）
              <input v-model="panel.correctDrug" autocomplete="off" required />
            </label>
            <div class="grid-two" style="gap: 12px">
              <label class="field">
                剂量（可选）
                <input v-model="panel.correctDosage" autocomplete="off" placeholder="例如 0.25g" />
              </label>
              <label class="field">
                频次（可选）
                <input v-model="panel.correctFrequency" autocomplete="off" placeholder="例如 每日三次" />
              </label>
            </div>
            <label class="field">
              修正原因
              <input v-model="panel.note" autocomplete="off" placeholder="例如 OCR 将 0.25g 误读为 0.75g" />
            </label>
          </template>
          <template v-else>
            <label class="field">
              跳过原因
              <input v-model="panel.skipReason" autocomplete="off" placeholder="例如 图片对应的药品已停用" />
              <small>跳过不会写入健康记录，原始证据仍会保留。</small>
            </label>
          </template>
          <div class="row-actions">
            <button type="submit" class="btn btn-clay btn-small" :disabled="busyTaskId === task.id">
              {{ busyTaskId === task.id ? '正在保存' : panel.mode === 'confirm' ? '确认保存' : '提交' }}
            </button>
          </div>
        </form>
      </li>
    </ul>
  </section>

  <section v-if="settledTasks.length > 0" class="card">
    <div class="card-heading">
      <div>
        <p class="eyebrow">处理记录</p>
        <h3 class="card-title">已处理的复核</h3>
      </div>
    </div>
    <ul class="list-plain">
      <li v-for="task in visibleSettled" :key="task.id" class="row-card review-settled-row">
        <div class="row-top">
          <span class="row-title">
            {{ settledDrugLabel(task) }}
            <span class="pill" :class="statusTone(task.status)">{{ reviewStatusLabel(task.status) }}</span>
          </span>
          <span class="text-faint" style="font-size: 12.5px">
            {{ task.confirmed_at ? formatDateTime(task.confirmed_at) : formatDateTime(task.updated_at) }}
          </span>
        </div>
        <p class="row-meta" style="margin: 0">
          <span v-if="showAllMembers">{{ task.memberName }} · </span>
          {{ task.status === 'SKIPPED' ? '未写入健康记录' : '已写入家庭健康记录' }}
          {{ task.confirmed_by ? ` · 操作人 ${task.confirmed_by}` : '' }}
        </p>
      </li>
    </ul>
    <div v-if="settledTasks.length > SETTLED_PREVIEW" class="more-wrap">
      <button type="button" class="more-btn" :class="{ open: showAllSettled }" @click="showAllSettled = !showAllSettled">
        <AppIcon name="arrow-right" :size="13" />
        {{ showAllSettled ? '收起记录' : `展开更早的 ${settledTasks.length - SETTLED_PREVIEW} 条记录` }}
      </button>
    </div>
  </section>
</template>
