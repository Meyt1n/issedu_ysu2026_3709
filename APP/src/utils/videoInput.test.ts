import { describe, expect, it } from 'vitest'

import {
  VIDEO_MAX_BYTES,
  VIDEO_MAX_DURATION_SECONDS,
  formatByteSize,
  validateMedicineVideo,
  type VideoProbe,
} from './videoInput'

function makeVideoFile(overrides: Partial<File> & { name?: string; type?: string; size?: number } = {}): File {
  const name = overrides.name ?? 'clip.mp4'
  const type = overrides.type ?? 'video/mp4'
  const size = overrides.size ?? 1024
  return new File([new Uint8Array(size)], name, { type })
}

const GOOD_PROBE: VideoProbe = { durationSeconds: 8.4, width: 720, height: 1280 }

describe('MOB-149 validateMedicineVideo', () => {
  it('通过校验并输出“将上传”摘要（竖屏）', () => {
    const result = validateMedicineVideo(makeVideoFile({ size: 2_500_000 }), GOOD_PROBE)
    expect(result.ok).toBe(true)
    expect(result.message).toBe('')
    expect(result.summary).toContain('MP4')
    expect(result.summary).toContain('8.4 秒')
    expect(result.summary).toContain('竖屏')
  })

  it('横屏视频摘要标注横屏', () => {
    const result = validateMedicineVideo(makeVideoFile(), { durationSeconds: 5, width: 1280, height: 720 })
    expect(result.ok).toBe(true)
    expect(result.summary).toContain('横屏')
  })

  it('拒绝不支持的扩展名', () => {
    const result = validateMedicineVideo(makeVideoFile({ name: 'clip.avi', type: 'video/x-msvideo' }), GOOD_PROBE)
    expect(result.ok).toBe(false)
    expect(result.message).toContain('avi')
    expect(result.message).toContain('不会上传')
  })

  it('拒绝不受支持的 MIME 类型', () => {
    const result = validateMedicineVideo(makeVideoFile({ name: 'clip.mp4', type: 'video/webm' }), GOOD_PROBE)
    expect(result.ok).toBe(false)
    expect(result.message).toContain('video/webm')
  })

  it('允许 Android 文件选择器未提供 MIME 的 MP4', () => {
    const result = validateMedicineVideo(makeVideoFile({ name: 'clip.mp4', type: '' }), GOOD_PROBE)
    expect(result.ok).toBe(true)
    expect(result.summary).toContain('MP4')
  })

  it('允许未提供 MIME 的 MOV，并接受大小写不同的标准 MIME', () => {
    const result = validateMedicineVideo(makeVideoFile({ name: 'clip.mov', type: '' }), GOOD_PROBE)
    expect(result.ok).toBe(true)
    expect(result.summary).toContain('MOV')

    const normalized = validateMedicineVideo(makeVideoFile({ name: 'clip.mov', type: 'Video/QuickTime' }), GOOD_PROBE)
    expect(normalized.ok).toBe(true)
  })

  it('拒绝超过大小上限的视频', () => {
    const result = validateMedicineVideo(makeVideoFile({ size: VIDEO_MAX_BYTES + 1 }), GOOD_PROBE)
    expect(result.ok).toBe(false)
    expect(result.message).toContain('超过上限')
  })

  it('拒绝无法读取元数据的视频（fail-closed）', () => {
    const result = validateMedicineVideo(makeVideoFile(), { durationSeconds: 0, width: 0, height: 0 })
    expect(result.ok).toBe(false)
    expect(result.message).toContain('无法读取视频时长')
  })

  it('拒绝超过时长上限的视频', () => {
    const result = validateMedicineVideo(makeVideoFile(), {
      durationSeconds: VIDEO_MAX_DURATION_SECONDS + 0.5,
      width: 720,
      height: 1280,
    })
    expect(result.ok).toBe(false)
    expect(result.message).toContain('超过上限 30 秒')
  })
})

describe('MOB-149 formatByteSize', () => {
  it('MB 与 KB 两种呈现', () => {
    expect(formatByteSize(2_500_000)).toBe('2.4 MB')
    expect(formatByteSize(2048)).toBe('2 KB')
    expect(formatByteSize(500)).toBe('1 KB')
  })
})
