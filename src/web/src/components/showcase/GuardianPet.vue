<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import AppIcon from '../AppIcon.vue'
import { pushToast, session, setView } from '../../store'
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
  if (hour < 5) return ['夜深了，记得早点休息，我来守着数据。']
  if (hour < 11) return ['早上好呀，今天也一起守护家人健康吧。', '所有健康数据都留在家里，不出网。']
  if (hour < 14) return ['中午好，别忘了按时吃饭呀。', '有我在，数据安安全全的。']
  if (hour < 19) return ['下午好～需要我帮你看看家庭近况吗？', '点我一下，可以快速打开健康助手。']
  return ['晚上好，今天家人的记录都同步好了。', '晚风轻轻的，记得提醒家人按时用药哦。']
})

const contextMessage = computed<string | null>(() => {
  if (state.value === 'offline') return '本地服务暂时不在线，我陪你一起等它回来。'
  if (state.value === 'loading') return '正在同步家庭数据，稍等一下下…'
  if (state.value === 'attention') return `有 ${session.pendingReviewCount} 条识别候选等你复核，不会自动入档。`
  if (state.value === 'assistant') return '问吧，我一直在听。'
  if (state.value === 'scanning') return '正在本机识别图片，完成后会请你人工确认。'
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

const CHIRP_LINES = ['嘿嘿，找我呀？', '在呢在呢～', '要点什么？', '叮！桌宠待命中。']

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

function toggleMenu(): void {
  menuOpen.value = !menuOpen.value
  if (menuOpen.value) {
    bubbleVisible.value = false
    // 三成概率随机啾一下，让每次打开都有点惊喜。
    if (Math.random() < 0.3) {
      showMessage(CHIRP_LINES[Math.floor(Math.random() * CHIRP_LINES.length)] ?? '在呢～', 2400)
    }
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

function petHead(): void {
  heartsTick.value += 1
  showHearts.value = true
  if (state.value === 'offline') {
    pushToast('info', '桌宠只是视觉陪伴，不做健康判断；本地服务恢复后它会亮起来。')
  } else {
    pushToast('success', '桌宠很开心！它只是视觉陪伴，不做健康判断。')
  }
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
}

function onGlobalKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape' && menuOpen.value) menuOpen.value = false
}

onMounted(() => {
  restorePos()
  cycleTimer = setInterval(cycleMessage, 40_000)
  // 首次进入 4 秒后打招呼。
  setTimeout(() => { if (state.value !== 'offline') showMessage(idleMessages.value[0] ?? '我在这儿呢。', 6000) }, 4_000)
  globalThis.addEventListener?.('resize', onViewportResize)
  globalThis.addEventListener?.('keydown', onGlobalKeydown)
})

onBeforeUnmount(() => {
  if (cycleTimer) clearInterval(cycleTimer)
  if (hideTimer) clearTimeout(hideTimer)
  if (munchTimer) clearTimeout(munchTimer)
  globalThis.removeEventListener?.('resize', onViewportResize)
  globalThis.removeEventListener?.('keydown', onGlobalKeydown)
})
</script>

<template>
  <div
    v-if="session.status === 'ready'"
    ref="rootEl"
    class="pet-root"
    :class="[`pet-root--${state}`, { 'pet-root--dragging': dragging, 'pet-root--munch': munching, 'pet-root--night': isNight }]"
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
      <div v-if="menuOpen" class="pet-menu" role="menu" aria-label="桌宠快捷菜单">
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
      :aria-label="`桌宠小精灵。当前状态：${stateLabel[state]}。点击打开快捷菜单，拖动可调整位置`"
      :aria-expanded="menuOpen"
      aria-haspopup="menu"
      :title="`${stateLabel[state]} · 点击打开快捷菜单`"
      @click="dragMoved ? undefined : toggleMenu()"
      @dblclick.prevent="menuOpen = false; petHead()"
      @pointerdown="onDragStart"
      @pointermove="onDragMove"
      @pointerup="onDragEnd"
      @pointercancel="onDragEnd"
      @mouseenter="bubbleVisible = bubbleVisible || state === 'idle'"
    >
      <svg class="pet-body" viewBox="0 0 96 96" fill="none" aria-hidden="true">
        <!-- 头顶新芽 -->
        <g class="pet-sprout">
          <path d="M48 15c0-5 3-8 8-9-1 5-4 8-8 9z" />
          <path d="M48 15c0-4-2.5-6.5-6.5-7.5.8 4 3.2 6.5 6.5 7.5z" opacity="0.7" />
          <path d="M48 15v5" />
        </g>
        <!-- 身体 -->
        <path
          class="pet-blob"
          d="M48 18c17 0 28 10.5 28 25 0 8-2.6 14.5-6.4 19.4C64.6 68.8 57 74 48 74s-16.6-5.2-21.6-11.6C22.6 57.5 20 51 20 43c0-14.5 11-25 28-25z"
        />
        <!-- 腮红 -->
        <circle class="pet-cheek" cx="33" cy="48" r="3.4" />
        <circle class="pet-cheek" cx="63" cy="48" r="3.4" />
        <!-- 眼睛 -->
        <g class="pet-eyes">
          <g class="pet-eye">
            <ellipse cx="38.5" cy="43" rx="3.4" ry="4.1" />
            <circle class="pet-eye-light" cx="39.8" cy="41.4" r="1.15" />
          </g>
          <g class="pet-eye">
            <ellipse cx="57.5" cy="43" rx="3.4" ry="4.1" />
            <circle class="pet-eye-light" cx="58.8" cy="41.4" r="1.15" />
          </g>
        </g>
        <!-- 开心眯眼（assistant / attention 用） -->
        <g class="pet-eyes-happy">
          <path d="M34.5 44c2.4-3.4 5.6-3.4 8 0" />
          <path d="M53.5 44c2.4-3.4 5.6-3.4 8 0" />
        </g>
        <!-- 睡着（offline / 夜间打盹） -->
        <g class="pet-eyes-sleep">
          <path d="M35 43.5h7" />
          <path d="M54 43.5h7" />
        </g>
        <!-- 嘴 -->
        <path class="pet-mouth" d="M44.5 52.5c2.2 2.2 4.8 2.2 7 0" />
        <!-- 需要注意的叹气滴 -->
        <g class="pet-alert-drop">
          <circle cx="66" cy="58" r="2.2" />
        </g>
        <!-- 扫描配饰：放大镜 -->
        <g class="pet-gear pet-gear--magnifier">
          <circle cx="74" cy="36" r="6" fill="#fffdf6" stroke="var(--sky, #47708c)" stroke-width="2" />
          <line x1="78.5" y1="40.5" x2="83" y2="45" stroke="var(--sky, #47708c)" stroke-width="2.4" stroke-linecap="round" />
        </g>
        <!-- 陪伴配饰：耳机 -->
        <g class="pet-gear pet-gear--headphone">
          <path d="M33 30a15 15 0 0 1 30 0" fill="none" stroke="var(--pine, #38665a)" stroke-width="2.4" stroke-linecap="round" />
          <rect x="30" y="28" width="6" height="10" rx="3" fill="var(--pine, #38665a)" />
          <rect x="60" y="28" width="6" height="10" rx="3" fill="var(--pine, #38665a)" />
        </g>
        <!-- 夜晚/离线配饰：瞌睡 zz -->
        <g class="pet-gear pet-gear--zzz" fill="var(--pine, #38665a)">
          <text x="66" y="26" font-size="10" font-weight="700">z</text>
          <text x="73" y="20" font-size="7.5" font-weight="700" opacity="0.75">z</text>
        </g>
        <!-- 夜晚配饰：月牙 -->
        <g class="pet-gear pet-gear--moon">
          <path d="M76 22a7.5 7.5 0 0 1-9.6 9 8.4 8.4 0 0 0 4.2-11.4A8.4 8.4 0 0 1 76 22z" fill="#e9c46a" stroke="#c99b3f" stroke-width="1.2" />
        </g>
      </svg>
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
  background: rgba(255, 253, 247, 0.98);
  border: 1px solid color-mix(in srgb, var(--pine, #38665a) 26%, var(--line, #d7dde5));
  border-radius: 16px;
  bottom: calc(100% + 10px);
  box-shadow: 0 18px 40px rgba(64, 84, 74, 0.2);
  color: var(--ink, #3f3a31);
  min-width: 236px;
  padding: 10px;
  pointer-events: auto;
  position: absolute;
  right: 0;
}

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
