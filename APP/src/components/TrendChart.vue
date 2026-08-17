<script setup lang="ts">
import { computed } from 'vue'

import type { TrendPoint } from '@/data/types'

const props = defineProps<{
  points: TrendPoint[]
}>()

const summary = computed(() =>
  props.points
    .map(p => `${p.label === '今' ? '今天' : `星期${p.label}`}完成 ${p.done}/${p.total}`)
    .join('，'),
)

function ratio(point: TrendPoint): number {
  if (point.total <= 0) return 0
  return Math.min(1, point.done / point.total)
}

function barHeight(point: TrendPoint): number {
  // 最低 8% 高度保证空日也有可见基柱。
  return Math.max(8, Math.round(ratio(point) * 100))
}
</script>

<template>
  <div class="trend" role="img" :aria-label="`近 7 天任务完成趋势：${summary}`">
    <div class="trend-bars" aria-hidden="true">
      <div v-for="(point, index) in points" :key="index" class="trend-col">
        <span class="trend-count">{{ point.total > 0 ? `${point.done}/${point.total}` : '-' }}</span>
        <div class="trend-track">
          <div
            class="trend-bar"
            :data-today="point.label === '今'"
            :data-full="point.total > 0 && point.done >= point.total"
            :style="{ height: `${barHeight(point)}%`, animationDelay: `${index * 60}ms` }"
          ></div>
        </div>
        <span class="trend-label" :data-today="point.label === '今'">{{ point.label }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.trend { display: grid; gap: 4px; }
.trend-bars {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 8px;
  align-items: end;
}
.trend-col { display: grid; gap: 5px; justify-items: center; }
.trend-count { font-size: 0.66rem; font-weight: 700; color: var(--c-ink-faint); }
.trend-track {
  width: 100%;
  max-width: 34px;
  height: 74px;
  background: var(--well-bg);
  border-radius: 10px;
  display: flex;
  align-items: flex-end;
  overflow: hidden;
  box-shadow: inset 0 1px 3px rgba(0, 0, 0, 0.05);
}
.trend-bar {
  width: 100%;
  border-radius: 10px 10px 0 0;
  background: linear-gradient(180deg, #58b28f, var(--c-brand));
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.35);
  animation: trend-grow 0.6s var(--ease-spring) backwards;
  transform-origin: bottom;
}
.trend-bar[data-today='true'] {
  background: linear-gradient(180deg, #ffd98f, var(--c-accent));
}
.trend-bar[data-full='true'] {
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.45), 0 0 10px rgba(87, 153, 111, 0.45);
}
@keyframes trend-grow {
  from { transform: scaleY(0); }
  to { transform: scaleY(1); }
}
.trend-label {
  font-size: 0.72rem;
  font-weight: 700;
  color: var(--c-ink-faint);
}
.trend-label[data-today='true'] { color: var(--c-accent-deep); font-weight: 800; }

html[data-contrast='high'] .trend-track { border: 1px solid #000; box-shadow: none; }
html[data-contrast='high'] .trend-bar { background: var(--c-brand); box-shadow: none; }
html[data-contrast='high'] .trend-bar[data-today='true'] { background: #7a4708; }
</style>
