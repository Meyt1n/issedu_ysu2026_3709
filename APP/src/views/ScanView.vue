<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import AppIcon from '@/components/AppIcon.vue'
import ErrorNotice from '@/components/ErrorNotice.vue'
import LevelTag from '@/components/LevelTag.vue'
import PrivacyBadge from '@/components/PrivacyBadge.vue'
import { useSpeech } from '@/composables/useSpeech'
import { activeProvider, canSubmitWrites } from '@/data'
import { recognitionStatusLabel } from '@/data/labels'
import type { MemberSummary, QualityCheckResult, RecognitionCandidate } from '@/data/types'
import { imageInputUnavailableMessage, validateMedicineImage } from '@/utils/uploadInput'
import { CAPABILITY_IDS, useCapabilities } from '@/stores/capabilities'
import { sessionContextKey, useSession } from '@/stores/session'
import { presentApiError, type ErrorPresentation } from '@/api/errors'

type Stage = 'idle' | 'checking' | 'quality' | 'recognizing' | 'result'

const { session } = useSession()
const { capabilities, hasCapability } = useCapabilities()
const speech = useSpeech()
let memberLoadGeneration = 0

const members = ref<MemberSummary[]>([])
const membersLoading = ref(true)
const memberId = ref('')
const stage = ref<Stage>('idle')
const file = ref<File | null>(null)
const previewUrl = ref('')
const quality = ref<QualityCheckResult | null>(null)
const candidate = ref<RecognitionCandidate | null>(null)
const error = ref<ErrorPresentation | null>(null)
const inputNotice = ref('')
const visionTaskAvailable = computed(() =>
  session.dataMode === 'demo' || hasCapability(CAPABILITY_IDS.visionTask),
)
/** 正式会话失效时禁止上传与创建视觉任务：写操作在页面层就被拦住。 */
const writesAllowed = computed(() => canSubmitWrites())
const captureAllowed = computed(() => visionTaskAvailable.value && writesAllowed.value)
const isBusy = computed(() => stage.value === 'checking' || stage.value === 'recognizing')
const cameraAvailable = computed(() => {
  if (typeof navigator === 'undefined') return false
  return Boolean(navigator.mediaDevices?.getUserMedia)
})
const handoff = computed(() => candidate.value?.handoff ?? {
  taskId: 'demo-review-pending',
  taskStatus: 'PENDING_REVIEW',
  source: 'DEMO' as const,
  nextStep: '请在网页端人工复核中心确认识别候选。',
})

const steps = [
  { key: 'shoot', label: '拍摄' },
  { key: 'quality', label: '质量检查' },
  { key: 'candidate', label: '识别候选' },
  { key: 'review', label: '人工确认' },
]

const activeStepIndex = computed(() => {
  if (stage.value === 'idle') return 0
  if (stage.value === 'checking' || stage.value === 'quality') return 1
  if (stage.value === 'recognizing') return 2
  return 3
})

function releasePreview(): void {
  if (previewUrl.value) {
    URL.revokeObjectURL(previewUrl.value)
    previewUrl.value = ''
  }
}

function reset(): void {
  releasePreview()
  file.value = null
  quality.value = null
  candidate.value = null
  error.value = null
  stage.value = 'idle'
  inputNotice.value = ''
}

function clearSelection(): void {
  if (isBusy.value) return
  releasePreview()
  file.value = null
  quality.value = null
  candidate.value = null
  error.value = null
  stage.value = 'idle'
  inputNotice.value = '已取消本次本地图片选择；未发起上传，也未创建视觉任务。'
}

async function onFilePicked(event: Event): Promise<void> {
  if (!captureAllowed.value || isBusy.value) return
  const input = event.target as HTMLInputElement
  const picked = input.files?.[0]
  input.value = ''
  if (!picked) return

  const validation = validateMedicineImage(picked)
  if (!validation.ok) {
    inputNotice.value = validation.message
    error.value = null
    return
  }

  releasePreview()
  file.value = picked
  previewUrl.value = URL.createObjectURL(picked)
  quality.value = null
  candidate.value = null
  inputNotice.value = ''
  await checkQuality(picked)
}

async function checkQuality(picked: File): Promise<void> {
  const expectedKey = sessionContextKey(session)
  error.value = null
  stage.value = 'checking'
  try {
    const nextQuality = await activeProvider().checkImageQuality(picked)
    if (expectedKey !== sessionContextKey(session)) return
    quality.value = nextQuality
    stage.value = 'quality'
    if (quality.value.decision === 'PASS') {
      speech.speak('照片质量合格，可以开始识别。')
    } else {
      speech.speak(`照片需要重拍。${quality.value.retakePrompts.join('，')}`)
    }
  } catch (cause) {
    if (expectedKey !== sessionContextKey(session)) return
    error.value = presentApiError(cause)
    stage.value = 'idle'
  }
}

