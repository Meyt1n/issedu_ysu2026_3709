<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import AppIcon from '@/components/AppIcon.vue'
import LevelTag from '@/components/LevelTag.vue'
import PrivacyBadge from '@/components/PrivacyBadge.vue'
import { useSpeech } from '@/composables/useSpeech'
import { activeProvider } from '@/data'
import { recognitionStatusLabel } from '@/data/labels'
import type { MemberSummary, QualityCheckResult, RecognitionCandidate } from '@/data/types'
import { useSession } from '@/stores/session'

type Stage = 'idle' | 'checking' | 'quality' | 'recognizing' | 'result'

const { session } = useSession()
const speech = useSpeech()

const members = ref<MemberSummary[]>([])
const memberId = ref('')
const stage = ref<Stage>('idle')
const file = ref<File | null>(null)
const previewUrl = ref('')
const quality = ref<QualityCheckResult | null>(null)
const candidate = ref<RecognitionCandidate | null>(null)
const error = ref('')

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
  error.value = ''
  stage.value = 'idle'
}

async function onFilePicked(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const picked = input.files?.[0]
  input.value = ''
  if (!picked) return

  releasePreview()
  file.value = picked
  previewUrl.value = URL.createObjectURL(picked)
  quality.value = null
  candidate.value = null
  error.value = ''
  stage.value = 'checking'

  try {
    quality.value = await activeProvider().checkImageQuality(picked)
    stage.value = 'quality'
    if (quality.value.decision === 'PASS') {
      speech.speak('照片质量合格，可以开始识别。')
    } else {
      speech.speak(`照片需要重拍。${quality.value.retakePrompts.join('，')}`)
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '质量检查失败，请重试'
    stage.value = 'idle'
  }
}

async function recognize(): Promise<void> {
  if (!file.value || !memberId.value) return
  stage.value = 'recognizing'
  error.value = ''
  try {
    candidate.value = await activeProvider().recognizeMedicine(file.value, memberId.value)
    stage.value = 'result'
    speech.speak(`识别结果：${recognitionStatusLabel(candidate.value.status)}。${candidate.value.notice}`)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '识别失败，请重试'
    stage.value = 'quality'
  }
}

onMounted(async () => {
  try {
    members.value = await activeProvider().listMembers()
    memberId.value = session.currentMemberId || members.value[0]?.id || ''
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '成员加载失败'
  }
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
      <li v-for="(step, index) in steps" :key="step.key" :data-active="index === activeStepIndex">
        {{ index + 1 }}.{{ step.label }}
      </li>
    </ol>

    <label class="field">
      为哪位成员录入
      <select v-model="memberId">
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
        <label class="btn btn-lg" :data-disabled="stage === 'checking' || stage === 'recognizing'">
          <AppIcon name="camera" :size="20" />
          {{ file ? '重新拍摄' : '拍摄药盒' }}
          <input
            type="file"
            accept="image/*"
            capture="environment"
            class="visually-hidden-input"
            :disabled="stage === 'checking' || stage === 'recognizing'"
            @change="onFilePicked"
          />
        </label>
        <label class="btn btn-quiet btn-lg">
          从相册选择
          <input
            type="file"
            accept="image/*"
            class="visually-hidden-input"
            :disabled="stage === 'checking' || stage === 'recognizing'"
            @change="onFilePicked"
          />
        </label>
      </div>
    </div>

    <p v-if="error" class="notice" data-tone="error" role="alert">{{ error }}</p>
    <p v-if="stage === 'checking'" class="notice" role="status">正在进行图片质量检查…</p>
    <p v-if="stage === 'recognizing'" class="notice" role="status">正在提取 OCR、条码与包装特征证据…</p>

    <section v-if="quality && stage !== 'checking'" class="card" aria-labelledby="quality-title">
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
        :disabled="!memberId"
        @click="recognize"
      >
        开始识别
      </button>
    </section>

    <section v-if="candidate && stage === 'result'" class="card" aria-labelledby="candidate-title">
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
html[data-contrast='high'] .metric-grid li { border: 2px solid #000; background: #fff; }
</style>
