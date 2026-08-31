import { describe, expect, it } from 'vitest'

import {
  YOLO_OVERLAY_MIN_CONFIDENCE,
  yoloBoxMeetsOverlayThreshold,
  yoloBoxesForOverlay,
} from './yoloOverlay'

describe('YOLO overlay confidence floor', () => {
  it('uses 0.8 as the display threshold', () => {
    expect(YOLO_OVERLAY_MIN_CONFIDENCE).toBe(0.8)
  })

  it('hides boxes below 0.8 and shows boxes at or above 0.8', () => {
    expect(yoloBoxMeetsOverlayThreshold(0.79)).toBe(false)
    expect(yoloBoxMeetsOverlayThreshold(0.8)).toBe(true)
    expect(yoloBoxMeetsOverlayThreshold(0.93)).toBe(true)
  })

  it('only keeps YOLO regions that pass the overlay floor', () => {
    const items = [
      { id: 'yolo-low', channel: 'yolo', confidence: 0.42, region: { width: 0.4, height: 0.5 } },
      { id: 'yolo-ok', channel: 'yolo', confidence: 0.81, region: { width: 0.4, height: 0.5 } },
      { id: 'yolo-empty', channel: 'yolo', confidence: 0.99, region: { width: 0, height: 0 } },
      { id: 'ocr-high', channel: 'ocr', confidence: 0.99, region: { width: 0.2, height: 0.1 } },
    ]

    expect(yoloBoxesForOverlay(items).map(item => item.id)).toEqual(['yolo-ok'])
  })
})
