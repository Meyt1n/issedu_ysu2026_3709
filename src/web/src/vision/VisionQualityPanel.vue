<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { ApiClientError, apiClient } from '../api/client'
import type { VisionQualityResponse, VisionTask } from '../api/types'
import AppIcon from '../components/AppIcon.vue'
import captureExampleUrl from '../assets/vision-capture-example-v2.png'
import {
  canCreateVisionTask,
  formatMetricValue,
  metricLabels,
  qualityStateLabel,
  queuePassedVisionFile,
  type QualityFlowState,
  validateVisionImage,
} from './qualityView'

const props = defineProps<{
  actorId: string
  memberId?: string
  accessPurpose?: string
  audience?: 'member' | 'admin'
}>()

const emit = defineEmits<{
  (event: 'task-created', task: VisionTask): void
}>()

const selectedFile = ref<File | null>(null)
const previewUrl = ref('')
const qualityResult = ref<VisionQualityResponse | null>(null)
const createdTask = ref<VisionTask | null>(null)
const state = ref<QualityFlowState>('idle')
const error = ref('')
const guideOpen = ref(false)
let requestGeneration = 0

const isBusy = computed(() => state.value === 'checking' || state.value === 'queueing')
const isMemberView = computed(() => props.audience === 'member')
const canCheck = computed(() => Boolean(selectedFile.value && props.actorId && !isBusy.value))
const canQueue = computed(
  () => (
    canCreateVisionTask(qualityResult.value)
    && Boolean(props.memberId)
    && !createdTask.value
    && !isBusy.value
  ),
)
const visibleMetrics = computed(() => {
  const metrics = qualityResult.value?.metrics ?? {}
  return Object.keys(metricLabels)
    .filter(key => metrics[key])
    .map(key => ({ key, label: metricLabels[key], metric: metrics[key]! }))
})

const stepStates = computed(() => {
  const flow = state.value
  const hasFile = Boolean(selectedFile.value)
  const passed = flow === 'passed' || flow === 'queueing' || flow === 'queued'
  return [
    { label: '选择图片', state: hasFile ? 'done' : 'current' },
    {
      label: '质量检查',
      state: passed ? 'done' : flow === 'checking' ? 'current' : hasFile ? 'current' : 'idle',
    },
    {
      label: '创建识别任务',
      state: flow === 'queued' ? 'done' : passed ? 'current' : 'idle',
    },
    { label: isMemberView.value ? '等待家人确认' : '人工复核后入档', state: 'idle' },
  ]
})

function releasePreview(): void {
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = ''
}

function resetEvidence(): void {
  requestGeneration += 1
  qualityResult.value = null
  createdTask.value = null
  error.value = ''
}

function clearFile(): void {
  resetEvidence()
  selectedFile.value = null
  releasePreview()
  state.value = 'idle'
}

function openGuide(): void {
  guideOpen.value = true
}

function closeGuide(): void {
  guideOpen.value = false
}

function handleGuideKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') closeGuide()
}

function selectFile(event: Event): void {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0] ?? null
  clearFile()
  input.value = ''
  if (!file) return

  const validationError = validateVisionImage(file)
  if (validationError) {
    state.value = 'error'
    error.value = validationError
    return
  }

  selectedFile.value = file
  previewUrl.value = URL.createObjectURL(file)
  state.value = 'ready'
}

function explainError(cause: unknown): string {
  if (cause instanceof ApiClientError) {
    if (cause.code === 'DEPENDENCY_UNAVAILABLE') return '本地服务不可用，请启动 API 后重试。'
    if (cause.status === 413) return '图片过大，请缩小图片后重试。'
    if (cause.status === 422) return '图片格式或内容不符合要求，请重新拍摄。'
    if (cause.status === 409) return '质量凭证已失效，请重新进行质量检查。'
  }
  return '处理失败，未创建识别任务。请重试。'
}

async function checkQuality(): Promise<void> {
  const file = selectedFile.value
  if (!file) return
  if (!props.actorId) {
    state.value = 'error'
    error.value = '请先进入家庭空间。'
    return
  }

  const generation = ++requestGeneration
  qualityResult.value = null
  createdTask.value = null
  error.value = ''
  state.value = 'checking'
  try {
    const result = await apiClient.checkVisionQuality(file, { actorId: props.actorId })
    if (generation !== requestGeneration || file !== selectedFile.value) return
    qualityResult.value = result
    state.value = canCreateVisionTask(result) ? 'passed' : 'retake'
  } catch (cause) {
    if (generation !== requestGeneration) return
    state.value = 'error'
    error.value = explainError(cause)
  }
}

