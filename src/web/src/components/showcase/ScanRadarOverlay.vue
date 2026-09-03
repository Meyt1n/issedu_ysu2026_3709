<script setup lang="ts">
import { computed } from 'vue'

import type { VisionTask } from '../../api/types'
import AppIcon from '../AppIcon.vue'
import { radarStageFor, type RadarStage } from '../../ui/showcase'

const props = defineProps<{
  task: VisionTask | null
}>()

const stage = computed<RadarStage>(() => radarStageFor(
  props.task?.status ?? 'idle',
  Boolean(props.task?.result),
))

const stageLabel: Record<RadarStage, string> = {
  idle: '等待本地视觉任务',
  queued: '任务已进入本地队列',
  analyzing: '本地视觉分析中',
  review: '分析完成 · 等待人工复核',
  error: '分析未完成 · 可检查任务详情',
}

const stageDetail: Record<RadarStage, string> = {
  idle: '上传图片并通过质量门控后，扫描会开始工作。',
  queued: '正在等待本机视觉 worker 接手，不会自动写入健康记录。',
  analyzing: '正在读取图像、OCR 与条码证据，请稍候。',
  review: '候选结果仅供人工确认，未确认内容不会进入健康记录。',
  error: '请查看下方任务错误说明；必要时可重新处理。',
}

const activeStep = computed(() => {
  if (stage.value === 'queued') return 1
  if (stage.value === 'analyzing') return 2
  if (stage.value === 'review') return 4
  if (stage.value === 'error') return 3
  return 0
})

const steps = ['质量门控', '本地队列', 'OCR / 条码', '候选融合', '人工复核']
</script>

<template>
  <section
    v-if="task && stage !== 'idle'"
    class="scan-radar-overlay"
    :class="`scan-radar-overlay--${stage}`"
    aria-live="polite"
    aria-label="视觉扫描状态"
  >
    <div class="scan-radar-visual" aria-hidden="true">
      <div class="scan-stage" :class="`scan-stage--${stage}`">
        <svg class="scan-stage-art" viewBox="0 0 120 92" fill="none">
          <rect x="16" y="8" width="88" height="76" rx="10" stroke="currentColor" stroke-width="2.4" />
          <rect
            x="25" y="17" width="70" height="58" rx="6"
            stroke="currentColor" stroke-width="1.1" stroke-dasharray="3 4" opacity="0.5"
          />
          <g stroke="currentColor" stroke-width="1.9">
            <circle cx="42" cy="34" r="6.5" />
            <circle cx="64" cy="34" r="6.5" />
            <circle cx="86" cy="34" r="6.5" />
            <circle cx="42" cy="56" r="6.5" />
            <circle cx="64" cy="56" r="6.5" />
            <circle cx="86" cy="56" r="6.5" />
          </g>
          <circle cx="64" cy="34" r="6.5" fill="currentColor" opacity="0.16" />
          <circle cx="42" cy="56" r="6.5" fill="currentColor" opacity="0.16" />
          <path
            d="M20 78c8-2 12-7 13-15"
            stroke="currentColor" stroke-width="1.5" stroke-linecap="round" opacity="0.6"
          />
          <path
            d="M24 73c-1.5-4 0-7.5 3.5-10.5 1.2 4.2 0 7.8-3.5 10.5z"
            fill="currentColor" opacity="0.4"
          />
        </svg>
        <span class="scan-stage-beam" />
        <span class="scan-stage-corner scan-stage-corner--tl" />
        <span class="scan-stage-corner scan-stage-corner--tr" />
        <span class="scan-stage-corner scan-stage-corner--bl" />
        <span class="scan-stage-corner scan-stage-corner--br" />
      </div>
      <p class="scan-stage-caption">本地识别 · 结果仅供人工复核</p>
    </div>
    <div class="scan-radar-copy">
      <div class="scan-radar-heading">
        <div>
          <p class="eyebrow">实时视觉状态</p>
          <h3>{{ stageLabel[stage] }}</h3>
        </div>
        <span class="scan-radar-status"><AppIcon name="scan" :size="14" />{{ stage.toUpperCase() }}</span>
      </div>
      <p>{{ stageDetail[stage] }}</p>
      <ol class="scan-radar-steps">
        <li v-for="(step, index) in steps" :key="step" :class="{ done: index < activeStep, active: index === activeStep }">
          <span>{{ index < activeStep ? '✓' : index + 1 }}</span>{{ step }}
        </li>
      </ol>
    </div>
  </section>
</template>
