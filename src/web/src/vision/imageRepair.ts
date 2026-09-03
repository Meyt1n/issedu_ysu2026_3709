import type { VisionQualityResponse } from '../api/types'

/** Demo quality-gate floor; keep in sync with `QualityThresholds` in quality_gate.py. */
export const MIN_VISION_WIDTH = 640
export const MIN_VISION_HEIGHT = 480
export const MAX_VISION_EDGE = 1920

export const REPAIRABLE_QUALITY_REASONS = [
  'BLURRY',
  'TOO_DARK',
  'TOO_BRIGHT',
  'TOO_MANY_DARK_PIXELS',
  'TOO_MANY_BRIGHT_PIXELS',
  'GLARE',
  'IMAGE_TOO_SMALL',
] as const

const repairableReasonSet = new Set<string>(REPAIRABLE_QUALITY_REASONS)

export function shouldAttemptAutoRepair(reasons: readonly string[] | undefined): boolean {
  if (!reasons?.length) return false
  return reasons.some(reason => repairableReasonSet.has(reason))
}

export function computeUpscaleSize(
  srcWidth: number,
  srcHeight: number,
  minWidth = MIN_VISION_WIDTH,
  minHeight = MIN_VISION_HEIGHT,
  maxEdge = MAX_VISION_EDGE,
): { width: number, height: number, scale: number } {
  const width = Math.max(1, Math.round(srcWidth))
  const height = Math.max(1, Math.round(srcHeight))
  let scale = Math.max(1, minWidth / width, minHeight / height)
  let nextWidth = Math.max(1, Math.round(width * scale))
  let nextHeight = Math.max(1, Math.round(height * scale))
  const edge = Math.max(nextWidth, nextHeight)
  if (edge > maxEdge) {
    const down = maxEdge / edge
    nextWidth = Math.max(1, Math.round(nextWidth * down))
    nextHeight = Math.max(1, Math.round(nextHeight * down))
    scale *= down
  }
  return { width: nextWidth, height: nextHeight, scale }
}

export function enhancePixelBuffer(
  data: Uint8ClampedArray,
  options: { reasons?: readonly string[] } = {},
): boolean {
  const reasons = new Set(options.reasons ?? [])
  const pixelCount = data.length / 4
  if (pixelCount < 1) return false

  let luminanceSum = 0
  for (let index = 0; index < data.length; index += 4) {
    luminanceSum += 0.299 * data[index] + 0.587 * data[index + 1] + 0.114 * data[index + 2]
  }
  const mean = luminanceSum / pixelCount

  let brightness = 0
  let contrast = 1.12
  if (reasons.has('TOO_DARK') || reasons.has('TOO_MANY_DARK_PIXELS') || mean < 90) {
    brightness = mean < 55 ? 36 : 24
    contrast = 1.2
  } else if (reasons.has('TOO_BRIGHT') || reasons.has('TOO_MANY_BRIGHT_PIXELS') || mean > 200) {
    brightness = -16
    contrast = 1.06
  }
  if (reasons.has('GLARE')) brightness -= 6

  const compressHighlights = reasons.has('GLARE') || reasons.has('TOO_BRIGHT') || reasons.has('TOO_MANY_BRIGHT_PIXELS')
  const midpoint = 128
  for (let index = 0; index < data.length; index += 4) {
    for (let channel = 0; channel < 3; channel += 1) {
      let value = (data[index + channel] - midpoint) * contrast + midpoint + brightness
      if (compressHighlights && value > 230) value = 230 + (value - 230) * 0.35
      data[index + channel] = value < 0 ? 0 : value > 255 ? 255 : value
    }
  }
  return true
}

export function sharpenPixelBuffer(
  data: Uint8ClampedArray,
  width: number,
  height: number,
  amount = 0.32,
): void {
  if (width < 3 || height < 3 || amount <= 0) return
  const source = new Uint8ClampedArray(data)
  const row = width * 4
  for (let y = 1; y < height - 1; y += 1) {
    for (let x = 1; x < width - 1; x += 1) {
      const index = y * row + x * 4
      for (let channel = 0; channel < 3; channel += 1) {
        const center = source[index + channel]
        const blur = (
          source[index - row + channel]
          + source[index + row + channel]
          + source[index - 4 + channel]
          + source[index + 4 + channel]
        ) / 4
        const value = center + amount * (center - blur)
        data[index + channel] = value < 0 ? 0 : value > 255 ? 255 : value
      }
    }
  }
}

function outputType(file: File): 'image/jpeg' | 'image/png' {
  return file.type === 'image/png' ? 'image/png' : 'image/jpeg'
}

function outputName(file: File, type: 'image/jpeg' | 'image/png'): string {
  if (type === 'image/png') return file.name
  if (/\.jpe?g$/i.test(file.name)) return file.name
  return `${file.name.replace(/\.[^.]+$/, '')}.jpg`
}

