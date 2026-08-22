<script setup lang="ts">
import { computed, defineAsyncComponent, onBeforeUnmount, onMounted, ref, watch, type Component } from 'vue'

import AppIcon from './components/AppIcon.vue'
import CommandPalette from './components/CommandPalette.vue'
import ConfirmDialog from './components/ConfirmDialog.vue'
import SkeletonList from './components/SkeletonList.vue'
import {
  dismissToast,
  selectHousehold,
  session,
  setView,
  signOut,
  type ViewName,
} from './store'
import { installRipple, vMagnet } from './ui/motion'
import { THEMES, applyTheme, currentTheme, type ThemeId } from './ui/themes'
// 欢迎页是首屏必经路径，保持同步加载；十二个业务视图按需拆包，
// 首屏只下载当前视图的代码，切换视图时由 Vite 预构建的 chunk 即时载入。
import WelcomeView from './views/WelcomeView.vue'

function lazyView(loader: () => Promise<{ default: Component }>) {
  return defineAsyncComponent({
    loader,
    loadingComponent: SkeletonList,
    delay: 0,
    timeout: 20_000,
  })
}

const VIEW_LOADERS = {
  overview: () => import('./views/OverviewView.vue'),
  members: () => import('./views/MembersView.vue'),
  plans: () => import('./views/PlansView.vue'),
  scan: () => import('./views/ScanView.vue'),
  review: () => import('./views/ReviewView.vue'),
  risks: () => import('./views/RisksView.vue'),
  graph: () => import('./views/GraphView.vue'),
  assistant: () => import('./views/AssistantView.vue'),
  bigscreen: () => import('./views/BigScreenView.vue'),
  authorizations: () => import('./views/AuthView.vue'),
  knowledge: () => import('./views/KnowledgeView.vue'),
  modellab: () => import('./views/ModelLabView.vue'),
  'face-credentials': () => import('./views/FaceCredentialView.vue'),
} satisfies Record<ViewName, () => Promise<{ default: Component }>>

const OverviewView = lazyView(VIEW_LOADERS.overview)
const MembersView = lazyView(VIEW_LOADERS.members)
const PlansView = lazyView(VIEW_LOADERS.plans)
const ScanView = lazyView(VIEW_LOADERS.scan)
const ReviewView = lazyView(VIEW_LOADERS.review)
const RisksView = lazyView(VIEW_LOADERS.risks)
const GraphView = lazyView(VIEW_LOADERS.graph)
const AssistantView = lazyView(VIEW_LOADERS.assistant)
const BigScreenView = lazyView(VIEW_LOADERS.bigscreen)
const AuthView = lazyView(VIEW_LOADERS.authorizations)
const KnowledgeView = lazyView(VIEW_LOADERS.knowledge)
const ModelLabView = lazyView(VIEW_LOADERS.modellab)
const FaceCredentialView = lazyView(VIEW_LOADERS['face-credentials'])

const NAV_ITEMS: Array<{ view: ViewName; label: string; icon: string; group: string }> = [
  { view: 'overview', label: '家庭总览', icon: 'home', group: '日常照护' },
  { view: 'members', label: '成员档案', icon: 'members', group: '日常照护' },
  { view: 'plans', label: '健康计划', icon: 'plan', group: '日常照护' },
  { view: 'scan', label: '视觉扫描', icon: 'scan', group: '证据录入' },
  { view: 'review', label: '人工复核', icon: 'review', group: '证据录入' },
  { view: 'risks', label: '用药安全', icon: 'shield', group: '安全与洞察' },
  { view: 'graph', label: '健康图谱', icon: 'compass', group: '安全与洞察' },
  { view: 'assistant', label: '本地助手', icon: 'assistant', group: '安全与洞察' },
  { view: 'bigscreen', label: '家庭大屏', icon: 'sun', group: '家庭与研发' },
  { view: 'authorizations', label: '授权管理', icon: 'key', group: '家庭与研发' },
  { view: 'knowledge', label: '知识文档', icon: 'leaf', group: '家庭与研发' },
  { view: 'modellab', label: '模型实验室', icon: 'sparkle', group: '家庭与研发' },
  { view: 'face-credentials', label: '人脸凭证', icon: 'shield', group: '家庭与研发' },
]

const VIEW_COMPONENTS: Record<ViewName, unknown> = {
  overview: OverviewView,
  members: MembersView,
  plans: PlansView,
  scan: ScanView,
  review: ReviewView,
  risks: RisksView,
  graph: GraphView,
  assistant: AssistantView,
  authorizations: AuthView,
  bigscreen: BigScreenView,
  knowledge: KnowledgeView,
  modellab: ModelLabView,
  'face-credentials': FaceCredentialView,
}

const navGroups = computed(() => {
  const groups: Array<{ name: string; items: typeof NAV_ITEMS }> = []
  for (const item of NAV_ITEMS) {
    const group = groups.find(entry => entry.name === item.group)
    if (group) group.items.push(item)
    else groups.push({ name: item.group, items: [item] })
  }
  return groups
})

