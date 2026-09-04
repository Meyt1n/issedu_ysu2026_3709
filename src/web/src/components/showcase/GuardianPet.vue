<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import AppIcon from '../AppIcon.vue'
import CompanionPet from '../CompanionPet.vue'
import type { CompanionPetState } from '../../assets/pet/manifest'
import { session, setView } from '../../store'
import { resolvePetMenuPlacement } from '../../ui/petMenuPlacement'
import { guardianStateFor, type GuardianState } from '../../ui/showcase'

/* ── 家健镜桌宠（HCT-534）──
 * 角色化的陪伴小精灵：反映真实系统状态（登录/同步/扫描/待复核/离线），
 * 提供 AI 助手等快捷入口；可拖拽重位并记忆。它只是视觉陪伴，不做健康判断。 */

const state = computed<GuardianState>(() => guardianStateFor({
  sessionStatus: session.status,
  currentView: session.currentView,
  loadingScope: session.loadingScope,
  pendingReviewCount: session.pendingReviewCount,
}))

const stateLabel: Record<GuardianState, string> = {
  idle: '守护在线',
  loading: '正在同步',
  scanning: '扫描中',
  assistant: '陪伴中',
  attention: '需要注意',
  offline: '离线',
}

/* ── 情境气泡 ── */

const hour = new Date().getHours()
const idleMessages = computed(() => {
  if (hour < 5) return ['夜深啦，先好好休息吧，我会安静陪着你 (－ω－) zzZ']
  if (hour < 11) return ['早上好呀，今天也一起照顾好家人吧 (｡•̀ᴗ-)✧', '家庭记录都在本地可信空间里，安心交给我吧 ( ´ ▽ ` )ﾉ']
  if (hour < 14) return ['中午好，忙碌的时候也别忘了按时吃饭呀 (๑´ڡ`๑)', '我在这里，需要时轻轻叫我就好 (｡･ω･｡)ﾉ♡']
  if (hour < 19) return ['下午好～要不要一起看看家里最近的变化？( •̀ ω •́ )✧', '左键和我互动，右键可以打开快捷入口哦 (￣▽￣)ノ']
  return ['晚上好，今天也辛苦啦 (づ｡◕‿‿◕｡)づ', '慢慢整理就好，我会一直陪着你 (｡•́‿•̀｡)']
})

const contextMessage = computed<string | null>(() => {
  if (state.value === 'offline') return '本地服务暂时没连上，我陪你一起等等 (｡•́︿•̀｡)'
  if (state.value === 'loading') return '正在整理家庭数据，马上就好啦 ( •̀ᴗ•́ )و'
  if (state.value === 'attention') return `有 ${session.pendingReviewCount} 条识别候选等你复核，不会自动入档哦 (｀･ω･´)ゞ`
  if (state.value === 'assistant') return '我在认真听呢，请慢慢说 (｡･ω･｡)'
  if (state.value === 'scanning') return '正在本机识别图片，稍后还要请你确认一下 ( •̀ ω •́ )✧'
  return null
})

const bubbleText = ref(idleMessages.value[0] ?? '我在这儿呢。')
const bubbleVisible = ref(false)

let cycleTimer: ReturnType<typeof setInterval> | null = null
let hideTimer: ReturnType<typeof setTimeout> | null = null
let messageIndex = 0

function showMessage(text: string, duration = 7000): void {
  bubbleText.value = text
  bubbleVisible.value = true
  if (hideTimer) clearTimeout(hideTimer)
  hideTimer = setTimeout(() => { bubbleVisible.value = false }, duration)
}

function cycleMessage(): void {
  if (state.value !== 'idle') return
  const pool = idleMessages.value
  messageIndex = (messageIndex + 1) % pool.length
  showMessage(pool[messageIndex])
}

/* ── 快捷菜单 ── */

const menuOpen = ref(false)

const homeView = computed(() => (session.portal === 'member' ? 'member-home' : 'overview'))

