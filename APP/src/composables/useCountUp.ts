import { ref, watch, type Ref } from 'vue'

import { useA11y } from '@/stores/accessibility'

function easeOutCubic(t: number): number {
  return 1 - Math.pow(1 - t, 3)
}

/**
 * 数字滚动：源值变化时用 rAF 做缓出滚动动画。
 * 减少动效开启或环境不支持 rAF 时直接跳到终值。
 */
export function useCountUp(source: () => number, durationMs = 650): Readonly<Ref<number>> {
  const display = ref(source())
  const { settings } = useA11y()
  let frame = 0

  watch(source, target => {
    if (typeof requestAnimationFrame !== 'function' || settings.reduceMotion) {
      display.value = target
      return
    }
    cancelAnimationFrame(frame)
    const from = display.value
    const start = performance.now()
    const tick = (now: number) => {
      const progress = Math.min(1, (now - start) / durationMs)
      display.value = Math.round(from + (target - from) * easeOutCubic(progress))
      if (progress < 1) frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
  })

  return display
}
