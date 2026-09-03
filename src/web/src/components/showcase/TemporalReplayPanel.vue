<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'

import AppIcon from '../AppIcon.vue'

interface ReplayPoint {
  label: string
  count: number
}

const props = defineProps<{ points: ReplayPoint[] }>()

const selectedIndex = ref(Math.max(props.points.length - 1, 0))
const playing = ref(false)
const direction = ref<'forward' | 'reverse'>('forward')
let timer: ReturnType<typeof setInterval> | null = null

const current = computed(() => props.points[selectedIndex.value] ?? { label: '暂无数据', count: 0 })
const maxCount = computed(() => Math.max(...props.points.map(point => point.count), 1))
const progress = computed(() => (props.points.length > 1 ? selectedIndex.value / (props.points.length - 1) : 1))

function stop(): void {
  playing.value = false
  if (timer) clearInterval(timer)
  timer = null
}

function play(nextDirection: 'forward' | 'reverse'): void {
  if (props.points.length < 2) return
  if (playing.value && direction.value === nextDirection) {
    stop()
    return
  }
  direction.value = nextDirection
  if (timer) clearInterval(timer)
  playing.value = true
  timer = setInterval(() => {
    const nextIndex = selectedIndex.value + (direction.value === 'forward' ? 1 : -1)
    if (nextIndex > props.points.length - 1) selectedIndex.value = 0
    else if (nextIndex < 0) selectedIndex.value = props.points.length - 1
    else selectedIndex.value = nextIndex
  }, 1_050)
}

watch(() => props.points.length, () => {
  selectedIndex.value = Math.min(selectedIndex.value, Math.max(props.points.length - 1, 0))
})

onBeforeUnmount(stop)
</script>

<template>
  <section
    class="temporal-replay"
    :class="{ 'temporal-replay--rewinding': playing && direction === 'reverse', 'temporal-replay--playing': playing }"
    aria-label="近七日事件趋势回放"
  >
    <div class="temporal-heading">
      <div>
        <span class="temporal-eyebrow"><AppIcon name="history" :size="13" /> 家庭记忆回放</span>
        <h3>时间回溯 · 近七日轨迹</h3>
      </div>
      <div class="temporal-actions">
        <button type="button" class="temporal-play" :class="{ active: playing && direction === 'forward' }" :aria-label="playing && direction === 'forward' ? '暂停回放' : '播放回放'" @click="play('forward')">
          <AppIcon :name="playing && direction === 'forward' ? 'pause' : 'play'" :size="15" />
          {{ playing && direction === 'forward' ? '暂停' : '回放' }}
        </button>
        <button type="button" class="temporal-play temporal-play--reverse" :class="{ active: playing && direction === 'reverse' }" :aria-label="playing && direction === 'reverse' ? '暂停倒带' : '播放倒带'" @click="play('reverse')">
          <AppIcon name="rewind" :size="15" />
          {{ playing && direction === 'reverse' ? '暂停' : '倒带' }}
        </button>
      </div>
    </div>

    <div class="temporal-stage">
      <div class="temporal-readout" aria-live="polite">
        <span>{{ current.label }}</span>
        <strong>{{ current.count }}</strong>
        <small>已确认事件</small>
      </div>
      <div class="temporal-bars" aria-hidden="true">
        <i
          v-for="(point, index) in points"
          :key="`${point.label}-${index}`"
          :class="{ active: index === selectedIndex, passed: index < selectedIndex }"
          :style="{ height: `${Math.max(12, (point.count / maxCount) * 100)}%` }"
        />
      </div>
    </div>

    <div class="temporal-controls">
      <input
        v-model.number="selectedIndex"
        type="range"
        min="0"
        :max="Math.max(points.length - 1, 0)"
        step="1"
        aria-label="选择回放日期"
        :style="{ '--replay-progress': `${progress * 100}%` }"
        @input="stop"
      />
      <div class="temporal-labels">
        <span>{{ points[0]?.label ?? '起点' }}</span>
        <span>{{ points[points.length - 1]?.label ?? '终点' }}</span>
      </div>
    </div>
    <p>仅回放近七日已确认事件数量，不改变当前家庭状态。</p>
  </section>
</template>
