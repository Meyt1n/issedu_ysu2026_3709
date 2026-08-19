import { describe, expect, it, vi } from 'vitest'

import type { VisionQualityResponse } from '../api/types'
import {
  canCreateVisionTask,
  formatMetricValue,
  qualityStateLabel,
  qualityStateLabels,
  queuePassedVisionFile,
  validateVisionImage,
} from './qualityView'

function qualityResult(overrides: Partial<VisionQualityResponse> = {}): VisionQualityResponse {
  return {
    schema_version: 'vision-quality-result-v1',
    config_version: 'opencv-quality-demo-v1',
    media_type: 'image',
    decision: 'PASS',
    allow_downstream: true,
    source: { source_id: 'hidden', sha256: 'a'.repeat(64), digest_scope: 'uploaded_file_bytes' },
    metrics: {},
    thresholds: {},
    reasons: [],
    retake_prompts: [],
    correction: null,
    frames: [],
    limitations: [],
    quality_receipt: 'signed-receipt',
    ...overrides,
  }
}

describe('vision quality view rules', () => {
  it('accepts only non-empty JPEG and PNG files', () => {
    expect(validateVisionImage(new File(['image'], 'box.jpg', { type: 'image/jpeg' }))).toBeNull()
    expect(validateVisionImage(new File(['image'], 'box.png', { type: 'image/png' }))).toBeNull()
    expect(validateVisionImage(new File(['image'], 'box.jpg', { type: 'video/mp4' }))).toContain('JPEG')
    expect(validateVisionImage(new File([], 'box.png', { type: 'image/png' }))).toContain('为空')
  })

  it('allows queueing only for an explicit PASS carrying a receipt', () => {
    expect(canCreateVisionTask(qualityResult())).toBe(true)
    expect(canCreateVisionTask(qualityResult({ decision: 'RETAKE' }))).toBe(false)
    expect(canCreateVisionTask(qualityResult({ allow_downstream: false }))).toBe(false)
    expect(canCreateVisionTask(qualityResult({ quality_receipt: null }))).toBe(false)
  })

  it('formats proxy ratios as percentages without changing evidence', () => {
    expect(formatMetricValue('glare_ratio', 0.125)).toBe('12.5%')
    expect(formatMetricValue('blur_variance', 123.456)).toBe('123.5')
  })

  it('maps every flow state to a human-readable status label', () => {
    const states = ['idle', 'ready', 'checking', 'retake', 'passed', 'queueing', 'queued', 'error'] as const
    for (const state of states) {
      const label = qualityStateLabel(state)
      expect(label).toBe(qualityStateLabels[state])
      expect(label).not.toBe(state)
      expect(label.length).toBeGreaterThan(0)
    }
  })

  it('does not upload or queue a RETAKE result', async () => {
    const api = queueApi()

    await expect(queuePassedVisionFile({
      file: new File(['image'], 'box.png', { type: 'image/png' }),
      result: qualityResult({ decision: 'RETAKE', allow_downstream: false, quality_receipt: null }),
      actorId: 'owner-a',
      idempotencyKey: 'request-1',
      isCurrent: () => true,
    }, api)).rejects.toThrow('QUALITY_GATE_REQUIRED')

    expect(api.uploadFile).not.toHaveBeenCalled()
    expect(api.createVisionTask).not.toHaveBeenCalled()
  })

  it('does not upload a passed result without a selected member', async () => {
    const api = queueApi()

    await expect(queuePassedVisionFile({
      file: new File(['image'], 'box.png', { type: 'image/png' }),
      result: qualityResult(),
      actorId: 'owner-a',
      idempotencyKey: 'request-without-member',
      isCurrent: () => true,
    }, api)).rejects.toThrow('MEMBER_REQUIRED')

    expect(api.uploadFile).not.toHaveBeenCalled()
    expect(api.createVisionTask).not.toHaveBeenCalled()
  })

  it('uses the immutable actor to clean an upload after identity changes', async () => {
    let current = true
    const api = queueApi()
    api.uploadFile.mockImplementation(async () => {
      current = false
      return uploadedFile()
    })

    const task = await queuePassedVisionFile({
      file: new File(['image'], 'box.png', { type: 'image/png' }),
      result: qualityResult(),
      actorId: 'owner-before-switch',
      memberId: 'member-before-switch',
      accessPurpose: 'family-care',
      idempotencyKey: 'request-2',
      isCurrent: () => current,
    }, api)

    expect(task).toBeNull()
    expect(api.createVisionTask).not.toHaveBeenCalled()
    expect(api.deleteUploadedFile).toHaveBeenCalledWith(
      'stored.png',
      { actorId: 'owner-before-switch', accessPurpose: 'family-care' },
    )
  })

  it('cleans digest mismatches and task creation failures', async () => {
    const mismatchApi = queueApi({ hash: 'b'.repeat(64) })
    const input = {
      file: new File(['image'], 'box.png', { type: 'image/png' }),
      result: qualityResult(),
      actorId: 'owner-a',
      memberId: 'member-a',
      idempotencyKey: 'request-3',
      isCurrent: () => true,
    }

    await expect(queuePassedVisionFile(input, mismatchApi)).rejects.toThrow('UPLOAD_DIGEST_MISMATCH')
    expect(mismatchApi.deleteUploadedFile).toHaveBeenCalledWith('stored.png', { actorId: 'owner-a' })

    const failingApi = queueApi()
    failingApi.createVisionTask.mockRejectedValue(new Error('TASK_FAILED'))
    await expect(queuePassedVisionFile(input, failingApi)).rejects.toThrow('TASK_FAILED')
    expect(failingApi.deleteUploadedFile).toHaveBeenCalledWith('stored.png', { actorId: 'owner-a' })
  })

  it('keeps an already-created task bound to the immutable actor during a late switch', async () => {
    let current = true
    const api = queueApi()
    api.createVisionTask.mockImplementation(async () => {
      current = false
      return queueApi().createVisionTask()
    })

    const task = await queuePassedVisionFile({
      file: new File(['image'], 'box.png', { type: 'image/png' }),
      result: qualityResult(),
      actorId: 'owner-before-switch',
      memberId: 'member-before-switch',
      idempotencyKey: 'request-4',
      isCurrent: () => current,
    }, api)

    expect(task?.status).toBe('queued')
    expect(api.createVisionTask).toHaveBeenCalledWith(
      expect.objectContaining({ member_id: 'member-before-switch' }),
      { actorId: 'owner-before-switch' },
    )
    expect(api.deleteUploadedFile).not.toHaveBeenCalled()
  })
})

function uploadedFile(overrides = {}) {
  return {
    original_name: 'box.png',
    storage_key: 'stored.png',
    size_bytes: 5,
    hash_algo: 'sha256',
    hash: 'a'.repeat(64),
    extension: '.png',
    ...overrides,
  }
}

function queueApi(uploadOverrides = {}) {
  return {
    uploadFile: vi.fn().mockResolvedValue(uploadedFile(uploadOverrides)),
    deleteUploadedFile: vi.fn().mockResolvedValue({ deleted: true }),
    createVisionTask: vi.fn().mockResolvedValue({
      id: 'task-1',
      household_id: 'system',
      member_id: null,
      file_id: 'stored.png',
      task_type: 'ocr',
      status: 'queued',
      error_code: null,
      error_message: null,
      error_detail: null,
      preprocess_version: 'opencv-quality-demo-v1',
      input_digest: 'a'.repeat(64),
      created_by: 'owner-a',
      created_at: '2026-08-11T00:00:00Z',
    }),
  }
}
