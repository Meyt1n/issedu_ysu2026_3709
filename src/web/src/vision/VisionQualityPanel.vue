<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { ApiClientError, apiClient } from '../api/client'
import type { VisionQualityResponse, VisionTask } from '../api/types'
import AppIcon from '../components/AppIcon.vue'
import captureExampleUrl from '../assets/vision-capture-example-v2.png'
import { requestOptions } from '../store'
import { runVisionQualityCheckWithRepair } from './imageRepair'
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
const autoRepaired = ref(false)
const state = ref<QualityFlowState>('idle')
const error = ref('')
const guideOpen = ref(false)
let requestGeneration = 0

const isBusy = computed(() => state.value === 'checking' || state.value === 'queueing')
const isMemberView = computed(() => props.audience === 'member')
const canCheck = computed(() => Boolean(selectedFile.value && requestOptions.value.sessionToken && !isBusy.value))
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
  if (isMemberView.value) {
    return [
      { label: '选照片', state: hasFile ? 'done' : 'current' },
      {
        label: '看清不清楚',
        state: passed ? 'done' : flow === 'checking' ? 'current' : hasFile ? 'current' : 'idle',
      },
      {
        label: '交给家人',
        state: flow === 'queued' ? 'done' : passed ? 'current' : 'idle',
      },
      { label: '等确认', state: 'idle' },
    ]
  }
  return [
    { label: '选择图片', state: hasFile ? 'done' : 'current' },
    {
      label: '质量检查',
      state: passed ? 'done' : flow === 'checking' ? 'current' : hasFile ? 'current' : 'idle',
    },
    {
      label: '创建任务',
      state: flow === 'queued' ? 'done' : passed ? 'current' : 'idle',
    },
    { label: '复核入档', state: 'idle' },
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
  autoRepaired.value = false
  error.value = ''
}

function replaceSelectedFile(file: File): void {
  selectedFile.value = file
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = URL.createObjectURL(file)
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
    if (cause.code === 'REQUEST_TIMEOUT') {
      return isMemberView.value
        ? '这张照片检查得有点慢，请稍等一下再试一次。'
        : '本地服务响应超时，可能仍在处理；请稍候重试。'
    }
    if (cause.code === 'DEPENDENCY_UNAVAILABLE') {
      return isMemberView.value
        ? '家里的服务暂时连不上，请让家人帮忙看一下。'
        : '本地服务连不上，请确认 API 已启动后重试。'
    }
    if (cause.status === 413) {
      return isMemberView.value ? '照片太大了，请换一张小一点的再试。' : '图片过大，请缩小图片后重试。'
    }
    if (cause.status === 422) {
      return isMemberView.value ? '这张照片格式不对，请重新拍一张。' : '图片格式或内容不符合要求，请重新拍摄。'
    }
    if (cause.status === 409) {
      return isMemberView.value
        ? '刚才的检查过期了，请再点一次「检查照片」。'
        : '质量凭证已失效，请重新进行质量检查。'
    }
    if (cause.status === 403 || cause.status === 404) {
      return isMemberView.value
        ? '暂时不能提交这张照片，请让家人帮忙。'
        : '当前身份或用途无权为该成员创建识别任务。'
    }
  }
  return isMemberView.value ? '提交没成功，请再试一次。' : '处理失败，未创建识别任务。请重试。'
}

async function checkQuality(): Promise<void> {
  const file = selectedFile.value
  if (!file) return
  if (!requestOptions.value.sessionToken) {
    state.value = 'error'
    error.value = '正式会话已失效，请重新登录。'
    return
  }

  const generation = ++requestGeneration
  qualityResult.value = null
  createdTask.value = null
  autoRepaired.value = false
  error.value = ''
  state.value = 'checking'
  try {
    const outcome = await runVisionQualityCheckWithRepair({
      file,
      check: current => apiClient.checkVisionQuality(current, requestOptions.value),
      isCurrent: () => generation === requestGeneration,
      onFileChanged: replaceSelectedFile,
    })
    if (!outcome || generation !== requestGeneration) return
    qualityResult.value = outcome.result
    autoRepaired.value = outcome.repaired && canCreateVisionTask(outcome.result)
    state.value = canCreateVisionTask(outcome.result) ? 'passed' : 'retake'
  } catch (cause) {
    if (generation !== requestGeneration) return
    state.value = 'error'
    error.value = explainError(cause)
  }
}

