<script setup lang="ts">
import { computed, ref } from 'vue'

import AppIcon from '../AppIcon.vue'

const props = defineProps<{
  memberCount: number
  taskCount: number
  pendingReviews: number
  severeCount: number
}>()

interface Room {
  id: string
  label: string
  detail: string
  value: number
  icon: string
  tone: string
}

const focusedRoom = ref('family')
const tiltX = ref(0)
const tiltY = ref(0)
const zoom = ref(1)

const sceneStyle = computed(() => ({
  '--diorama-tilt-x': `${tiltX.value.toFixed(2)}deg`,
  '--diorama-tilt-y': `${tiltY.value.toFixed(2)}deg`,
  '--diorama-zoom': zoom.value.toFixed(2),
}))

const rooms = computed<Room[]>(() => [
  { id: 'family', label: '家庭节点', detail: '当前可见成员', value: props.memberCount, icon: 'members', tone: 'mint' },
  { id: 'tasks', label: '任务中枢', detail: '已确认计划摘要', value: props.taskCount, icon: 'plans', tone: 'warm' },
  { id: 'evidence', label: '证据工作台', detail: '等待人工复核', value: props.pendingReviews, icon: 'scan', tone: 'clay' },
  { id: 'beacon', label: '安全灯塔', detail: '严重信号数量', value: props.severeCount, icon: 'shield', tone: 'rose' },
])

const activeRoom = computed(() => rooms.value.find(room => room.id === focusedRoom.value) ?? rooms.value[0])

function onPointerMove(event: PointerEvent): void {
  const target = event.currentTarget as HTMLElement
  const rect = target.getBoundingClientRect()
  tiltY.value = ((event.clientX - rect.left) / rect.width - 0.5) * 8
  tiltX.value = ((event.clientY - rect.top) / rect.height - 0.5) * -6
}

function resetPointer(): void {
  tiltX.value = 0
  tiltY.value = 0
}

function onWheel(event: WheelEvent): void {
  event.preventDefault()
  zoom.value = Math.min(1.16, Math.max(0.9, zoom.value - event.deltaY / 1_200))
}

function adjustZoom(delta: number): void {
  zoom.value = Math.min(1.16, Math.max(0.9, zoom.value + delta))
}

function resetView(): void {
  zoom.value = 1
  resetPointer()
}
</script>

<template>
  <section class="home-diorama" aria-label="家庭空间视觉沙盘">
    <div class="diorama-heading">
      <div>
        <span class="diorama-eyebrow">数字家园 · 本地优先</span>
        <h3>家庭空间投影</h3>
      </div>
      <span class="diorama-live"><i />实时聚合</span>
    </div>

    <div
      class="diorama-viewport"
      @pointermove="onPointerMove"
      @pointerleave="resetPointer"
      @wheel="onWheel"
    >
      <div class="diorama-fireflies" aria-hidden="true"><i /><i /><i /><i /></div>
      <div class="diorama-scene" :style="sceneStyle">
        <svg class="diorama-house-art" viewBox="0 0 260 208" aria-hidden="true">
          <!-- 地面 -->
          <ellipse cx="130" cy="182" rx="112" ry="18" class="di-ground" />
          <!-- 侧墙 -->
          <polygon points="165,96 214,118 214,168 165,158" class="di-wall-side" />
          <!-- 前墙 -->
          <rect x="58" y="92" width="107" height="66" rx="3" class="di-wall-front" />
          <!-- 屋顶 -->
          <polygon points="48,94 112,46 190,46 176,96 70,96" class="di-roof-front" />
          <polygon points="176,96 190,46 226,72 214,120" class="di-roof-side" />
          <!-- 烟囱 -->
          <rect x="186" y="52" width="12" height="24" rx="2" class="di-chimney" />
          <!-- 门 -->
          <rect x="76" y="112" width="24" height="46" rx="11" class="di-door" />
          <circle cx="95" cy="136" r="1.6" class="di-door-knob" />
          <!-- 窗 -->
          <g class="di-window">
            <rect x="118" y="108" width="26" height="22" rx="4" />
            <path d="M131 108v22M118 119h26" class="di-window-bar" />
          </g>
          <g class="di-window di-window--side">
            <rect x="178" y="122" width="20" height="18" rx="3.5" />
          </g>
          <!-- 烟囱炊烟 -->
          <g class="di-smoke">
            <circle cx="192" cy="42" r="3.4" />
            <circle cx="197" cy="34" r="2.5" />
            <circle cx="191" cy="26" r="1.8" />
          </g>
          <!-- 灌木 -->
          <g class="di-bush">
            <circle cx="44" cy="158" r="9" />
            <circle cx="55" cy="153" r="7" />
            <circle cx="36" cy="163" r="6" />
          </g>
          <g class="di-bush di-bush--right">
            <circle cx="224" cy="162" r="7" />
            <circle cx="232" cy="166" r="5.5" />
          </g>
          <!-- 门前小路 -->
          <ellipse cx="88" cy="172" rx="20" ry="5" class="di-path" />
        </svg>

        <button
          v-for="room in rooms"
          :key="room.id"
          type="button"
          class="diorama-room"
          :class="[`diorama-room--${room.id}`, `diorama-room--${room.tone}`, { active: focusedRoom === room.id }]"
          :aria-label="`${room.label}，${room.value}`"
          @focus="focusedRoom = room.id"
          @mouseenter="focusedRoom = room.id"
        >
          <AppIcon :name="room.icon" :size="15" />
          <strong>{{ room.value }}</strong>
          <small>{{ room.label }}</small>
        </button>
      </div>
      <div class="diorama-callout" aria-live="polite">
        <span>{{ activeRoom.label }}</span>
        <strong>{{ activeRoom.value }}</strong>
        <small>{{ activeRoom.detail }} · 仅展示聚合数量</small>
      </div>
    </div>

    <div class="diorama-explorer-tools" aria-label="沙盘视角控制">
      <span>移动 / 滚轮 观察小屋</span>
      <button type="button" aria-label="缩小沙盘" @click="adjustZoom(-0.04)">−</button>
      <output>{{ Math.round(zoom * 100) }}%</output>
      <button type="button" aria-label="放大沙盘" @click="adjustZoom(0.04)">+</button>
      <button type="button" aria-label="重置沙盘视角" @click="resetView">
        <AppIcon name="refresh" :size="12" />
      </button>
    </div>

    <p class="diorama-note">
      <AppIcon name="lock" :size="13" /> 这是视觉化投影，不替代真实健康记录，也不生成医疗结论。
    </p>
  </section>
</template>
