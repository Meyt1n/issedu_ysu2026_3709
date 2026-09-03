<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import AppIcon from '../AppIcon.vue'

interface PulseMember {
  id: string
  name: string
  planCount: number
  reviewCount: number
  riskCount: number
}

const props = defineProps<{
  eventsToday: number
  severeCount: number
  pendingReviews: number
  runtimeOnline: number
  runtimeTotal: number
  members: PulseMember[]
}>()

const systemHealth = computed(() => {
  if (props.runtimeTotal <= 0) return 0
  return Math.round((props.runtimeOnline / props.runtimeTotal) * 100)
})

const pulseLabel = computed(() => {
  if (props.severeCount > 0) return '注意信号'
  if (props.pendingReviews > 0) return '复核信号'
  return '平稳信号'
})

/* ── 数字孪生轨道核心（Canvas 2D）──
 * 浅色观测台：呼吸核心 + 三层透视轨道 + 成员节点公转 + 雷达扫掠 + 底部示波脉搏线。
 * 配色一律从主题令牌读取，与整屏暖纸色域一致，不做突兀深色块；
 * 只投影聚合数量与真实运行状态，不做医疗判断；减少动效时绘制单帧静像。 */

const canvas = ref<HTMLCanvasElement | null>(null)
let renderFrame = 0
let resizeObserver: ResizeObserver | null = null
let themeObserver: MutationObserver | null = null
let motionMedia: MediaQueryList | null = null
let reducedMotion = false
let startTime = 0

/* Canvas 不认识 color-mix()，所以把令牌解析成 rgb 后自行调透明度。 */
const PALETTE_FALLBACK = {
  card: '#fffdf8',
  paper: '#f6f1e6',
  paperDeep: '#efe7d6',
  pine: '#38665a',
  pineDeep: '#2a5045',
  clay: '#c26744',
  gold: '#a97e1f',
  sky: '#47708c',
  rose: '#ad4152',
  sage: '#6e8a74',
  ink: '#37332b',
  line: '#e5dbc6',
}

type Palette = typeof PALETTE_FALLBACK

const TOKEN_OF: Record<keyof Palette, string> = {
  card: '--card',
  paper: '--paper',
  paperDeep: '--paper-deep',
  pine: '--pine',
  pineDeep: '--pine-deep',
  clay: '--clay',
  gold: '--gold',
  sky: '--sky',
  rose: '--rose',
  sage: '--sage',
  ink: '--ink',
  line: '--line',
}

let palette: Palette = { ...PALETTE_FALLBACK }

function readPalette(): void {
  const root = globalThis.document?.documentElement
  if (!root || typeof globalThis.getComputedStyle !== 'function') return
  const style = globalThis.getComputedStyle(root)
  const next = { ...PALETTE_FALLBACK }
  for (const key of Object.keys(TOKEN_OF) as Array<keyof Palette>) {
    const value = style.getPropertyValue(TOKEN_OF[key]).trim()
    if (value) next[key] = value
  }
  palette = next
}

function toRgb(color: string): [number, number, number] {
  const value = color.trim()
  if (value.startsWith('#')) {
    const hex = value.slice(1)
    const full = hex.length === 3 ? hex.replace(/./g, char => char + char) : hex
    const int = Number.parseInt(full.slice(0, 6), 16)
    if (!Number.isNaN(int)) return [(int >> 16) & 255, (int >> 8) & 255, int & 255]
  }
  const parts = value.match(/\d+(?:\.\d+)?/g)
  if (parts && parts.length >= 3) return [Number(parts[0]), Number(parts[1]), Number(parts[2])]
  return [56, 102, 90]
}

function alpha(color: string, value: number): string {
  const [r, g, b] = toRgb(color)
  return `rgba(${r}, ${g}, ${b}, ${value})`
}

const orbitMembers = computed(() => props.members.slice(0, 6))

function memberPalette(): string[] {
  return [palette.pine, palette.clay, palette.gold, palette.sky, palette.rose, palette.sage]
}