async function queueVisionTask(): Promise<void> {
  const file = selectedFile.value
  const result = qualityResult.value
  if (!file || !requestOptions.value.sessionToken || !canCreateVisionTask(result) || !result?.quality_receipt) return

  const generation = ++requestGeneration
  const memberId = props.memberId
  error.value = ''
  state.value = 'queueing'
  try {
    const task = await queuePassedVisionFile({
      file,
      result,
      requestOptions: requestOptions.value,
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
      ? (isMemberView.value
        ? '照片和刚才检查的那张对不上，请重新选图再检查。'
        : '上传文件与已检查图片不一致，已停止并清理文件，请重新检查。')
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
          {{ isMemberView ? '选择药盒照片' : '先检查图片质量，再进入识别' }}
        </h3>
      </div>
      <span
        class="pill"
        :class="state === 'queued' ? 'pine' : state === 'retake' || state === 'error' ? 'rose' : state === 'passed' ? 'gold' : 'plain'"
      >
        {{
          isMemberView
            ? (
              state === 'idle' ? '还没选照片'
              : state === 'ready' ? '还没检查'
              : state === 'checking' ? '正在检查'
              : state === 'retake' ? '请重新拍'
              : state === 'passed' ? '照片可以了'
              : state === 'queueing' ? '正在提交'
              : state === 'queued' ? '已交给家人'
              : '出了点问题'
            )
            : (
              state === 'idle' ? '等待图片'
              : state === 'ready' ? '待检查'
              : state === 'checking' ? '正在检查'
              : state === 'retake' ? '需要重拍'
              : state === 'passed' ? '质量通过'
              : state === 'queueing' ? '正在创建任务'
              : state === 'queued' ? '任务已入队'
              : '出现问题'
            )
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

    <div class="grid-two capture-layout">
      <label class="capture-zone" :class="{ checking: state === 'checking', 'has-preview': Boolean(previewUrl) }" :aria-disabled="isBusy">
        <img v-if="previewUrl" :src="previewUrl" alt="当前待检查药盒图片的本地预览" />
        <template v-else>
          <div class="capture-empty">
            <span class="capture-empty-icon"><AppIcon name="scan" :size="26" /></span>
            <strong>{{ isMemberView ? '点击选照片' : '点击选择药盒照片' }}</strong>
            <span>{{ isMemberView ? '拍照或从相册选图' : '支持 JPEG / PNG · 仅在本机预览' }}</span>
          </div>
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
          已选择：{{ selectedFile.name }}{{ isMemberView ? '（先在本机看看，还没交给家人）' : '（仅本地预览，未上传）' }}
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
          {{ isMemberView ? '这张照片不会保存，请重新拍一张。' : '本次不会上传文件，也不会创建识别任务。' }}
        </div>

        <template v-if="qualityResult?.decision === 'PASS'">
          <div class="notice ok" role="status">
            <AppIcon name="check" :size="16" />
            {{
              isMemberView
                ? (autoRepaired ? '已帮你调清楚一点，可以交给家人确认。' : '照片清楚，可以交给家人确认。')
                : (
                  autoRepaired
                    ? `已自动调整清晰度和曝光后再检查通过（配置 ${qualityResult.config_version}），可以创建本地识别任务。`
                    : `图片质量通过（配置 ${qualityResult.config_version}），可以创建本地识别任务。`
                )
            }}
          </div>
          <dl v-if="!isMemberView" class="quality-metrics">
            <div v-for="item in visibleMetrics" :key="item.key">
              <dt>{{ item.label }}</dt>
              <dd :data-passed="item.metric.passed">{{ formatMetricValue(item.key, item.metric.value) }}</dd>
            </div>
          </dl>
          <button type="button" class="btn btn-clay" :disabled="!canQueue" @click="queueVisionTask">
            {{ state === 'queueing' ? '正在提交' : isMemberView ? '交给家人确认' : '通过并创建识别任务' }}
            <AppIcon v-if="state !== 'queueing'" name="arrow-right" :size="16" />
          </button>
        </template>

        <div v-if="createdTask" class="notice ok" role="status" style="display: block">
          <strong style="display: block; margin-bottom: 4px">{{ isMemberView ? '照片已交给家人' : '本地识别任务已创建' }}</strong>
          {{ isMemberView
            ? '家人确认后，药品信息才会出现在「我的记录」里。'
            : `任务编号 ${createdTask.id} · 类型 ${createdTask.task_type?.toUpperCase?.() ?? 'OCR'} · 当前进入 OCR 待处理队列，不会自动写入健康记录。` }}
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
