<script setup lang="ts">
import { ref } from 'vue'

import { useA11y } from '@/stores/accessibility'

interface Particle {
  id: number
  left: number
  delay: number
  duration: number
  color: string
  size: number
  drift: number
}

const COLORS = ['#57b28f', '#f2a355', '#63a9b8', '#e9a05c', '#a08fd6', '#ffd98f']

const particles = ref<Particle[]>([])
const { settings } = useA11y()
let burstId = 0

/** 触发一次彩带（约 2.6 秒后自动清理）；减少动效模式下不触发。 */
function fire(count = 28): void {
  if (settings.reduceMotion) return
  const batch: Particle[] = []
  for (let i = 0; i < count; i += 1) {
    burstId += 1
    batch.push({
      id: burstId,
      left: Math.random() * 100,
      delay: Math.random() * 0.35,
      duration: 1.7 + Math.random() * 0.9,
      color: COLORS[Math.floor(Math.random() * COLORS.length)]!,
      size: 7 + Math.random() * 6,
      drift: (Math.random() - 0.5) * 120,
    })
  }
  particles.value = batch
  setTimeout(() => {
    particles.value = []
  }, 3000)
}

defineExpose({ fire })
</script>

<template>
  <div class="confetti" aria-hidden="true">
    <span
      v-for="p in particles"
      :key="p.id"
      class="confetti-piece"
      :style="{
        left: `${p.left}%`,
        width: `${p.size}px`,
        height: `${p.size * 0.45}px`,
        background: p.color,
        animationDelay: `${p.delay}s`,
        animationDuration: `${p.duration}s`,
        '--drift': `${p.drift}px`,
      }"
    ></span>
  </div>
</template>

<style scoped>
.confetti {
  position: fixed;
  inset: 0;
  z-index: 55;
  pointer-events: none;
  overflow: hidden;
}
.confetti-piece {
  position: absolute;
  top: -3vh;
  border-radius: 2px;
  opacity: 0;
  animation-name: confetti-fall;
  animation-timing-function: ease-in;
  animation-fill-mode: forwards;
}
@keyframes confetti-fall {
  0% { opacity: 1; transform: translate3d(0, 0, 0) rotate(0deg); }
  100% { opacity: 0.15; transform: translate3d(var(--drift, 0px), 106vh, 0) rotate(540deg); }
}
</style>
