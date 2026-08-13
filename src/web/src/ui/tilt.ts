import type { Directive } from 'vue'

interface TiltHandlers {
  move: (event: PointerEvent) => void
  leave: () => void
}

const handlerStore = new WeakMap<HTMLElement, TiltHandlers>()

function motionAllowed(): boolean {
  if (typeof globalThis.matchMedia !== 'function') return false
  return (
    !globalThis.matchMedia('(prefers-reduced-motion: reduce)').matches &&
    globalThis.matchMedia('(hover: hover)').matches
  )
}

/**
 * v-tilt：指针跟随的 3D 倾斜 + 高光。
 * 用法：v-tilt 或 v-tilt="5"（最大倾斜角度，默认 6 度）。
 * 触屏设备与「减少动态效果」偏好下自动禁用。
 */
export const vTilt: Directive<HTMLElement, number | undefined> = {
  mounted(el, binding) {
    if (!motionAllowed()) return

    const maxDeg = binding.value ?? 6
    el.classList.add('tilt-3d', 'tilt-glare')

    const move = (event: PointerEvent): void => {
      const rect = el.getBoundingClientRect()
      if (rect.width === 0 || rect.height === 0) return
      const ratioX = (event.clientX - rect.left) / rect.width
      const ratioY = (event.clientY - rect.top) / rect.height
      el.classList.add('tilting')
      el.style.setProperty('--tilt-ry', `${((ratioX - 0.5) * 2 * maxDeg).toFixed(2)}deg`)
      el.style.setProperty('--tilt-rx', `${((0.5 - ratioY) * 2 * maxDeg).toFixed(2)}deg`)
      el.style.setProperty('--glare-x', `${(ratioX * 100).toFixed(1)}%`)
      el.style.setProperty('--glare-y', `${(ratioY * 100).toFixed(1)}%`)
    }

    const leave = (): void => {
      el.classList.remove('tilting')
      el.style.setProperty('--tilt-rx', '0deg')
      el.style.setProperty('--tilt-ry', '0deg')
    }

    el.addEventListener('pointermove', move)
    el.addEventListener('pointerleave', leave)
    handlerStore.set(el, { move, leave })
  },

  unmounted(el) {
    const handlers = handlerStore.get(el)
    if (handlers) {
      el.removeEventListener('pointermove', handlers.move)
      el.removeEventListener('pointerleave', handlers.leave)
      handlerStore.delete(el)
    }
  },
}