const CHIRP_LINES = [
  '嘿嘿，找到我啦 (≧▽≦)',
  '我在呢～(｡･ω･｡)ﾉ',
  '今天也一起加油吧 (ง •̀_•́)ง',
  '被摸摸头啦，好开心 (๑˃̵ᴗ˂̵)و',
  '慢慢来，我陪着你 (づ￣ ³￣)づ',
]

const menuItems = computed(() => {
  const items: Array<{ key: string; label: string; hint: string; icon: string; badge?: number; run: () => void }> = [
    {
      key: 'assistant',
      label: '打开健康助手',
      hint: 'AI 问答 · 证据优先',
      icon: 'assistant',
      run: () => setView('assistant'),
    },
    {
      key: 'home',
      label: session.portal === 'member' ? '回到我的首页' : '家庭总览',
      hint: '看看家里最近的近况',
      icon: 'home',
      run: () => setView(homeView.value),
    },
  ]
  if (session.portal === 'admin') {
    items.push({
      key: 'scan',
      label: '扫描药盒',
      hint: '拍照识别，人工确认后入档',
      icon: 'scan',
      run: () => setView('scan'),
    })
    if (session.pendingReviewCount > 0) {
      items.push({
        key: 'review',
        label: '待人工复核',
        hint: `${session.pendingReviewCount} 条候选等待确认`,
        icon: 'review',
        badge: session.pendingReviewCount,
        run: () => setView('review'),
      })
    }
  }
  return items
})

const menuVertical = ref<'above' | 'below'>('above')
const menuHorizontal = ref<'left' | 'right'>('right')
const menuLeft = ref(0)

function updateMenuPlacement(): void {
  const rect = rootEl.value?.getBoundingClientRect()
  if (!rect) return
  const estimatedMenuWidth = 246
  const estimatedMenuHeight = session.portal === 'admin' ? 350 : 270
  const viewportWidth = globalThis.innerWidth || 1280
  const viewportHeight = globalThis.innerHeight || 720
  const actualMenuWidth = Math.min(estimatedMenuWidth, Math.max(viewportWidth - 20, 1))
  const placement = resolvePetMenuPlacement(
    rect,
    { width: viewportWidth, height: viewportHeight },
    { width: actualMenuWidth, height: estimatedMenuHeight },
  )
  menuVertical.value = placement.vertical
  menuHorizontal.value = placement.horizontal

  const idealLeft = placement.horizontal === 'left' ? rect.left : rect.right - actualMenuWidth
  const clampedLeft = Math.min(
    Math.max(idealLeft, 10),
    Math.max(viewportWidth - actualMenuWidth - 10, 10),
  )
  menuLeft.value = clampedLeft - rect.left
}

function toggleContextMenu(): void {
  updateMenuPlacement()
  menuOpen.value = !menuOpen.value
  bubbleVisible.value = false
}

function onPetKeydown(event: KeyboardEvent): void {
  if (event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10')) {
    event.preventDefault()
    toggleContextMenu()
  }
}

function runItem(run: () => void): void {
  menuOpen.value = false
  run()
}

/* ── 摸摸头与喂小饼干：爱心/饼干反应 ── */

const heartsTick = ref(0)
const showHearts = ref(false)
const showCookie = ref(false)
const munching = ref(false)
let munchTimer: ReturnType<typeof setTimeout> | null = null

const companionState = computed<CompanionPetState>(() => {
  if (showHearts.value) return 'cheer'
  if (munching.value) return 'happy'
  const stateMap: Record<GuardianState, CompanionPetState> = {
    idle: 'idle',
    loading: 'loading',
    scanning: 'think',
    assistant: 'listening',
    attention: 'reminder',
    offline: 'sleep',
  }
  return stateMap[state.value]
})

function petHead(): void {
  heartsTick.value += 1
  showHearts.value = true
  showMessage(
    contextMessage.value
      ?? CHIRP_LINES[Math.floor(Math.random() * CHIRP_LINES.length)]
      ?? '我在呢～(｡･ω･｡)ﾉ',
    3200,
  )
  setTimeout(() => { showHearts.value = false }, 1800)
}