const activeNav = computed(
  () => NAV_ITEMS.find(item => item.view === session.currentView) ?? NAV_ITEMS[0]!,
)

const currentComponent = computed(() => VIEW_COMPONENTS[session.currentView])

const toastIcon: Record<string, string> = {
  success: 'check',
  error: 'alert',
  info: 'info',
}

/* ── 命令面板（Ctrl+K） ── */

const paletteRef = ref<InstanceType<typeof CommandPalette> | null>(null)

/* ── 主题切换 ── */

const themeMenuOpen = ref(false)

function pickTheme(id: ThemeId): void {
  applyTheme(id)
  themeMenuOpen.value = false
}

/* ── 折叠侧栏 ── */

const SIDEBAR_KEY = 'hct-sidebar'
const sidebarMini = ref(globalThis.localStorage?.getItem(SIDEBAR_KEY) === 'mini')

function toggleSidebar(): void {
  sidebarMini.value = !sidebarMini.value
  try {
    globalThis.localStorage?.setItem(SIDEBAR_KEY, sidebarMini.value ? 'mini' : 'full')
  } catch {
    // 无法持久化时仅本次会话生效。
  }
}

/* ── 方向感页面过渡 ── */

const transitionName = ref('page-forward')
const transitioning = ref(false)

watch(
  () => session.currentView,
  (next, previous) => {
    const nextIndex = NAV_ITEMS.findIndex(item => item.view === next)
    const previousIndex = NAV_ITEMS.findIndex(item => item.view === previous)
    transitionName.value = nextIndex >= previousIndex ? 'page-forward' : 'page-back'
    globalThis.scrollTo?.({ top: 0, behavior: 'smooth' })
  },
)

function prefetchViews(): void {
  const schedule =
    typeof globalThis.requestIdleCallback === 'function'
      ? (cb: () => void) => globalThis.requestIdleCallback(cb, { timeout: 1600 })
      : (cb: () => void) => globalThis.setTimeout(cb, 280)
  schedule(() => {
    for (const load of Object.values(VIEW_LOADERS)) void load()
  })
}

watch(
  () => session.status,
  status => {
    if (status === 'ready') prefetchViews()
  },
)

async function onHouseholdChange(event: Event): Promise<void> {
  const target = event.target as HTMLSelectElement
  await selectHousehold(target.value)
}

/* ── 光标追光 ── */

const glowEl = ref<HTMLElement | null>(null)
let glowFrame = 0
let glowHandler: ((event: PointerEvent) => void) | null = null

onMounted(() => {
  installRipple()

  const motionOk =
    globalThis.matchMedia?.('(hover: hover)').matches &&
    !globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  if (!motionOk) return

  glowHandler = (event: PointerEvent) => {
    cancelAnimationFrame(glowFrame)
    glowFrame = requestAnimationFrame(() => {
      glowEl.value?.style.setProperty(
        'transform',
        `translate3d(${event.clientX}px, ${event.clientY}px, 0)`,
      )
    })
  }
  window.addEventListener('pointermove', glowHandler, { passive: true })
})

onBeforeUnmount(() => {
  if (glowHandler) window.removeEventListener('pointermove', glowHandler)
  cancelAnimationFrame(glowFrame)
})
</script>