function intensity(): number {
  return Math.min(props.eventsToday * 1.6 + props.pendingReviews * 2 + props.severeCount * 6, 30)
}

function drawTwin(time: number): void {
  const element = canvas.value
  const context = element?.getContext('2d')
  if (!element || !context) return
  const width = element.clientWidth || 640
  const height = element.clientHeight || 260
  const cx = width / 2
  const cy = height * 0.46
  const baseRadius = Math.min(width * 0.3, height * 0.42, 150)
  const colors = memberPalette()

  // 浅色底是半透明的，必须先清帧；否则每帧叠加会把中心糊成一团深色。
  context.clearRect(0, 0, width, height)

  // 浅色观测台底：与卡片同一套纸色，只在中心留一点松绿晕。
  const bg = context.createRadialGradient(cx, cy, 12, cx, cy, Math.max(width, height) * 0.72)
  bg.addColorStop(0, alpha(palette.pine, 0.06))
  bg.addColorStop(0.55, alpha(palette.paper, 0.85))
  bg.addColorStop(1, palette.paperDeep)
  context.fillStyle = bg
  context.fillRect(0, 0, width, height)

  const t = time / 1000

  // 悬浮尘埃（暖金微粒）
  const dustCount = 42
  for (let i = 0; i < dustCount; i += 1) {
    const seed = i * 12.9898
    const px = (Math.abs(Math.sin(seed)) * width + t * (2.5 + (i % 3))) % width
    const py = (Math.abs(Math.cos(seed * 1.7)) * height + t * 1.1) % height
    const twinkle = 0.14 + Math.abs(Math.sin(t * 0.9 + i)) * 0.22
    context.beginPath()
    context.arc(px, py, i % 4 === 0 ? 1.4 : 0.8, 0, Math.PI * 2)
    context.fillStyle = alpha(palette.gold, twinkle)
    context.fill()
  }

  // 三层透视轨道环（虚线 + 慢速旋转）
  const ringSquash = 0.36
  for (let ring = 0; ring < 3; ring += 1) {
    const radius = baseRadius * (0.66 + ring * 0.24)
    const speed = (ring % 2 === 0 ? 1 : -1) * (0.12 + ring * 0.05)
    context.save()
    context.translate(cx, cy)
    context.scale(1, ringSquash)
    context.rotate(t * speed)
    context.beginPath()
    context.arc(0, 0, radius, 0, Math.PI * 2)
    context.setLineDash(ring === 1 ? [2, 9] : [7, 7])
    context.lineWidth = 1.1
    context.strokeStyle = alpha(palette.pine, 0.42 - ring * 0.08)
    context.stroke()
    context.setLineDash([])
    // 环上彗星光点
    const cometAngle = t * (0.5 + ring * 0.22) * (ring % 2 === 0 ? 1 : -1)
    const cometX = Math.cos(cometAngle) * radius
    const cometY = Math.sin(cometAngle) * radius
    const comet = context.createRadialGradient(cometX, cometY, 0, cometX, cometY, 9)
    comet.addColorStop(0, alpha(palette.clay, 0.72))
    comet.addColorStop(1, alpha(palette.clay, 0))
    context.fillStyle = comet
    context.beginPath()
    context.arc(cometX, cometY, 9, 0, Math.PI * 2)
    context.fill()
    context.restore()
  }

  // 雷达扫掠
  const sweepAngle = t * 0.9
  const sweep = context.createConicGradient?.(sweepAngle, cx, cy)
  if (sweep) {
    sweep.addColorStop(0, alpha(palette.pine, 0.16))
    sweep.addColorStop(0.12, alpha(palette.pine, 0))
    sweep.addColorStop(1, alpha(palette.pine, 0))
    context.save()
    context.translate(cx, cy)
    context.scale(1, ringSquash)
    context.beginPath()
    context.arc(0, 0, baseRadius * 1.16, 0, Math.PI * 2)
    context.fillStyle = sweep
    context.fill()
    context.restore()
  }

  // 成员节点（公转）
  const members = orbitMembers.value
  for (let i = 0; i < members.length; i += 1) {
    const member = members[i]
    const ringIndex = i % 3
    const radius = baseRadius * (0.66 + ringIndex * 0.24)
    const speed = 0.22 + i * 0.045
    const angle = t * speed + (i / Math.max(members.length, 1)) * Math.PI * 2
    const x = cx + Math.cos(angle) * radius
    const y = cy + Math.sin(angle) * radius * ringSquash
    const color = colors[i % colors.length] ?? palette.pine
    const glow = member.planCount > 0 ? 12 : 7

    // 与核心的引力连线
    context.beginPath()
    context.moveTo(cx, cy)
    context.lineTo(x, y)
    context.strokeStyle = alpha(palette.pine, 0.16)
    context.lineWidth = 1
    context.stroke()

    const halo = context.createRadialGradient(x, y, 0, x, y, glow + 4)
    halo.addColorStop(0, alpha(color, 0.55))
    halo.addColorStop(1, alpha(color, 0))
    context.fillStyle = halo
    context.beginPath()
    context.arc(x, y, glow + 4, 0, Math.PI * 2)
    context.fill()
    context.beginPath()
    context.arc(x, y, 4.2, 0, Math.PI * 2)
    context.fillStyle = color
    context.fill()

    context.font = '600 10px ui-sans-serif, system-ui, sans-serif'
    context.textAlign = 'center'
    context.fillStyle = alpha(palette.ink, 0.78)
    context.fillText(member.name.slice(0, 6), x, y - 10)
  }

  // 呼吸核心：只留一圈淡光晕，中心留白交给 DOM 上的读数。
  const breathe = 1 + Math.sin(t * 1.4) * 0.05
  const coreRadius = baseRadius * 0.3 * breathe
  const coreGlow = context.createRadialGradient(cx, cy, coreRadius * 0.9, cx, cy, coreRadius * 2.4)
  coreGlow.addColorStop(0, alpha(palette.gold, 0.22))
  coreGlow.addColorStop(0.45, alpha(palette.pine, 0.16))
  coreGlow.addColorStop(1, alpha(palette.pine, 0))
  context.fillStyle = coreGlow
  context.beginPath()
  context.arc(cx, cy, coreRadius * 2.4, 0, Math.PI * 2)
  context.fill()
  context.beginPath()
  context.arc(cx, cy, coreRadius, 0, Math.PI * 2)
  context.strokeStyle = alpha(palette.pine, 0.5)
  context.lineWidth = 1.4
  context.stroke()

  // 底部示波脉搏线
  const waveBase = height * 0.9
  const waveAmp = 7 + intensity() * 0.5
  const wave = context.createLinearGradient(0, 0, width, 0)
  wave.addColorStop(0, alpha(palette.pine, 0.24))
  wave.addColorStop(0.5, alpha(palette.pine, 0.85))
  wave.addColorStop(1, alpha(palette.clay, 0.85))
  context.beginPath()
  for (let x = 0; x <= width; x += 4) {
    const phase = x * 0.045 + t * 2.2
    const spike = Math.exp(-((((x % 130) - 65) ** 2) / 260)) * intensity() * 0.6
    const y = waveBase - Math.sin(phase) * waveAmp * 0.4 - spike
    if (x === 0) context.moveTo(x, y)
    else context.lineTo(x, y)
  }
  context.strokeStyle = wave
  context.lineWidth = 1.8
  context.stroke()
  context.strokeStyle = alpha(palette.line, 0.9)
  context.lineWidth = 1
  context.beginPath()
  context.moveTo(0, waveBase)
  context.lineTo(width, waveBase)
  context.stroke()

  // HUD 四角
  context.strokeStyle = alpha(palette.pine, 0.4)
  context.lineWidth = 1.5
  const corner = 14
  const pad = 8
  for (const [sx, sy] of [[pad, pad], [width - pad, pad], [pad, height - pad], [width - pad, height - pad]] as const) {
    const dirX = sx < cx ? 1 : -1
    const dirY = sy < cy ? 1 : -1
    context.beginPath()
    context.moveTo(sx + dirX * corner, sy)
    context.lineTo(sx, sy)
    context.lineTo(sx, sy + dirY * corner)
    context.stroke()
  }
}