async function recognize(): Promise<void> {
  if (
    !file.value
    || !memberId.value
    || !captureAllowed.value
    || stage.value === 'checking'
    || stage.value === 'recognizing'
  ) return
  const expectedKey = sessionContextKey(session)
  stage.value = 'recognizing'
  error.value = null
  try {
    const nextCandidate = await activeProvider().recognizeMedicine(file.value, memberId.value)
    if (expectedKey !== sessionContextKey(session)) return
    candidate.value = nextCandidate
    stage.value = 'result'
    speech.speak(`识别结果：${recognitionStatusLabel(candidate.value.status)}。${candidate.value.notice}`)
  } catch (cause) {
    if (expectedKey !== sessionContextKey(session)) return
    error.value = presentApiError(cause)
    stage.value = 'quality'
    inputNotice.value = '本次识别未确认创建视觉任务。保留已通过质量检查的图片，可点击“开始识别”重试；请勿重复选择图片。'
  }
}

async function loadMembers(): Promise<void> {
  const generation = ++memberLoadGeneration
  const expectedKey = sessionContextKey(session)
  membersLoading.value = true
  error.value = null
  members.value = []
  memberId.value = ''
  try {
    const nextMembers = await activeProvider().listMembers()
    if (generation !== memberLoadGeneration || expectedKey !== sessionContextKey(session)) return
    members.value = nextMembers
    memberId.value = session.currentMemberId || nextMembers[0]?.id || ''
  } catch (cause) {
    if (generation !== memberLoadGeneration || expectedKey !== sessionContextKey(session)) return
    error.value = presentApiError(cause)
  } finally {
    if (generation === memberLoadGeneration) membersLoading.value = false
  }
}

async function retry(): Promise<void> {
  if (file.value && !quality.value) {
    await checkQuality(file.value)
    return
  }
  if (file.value && quality.value) {
    await recognize()
    return
  }
  await loadMembers()
}

onMounted(loadMembers)
watch(() => sessionContextKey(session), () => {
  reset()
  void loadMembers()
})

onBeforeUnmount(releasePreview)
</script>