async function queueVisionTask(): Promise<void> {
  const file = selectedFile.value
  const result = qualityResult.value
  if (!file || !props.actorId || !canCreateVisionTask(result) || !result?.quality_receipt) return

  const generation = ++requestGeneration
  const actorId = props.actorId
  const memberId = props.memberId
  error.value = ''
  state.value = 'queueing'
  try {
    const task = await queuePassedVisionFile({
      file,
      result,
      actorId,
      memberId,
      accessPurpose: props.accessPurpose,
      idempotencyKey: globalThis.crypto?.randomUUID?.() ?? `web-${Date.now()}`,
      isCurrent: () => generation === requestGeneration && file === selectedFile.value,
    }, apiClient)
    if (!task || generation !== requestGeneration) return
    createdTask.value = task
    state.value = 'queued'
    emit('task-created', task)
  } catch (cause) {
    if (generation !== requestGeneration) return
    state.value = 'error'
    error.value = cause instanceof Error && cause.message === 'UPLOAD_DIGEST_MISMATCH'
      ? '上传文件与已检查图片不一致，已停止并清理文件，请重新检查。'
      : explainError(cause)
  }
}

onMounted(() => window.addEventListener('keydown', handleGuideKeydown))

onBeforeUnmount(() => {
  releasePreview()
  window.removeEventListener('keydown', handleGuideKeydown)
})

watch(() => [props.actorId, props.memberId, props.accessPurpose], () => {
  resetEvidence()
  state.value = selectedFile.value ? 'ready' : 'idle'
})
</script>

