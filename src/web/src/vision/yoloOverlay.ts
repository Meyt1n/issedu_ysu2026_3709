/** Overlay-only floor for YOLO package boxes on the scan/review image. */
export const YOLO_OVERLAY_MIN_CONFIDENCE = 0.8

type OverlayCandidate = {
  channel: string
  confidence: number
  region?: { width: number, height: number } | null
}

export function yoloBoxMeetsOverlayThreshold(
  confidence: number,
  threshold = YOLO_OVERLAY_MIN_CONFIDENCE,
): boolean {
  return Number.isFinite(confidence) && confidence >= threshold
}

export function yoloBoxesForOverlay<T extends OverlayCandidate>(
  items: readonly T[],
  threshold = YOLO_OVERLAY_MIN_CONFIDENCE,
): T[] {
  return items.filter(item =>
    item.channel === 'yolo'
    && item.region
    && item.region.width > 0
    && item.region.height > 0
    && yoloBoxMeetsOverlayThreshold(item.confidence, threshold),
  )
}