function loop(time: number): void {
  drawTwin(time)
  if (!reducedMotion) renderFrame = requestAnimationFrame(loop)
}

function startLoop(): void {
  cancelAnimationFrame(renderFrame)
  readPalette()
  if (!startTime) startTime = performance.now()
  if (reducedMotion) {
    drawTwin(startTime)
    return
  }
  renderFrame = requestAnimationFrame(loop)
}

function onMotionChange(event: MediaQueryListEvent): void {
  reducedMotion = event.matches
  startLoop()
}

onMounted(() => {
  startTime = performance.now()
  readPalette()
  motionMedia = globalThis.matchMedia?.('(prefers-reduced-motion: reduce)') ?? null
  reducedMotion = motionMedia?.matches ?? false
  motionMedia?.addEventListener?.('change', onMotionChange)
  if (canvas.value && typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(() => startLoop())
    resizeObserver.observe(canvas.value)
  }
  // 切主题后重新取色，画面跟随整屏配色，不残留上一套颜色。
  const root = globalThis.document?.documentElement
  if (root && typeof MutationObserver !== 'undefined') {
    themeObserver = new MutationObserver(() => startLoop())
    themeObserver.observe(root, { attributeFilter: ['data-theme'] })
  }
  const ratio = Math.min(globalThis.devicePixelRatio || 1, 2)
  const setup = (): void => {
    const element = canvas.value
    if (!element) return
    element.width = Math.round(element.clientWidth * ratio)
    element.height = Math.round(element.clientHeight * ratio)
    element.getContext('2d')?.setTransform(ratio, 0, 0, ratio, 0, 0)
  }
  setup()
  startLoop()
})

