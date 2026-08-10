import type {
  CreateVisionTaskInput,
  RequestOptions,
  UploadedFile,
  VisionQualityResponse,
  VisionTask,
} from '../api/types'

export type QualityFlowState =
  | 'idle'
  | 'ready'
  | 'checking'
  | 'retake'
  | 'passed'
  | 'queueing'
  | 'queued'
  | 'error'

const allowedImageTypes = new Set(['image/jpeg', 'image/png'])
const allowedExtensions = new Set(['jpg', 'jpeg', 'png'])

export function validateVisionImage(file: File): string | null {
  const extension = file.name.split('.').pop()?.toLowerCase() ?? ''
  if (!allowedImageTypes.has(file.type) || !allowedExtensions.has(extension)) {
    return '请选择 JPEG 或 PNG 图片。'
  }
  if (file.size === 0) return '图片为空，请重新拍摄或选择。'
  return null
}

export function canCreateVisionTask(result: VisionQualityResponse | null): boolean {
  return Boolean(
    result?.decision === 'PASS'
      && result.allow_downstream
      && result.quality_receipt,
  )
}

export const metricLabels: Record<string, string> = {
  blur_variance: '清晰度',
  mean_luminance: '平均亮度',
  glare_ratio: '反光占比',
  subject_area_ratio: '主体占比',
}

export function formatMetricValue(key: string, value: number): string {
  if (key.endsWith('_ratio')) return `${(value * 100).toFixed(1)}%`
  return Number.isInteger(value) ? String(value) : value.toFixed(1)
}

interface VisionQueueApi {
  uploadFile(file: File, options?: RequestOptions): Promise<UploadedFile>
  deleteUploadedFile(storageKey: string, options?: RequestOptions): Promise<{ deleted: boolean }>
  createVisionTask(input: CreateVisionTaskInput, options?: RequestOptions): Promise<VisionTask>
}

interface QueueVisionFileInput {
  file: File
  result: VisionQualityResponse
  actorId: string
  memberId?: string
  idempotencyKey: string
  isCurrent: () => boolean
}

export async function queuePassedVisionFile(
  input: QueueVisionFileInput,
  api: VisionQueueApi,
): Promise<VisionTask | null> {
  if (!canCreateVisionTask(input.result) || !input.result.quality_receipt) {
    throw new Error('QUALITY_GATE_REQUIRED')
  }

  const requestOptions = { actorId: input.actorId }
  const uploaded = await api.uploadFile(input.file, requestOptions)
  const cleanup = () => api
    .deleteUploadedFile(uploaded.storage_key, requestOptions)
    .catch(() => undefined)
  if (!input.isCurrent()) {
    await cleanup()
    return null
  }
  try {
    if (uploaded.hash_algo !== 'sha256' || uploaded.hash !== input.result.source.sha256) {
      throw new Error('UPLOAD_DIGEST_MISMATCH')
    }
    return await api.createVisionTask({
      file_id: uploaded.storage_key,
      member_id: input.memberId,
      task_type: 'ocr',
      idempotency_key: input.idempotencyKey,
      quality_receipt: input.result.quality_receipt,
    }, requestOptions)
  } catch (cause) {
    await cleanup()
    throw cause
  }
}
