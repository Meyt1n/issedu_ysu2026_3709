/** 轻触觉反馈：设备支持时短震动确认操作，不支持时静默。 */
export function tapFeedback(pattern: number | number[] = 12): boolean {
  if (typeof navigator === 'undefined' || typeof navigator.vibrate !== 'function') return false
  try {
    return navigator.vibrate(pattern)
  } catch {
    return false
  }
}
