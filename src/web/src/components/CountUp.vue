<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'

const props = defineProps<{
  value: number
  durationMs?: number
}>()

const displayed = ref(0)
let frame = 0

function animateTo(target: number): void {
  cancelAnimationFrame(frame)
  const from = displayed.value
  const delta = target - from
  if (delta === 0) return
  const duration = props.durationMs ?? 800
  const start = performance.now()

  const step = (now: number): void => {
    const progress = Math.min((now - start) / duration, 1)
    const eased = 1 - Math.pow(1 - progress, 3)
    displayed.value = Math.round(from + delta * eased)
    if (progress < 1) frame = requestAnimationFrame(step)
  }
  frame = requestAnimationFrame(step)
}

watch(() => props.value, target => animateTo(target), { immediate: true })

onBeforeUnmount(() => cancelAnimationFrame(frame))
</script>

<template>
  <span>{{ displayed }}</span>
</template>