function feedPet(): void {
  showCookie.value = true
  munching.value = true
  showMessage('谢谢投喂！数据小饼干最好吃了。', 3200)
  if (munchTimer) clearTimeout(munchTimer)
  munchTimer = setTimeout(() => {
    showCookie.value = false
    munching.value = false
  }, 1600)
}

/* ── 夜晚模式：22 点后打瞌睡，头顶挂月牙 ── */

const hourNow = new Date().getHours()
const isNight = hourNow >= 22 || hourNow < 6

/* ── 拖拽重位（记忆到 localStorage）── */

const PET_POS_KEY = 'hct:pet-pos'
const rootEl = ref<HTMLElement | null>(null)
const petPos = ref<{ left: number; top: number } | null>(null)
let dragging = false
let dragMoved = false
let dragStartX = 0
let dragStartY = 0
let originLeft = 0
let originTop = 0

function clampPos(left: number, top: number): { left: number; top: number } {
  const width = rootEl.value?.offsetWidth ?? 200
  const height = rootEl.value?.offsetHeight ?? 96
  const maxX = globalThis.innerWidth - width - 8
  const maxY = globalThis.innerHeight - height - 8
  return {
    left: Math.min(Math.max(left, 8), Math.max(maxX, 8)),
    top: Math.min(Math.max(top, 8), Math.max(maxY, 8)),
  }
}

function restorePos(): void {
  try {
    const raw = globalThis.localStorage?.getItem(PET_POS_KEY)
    if (!raw) return
    const parsed = JSON.parse(raw) as { left?: unknown; top?: unknown }
    if (typeof parsed.left === 'number' && typeof parsed.top === 'number') {
      petPos.value = clampPos(parsed.left, parsed.top)
    }
  } catch {
    // 无法持久化时使用默认位置。
  }
}

function persistPos(): void {
  if (!petPos.value) return
  try {
    globalThis.localStorage?.setItem(PET_POS_KEY, JSON.stringify(petPos.value))
  } catch {
    // 忽略持久化失败。
  }
}

function onDragStart(event: PointerEvent): void {
  if (event.button !== 0) return
  if ((event.target as HTMLElement).closest('.pet-menu') !== null) return
  dragging = true
  dragMoved = false
  dragStartX = event.clientX
  dragStartY = event.clientY
  const rect = rootEl.value?.getBoundingClientRect()
  originLeft = rect?.left ?? 0
  originTop = rect?.top ?? 0
  ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
}

function onDragMove(event: PointerEvent): void {
  if (!dragging) return
  const dx = event.clientX - dragStartX
  const dy = event.clientY - dragStartY
  if (!dragMoved && Math.hypot(dx, dy) < 6) return
  dragMoved = true
  menuOpen.value = false
  bubbleVisible.value = false
  petPos.value = clampPos(originLeft + dx, originTop + dy)
}

function onDragEnd(): void {
  if (!dragging) return
  dragging = false
  if (dragMoved) persistPos()
}

function onViewportResize(): void {
  if (petPos.value) petPos.value = clampPos(petPos.value.left, petPos.value.top)
  if (menuOpen.value) updateMenuPlacement()
}

function onGlobalKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape' && menuOpen.value) menuOpen.value = false
}

function onDocumentPointerDown(event: PointerEvent): void {
  if (!menuOpen.value) return
  const target = event.target as Node | null
  if (target && !rootEl.value?.contains(target)) menuOpen.value = false
}

onMounted(() => {
  restorePos()
  cycleTimer = setInterval(cycleMessage, 40_000)
  // 首次进入 4 秒后打招呼。
  setTimeout(() => { if (state.value !== 'offline') showMessage(idleMessages.value[0] ?? '我在这儿呢。', 6000) }, 4_000)
  globalThis.addEventListener?.('resize', onViewportResize)
  globalThis.addEventListener?.('keydown', onGlobalKeydown)
  globalThis.document?.addEventListener('pointerdown', onDocumentPointerDown)
})

onBeforeUnmount(() => {
  if (cycleTimer) clearInterval(cycleTimer)
  if (hideTimer) clearTimeout(hideTimer)
  if (munchTimer) clearTimeout(munchTimer)
  globalThis.removeEventListener?.('resize', onViewportResize)
  globalThis.removeEventListener?.('keydown', onGlobalKeydown)
  globalThis.document?.removeEventListener('pointerdown', onDocumentPointerDown)
})
</script>

