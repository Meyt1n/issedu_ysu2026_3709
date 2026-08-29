import { describe, expect, it } from 'vitest'

import type { VisionTaskErrorDetail } from '../api/types'
import {
  findingLabel,
  fusionStatusHint,
  visionErrorMessage,
  visionErrorNextAction,
  visionErrorTitle,
} from './visionReasons'

describe('vision family-facing reason copy', () => {
  it('translates worker errors without exposing internal model terminology', () => {
    const detail: VisionTaskErrorDetail = {
      code: 'MODEL_INFERENCE_ERROR',
      message: 'Traceback: model path C:/weights crashed',
      retryable: true,
      next_action: 'restart worker',
    }

    expect(visionErrorTitle(detail.code)).toBe('识别没有完成')
    expect(visionErrorMessage(detail)).toContain('未写入健康记录')
    expect(visionErrorNextAction(detail)).toContain('重新处理')
    expect(visionErrorMessage(detail)).not.toContain('C:/weights')
    expect(visionErrorMessage(detail)).not.toContain('model')
  })

  it('gives actionable copy for image, video, and unknown failures', () => {
    expect(visionErrorTitle('VIDEO_DURATION_EXCEEDED')).toBe('视频太长')
    expect(visionErrorNextAction({ code: 'VIDEO_DURATION_EXCEEDED' } as VisionTaskErrorDetail)).toContain('较短')
    expect(visionErrorTitle('unregistered-internal-code')).toBe('识别没有完成')
    expect(visionErrorNextAction(null)).toContain('重新拍摄')
  })

  it('translates four-state finding reasons and keeps unknown codes neutral', () => {
    expect(findingLabel('EVIDENCE_CONFLICT')).toBe('不同识别依据互相矛盾')
    expect(findingLabel('CANDIDATE_MARGIN_TOO_SMALL')).toBe('多个候选结果比较接近')
    expect(findingLabel('internal-model-stack')).toBe('有一项信息需要人工核对')
    expect(fusionStatusHint('UNKNOWN')).toContain('补拍')
    expect(fusionStatusHint('CONFLICT')).toContain('核对')
  })
})