<template>
  <main id="main" class="screen">
    <header class="screen-header">
      <p class="eyebrow">多证据视觉录入</p>
      <h1>拍药盒</h1>
      <p class="screen-subtitle">拍摄药盒正面，系统先做质量检查，再给出多渠道证据候选；只有人工确认后才会写入健康档案。</p>
      <PrivacyBadge />
    </header>

    <ol class="steps" aria-label="录入步骤">
      <li
        v-for="(step, index) in steps"
        :key="step.key"
        :data-active="index === activeStepIndex"
        :aria-current="index === activeStepIndex ? 'step' : undefined"
      >
        {{ index + 1 }}.{{ step.label }}
      </li>
    </ol>

    <p v-if="membersLoading" class="notice" role="status">正在加载家庭和成员数据…</p>
    <p v-else-if="members.length === 0 && !error" class="notice" data-tone="warn" role="status">
      当前家庭暂无可用成员，请到“我的”检查联机身份、家庭和授权设置；没有成员时不能开始录入。
    </p>
    <p
      v-if="session.dataMode === 'live' && !capabilities.snapshot"
      class="notice"
      data-tone="warn"
      role="status"
    >
      尚未完成后端能力探测；请先到“我的”测试连接。未确认提供视觉任务前，拍摄和相册入口保持禁用。
    </p>
    <p
      v-else-if="session.dataMode === 'live' && !visionTaskAvailable"
      class="notice"
      data-tone="warn"
      role="status"
    >
      当前家庭服务器未提供视觉任务，拍摄和相册入口已禁用；不会把未提供的识别接口包装成可用功能。
    </p>
    <p
      v-else-if="session.dataMode === 'live' && !writesAllowed"
      class="notice"
      data-tone="warn"
      role="status"
    >
      登录会话已失效或尚未登录，拍摄、上传和识别入口已禁用；请重新登录后再提交，避免重复创建任务。
    </p>

    <p v-if="!cameraAvailable" class="notice" data-tone="warn" role="status">
      {{ imageInputUnavailableMessage() }}
    </p>
    <label class="field">
      为哪位成员录入
      <select v-model="memberId" :disabled="membersLoading || members.length === 0">
        <option v-for="member in members" :key="member.id" :value="member.id">
          {{ member.name }}（{{ member.relation }}）
        </option>
      </select>
    </label>

    <div class="card">
      <div
        class="viewfinder"
        :data-scanning="stage === 'checking' || stage === 'recognizing'"
        :data-has-photo="Boolean(previewUrl)"
      >
        <img v-if="previewUrl" :src="previewUrl" alt="待识别的药盒照片预览" />
        <div v-else class="vf-hint">
          <AppIcon name="camera" :size="34" />
          <p>把药盒正面放满取景框<br />光线充足、避免反光</p>
        </div>
        <span class="vf-corner vf-tl" aria-hidden="true"></span>
        <span class="vf-corner vf-tr" aria-hidden="true"></span>
        <span class="vf-corner vf-bl" aria-hidden="true"></span>
        <span class="vf-corner vf-br" aria-hidden="true"></span>
        <span
          v-if="stage === 'checking' || stage === 'recognizing'"
          class="vf-line"
          aria-hidden="true"
        ></span>
      </div>
      <div class="btn-row">
        <label
          class="btn btn-lg"
          :data-disabled="!captureAllowed || membersLoading || members.length === 0 || stage === 'checking' || stage === 'recognizing'"
          :aria-disabled="!captureAllowed || membersLoading || members.length === 0 || stage === 'checking' || stage === 'recognizing'"
        >
          <AppIcon name="camera" :size="20" />
          {{ file ? '重新拍摄' : '拍摄药盒' }}
          <input
            type="file"
            accept="image/*"
            capture="environment"
            class="visually-hidden-input"
            :disabled="!captureAllowed || membersLoading || members.length === 0 || stage === 'checking' || stage === 'recognizing'"
            @change="onFilePicked"
          />
        </label>
        <label
          class="btn btn-quiet btn-lg"
          :data-disabled="!captureAllowed || membersLoading || members.length === 0"
          :aria-disabled="!captureAllowed || members.length === 0"
        >
          从相册选择
          <input
            type="file"
            accept="image/*"
            class="visually-hidden-input"
            :disabled="!captureAllowed || membersLoading || members.length === 0 || stage === 'checking' || stage === 'recognizing'"
            @change="onFilePicked"
          />
        </label>
      </div>
      <button
        v-if="file && !isBusy"
        type="button"
        class="btn btn-quiet btn-block"
        @click="clearSelection"
      >
        取消本次选择
      </button>
    </div>

    <p v-if="inputNotice" class="notice" data-tone="warn" role="status">{{ inputNotice }}</p>
    <ErrorNotice v-if="error" :error="error" @retry="retry" />
    <p v-if="stage === 'checking'" class="notice" role="status">正在进行图片质量检查…</p>
    <p v-if="stage === 'recognizing'" class="notice" role="status">正在提取 OCR、条码与包装特征证据…</p>

    <section v-if="quality && stage !== 'checking'" class="card" aria-labelledby="quality-title" aria-live="polite">
      <div class="card-title-row">
        <h2 id="quality-title">质量检查</h2>
        <span
          class="tag"
          :data-tone="quality.decision === 'PASS' ? 'calm' : 'danger'"
        >
          {{ quality.decision === 'PASS' ? '通过' : '需要重拍' }}
        </span>
      </div>
      <ul class="metric-grid">
        <li v-for="metric in quality.metrics" :key="metric.label">
          <span class="meta-line">{{ metric.label }}</span>
          <strong :data-passed="metric.passed">{{ metric.value }}{{ metric.passed ? '' : '（未达标）' }}</strong>
        </li>
      </ul>
      <template v-if="quality.decision === 'RETAKE'">
        <p v-for="prompt in quality.retakePrompts" :key="prompt" class="notice" data-tone="warn">{{ prompt }}</p>
      </template>
      <button
        v-if="quality.decision === 'PASS' && stage === 'quality'"
        type="button"
        class="btn btn-block btn-lg"
        :disabled="!memberId || !captureAllowed"
        @click="recognize"
      >
        开始识别
      </button>
    </section>

    <section v-if="candidate && stage === 'result'" class="card" aria-labelledby="candidate-title" aria-live="polite">
      <div class="card-title-row">
        <h2 id="candidate-title">识别候选</h2>
        <LevelTag kind="recognition" :value="candidate.status" />
      </div>
      <ul class="divided-list">
        <li v-for="field in candidate.fields" :key="field.label">
          <div class="card-title-row">
            <strong>{{ field.label }}</strong>
            <span class="meta-line">{{ field.source }} · 置信 {{ Math.round(field.confidence * 100) }}%</span>
          </div>
          <span>{{ field.value }}</span>
        </li>
      </ul>
      <p v-for="conflict in candidate.conflicts" :key="conflict" class="notice" data-tone="error">
        冲突：{{ conflict }}
      </p>
      <p class="notice" data-tone="warn">{{ candidate.notice }}</p>
      <section class="handoff" aria-labelledby="handoff-title">
        <h3 id="handoff-title">后续人工复核</h3>
        <p><strong>任务状态：</strong>{{ handoff.taskStatus }}</p>
        <p><strong>任务编号：</strong>{{ handoff.taskId }}</p>
        <p>{{ handoff.nextStep }}</p>
        <p v-if="handoff.source === 'DEMO'" class="meta-line">演示模式不会创建真实复核任务。</p>
      </section>
      <p class="meta-line">
        版本：<template v-for="(version, key) in candidate.versions" :key="key">{{ key }} {{ version }}　</template>
      </p>
      <div class="btn-row">
        <button type="button" class="btn btn-quiet" @click="reset">再拍一张</button>
        <RouterLink class="btn" to="/">完成，返回今日</RouterLink>
      </div>
    </section>

    <footer class="disclaimer">
      识别候选永远需要人工确认；冲突、未知或低质量结果不会自动写入健康档案（与网页端复核中心一致）。
    </footer>
  </main>
