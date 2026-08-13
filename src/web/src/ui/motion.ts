import type { Directive } from 'vue'

function motionAllowed(): boolean {
  if (typeof globalThis.matchMedia !== 'function') return false
  return !globalThis.matchMedia('(prefers-reduced-motion: reduce)').matches
}

/* ── v-reveal：滚动进入视口时列表逐项渐显 ─────────────────── */

const revealObserver: IntersectionObserver | null =
  typeof globalThis.IntersectionObserver === 'function'
    ? new IntersectionObserver(
        entries => {
          for (const entry of entries) {
            if (entry.isIntersecting) {
              entry.target.classList.add('reveal-in')
              revealObserver?.unobserve(entry.target)
            }
          }
        },
        { rootMargin: '0px 0px -8% 0px', threshold: 0.08 },
      )
    : null

export const vReveal: Directive<HTMLElement> = {
  mounted(el) {
    if (!motionAllowed() || !revealObserver) {
      el.classList.add('reveal-in')
      return
    }
    el.classList.add('reveal-group')
    revealObserver.observe(el)
  },
  unmounted(el) {
    revealObserver?.unobserve(el)
  },
}

/* ── v-magnet：关键按钮的磁吸悬浮 ─────────────────────────── */

interface MagnetHandlers {
  move: (event: PointerEvent) => void
  leave: () => void
}

const magnetStore = new WeakMap<HTMLElement, MagnetHandlers>()

export const vMagnet: Directive<HTMLElement, number | undefined> = {
  mounted(el, binding) {
    if (!motionAllowed() || !globalThis.matchMedia('(hover: hover)').matches) return
    const strength = binding.value ?? 4

    const move = (event: PointerEvent): void => {
      const rect = el.getBoundingClientRect()
      const dx = ((event.clientX - rect.left) / rect.width - 0.5) * 2 * strength
      const dy = ((event.clientY - rect.top) / rect.height - 0.5) * 2 * strength
      el.style.transform = `translate(${dx.toFixed(1)}px, ${dy.toFixed(1)}px) scale(1.03)`
    }
    const leave = (): void => {
      el.style.transform = ''
    }

    el.classList.add('magnet')
    el.addEventListener('pointermove', move)
    el.addEventListener('pointerleave', leave)
    magnetStore.set(el, { move, leave })
  },
  unmounted(el) {
    const handlers = magnetStore.get(el)
    if (handlers) {
      el.removeEventListener('pointermove', handlers.move)
      el.removeEventListener('pointerleave', handlers.leave)
      magnetStore.delete(el)
    }
  },
}

/* ── 点击涟漪：委托到全局，一次注册 ───────────────────────── */

let rippleInstalled = false

export function installRipple(): void {
  if (rippleInstalled || !motionAllowed() || typeof document === 'undefined') return
  rippleInstalled = true

  document.addEventListener(
    'pointerdown',
    event => {
      const button = (event.target as HTMLElement | null)?.closest?.('.btn') as HTMLElement | null
      if (!button || button.hasAttribute('disabled')) return

      const rect = button.getBoundingClientRect()
      const size = Math.max(rect.width, rect.height) * 2.1
      const ripple = document.createElement('span')
      ripple.className = 'btn-ripple'
      ripple.style.width = `${size}px`
      ripple.style.height = `${size}px`
      ripple.style.left = `${event.clientX - rect.left - size / 2}px`
      ripple.style.top = `${event.clientY - rect.top - size / 2}px`
      button.appendChild(ripple)
      setTimeout(() => ripple.remove(), 650)
    },
    { passive: true },
  )
}