<template>
  <div
    v-if="session.status === 'ready'"
    ref="rootEl"
    class="pet-root"
    :class="[
      `pet-root--${state}`,
      `pet-root--menu-${menuVertical}`,
      `pet-root--menu-${menuHorizontal}`,
      { 'pet-root--dragging': dragging, 'pet-root--munch': munching, 'pet-root--night': isNight },
    ]"
    :style="petPos ? { left: `${petPos.left}px`, top: `${petPos.top}px`, right: 'auto', bottom: 'auto' } : undefined"
  >
    <!-- 情境气泡 -->
    <Transition name="pet-bubble">
      <div
        v-if="bubbleVisible"
        class="pet-bubble"
        role="status"
        aria-live="polite"
      >
        {{ bubbleText }}
      </div>
    </Transition>

    <!-- 快捷菜单 -->
    <Transition name="pet-menu">
      <div
        v-if="menuOpen"
        class="pet-menu"
        :class="[`pet-menu--${menuVertical}`, `pet-menu--${menuHorizontal}`]"
        :style="{ left: `${menuLeft}px`, right: 'auto' }"
        role="menu"
        aria-label="小芽精灵快捷菜单"
      >
        <p class="pet-menu-title">{{ stateLabel[state] }} · 快捷入口</p>
        <button
          v-for="item in menuItems"
          :key="item.key"
          type="button"
          class="pet-menu-item"
          role="menuitem"
          @click="runItem(item.run)"
        >
          <AppIcon :name="item.icon" :size="15" />
          <span class="pet-menu-copy">
            <strong>{{ item.label }}</strong>
            <small>{{ item.hint }}</small>
          </span>
          <span v-if="item.badge" class="pet-menu-badge">{{ item.badge > 9 ? '9+' : item.badge }}</span>
        </button>
        <button type="button" class="pet-menu-item pet-menu-item--pet" role="menuitem" @click="petHead(); menuOpen = false">
          <AppIcon name="sparkle" :size="15" />
          <span class="pet-menu-copy">
            <strong>摸摸头</strong>
            <small>和它打个招呼</small>
          </span>
        </button>
        <button type="button" class="pet-menu-item pet-menu-item--pet" role="menuitem" @click="feedPet(); menuOpen = false">
          <AppIcon name="sun" :size="15" />
          <span class="pet-menu-copy">
            <strong>喂小饼干</strong>
            <small>投喂一块数据小饼干</small>
          </span>
        </button>
        <p class="pet-menu-note">视觉陪伴 · 不做健康判断</p>
      </div>
    </Transition>

    <!-- 摸摸头爱心 -->
    <div v-if="showHearts" :key="heartsTick" class="pet-hearts" aria-hidden="true">
      <i>♥</i><i>♥</i><i>♥</i>
    </div>

    <!-- 喂食小饼干 -->
    <Transition name="pet-cookie">
      <span v-if="showCookie" class="pet-cookie" aria-hidden="true">🍪</span>
    </Transition>

    <!-- 桌宠本体 -->
    <button
      type="button"
      class="pet-button"
      :aria-label="`小芽精灵。当前状态：${stateLabel[state]}。左键互动，右键打开快捷菜单，拖动可调整位置`"
      :aria-expanded="menuOpen"
      aria-haspopup="menu"
      :title="`${stateLabel[state]} · 左键互动，右键打开快捷栏`"
      @click="dragMoved ? undefined : petHead()"
      @contextmenu.prevent="toggleContextMenu"
      @keydown="onPetKeydown"
      @pointerdown="onDragStart"
      @pointermove="onDragMove"
      @pointerup="onDragEnd"
      @pointercancel="onDragEnd"
      @mouseenter="bubbleVisible = bubbleVisible || state === 'idle'"
    >
      <CompanionPet
        class="pet-body"
        :state="isNight && state === 'idle' ? 'sleep' : companionState"
        size="medium"
        :clickable="false"
        :show-bubble="false"
        :loop="true"
        :autoplay="true"
      />
      <span class="pet-status" aria-hidden="true"><i /></span>
    </button>
  </div>
