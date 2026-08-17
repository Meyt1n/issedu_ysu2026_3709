<script setup lang="ts">
import { computed } from 'vue'

import {
  recognitionStatusLabel,
  recognitionStatusTone,
  riskLevelLabel,
  riskLevelTone,
  taskLevelLabel,
  taskLevelTone,
  taskStatusLabel,
  type Tone,
} from '@/data/labels'
import type { RecognitionStatus, TaskLevel, TaskStatus } from '@/data/types'

const props = defineProps<{
  kind: 'task' | 'risk' | 'recognition' | 'taskStatus'
  value: string
}>()

const view = computed<{ label: string; tone: Tone; prefix: string }>(() => {
  switch (props.kind) {
    case 'task':
      return {
        label: taskLevelLabel(props.value as TaskLevel),
        tone: taskLevelTone(props.value as TaskLevel),
        prefix: '提醒等级',
      }
    case 'risk':
      return { label: riskLevelLabel(props.value), tone: riskLevelTone(props.value), prefix: '风险等级' }
    case 'recognition':
      return {
        label: recognitionStatusLabel(props.value as RecognitionStatus),
        tone: recognitionStatusTone(props.value as RecognitionStatus),
        prefix: '识别状态',
      }
    case 'taskStatus':
      return {
        label: taskStatusLabel(props.value as TaskStatus),
        tone: props.value === 'CONFIRMED' ? 'calm' : 'neutral',
        prefix: '处理状态',
      }
    default:
      return { label: props.value, tone: 'neutral', prefix: '状态' }
  }
})
</script>

<template>
  <span class="tag" :data-tone="view.tone" :aria-label="`${view.prefix}：${view.label}`">
    {{ view.label }}
  </span>
</template>
