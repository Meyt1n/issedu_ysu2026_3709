import { describe, expect, it, vi } from 'vitest'

import type { VisionQualityResponse } from '../api/types'
import {
  computeUpscaleSize,
  enhancePixelBuffer,
  runVisionQualityCheckWithRepair,
  sharpenPixelBuffer,
  shouldAttemptAutoRepair,
} from './imageRepair'

function qualityResult(overrides: Partial<VisionQualityResponse> = {}): VisionQualityResponse {
  return {
    schema_version: 'vision-quality-result-v1',
    config_version: 'opencv-quality-demo-v2-lenient-exposure',
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

describe('vision image repair helpers', () => {
  it('scales small images up to the quality-gate floor without stretching', () => {
    expect(computeUpscaleSize(160, 120)).toEqual({ width: 640, height: 480, scale: 4 })
    expect(computeUpscaleSize(800, 600)).toEqual({ width: 800, height: 600, scale: 1 })
    expect(computeUpscaleSize(400, 800)).toEqual({ width: 640, height: 1280, scale: 1.6 })
  })

  it('caps an extreme upscale so the long edge stays within the canvas budget', () => {
    const sized = computeUpscaleSize(10, 2)
    expect(sized.width).toBeLessThanOrEqual(1920)
    expect(sized.height).toBeLessThanOrEqual(1920)
    expect(sized.width / sized.height).toBeCloseTo(10 / 2, 5)
  })

  it('only auto-repairs known exposure, blur, glare and size reasons', () => {
    expect(shouldAttemptAutoRepair([])).toBe(false)
    expect(shouldAttemptAutoRepair(['SUBJECT_CROPPED'])).toBe(false)
    expect(shouldAttemptAutoRepair(['synthetic blur'])).toBe(false)
    expect(shouldAttemptAutoRepair(['BLURRY'])).toBe(true)
    expect(shouldAttemptAutoRepair(['TOO_DARK', 'IMAGE_TOO_SMALL'])).toBe(true)
  })

  it('lifts a dark buffer so OCR-facing contrast is higher', () => {
    const data = new Uint8ClampedArray([40, 40, 40, 255, 36, 32, 30, 255])
    expect(enhancePixelBuffer(data, { reasons: ['TOO_DARK'] })).toBe(true)
    expect(data[0]).toBeGreaterThan(40)
    expect(data[4]).toBeGreaterThan(36)
  })

  it('compresses clipped highlights when glare is reported', () => {
    const data = new Uint8ClampedArray([250, 250, 250, 255, 240, 240, 240, 255])
    enhancePixelBuffer(data, { reasons: ['GLARE'] })
    expect(data[0]).toBeLessThan(250)
  })

  it('increases local contrast on a darker neighbour field', () => {
    const width = 3
    const height = 3
    const data = new Uint8ClampedArray(width * height * 4)
    for (let index = 0; index < data.length; index += 4) {
      data[index] = 80
      data[index + 1] = 80
      data[index + 2] = 80
      data[index + 3] = 255
    }
    data[16] = 160
    data[17] = 160
    data[18] = 160
    sharpenPixelBuffer(data, width, height, 0.5)
    expect(data[16]).toBeGreaterThan(160)
  })
})

describe('vision quality check with one local repair pass', () => {
  it('upscales first, then repairs RETAKE reasons and rechecks the enhanced file', async () => {
    const original = new File(['raw'], 'box.jpg', { type: 'image/jpeg' })
    const prepared = new File(['prepared'], 'box.jpg', { type: 'image/jpeg' })
    const repaired = new File(['repaired'], 'box.jpg', { type: 'image/jpeg' })
    const seen: string[] = []
    const files: File[] = []

    const outcome = await runVisionQualityCheckWithRepair({
      file: original,
      isCurrent: () => true,
      onFileChanged: file => files.push(file),
      prepareImage: async file => {
        expect(file).toBe(original)
        return { file: prepared, changed: true }
      },
      repairImage: async (file, reasons) => {
        expect(file).toBe(prepared)
        expect(reasons).toEqual(['BLURRY', 'TOO_DARK'])
        return { file: repaired, changed: true }
      },
      check: async file => {
        seen.push(file === prepared ? 'prepared' : file === repaired ? 'repaired' : 'other')
        if (file === prepared) {
          return qualityResult({
            decision: 'RETAKE',
            allow_downstream: false,
            quality_receipt: null,
            reasons: ['BLURRY', 'TOO_DARK'],
          })
        }
        return qualityResult()
      },
    })

    expect(outcome?.repaired).toBe(true)
    expect(outcome?.upscaled).toBe(true)
    expect(outcome?.file).toBe(repaired)
    expect(outcome?.result.decision).toBe('PASS')
    expect(seen).toEqual(['prepared', 'repaired'])
    expect(files).toEqual([prepared, repaired])
  })

  it('放大到最小尺寸不算画质修复：upscaled 为真而 repaired 为假', async () => {
    const original = new File(['raw'], 'box.jpg', { type: 'image/jpeg' })
    const prepared = new File(['prepared'], 'box.jpg', { type: 'image/jpeg' })
    const repairImage = vi.fn()

    const outcome = await runVisionQualityCheckWithRepair({
      file: original,
      isCurrent: () => true,
      // 小图被等比放大到 640×480 下限，但像素内容未增强。
      prepareImage: async () => ({ file: prepared, changed: true }),
      repairImage,
      check: async () => qualityResult(),
    })

    expect(outcome?.upscaled).toBe(true)
    expect(outcome?.repaired).toBe(false)
    expect(outcome?.file).toBe(prepared)
    expect(repairImage).not.toHaveBeenCalled()
  })

  it('does not rewrite a passing image that has no repairable reasons', async () => {
    const original = new File(['raw'], 'box.jpg', { type: 'image/jpeg' })
    const repairImage = vi.fn()

    const outcome = await runVisionQualityCheckWithRepair({
      file: original,
      isCurrent: () => true,
      prepareImage: async file => ({ file, changed: false }),
      repairImage,
      check: async () => qualityResult(),
    })

    expect(outcome?.repaired).toBe(false)
    expect(outcome?.upscaled).toBe(false)
    expect(outcome?.file).toBe(original)
    expect(repairImage).not.toHaveBeenCalled()
  })

  it('stops after a hard RETAKE that cannot be auto-repaired', async () => {
    const original = new File(['raw'], 'box.jpg', { type: 'image/jpeg' })
    const repairImage = vi.fn()
    const check = vi.fn(async () => qualityResult({
      decision: 'RETAKE',
      allow_downstream: false,
      quality_receipt: null,
      reasons: ['SUBJECT_CROPPED'],
    }))

    const outcome = await runVisionQualityCheckWithRepair({
      file: original,
      isCurrent: () => true,
      prepareImage: async file => ({ file, changed: false }),
      repairImage,
      check,
    })

    expect(outcome?.result.decision).toBe('RETAKE')
    expect(repairImage).not.toHaveBeenCalled()
    expect(check).toHaveBeenCalledTimes(1)
  })

  it('returns null when the caller cancelled during prepare', async () => {
    const outcome = await runVisionQualityCheckWithRepair({
      file: new File(['raw'], 'box.jpg', { type: 'image/jpeg' }),
      isCurrent: () => false,
      prepareImage: async file => ({ file, changed: true }),
      check: async () => qualityResult(),
    })
    expect(outcome).toBeNull()
  })
})