watch(
  () => [props.eventsToday, props.severeCount, props.pendingReviews, props.members.length],
  () => startLoop(),
)

onBeforeUnmount(() => {
  cancelAnimationFrame(renderFrame)
  resizeObserver?.disconnect()
  themeObserver?.disconnect()
  motionMedia?.removeEventListener?.('change', onMotionChange)
})
</script>

<template>
  <section class="vital-pulse" :class="{ 'vital-pulse--alert': severeCount > 0 }" aria-label="数字孪生家庭状态投影">
    <div class="vital-pulse-heading">
      <div>
        <span class="vital-eyebrow"><AppIcon name="timeline" :size="13" /> 聚合投影 · 本地可信域</span>
        <h3>家庭轨道核心</h3>
      </div>
      <span class="vital-signal" :class="{ alert: severeCount > 0, pending: severeCount === 0 && pendingReviews > 0 }"><i /> {{ pulseLabel }}</span>
    </div>

    <div class="vital-twin-stage">
      <canvas
        ref="canvas"
        class="vital-twin-canvas"
        role="img"
        :aria-label="`家庭数字孪生核心，链路健康度 ${systemHealth}%，${members.length} 位成员节点，今日事件 ${eventsToday}，待复核 ${pendingReviews}，严重信号 ${severeCount}`"
      />
      <div class="vital-twin-core" aria-hidden="true">
        <strong>{{ systemHealth }}<small>%</small></strong>
        <span>链路在线 {{ runtimeOnline }}/{{ runtimeTotal }}</span>
      </div>
      <div class="vital-twin-chip" aria-hidden="true">
        <strong>{{ eventsToday }}</strong>
        <span>今日事件</span>
      </div>
    </div>

    <div class="vital-alert-stack">
      <span :class="{ active: pendingReviews > 0 }"><i />待复核 {{ pendingReviews }}</span>
      <span :class="{ active: severeCount > 0, danger: severeCount > 0 }"><i />严重信号 {{ severeCount }}</span>
    </div>
    <p class="vital-note">视觉脉搏由当前可见的聚合状态驱动，不代表医学生命体征。</p>
  </section>
</template>