</template>

<style scoped>
.pet-root {
  bottom: 22px;
  pointer-events: none;
  position: fixed;
  right: 22px;
  z-index: 1200;
}

.pet-root--dragging { opacity: 0.92; }

.pet-button {
  background: transparent;
  border: 0;
  cursor: grab;
  display: block;
  padding: 0;
  pointer-events: auto;
  position: relative;
  touch-action: none;
  transition: transform 0.22s cubic-bezier(0.34, 1.56, 0.64, 1), filter 0.22s ease;
  animation: pet-float 4.4s ease-in-out infinite;
}

.pet-button:active { cursor: grabbing; }
.pet-root--dragging .pet-button { animation: none; transform: scale(1.05); }

.pet-button:hover { transform: translateY(-3px) scale(1.04); filter: drop-shadow(0 10px 16px rgba(64, 84, 74, 0.22)); }

@keyframes pet-float {
  0%, 100% { translate: 0 0; }
  50% { translate: 0 -4px; }
}

/* 状态光点 */
.pet-status {
  background: rgba(255, 252, 243, 0.92);
  border: 1px solid var(--line, #d7dde5);
  border-radius: 999px;
  box-shadow: 0 2px 8px rgba(63, 58, 49, 0.14);
  display: inline-flex;
  padding: 3px;
  position: absolute;
  right: 2px;
  top: 2px;
}

.pet-status i {
  background: var(--pine, #38665a);
  border-radius: 50%;
  display: block;
  height: 7px;
  width: 7px;
}

.pet-root--loading .pet-status i { background: var(--gold, #a97e1f); }
.pet-root--scanning .pet-status i { background: var(--sky, #47708c); }
.pet-root--assistant .pet-status i { background: #a8789b; }
.pet-root--attention .pet-status i { background: var(--clay, #c26744); animation: pet-blink-dot 1s ease-in-out infinite; }
.pet-root--offline .pet-status i { background: var(--ink-faint, #877966); }

@keyframes pet-blink-dot {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.35; }
}

/* 角色 */
.pet-body { display: block; height: 76px; width: 76px; }

.pet-blob {
  fill: #fbf3e2;
  filter: drop-shadow(0 8px 14px rgba(64, 84, 74, 0.18));
  stroke: var(--pine-deep, #2a4d42);
  stroke-width: 2;
}

.pet-sprout { fill: var(--pine, #38665a); stroke: var(--pine-deep, #2a4d42); stroke-linecap: round; stroke-width: 1.6; }
.pet-root--loading .pet-sprout { transform-box: fill-box; transform-origin: bottom center; animation: pet-sprout-sway 1s ease-in-out infinite; }
.pet-root--scanning .pet-sprout { transform-box: fill-box; transform-origin: bottom center; animation: pet-sprout-sway 0.7s ease-in-out infinite; }

@keyframes pet-sprout-sway {
  0%, 100% { transform: rotate(-8deg); }
  50% { transform: rotate(8deg); }
}

.pet-cheek { fill: rgba(226, 148, 116, 0.4); opacity: 0; transition: opacity 0.3s ease; }
.pet-root--assistant .pet-cheek,
.pet-root--attention .pet-cheek { opacity: 1; }

.pet-eye ellipse { fill: var(--pine-deep, #2a4d42); }
.pet-eye-light { fill: #fff; }
.pet-eyes { transform-box: fill-box; transform-origin: center; animation: pet-blink 4.6s ease-in-out infinite; }
.pet-eyes-happy,
.pet-eyes-sleep { display: none; stroke: var(--pine-deep, #2a4d42); stroke-linecap: round; stroke-width: 2.2; fill: none; }

.pet-root--assistant .pet-eyes-happy,
.pet-root--attention .pet-eyes-happy { display: block; }
.pet-root--assistant .pet-eyes,
.pet-root--attention .pet-eyes,
.pet-root--offline .pet-eyes { display: none; }
.pet-root--offline .pet-eyes-sleep { display: block; }

@keyframes pet-blink {
  0%, 92%, 100% { transform: scaleY(1); }
  95% { transform: scaleY(0.08); }
}

.pet-mouth { fill: none; stroke: var(--pine-deep, #2a4d42); stroke-linecap: round; stroke-width: 2; transition: d 0.3s ease; }
.pet-root--offline .pet-mouth { opacity: 0.45; }

.pet-alert-drop { display: none; fill: var(--clay, #c26744); }
.pet-root--attention .pet-alert-drop { display: block; animation: pet-drop-bounce 1.2s ease-in-out infinite; }

@keyframes pet-drop-bounce {
  0%, 100% { transform: translateY(0); opacity: 1; }
  50% { transform: translateY(-3px); opacity: 0.7; }
}

/* 状态配饰：默认全部隐藏，按状态/时段点亮。 */
.pet-gear { display: none; }
.pet-root--scanning .pet-gear--magnifier { display: block; animation: pet-gear-bob 1.6s ease-in-out infinite; transform-box: fill-box; transform-origin: center; }
.pet-root--assistant .pet-gear--headphone { display: block; }
.pet-root--offline .pet-gear--zzz { display: block; }
.pet-gear--zzz text { animation: pet-zzz-float 2.4s ease-in-out infinite; }
.pet-gear--zzz text:last-child { animation-delay: 1.2s; }

@keyframes pet-gear-bob {
  0%, 100% { transform: rotate(-6deg); }
  50% { transform: rotate(8deg); }
}

@keyframes pet-zzz-float {
  0%, 100% { opacity: 0.4; transform: translateY(0); }
  50% { opacity: 1; transform: translateY(-2px); }
}

/* 夜晚模式：深色调身体 + 月牙，空闲时打瞌睡。 */
.pet-root--night .pet-blob { fill: #efe6d2; }
.pet-root--night .pet-gear--moon { display: block; animation: pet-zzz-float 3.2s ease-in-out infinite; }
.pet-root--night.pet-root--idle .pet-eyes-sleep { display: block; }
.pet-root--night.pet-root--idle .pet-eyes { display: none; }

/* 喂食咀嚼：整体快速弹性压缩两下。 */
.pet-root--munch .pet-button { animation: pet-munch 0.4s ease-in-out 3; }

@keyframes pet-munch {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.07, 0.93); }
}

/* 小饼干从上方落下又被吃掉。 */
.pet-cookie {
  font-size: 20px;
  left: 50%;
  pointer-events: none;
  position: absolute;
  top: -12px;
  transform: translateX(-50%);
}

.pet-cookie-enter-active { animation: pet-cookie-drop 0.9s ease-in both; }
.pet-cookie-leave-active { transition: opacity 0.3s ease; }
.pet-cookie-leave-to { opacity: 0; }

@keyframes pet-cookie-drop {
  0% { opacity: 0; transform: translate(-50%, -18px) rotate(-30deg); }
  55% { opacity: 1; }
  100% { opacity: 1; transform: translate(-50%, 18px) rotate(12deg); }
}

/* 情境气泡 */
.pet-bubble {
  background: rgba(255, 252, 243, 0.97);
  border: 1px solid color-mix(in srgb, var(--pine, #38665a) 30%, var(--line, #d7dde5));
  border-radius: 14px 14px 14px 4px;
  bottom: calc(100% + 10px);
  box-shadow: 0 10px 26px rgba(64, 84, 74, 0.16);
  color: var(--ink, #3f3a31);
  font-size: 12.5px;
  left: 0;
  line-height: 1.55;
  max-width: 250px;
  padding: 10px 13px;
  pointer-events: none;
  position: absolute;
  white-space: normal;
  width: max-content;
}

.pet-bubble-enter-active,
.pet-bubble-leave-active { transition: opacity 0.24s ease, transform 0.24s ease; }
.pet-bubble-enter-from,
.pet-bubble-leave-to { opacity: 0; transform: translateY(6px) scale(0.96); }

/* 快捷菜单 */
.pet-menu {
  box-sizing: border-box;
  background: rgba(255, 253, 247, 0.98);
  border: 1px solid color-mix(in srgb, var(--pine, #38665a) 26%, var(--line, #d7dde5));
  border-radius: 16px;
  box-shadow: 0 18px 40px rgba(64, 84, 74, 0.2);
  color: var(--ink, #3f3a31);
  min-width: 0;
  padding: 10px;
  pointer-events: auto;
  position: absolute;
  width: min(246px, calc(100vw - 20px));
}

.pet-menu--above { bottom: calc(100% + 10px); top: auto; transform-origin: bottom; }
.pet-menu--below { bottom: auto; top: calc(100% + 10px); transform-origin: top; }
.pet-menu--left { left: 0; right: auto; }
.pet-menu--right { left: auto; right: 0; }

.pet-menu-title {
  color: var(--ink-faint, #877966);
  font-size: 10.5px;
  font-weight: 650;
  letter-spacing: 0.04em;
  margin: 2px 4px 8px;
}

.pet-menu-item {
  align-items: center;
  background: transparent;
  border: 0;
  border-radius: 11px;
  color: inherit;
  cursor: pointer;
  display: flex;
  gap: 10px;
  padding: 8px 9px;
  text-align: left;
  transition: background 0.16s ease;
  width: 100%;
}

.pet-menu-item:hover,
.pet-menu-item:focus-visible {
  background: color-mix(in srgb, var(--pine, #38665a) 10%, transparent);
  outline: none;
}

.pet-menu-item .app-icon { color: var(--pine, #38665a); flex-shrink: 0; }
.pet-menu-item--pet .app-icon { color: var(--clay, #c26744); }

.pet-menu-copy { display: grid; flex: 1; gap: 1px; min-width: 0; }
.pet-menu-copy strong { font-size: 13px; font-weight: 600; }
.pet-menu-copy small { color: var(--ink-soft, #6d6659); font-size: 11px; }

.pet-menu-badge {
  background: var(--clay, #c26744);
  border-radius: 999px;
  color: #fff;
  font-size: 10.5px;
  font-weight: 700;
  padding: 1.5px 7px;
}

.pet-menu-note {
  border-top: 1px dashed var(--line, #d7dde5);
  color: var(--ink-faint, #877966);
  font-size: 10.5px;
  margin: 8px 4px 2px;
  padding-top: 8px;
  text-align: center;
}

.pet-menu-enter-active,
.pet-menu-leave-active { transition: opacity 0.2s ease, transform 0.2s ease; }
.pet-menu-enter-from,
.pet-menu-leave-to { opacity: 0; transform: translateY(8px) scale(0.97); }

/* 摸摸头爱心 */
.pet-hearts {
  left: 50%;
  pointer-events: none;
  position: absolute;
  top: -6px;
}

.pet-hearts i {
  color: var(--clay, #c26744);
  font-size: 14px;
  font-style: normal;
  position: absolute;
  animation: pet-heart-rise 1.6s ease-out both;
}

.pet-hearts i:nth-child(1) { left: -6px; }
.pet-hearts i:nth-child(2) { left: 12px; animation-delay: 0.24s; font-size: 11px; }
.pet-hearts i:nth-child(3) { left: -20px; animation-delay: 0.42s; font-size: 12px; }

@keyframes pet-heart-rise {
  0% { opacity: 0; transform: translateY(4px) scale(0.6); }
  22% { opacity: 1; }
  100% { opacity: 0; transform: translateY(-46px) scale(1.15); }
}

@media (max-width: 768px) {
  .pet-root { bottom: 14px; right: 12px; }
  .pet-body { height: 62px; width: 62px; }
  .pet-bubble { max-width: 200px; font-size: 12px; }
}

@media (prefers-reduced-motion: reduce) {
  .pet-button,
  .pet-eyes,
  .pet-sprout,
  .pet-alert-drop,
  .pet-gear--zzz text,
  .pet-gear--moon,
  .pet-hearts i { animation: none !important; }
  .pet-root--munch .pet-button { animation: none !important; }
  .pet-cookie-enter-active { animation: none; }
}
</style>