function makeCanvas(width: number, height: number): OffscreenCanvas | HTMLCanvasElement {
  if (typeof OffscreenCanvas === 'function') return new OffscreenCanvas(width, height)
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  return canvas
}

async function canvasToFile(
  canvas: OffscreenCanvas | HTMLCanvasElement,
  original: File,
): Promise<File> {
  const type = outputType(original)
  const quality = type === 'image/jpeg' ? 0.92 : undefined
  const blob = 'convertToBlob' in canvas
    ? await canvas.convertToBlob({ type, quality })
    : await new Promise<Blob>((resolve, reject) => {
      canvas.toBlob(result => {
        if (result) resolve(result)
        else reject(new Error('IMAGE_ENCODE_FAILED'))
      }, type, quality)
    })
  return new File([blob], outputName(original, type), { type, lastModified: Date.now() })
}

export async function prepareVisionImage(file: File): Promise<{ file: File, changed: boolean }> {
  return rasterizeVisionImage(file, { mode: 'prepare' })
}

export async function enhanceVisionImage(
  file: File,
  options: { reasons?: readonly string[] } = {},
): Promise<{ file: File, changed: boolean }> {
  return rasterizeVisionImage(file, { mode: 'repair', reasons: options.reasons })
}

async function rasterizeVisionImage(
  file: File,
  options: { mode: 'prepare' | 'repair', reasons?: readonly string[] },
): Promise<{ file: File, changed: boolean }> {
  if (typeof createImageBitmap !== 'function') return { file, changed: false }
  let bitmap: ImageBitmap
  try {
    bitmap = await createImageBitmap(file)
  } catch {
    return { file, changed: false }
  }

  try {
    const target = computeUpscaleSize(bitmap.width, bitmap.height)
    const needResize = target.width !== bitmap.width || target.height !== bitmap.height
    if (options.mode === 'prepare' && !needResize) return { file, changed: false }

    const canvas = makeCanvas(target.width, target.height)
    const context = canvas.getContext('2d')
    if (!context || !('drawImage' in context) || !('getImageData' in context)) {
      return { file, changed: false }
    }
    context.imageSmoothingEnabled = true
    if ('imageSmoothingQuality' in context) context.imageSmoothingQuality = 'high'
    context.drawImage(bitmap, 0, 0, target.width, target.height)

    if (options.mode === 'repair') {
      const imageData = context.getImageData(0, 0, target.width, target.height)
      enhancePixelBuffer(imageData.data, { reasons: options.reasons })
      const amount = options.reasons?.includes('BLURRY') ? 0.42 : 0.28
      sharpenPixelBuffer(imageData.data, target.width, target.height, amount)
      context.putImageData(imageData, 0, 0)
    }

    return { file: await canvasToFile(canvas, file), changed: true }
  } catch {
    return { file, changed: false }
  } finally {
    bitmap.close()
  }
}

interface QualityCheckRepairInput {
  file: File
  check: (file: File) => Promise<VisionQualityResponse>
  isCurrent: () => boolean
  onFileChanged?: (file: File) => void
  prepareImage?: (file: File) => Promise<{ file: File, changed: boolean }>
  repairImage?: (file: File, reasons: readonly string[]) => Promise<{ file: File, changed: boolean }>
}

export interface QualityCheckRepairOutcome {
  result: VisionQualityResponse
  file: File
  /**
   * 是否真的做过像素级增强（亮度/对比度/锐化）。
   * 只有这一项为真时，才能对用户说「已帮你调清楚一点」。
   */
  repaired: boolean
  /** 是否仅为满足最小尺寸做过等比放大——那不是画质修复，别当成修复宣称。 */
  upscaled: boolean
}

export async function runVisionQualityCheckWithRepair(
  input: QualityCheckRepairInput,
): Promise<QualityCheckRepairOutcome | null> {
  let current = input.file
  let upscaled = false
  let repaired = false

  const prepared = await (input.prepareImage ?? prepareVisionImage)(current)
  if (!input.isCurrent()) return null
  if (prepared.changed) {
    current = prepared.file
    upscaled = true
    input.onFileChanged?.(current)
  }

  let result = await input.check(current)
  if (!input.isCurrent()) return null

  if (shouldAttemptAutoRepair(result.reasons)) {
    const enhanced = await (input.repairImage ?? ((file, reasons) => enhanceVisionImage(file, { reasons })))(
      current,
      result.reasons,
    )
    if (!input.isCurrent()) return null
    if (enhanced.changed) {
      current = enhanced.file
      repaired = true
      input.onFileChanged?.(current)
      result = await input.check(current)
      if (!input.isCurrent()) return null
    }
  }

  return { result, file: current, repaired, upscaled }
}
