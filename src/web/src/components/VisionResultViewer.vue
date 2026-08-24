<script setup lang="ts">
import { computed, ref } from 'vue'

import type { NormalizedEvidence, VisionTask } from '../api/types'
import AppIcon from './AppIcon.vue'

const props = defineProps<{
  task: VisionTask
  imageUrl: string | null
  imageLoading?: boolean
}>()

const naturalWidth = ref(0)
const naturalHeight = ref(0)
const hoveredId = ref<string | null>(null)

const scanning = computed(
  () => props.task.status === 'queued' || props.task.status === 'running',
)

const CHANNEL_META: Record<string, { label: string; color: string; tone: string }> = {
  ocr: { label: 'OCR 文本', color: '#38665a', tone: 'pine' },
  yolo: { label: 'YOLO 定位', color: '#c26744', tone: 'clay' },
  barcode: { label: '条码', color: '#47708c', tone: 'sky' },
}

const evidence = computed<NormalizedEvidence[]>(() => props.task.result?.evidence ?? [])

const boxedEvidence = computed(() =>
  evidence.value.filter(item => item.region && item.region.width > 0 && item.region.height > 0),
)

// 通道显隐开关（YOLO / OCR / 条码），点击图例切换
const channelVisible = ref<Record<string, boolean>>({ ocr: true, yolo: true, barcode: true })

function toggleChannel(channel: string): void {
  channelVisible.value = {
    ...channelVisible.value,
    [channel]: !(channelVisible.value[channel] ?? true),
  }
}

const yoloBoxes = computed(() => boxedEvidence.value.filter(item => item.channel === 'yolo'))
const otherBoxes = computed(() => boxedEvidence.value.filter(item => item.channel !== 'yolo'))

const visibleYoloBoxes = computed(() => (channelVisible.value.yolo ? yoloBoxes.value : []))
const visibleOtherBoxes = computed(() =>
  otherBoxes.value.filter(item => channelVisible.value[item.channel] ?? true),
)

/** YOLO 裁剪触发的二次 OCR token（id 形如 ocr-c2-1） */
function isCropToken(item: NormalizedEvidence): boolean {
  return item.channel === 'ocr' && /^ocr-c\d/.test(item.id)
}

const channelCounts = computed(() => {
  const counts: Record<string, number> = { yolo: 0, ocr: 0, barcode: 0 }
  for (const item of evidence.value) counts[item.channel] = (counts[item.channel] ?? 0) + 1
  return counts
})

/** 识别管线步骤：体现「YOLO 先定位 → OCR 识别 → 融合」的处理顺序 */
const pipeline = computed(() => {
  const cropCount = evidence.value.filter(isCropToken).length
  return [
    { label: '质量门控', count: null as number | null, state: 'done', hint: '上传前本地质量检查已通过' },
    {
      label: 'YOLO 包装定位',
      count: yoloBoxes.value.length,
      state: yoloBoxes.value.length > 0 ? 'yolo' : 'off',
      hint: yoloBoxes.value.length > 0
        ? '本地 YOLO11n 检测出药盒包装区域，为后续识别圈定重点'
        : '本任务处理时未启用 YOLO 权重',
    },
    {
      label: '全图 OCR',
      count: channelCounts.value.ocr - cropCount,
      state: 'on',
      hint: 'PaddleOCR 全图文本识别',
    },
    {
      label: '裁剪补录',
      count: cropCount,
      state: cropCount > 0 ? 'yolo' : 'off',
      hint: '对 YOLO 框出的区域二次 OCR，补充全图识别遗漏的文字',
    },
    { label: '条码', count: channelCounts.value.barcode, state: channelCounts.value.barcode > 0 ? 'on' : 'off', hint: 'OpenCV 条码解码' },
    { label: '字段候选', count: fields.value.length, state: 'on', hint: '规则与词典产出的结构化字段，仍需人工确认' },
  ]
})

function regionRect(item: NormalizedEvidence): { x: number; y: number; w: number; h: number } {
  const region = item.region!
  if (region.coordinate_space === 'normalized') {
    return {
      x: region.x * naturalWidth.value,
      y: region.y * naturalHeight.value,
      w: region.width * naturalWidth.value,
      h: region.height * naturalHeight.value,
    }
  }
  return { x: region.x, y: region.y, w: region.width, h: region.height }
}

/** YOLO 取景框：四角 bracket 路径（区别于 OCR/条码的细矩形） */
function bracketPath(item: NormalizedEvidence): string {
  const { x, y, w, h } = regionRect(item)
  const arm = Math.min(Math.min(w, h) * 0.24, 42)
  return [
    `M ${x} ${y + arm} L ${x} ${y} L ${x + arm} ${y}`,
    `M ${x + w - arm} ${y} L ${x + w} ${y} L ${x + w} ${y + arm}`,
    `M ${x + w} ${y + h - arm} L ${x + w} ${y + h} L ${x + w - arm} ${y + h}`,
    `M ${x + arm} ${y + h} L ${x} ${y + h} L ${x} ${y + h - arm}`,
  ].join(' ')
}