<template>
  <div class="bg-wash" aria-hidden="true" />
  <div class="aurora" aria-hidden="true"><span /><span /><span /></div>
  <div class="fireflies" aria-hidden="true"><i /><i /><i /><i /><i /><i /><i /><i /><i /><i /></div>
  <div class="leaves" aria-hidden="true"><i /><i /><i /><i /></div>
  <div ref="glowEl" class="cursor-glow" aria-hidden="true" />

  <main v-if="session.status !== 'ready'" lang="zh-CN">
    <WelcomeView />
  </main>

  <div v-else class="app-frame" :class="{ mini: sidebarMini }">
    <aside class="sidebar">
      <div class="brand">
        <span class="brand-mark"><AppIcon name="home" :size="24" /></span>
        <div>
          <div class="brand-name">家健镜</div>
          <div class="brand-sub">HomeCare Twin</div>
        </div>
      </div>

      <template v-for="group in navGroups" :key="group.name">
        <p class="nav-group-label">{{ group.name }}</p>
        <ul class="nav-list">
          <li v-for="item in group.items" :key="item.view">
            <button
              type="button"
              class="nav-item"
              :class="{ active: session.currentView === item.view }"
              :title="sidebarMini ? item.label : undefined"
              @click="setView(item.view)"
            >
              <AppIcon :name="item.icon" :size="19" />
              <span class="nav-label">{{ item.label }}</span>
            </button>
          </li>
        </ul>
      </template>

      <div class="sidebar-foot">
        <p class="privacy-note">
          <AppIcon name="lock" :size="16" />
          <span>家庭健康数据默认不出网，全部保存在本地可信域。</span>
        </p>
        <p class="privacy-note">
          <AppIcon name="leaf" :size="16" />
          <span>教学演示系统，不提供诊断、处方或用药决策。</span>
        </p>
        <button type="button" class="sidebar-collapse" :title="sidebarMini ? '展开导航' : '收起导航'" @click="toggleSidebar">
          <AppIcon name="arrow-right" :size="15" style="transform: rotate(180deg)" />
          <span v-if="!sidebarMini">收起导航</span>
        </button>
      </div>
    </aside>

    <div class="main-area">
      <div v-if="transitioning" class="route-progress" aria-hidden="true" />

      <header class="topbar">
        <div class="crumb">
          <span class="crumb-group">{{ activeNav.group }}</span>
          <span class="crumb-sep">/</span>
          <h1 class="topbar-title">{{ activeNav.label }}</h1>
        </div>
        <div class="topbar-side">
          <button
            type="button"
            class="palette-trigger"
            title="打开命令面板（Ctrl+K）"
            @click="paletteRef?.show()"
          >
            <AppIcon name="compass" :size="15" />
            <span class="palette-trigger-text">快速跳转</span>
            <kbd class="palette-kbd">Ctrl</kbd><kbd class="palette-kbd">K</kbd>
          </button>
          <span class="api-dot" :title="session.capabilities ? `本地 API 已连接 · 阶段 ${session.capabilities.phase}` : '本地 API 状态未知'">
            <i :class="session.capabilities ? 'on' : 'off'" />
            {{ session.capabilities ? '本地在线' : '状态未知' }}
          </span>
          <label v-if="session.households.length > 0" class="context-select">
            家庭
            <select
              :value="session.selectedHouseholdId"
              :disabled="session.loadingScope"
              @change="onHouseholdChange"
            >
              <option v-for="household in session.households" :key="household.id" :value="household.id">
                {{ household.name }}
              </option>
            </select>
          </label>
          <button
            v-if="session.currentView !== 'members'"
            v-magnet="3"
            type="button"
            class="btn btn-clay btn-small"
            title="到成员档案手工记录一条健康事实"
            @click="setView('members')"
          >
            <AppIcon name="plus" :size="15" />
            记一笔
          </button>
          <div class="theme-menu-wrap">
            <button
              type="button"
              class="icon-button"
              title="切换界面主题"
              :aria-expanded="themeMenuOpen"
              @click="themeMenuOpen = !themeMenuOpen"
            >
              <AppIcon name="palette" :size="19" />
            </button>
            <div v-if="themeMenuOpen" class="theme-backdrop" @click="themeMenuOpen = false" />
            <div v-if="themeMenuOpen" class="theme-menu" role="menu">
              <p class="theme-menu-label">界面主题</p>
              <button
                v-for="theme in THEMES"
                :key="theme.id"
                type="button"
                class="theme-option"
                :class="{ active: currentTheme === theme.id }"
                role="menuitem"
                @click="pickTheme(theme.id)"
              >
                <span class="theme-dots">
                  <i v-for="color in theme.swatches" :key="color" :style="{ background: color }" />
                </span>
                <span class="theme-name">
                  <strong>{{ theme.name }}</strong>
                  <span>{{ theme.tagline }}</span>
                </span>
                <AppIcon v-if="currentTheme === theme.id" class="theme-check" name="check" :size="15" />
              </button>
            </div>
          </div>
          <span class="identity-chip">
            {{ session.actorId }}
            <span class="role-tag" :class="{ caregiver: !session.isOwnerView }">
              {{ session.isOwnerView ? '家庭管理员' : '授权照护者' }}
            </span>
            <button type="button" class="icon-button" title="退出当前身份" @click="signOut">
              <AppIcon name="signout" :size="17" />
            </button>
          </span>
        </div>
      </header>

      <main class="view-stage" lang="zh-CN">
        <Transition
          :name="transitionName"
          mode="out-in"
          @before-leave="transitioning = true"
          @after-enter="transitioning = false"
        >
          <div
            class="view-container"
            :class="`view-${session.currentView}`"
            :key="session.currentView"
          >
            <Suspense>
              <component :is="currentComponent" />
              <template #fallback>
                <SkeletonList variant="cards" :rows="4" />
              </template>
            </Suspense>
          </div>
        </Transition>
      </main>

      <footer class="app-footer">
        家健镜 HomeCare Twin · 教学演示，不用于诊断或治疗 · 紧急情况请联系医生或当地急救服务
      </footer>
    </div>
  </div>

  <ConfirmDialog />
  <CommandPalette v-if="session.status === 'ready'" ref="paletteRef" :nav-items="NAV_ITEMS" />

  <div class="toast-region" role="status" aria-live="polite">
    <div v-for="toast in session.toasts" :key="toast.id" class="toast" :class="toast.kind">
      <AppIcon :name="toastIcon[toast.kind] ?? 'info'" :size="17" />
      <span>{{ toast.text }}</span>
      <button type="button" class="icon-button toast-close" title="关闭提醒" @click="dismissToast(toast.id)">
        <AppIcon name="close" :size="14" />
      </button>
    </div>
  </div>
</template>
