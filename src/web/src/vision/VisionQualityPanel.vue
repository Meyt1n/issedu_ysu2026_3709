<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'

import { ApiClientError, apiClient } from '../api/client'
import type { VisionQualityResponse, VisionTask } from '../api/types'
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
}>()

const selectedFile = ref<File | null>(null)
const previewUrl = ref('')
const qualityResult = ref<VisionQualityResponse | null>(null)
const createdTask = ref<VisionTask | null>(null)
const state = ref<QualityFlowState>('idle')
const error = ref('')
let requestGeneration = 0

const isBusy = computed(() => state.value === 'checking' || state.value === 'queueing')
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
    error.value = '请先填写顶部的开发身份。'
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
  } catch (cause) {
    if (generation !== requestGeneration) return
    state.value = 'error'
    error.value = cause instanceof Error && cause.message === 'UPLOAD_DIGEST_MISMATCH'
      ? '上传文件与已检查图片不一致，已停止并清理文件，请重新检查。'
      : explainError(cause)
  }
}

onBeforeUnmount(releasePreview)

watch(() => [props.actorId, props.memberId, props.accessPurpose], () => {
  resetEvidence()
  state.value = selectedFile.value ? 'ready' : 'idle'
})
</script>

<template>
  <!-- This panel is authored in Chinese inside an English-labelled page (WCAG 3.1.2). -->
  <section class="panel vision-quality-panel" aria-labelledby="vision-quality-title" lang="zh-CN">
    <div class="panel-heading">
      <div>
        <p class="section-label">本地药盒采集</p>
        <h2 id="vision-quality-title">先检查图片，再进入识别</h2>
      </div>
      <span class="quality-state" :data-state="state" role="status" aria-live="polite">{{ qualityStateLabel(state) }}</span>
    </div>

    <p class="preview-note">图片只发送到本机 API。质量通过不代表药品识别或用药结论，后续结果仍需人工确认。</p>

    <div class="capture-layout">
      <div class="capture-preview">
        <img v-if="previewUrl" :src="previewUrl" alt="当前待检查药盒图片的本地预览" />
        <p v-else>把药盒正面放入画面，避免反光和裁切。</p>
      </div>
      <div class="capture-actions">
        <label class="file-picker">
          拍照或选择图片
          <input
            type="file"
            accept=".jpg,.jpeg,.png,image/jpeg,image/png"
            capture="environment"
            :disabled="isBusy"
            @change="selectFile"
          />
        </label>
        <p v-if="selectedFile" class="local-file-note">已选择：{{ selectedFile.name }}（仅本地预览）</p>
        <div class="capture-buttons">
          <button type="button" :disabled="!canCheck" @click="checkQuality">
            {{ state === 'checking' ? '正在检查' : '检查图片质量' }}
          </button>
          <button v-if="selectedFile" type="button" class="quiet-button" :disabled="isBusy" @click="clearFile">清除</button>
        </div>
      </div>
    </div>

    <p v-if="error" class="notice error" role="alert">{{ error }}</p>

    <div v-if="qualityResult?.decision === 'RETAKE'" class="quality-result retake" role="status">
      <strong>需要重新拍摄</strong>
      <ul>
        <li v-for="prompt in qualityResult.retake_prompts" :key="prompt">{{ prompt }}</li>
      </ul>
      <p>本次不会上传文件，也不会创建识别任务。</p>
    </div>

    <div v-else-if="qualityResult?.decision === 'PASS'" class="quality-result passed" role="status">
      <div>
        <strong>图片质量通过</strong>
        <span>配置 {{ qualityResult.config_version }}</span>
      </div>
      <dl class="quality-metrics">
        <div v-for="item in visibleMetrics" :key="item.key">
          <dt>{{ item.label }}</dt>
          <dd :data-passed="item.metric.passed">{{ formatMetricValue(item.key, item.metric.value) }}</dd>
        </div>
      </dl>
      <button type="button" :disabled="!canQueue" @click="queueVisionTask">
        {{ state === 'queueing' ? '正在创建任务' : '通过并创建本地识别任务' }}
      </button>
    </div>

    <div v-if="createdTask" class="quality-result queued" role="status">
      <strong>本地识别任务已创建</strong>
      <span>状态：{{ createdTask.status }}</span>
      <span>任务编号：{{ createdTask.id }}</span>
      <p>当前只进入 OCR 待处理队列，不会自动写入健康记录。</p>
    </div>
  </section>
</template>
