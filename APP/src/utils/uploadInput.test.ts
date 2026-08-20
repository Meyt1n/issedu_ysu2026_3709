import { describe, expect, it } from 'vitest'

import { MAX_MEDICINE_IMAGE_BYTES, validateMedicineImage } from './uploadInput'

function makeFile(size: number, type: string): File {
  return new File([new Uint8Array(size)], 'medicine-upload', { type })
}

describe('medicine image input validation', () => {
  it('accepts a non-empty image within the local upload limit', () => {
    expect(validateMedicineImage(makeFile(1024, 'image/jpeg'))).toEqual({ ok: true })
  })

  it('rejects a non-image before a quality-check or upload request', () => {
    const result = validateMedicineImage(makeFile(1024, 'application/pdf'))
    expect(result.ok).toBe(false)
    if (!result.ok) expect(result.message).toContain('图片文件')
  })

  it('rejects an empty image before a quality-check or upload request', () => {
    const result = validateMedicineImage(makeFile(0, 'image/png'))
    expect(result.ok).toBe(false)
    if (!result.ok) expect(result.message).toContain('为空')
  })

  it('rejects an image larger than 10 MiB locally', () => {
    const result = validateMedicineImage(makeFile(MAX_MEDICINE_IMAGE_BYTES + 1, 'image/webp'))
    expect(result.ok).toBe(false)
    if (!result.ok) expect(result.message).toContain('10 MiB')
  })
})