</template>

<style scoped>
/* ---- 相机取景框 ---- */
.viewfinder {
  position: relative;
  aspect-ratio: 4 / 3;
  border-radius: calc(var(--r-card) - 8px);
  background:
    radial-gradient(95% 95% at 50% 42%, var(--c-brand-softer) 0%, transparent 78%),
    var(--well-bg);
  overflow: hidden;
  display: grid;
  place-items: center;
}
.viewfinder img { width: 100%; height: 100%; object-fit: contain; }

.vf-hint {
  display: grid;
  gap: 10px;
  justify-items: center;
  color: var(--c-ink-faint);
  text-align: center;
  font-size: 0.9rem;
  line-height: 1.6;
}
.vf-hint svg { animation: vf-pulse 2.4s ease-in-out infinite alternate; color: var(--c-brand); }

.vf-corner {
  position: absolute;
  width: 30px;
  height: 30px;
  border: 3.5px solid var(--c-brand);
  transition: border-color var(--speed);
}
.vf-tl { top: 12px; left: 12px; border-right: 0; border-bottom: 0; border-top-left-radius: 13px; }
.vf-tr { top: 12px; right: 12px; border-left: 0; border-bottom: 0; border-top-right-radius: 13px; }
.vf-bl { bottom: 12px; left: 12px; border-right: 0; border-top: 0; border-bottom-left-radius: 13px; }
.vf-br { bottom: 12px; right: 12px; border-left: 0; border-top: 0; border-bottom-right-radius: 13px; }

.viewfinder[data-has-photo='true'] .vf-corner { border-color: var(--c-calm); }
.viewfinder[data-scanning='true'] .vf-corner {
  border-color: var(--c-accent);
  animation: vf-blink 0.9s ease-in-out infinite alternate;
}

.vf-line {
  position: absolute;
  left: 7%;
  right: 7%;
  top: 10%;
  height: 3px;
  border-radius: 3px;
  background: linear-gradient(90deg, transparent, #57d8a8 18%, #a5f5d3 50%, #57d8a8 82%, transparent);
  box-shadow: 0 0 16px 3px rgba(87, 216, 168, 0.55);
  animation: vf-scan 2.1s ease-in-out infinite;
}

@keyframes vf-scan {
  0%, 100% { top: 9%; }
  50% { top: 88%; }
}
@keyframes vf-pulse {
  from { transform: scale(1); opacity: 0.72; }
  to { transform: scale(1.12); opacity: 1; }
}
@keyframes vf-blink {
  from { opacity: 0.5; }
  to { opacity: 1; }
}

html[data-contrast='high'] .viewfinder { border: 2px solid #000; }
html[data-contrast='high'] .vf-corner { border-color: #000; animation: none; }
html[data-contrast='high'] .vf-line { background: #000; box-shadow: none; }
.visually-hidden-input {
  position: absolute;
  width: 1px;
  height: 1px;
  opacity: 0;
  overflow: hidden;
}
.btn[data-disabled='true'] { pointer-events: none; opacity: 0.55; }
.metric-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}
.metric-grid li {
  display: grid;
  gap: 2px;
  background: var(--well-bg);
  border-radius: 12px;
  padding: 9px 12px;
  box-shadow: inset 0 1px 0 var(--hilite);
}
.metric-grid strong[data-passed='false'] { color: var(--c-danger-deep); }
.handoff { margin-top: 12px; padding: 12px; border: 1px solid var(--c-border); border-radius: var(--r-card); }
.handoff p { margin-top: 6px; }
html[data-contrast='high'] .metric-grid li { border: 2px solid #000; background: #fff; }
</style>
