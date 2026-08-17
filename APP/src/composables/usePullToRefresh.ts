import { onBeforeUnmount, onMounted, ref } from 'vue'

const TRIGGER_PX = 64
const MAX_PULL_PX = 104

/**
 * 页面顶部下拉刷新：仅在页面已滚动到顶时响应，
 * 拉动距离带阻尼；超过阈值松手触发 onRefresh。
 * 纯视觉增强，不阻止默认滚动行为。
 */
export function usePullToRefresh(onRefresh: () => Promise<void>) {
  const pull = ref(0)
  const refreshing = ref(false)
  let startY = 0
  let tracking = false

  function onTouchStart(event: TouchEvent): void {
    if (refreshing.value || window.scrollY > 2) return
    startY = event.touches[0]?.clientY ?? 0
    tracking = true
  }

  function onTouchMove(event: TouchEvent): void {
    if (!tracking || refreshing.value) return
    const delta = (event.touches[0]?.clientY ?? 0) - startY
    if (delta <= 0 || window.scrollY > 2) {
      pull.value = 0
      return
    }
    pull.value = Math.min(MAX_PULL_PX, Math.round(delta * 0.45))
  }

  async function onTouchEnd(): Promise<void> {
    if (!tracking) return
    tracking = false
    if (pull.value >= TRIGGER_PX && !refreshing.value) {
      refreshing.value = true
      pull.value = TRIGGER_PX
      try {
        await onRefresh()
      } finally {
        refreshing.value = false
        pull.value = 0
      }
    } else {
      pull.value = 0
    }
  }

  onMounted(() => {
    window.addEventListener('touchstart', onTouchStart, { passive: true })
    window.addEventListener('touchmove', onTouchMove, { passive: true })
    window.addEventListener('touchend', onTouchEnd, { passive: true })
  })

  onBeforeUnmount(() => {
    window.removeEventListener('touchstart', onTouchStart)
    window.removeEventListener('touchmove', onTouchMove)
    window.removeEventListener('touchend', onTouchEnd)
  })

  return { pull, refreshing, triggerThreshold: TRIGGER_PX }
}