<template>
  <section class="card" aria-labelledby="vision-quality-title">
    <div class="card-heading">
      <div>
        <p class="eyebrow">{{ isMemberView ? '拍照录药' : '本地药盒采集' }}</p>
        <h3 id="vision-quality-title" class="card-title">
          {{ isMemberView ? '拍一张清楚的药盒照片' : '先检查图片质量，再进入识别' }}
        </h3>
      </div>
      <span
        class="pill"
        :class="state === 'queued' ? 'pine' : state === 'retake' || state === 'error' ? 'rose' : state === 'passed' ? 'gold' : 'plain'"
      >
        {{
          state === 'idle' ? '等待图片'
          : state === 'ready' ? '待检查'
          : state === 'checking' ? '正在检查'
          : state === 'retake' ? '需要重拍'
          : state === 'passed' ? '质量通过'
          : state === 'queueing' ? '正在创建任务'
          : state === 'queued' ? '任务已入队'
          : '出现问题'
        }}
      </span>
    </div>

    <div class="step-rail" style="margin-bottom: 16px">
      <span
        v-for="(step, index) in stepStates"
        :key="step.label"
        class="step-chip"
        :class="step.state"
      >
        <span class="step-no">{{ index + 1 }}</span>
        {{ step.label }}
      </span>
    </div>

    <p class="card-note" style="margin: 0 0 14px">
      {{ isMemberView
        ? '照片只发送到本机，提交后由家庭管理员确认；没有确认前不会写入家庭记录。'
        : '图片只发送到本机 API。质量通过不代表识别成功，识别结果仅为候选，确认后才进入健康记录。' }}
    </p>

    <div class="grid-two capture-layout">
      <label class="capture-zone" :class="{ checking: state === 'checking' }" :aria-disabled="isBusy">
        <img v-if="previewUrl" :src="previewUrl" alt="当前待检查药盒图片的本地预览" />
        <template v-else>
          <div class="capture-empty">
            <span class="capture-empty-icon"><AppIcon name="scan" :size="30" /></span>
            <strong>点击选择药盒照片</strong>
            <span>支持 JPEG / PNG · 仅在本机预览</span>
          </div>
          <span class="capture-hint">点击此处拍照，或从设备选择图片</span>
        </template>
        <input
          type="file"
          accept=".jpg,.jpeg,.png,image/jpeg,image/png"
          capture="environment"
          :disabled="isBusy"
          style="display: none"
          @change="selectFile"
        />
      </label>

      <aside class="capture-example-panel" aria-labelledby="capture-example-title">
        <div class="capture-example-head">
          <div>
            <p class="capture-example-kicker">拍摄参考</p>
            <h4 id="capture-example-title">让正面信息完整入框</h4>
            <p>镜头与药盒正面保持平行，四边都留出一点边缘。</p>
          </div>
          <button type="button" class="capture-example-expand" @click="openGuide">
            <AppIcon name="eye" :size="15" />
            放大查看
          </button>
        </div>

        <button
          type="button"
          class="capture-example-media"
          aria-label="放大查看药盒拍摄示例"
          @click="openGuide"
        >
          <span class="capture-example-visual">
            <img :src="captureExampleUrl" alt="拍摄示例：药盒正面平行镜头，完整且无遮挡地进入取景框" />
            <span class="capture-frame-guides" aria-hidden="true">
              <i class="top-left" />
              <i class="top-right" />
              <i class="bottom-left" />
              <i class="bottom-right" />
              <b>正面平拍</b>
            </span>
          </span>
          <span class="capture-example-caption">
            <AppIcon name="eye" :size="14" />
            点击图片可放大查看
          </span>
        </button>

        <div class="capture-check-list" aria-label="拍摄要求">
          <div class="capture-check-item">
            <span class="capture-check-icon"><AppIcon name="check" :size="14" /></span>
            <span><strong>正面平拍</strong><small>镜头与药盒正面保持平行</small></span>
          </div>
          <div class="capture-check-item">
            <span class="capture-check-icon"><AppIcon name="check" :size="14" /></span>
            <span><strong>完整入框</strong><small>四边可见，不要裁掉关键信息</small></span>
          </div>
          <div class="capture-check-item">
            <span class="capture-check-icon"><AppIcon name="check" :size="14" /></span>
            <span><strong>减少反光</strong><small>避开闪光灯和强逆光，保持清晰</small></span>
          </div>
        </div>

        <div class="capture-example-foot">
          <AppIcon name="lock" :size="14" />
          {{ isMemberView ? '照片只在本机处理' : '拍摄参考' }}
        </div>
      </aside>

      <div class="section-stack">
        <p v-if="selectedFile" class="text-soft" style="font-size: 13px; margin: 0">
          已选择：{{ selectedFile.name }}（仅本地预览，未上传）
        </p>
        <div class="row-actions">
          <button type="button" class="btn btn-primary" :disabled="!canCheck" @click="checkQuality">
            {{ state === 'checking' ? '正在检查' : isMemberView ? '检查照片' : '检查图片质量' }}
          </button>
          <button v-if="selectedFile" type="button" class="btn btn-ghost" :disabled="isBusy" @click="clearFile">
            清除
          </button>
        </div>

        <p v-if="error" class="notice error" role="alert">
          <AppIcon name="alert" :size="16" />
          {{ error }}
        </p>

        <div v-if="qualityResult?.decision === 'RETAKE'" class="notice warn" role="status" style="display: block">
          <strong style="display: block; margin-bottom: 6px">需要重新拍摄</strong>
          <ul style="margin: 0 0 6px; padding-left: 18px">
            <li v-for="prompt in qualityResult.retake_prompts" :key="prompt">{{ prompt }}</li>
          </ul>
          本次不会上传文件，也不会创建识别任务。
        </div>

        <template v-if="qualityResult?.decision === 'PASS'">
          <div class="notice ok" role="status">
            <AppIcon name="check" :size="16" />
            {{ isMemberView ? '照片清楚，可以提交给家庭管理员确认。' : `图片质量通过（配置 ${qualityResult.config_version}），可以创建本地识别任务。` }}
          </div>
          <dl v-if="!isMemberView" class="quality-metrics">
            <div v-for="item in visibleMetrics" :key="item.key">
              <dt>{{ item.label }}</dt>
              <dd :data-passed="item.metric.passed">{{ formatMetricValue(item.key, item.metric.value) }}</dd>
            </div>
          </dl>
          <button type="button" class="btn btn-clay" :disabled="!canQueue" @click="queueVisionTask">
            {{ state === 'queueing' ? '正在提交' : isMemberView ? '提交给家庭管理员' : '通过并创建识别任务' }}
            <AppIcon v-if="state !== 'queueing'" name="arrow-right" :size="16" />
          </button>
        </template>

        <div v-if="createdTask" class="notice ok" role="status" style="display: block">
          <strong style="display: block; margin-bottom: 4px">{{ isMemberView ? '照片已提交，等待家庭管理员确认' : '本地识别任务已创建' }}</strong>
          {{ isMemberView
            ? '管理员确认后，药品信息才会出现在家庭记录中。'
            : `任务编号 ${createdTask.id} · 当前进入 OCR 待处理队列，不会自动写入健康记录。` }}
        </div>
      </div>
    </div>
  </section>

  <Teleport to="body">
    <div
      v-if="guideOpen"
      class="capture-lightbox"
      role="presentation"
      @click.self="closeGuide"
    >
      <div
        class="capture-lightbox-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="capture-lightbox-title"
      >
        <div class="capture-lightbox-head">
          <div>
            <p class="capture-example-kicker">拍摄参考</p>
            <h4 id="capture-lightbox-title">正面平拍，完整入框</h4>
          </div>
          <button type="button" class="capture-lightbox-close" aria-label="关闭拍摄示例" @click="closeGuide">
            <AppIcon name="close" :size="20" />
          </button>
        </div>
        <figure class="capture-lightbox-figure">
          <img :src="captureExampleUrl" alt="放大的药盒拍摄示例" />
          <figcaption>保持镜头与药盒正面平行，四边可见并避免反光。</figcaption>
        </figure>
      </div>
    </div>
  </Teleport>
</template>
