import type { VisionTaskErrorDetail } from '../api/types'

/**
 * Family-facing labels for the internal vision pipeline codes.
 *
 * The API keeps stable codes for operators and tests, but the scan page must
 * not make a user translate model, worker, or pipeline terminology. Unknown
 * values intentionally fall back to a neutral retry instruction instead of
 * echoing an internal code or local path.
 */
const ERROR_LABELS: Record<string, { title: string; message: string; nextAction: string }> = {
  IMAGE_DECODE_FAILED: {
    title: '图片无法读取',
    message: '这张图片没有成功打开。',
    nextAction: '请重新拍一张清晰的药盒正面照片。',
  },
  PREPROCESS_FAILED: {
    title: '图片处理没有完成',
    message: '这张图片或视频暂时无法处理。',
    nextAction: '请检查文件是否完整、画面是否清楚，然后重新处理。',
  },
  VIDEO_DURATION_EXCEEDED: {
    title: '视频太长',
    message: '视频超过了本地处理时长限制。',
    nextAction: '请截取较短的视频，或直接拍一张药盒正面照片。',
  },
  VIDEO_SIZE_EXCEEDED: {
    title: '视频文件太大',
    message: '视频超过了本地处理大小限制。',
    nextAction: '请压缩视频或改拍一张照片后重试。',
  },
  MODEL_NOT_FOUND: {
    title: '识别服务暂时不可用',
    message: '家里的识别服务还没有准备好。',
    nextAction: '请稍后再试；如果一直这样，请让家人检查本地服务。',
  },
  MODEL_INFERENCE_ERROR: {
    title: '识别没有完成',
    message: '这次识别过程中遇到了问题，未写入健康记录。',
    nextAction: '请确认本地服务正常后点击“重新处理”，也可以重新拍照。',
  },
  TIMEOUT: {
    title: '识别等待时间较长',
    message: '本地处理超过了等待时间，健康记录没有被修改。',
    nextAction: '请稍后点击“重新处理”，或让家人检查本地服务。',
  },
  WORKER_MAX_ATTEMPTS: {
    title: '识别暂时没有完成',
    message: '系统已多次尝试处理，但没有得到可用结果。',
    nextAction: '请重新拍摄清晰照片，或让家人检查本地识别服务。',
  },
  UNKNOWN: {
    title: '识别没有完成',
    message: '这次没有得到可用的识别结果，健康记录没有被修改。',
    nextAction: '请保持药盒正面、完整入框并重新处理。',
  },
}

const FINDING_LABELS: Record<string, string> = {
  BARCODE_EXACT: '条码与资料一致',
  NAME_EXACT: '药品名称与资料一致',
  NO_MASTER_CANDIDATE: '没有找到可核对的药品资料',
  SINGLE_CHANNEL_EVIDENCE: '目前只有一种识别依据',
  FUSION_SCORE_BELOW_UNKNOWN_THRESHOLD: '识别依据不足，暂时无法确认',
  FUSION_SCORE_BELOW_MATCH_THRESHOLD: '识别依据还不够充分',
  CANDIDATE_MARGIN_TOO_SMALL: '多个候选结果比较接近',
  EVIDENCE_CONFLICT: '不同识别依据互相矛盾',
  OCR_NAME_MASTER_CONFLICT: '图片文字与药品资料不一致',
  BARCODE_MASTER_CONFLICT: '条码与药品资料不一致',
  PACKAGING_MASTER_CONFLICT: '包装类型与药品资料不一致',
  METADATA_MASTER_CONFLICT: '规格或厂家信息与药品资料不一致',
}

const DEFAULT_ERROR: { title: string; message: string; nextAction: string } = {
  title: '识别没有完成',
  message: '这次没有得到可用结果，健康记录没有被修改。',
  nextAction: '请重新拍摄清晰的药盒正面照片后重试。',
}

export function visionErrorCopy(code: string | null | undefined): { title: string; message: string; nextAction: string } {
  return (code ? ERROR_LABELS[code] : undefined) ?? DEFAULT_ERROR
}

export function visionErrorTitle(code: string | null | undefined): string {
  return visionErrorCopy(code).title
}

export function visionErrorMessage(detail: VisionTaskErrorDetail | null | undefined): string {
  if (!detail) return DEFAULT_ERROR.message
  return visionErrorCopy(detail.code).message
}

export function visionErrorNextAction(detail: VisionTaskErrorDetail | null | undefined): string {
  if (!detail) return DEFAULT_ERROR.nextAction
  return visionErrorCopy(detail.code).nextAction
}

export function findingLabel(code: string | null | undefined): string {
  if (!code) return '需要人工核对'
  return FINDING_LABELS[code] ?? '有一项信息需要人工核对'
}

export function fusionReasonLabel(code: string | null | undefined): string {
  return findingLabel(code)
}

export function fusionStatusHint(status: string | null | undefined): string {
  if (status === 'CONFLICT') return '识别信息彼此不一致，请打开下方依据交给家人核对。'
  if (status === 'UNKNOWN') return '暂时没有足够依据确认药品，请补拍清晰照片或补充条码。'
  if (status === 'REVIEW') return '信息还不完整，需要家人查看候选后再决定。'
  if (status === 'MATCHED') return '候选信息较一致，但仍须人工确认后才能记入健康记录。'
  if (status === 'READY_FOR_FUSION') return '证据已准备好，下一步由本地规则继续核对。'
  return '识别结果仅供核对，确认前不会写入健康记录。'
}