const fields = computed(() => props.task.result?.fields ?? [])
const findings = computed(() => props.task.result?.findings ?? [])
const masterCandidates = computed(() => props.task.result?.master_candidates ?? [])
const versions = computed(() => props.task.result?.versions ?? {})

function onImageLoad(event: Event): void {
  const img = event.target as HTMLImageElement
  naturalWidth.value = img.naturalWidth
  naturalHeight.value = img.naturalHeight
}

const FIELD_LABELS: Record<string, string> = {
  drug_name: '药品名称',
  specification: '规格',
  manufacturer: '生产厂家',
  batch_number: '批号',
  expiry_date: '有效期',
  product_barcode: '条码',
  packaging_type: '包装类型',
}
</script>

<template>
  <div class="viewer-grid">
    <div class="viewer-stage" :class="{ scanning }">
      <template v-if="imageUrl">
        <img :src="imageUrl" alt="识别原图" @load="onImageLoad" />

        <svg
          v-if="naturalWidth > 0 && !scanning"
          class="viewer-overlay"
          :viewBox="`0 0 ${naturalWidth} ${naturalHeight}`"
          preserveAspectRatio="none"
        >
          <!-- YOLO 定位框先入场：四角取景框造型，体现「先定位、后识别」 -->
          <g
            v-for="(item, index) in visibleYoloBoxes"
            :key="item.id"
            class="ybox"
            :style="{ '--d': `${index * 0.12}s` }"
            :opacity="hoveredId === null || hoveredId === item.id ? 1 : 0.25"
          >
            <rect
              :x="regionRect(item).x"
              :y="regionRect(item).y"
              :width="regionRect(item).w"
              :height="regionRect(item).h"
              fill="#c26744"
              fill-opacity="0.07"
              stroke="none"
              rx="6"
            />
            <path
              :d="bracketPath(item)"
              fill="none"
              stroke="#c26744"
              :stroke-width="hoveredId === item.id ? 9 : 7"
              stroke-linecap="round"
            />
            <text
              :x="regionRect(item).x + 6"
              :y="Math.max(regionRect(item).y - 12, 22)"
              fill="#c26744"
              font-size="21"
              font-weight="800"
              paint-order="stroke"
              stroke="#fffdf7"
              stroke-width="5"
            >
              YOLO 定位 {{ (item.confidence * 100).toFixed(0) }}%
            </text>
          </g>

          <!-- OCR / 条码框随后入场 -->
          <g
            v-for="(item, index) in visibleOtherBoxes"
            :key="item.id"
            class="obox"
            :style="{ '--d': `${0.45 + Math.min(index * 0.07, 1)}s` }"
            :opacity="hoveredId === null || hoveredId === item.id ? 1 : 0.25"
          >
            <rect
              :x="regionRect(item).x"
              :y="regionRect(item).y"
              :width="regionRect(item).w"
              :height="regionRect(item).h"
              fill="none"
              :stroke="CHANNEL_META[item.channel]?.color ?? '#6e8a74'"
              :stroke-width="hoveredId === item.id ? 5 : 3"
              rx="4"
            />
            <text
              :x="regionRect(item).x + 4"
              :y="Math.max(regionRect(item).y - 8, 16)"
              :fill="CHANNEL_META[item.channel]?.color ?? '#6e8a74'"
              font-size="17"
              font-weight="700"
              paint-order="stroke"
              stroke="#fffdf7"
              stroke-width="4"
            >
              {{ CHANNEL_META[item.channel]?.label ?? item.channel }}
              {{ (item.confidence * 100).toFixed(0) }}%
            </text>
          </g>
        </svg>

        <!-- 通道图例开关（点击显隐对应通道的定位框） -->
        <div v-if="naturalWidth > 0 && !scanning && boxedEvidence.length > 0" class="viewer-channels">
          <button
            v-for="(meta, channel) in CHANNEL_META"
            :key="channel"
            type="button"
            class="channel-chip"
            :class="{ off: !(channelVisible[channel] ?? true), highlight: channel === 'yolo' && yoloBoxes.length > 0 }"
            :style="{ '--ch': meta.color }"
            :title="`点击${(channelVisible[channel] ?? true) ? '隐藏' : '显示'}${meta.label}标注`"
            @click="toggleChannel(channel)"
          >
            <i />
            {{ meta.label }}
            <b>{{ channelCounts[channel] ?? 0 }}</b>
          </button>
        </div>

        <div v-if="scanning" class="scan-overlay" aria-hidden="true">
          <span class="scan-beam" />
          <span class="scan-corner tl" /><span class="scan-corner tr" />
          <span class="scan-corner bl" /><span class="scan-corner br" />
          <span class="scan-status">
            <span class="loading-dots"><span /><span /><span /></span>
            {{ props.task.status === 'running' ? '本地 OCR 正在处理…' : '正在等待本地 OCR worker…' }}
          </span>
        </div>
      </template>
      <div v-else class="viewer-placeholder">
        <span v-if="imageLoading" class="loading-dots"><span /><span /><span /></span>
        <AppIcon v-else name="scan" :size="30" />
        <span>{{ imageLoading ? '正在载入原图' : '原图不可用' }}</span>
      </div>
    </div>

    <div class="viewer-panel">
      <template v-if="task.status === 'succeeded' && task.result">
        <p class="eyebrow" style="margin: 0">识别管线</p>
        <div class="pipe-flow" aria-label="本地识别处理顺序">
          <template v-for="(step, index) in pipeline" :key="step.label">
            <span v-if="index > 0" class="pipe-arrow" aria-hidden="true">→</span>
            <span class="pipe-step" :class="step.state" :title="step.hint">
              {{ step.label }}<b v-if="step.count !== null">{{ step.count }}</b>
            </span>
          </template>
        </div>

        <p class="eyebrow" style="margin: 10px 0 0">多渠道证据</p>
        <div v-if="boxedEvidence.length === 0 && evidence.length === 0" class="text-faint" style="font-size: 13px">
          本次没有可展示的证据条目。
        </div>
        <ul class="token-list">
          <li
            v-for="item in evidence"
            :key="item.id"
            class="token-row"
            :class="{ hovered: hoveredId === item.id }"
            @mouseenter="hoveredId = item.id"
            @mouseleave="hoveredId = null"
          >
            <span class="pill" :class="CHANNEL_META[item.channel]?.tone ?? 'sage'" style="flex: 0 0 auto">
              {{ isCropToken(item) ? 'YOLO 裁剪 OCR' : (CHANNEL_META[item.channel]?.label ?? item.channel) }}
            </span>
            <span class="token-text">{{ item.original_value }}</span>
            <span class="token-conf" :title="`置信度 ${(item.confidence * 100).toFixed(1)}%`">
              <i :style="{ width: `${item.confidence * 100}%` }" />
            </span>
          </li>
        </ul>

        <template v-if="fields.length > 0">
          <p class="eyebrow" style="margin: 10px 0 0">字段候选（未确认）</p>
          <div class="capability-chips">
            <span v-for="(field, index) in fields" :key="index" class="pill gold">
              {{ FIELD_LABELS[field.field_name] ?? field.field_name }}：{{ field.normalized_value }}
            </span>
          </div>
        </template>

        <template v-if="findings.length > 0">
          <p class="eyebrow" style="margin: 10px 0 0">发现事项</p>
          <div class="capability-chips">
            <span
              v-for="finding in findings"
              :key="finding.code"
              class="pill"
              :class="finding.severity === 'CONFLICT' ? 'rose' : finding.severity === 'REVIEW' ? 'gold' : 'sage'"
              :title="finding.detail"
            >
              {{ finding.code }}
            </span>
          </div>
        </template>

        <template v-if="masterCandidates.length > 0">
          <p class="eyebrow" style="margin: 10px 0 0">主数据核对</p>
          <ul class="evidence-chain-list">
            <li v-for="candidate in masterCandidates" :key="candidate.record_id">
              <strong>{{ candidate.record_id }}</strong>
              <span>{{ candidate.reasons.join('、') }}</span>
            </li>
          </ul>
        </template>

        <p class="text-faint" style="font-size: 11.5px; line-height: 1.6; margin: 10px 0 0">
          YOLO {{ versions.vision_model_version ?? '未登记' }} · OCR {{ versions.ocr_engine_version ?? '未知' }} ·
          条码 {{ versions.barcode_decoder_version ?? '未知' }} · 主数据 {{ versions.master_data_version ?? '未知' }} ·
          识别结果仅为候选，确认后才进入健康记录。
        </p>
      </template>

      <div v-else-if="scanning" class="section-stack" style="gap: 8px">
        <p class="eyebrow" style="margin: 0">识别进行中</p>
        <span class="rail-line text-faint">
          任务已进入本地识别队列；由家庭可信域内的 OCR worker（PaddleOCR 全图识别 + 条码解码）处理。
          首次运行会加载本地模型，可能需要十几秒；完成后会自动生成待复核任务。
        </span>
      </div>

      <div v-else class="section-stack" style="gap: 8px">
        <p class="eyebrow" style="margin: 0">任务状态</p>
        <span class="rail-line text-faint">
          {{ task.error_message ? `${task.error_code}：${task.error_message}` : '该任务没有识别结果可展示。' }}
        </span>
      </div>
    </div>
  </div>
</template>
