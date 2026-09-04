<script setup lang="ts">
import { computed, defineAsyncComponent, onBeforeUnmount, onMounted, ref, watch, type Component } from 'vue'

import AppIcon from './components/AppIcon.vue'
import AccountSecurityDialog from './components/AccountSecurityDialog.vue'
import CareAtlasBackdrop from './components/CareAtlasBackdrop.vue'
import CommandPalette from './components/CommandPalette.vue'
import ConfirmDialog from './components/ConfirmDialog.vue'
import GuardianPet from './components/showcase/GuardianPet.vue'
import VisualBootOverlay from './components/showcase/VisualBootOverlay.vue'
import SkeletonList from './components/SkeletonList.vue'
import {
  dismissToast,
  onHealthDataRefresh,
  refreshPendingReviewCount,
  selectedMember,
  session,
  setView,
  signOut,
  type ViewName,
} from './store'
import { activeNavItem, groupNavItems, NAV_ITEMS, visibleNavItemsFor } from './ui/navigation'
import { installRipple, vMagnet } from './ui/motion'
import { THEMES, applyTheme, currentTheme, type ThemeId } from './ui/themes'
// 欢迎页是首屏必经路径，保持同步加载；业务视图按需拆包，
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
  'member-home': () => import('./views/MemberHomeView.vue'),
  'member-capture': () => import('./views/MemberCaptureView.vue'),
  'member-plans': () => import('./views/MemberPlansView.vue'),
  'member-records': () => import('./views/MemberRecordsView.vue'),
  'member-help': () => import('./views/MemberHelpView.vue'),
  members: () => import('./views/MembersView.vue'),
  plans: () => import('./views/PlansView.vue'),
  scan: () => import('./views/ScanView.vue'),
  review: () => import('./views/ReviewView.vue'),
  risks: () => import('./views/RisksView.vue'),
  graph: () => import('./views/GraphView.vue'),
  'digital-twin': () => import('./views/DigitalTwinView.vue'),
  assistant: () => import('./views/AssistantView.vue'),
  bigscreen: () => import('./views/BigScreenView.vue'),
  authorizations: () => import('./views/AuthView.vue'),
  knowledge: () => import('./views/KnowledgeView.vue'),
  'face-credentials': () => import('./views/FaceCredentialView.vue'),
} satisfies Record<ViewName, () => Promise<{ default: Component }>>

const OverviewView = lazyView(VIEW_LOADERS.overview)
const MembersView = lazyView(VIEW_LOADERS.members)
const PlansView = lazyView(VIEW_LOADERS.plans)
const ScanView = lazyView(VIEW_LOADERS.scan)
const ReviewView = lazyView(VIEW_LOADERS.review)
const RisksView = lazyView(VIEW_LOADERS.risks)
const GraphView = lazyView(VIEW_LOADERS.graph)
const DigitalTwinView = lazyView(VIEW_LOADERS['digital-twin'])
const AssistantView = lazyView(VIEW_LOADERS.assistant)
const BigScreenView = lazyView(VIEW_LOADERS.bigscreen)
const AuthView = lazyView(VIEW_LOADERS.authorizations)
const KnowledgeView = lazyView(VIEW_LOADERS.knowledge)
const FaceCredentialView = lazyView(VIEW_LOADERS['face-credentials'])
const MemberHomeView = lazyView(VIEW_LOADERS['member-home'])
const MemberCaptureView = lazyView(VIEW_LOADERS['member-capture'])
const MemberPlansView = lazyView(VIEW_LOADERS['member-plans'])
const MemberRecordsView = lazyView(VIEW_LOADERS['member-records'])
const MemberHelpView = lazyView(VIEW_LOADERS['member-help'])

const VIEW_COMPONENTS: Record<ViewName, unknown> = {
  'member-home': MemberHomeView,
  'member-capture': MemberCaptureView,
  'member-plans': MemberPlansView,
  'member-records': MemberRecordsView,
  'member-help': MemberHelpView,
  overview: OverviewView,
  members: MembersView,
  plans: PlansView,
  scan: ScanView,
  review: ReviewView,
  risks: RisksView,
  graph: GraphView,
  'digital-twin': DigitalTwinView,
  assistant: AssistantView,
  authorizations: AuthView,
  bigscreen: BigScreenView,
  knowledge: KnowledgeView,
  'face-credentials': FaceCredentialView,
}

// 导航条目、门户过滤与按 view 去重都在 ui/navigation.ts（HCT-447）：
// 保证同一 view（如共享的 assistant）在任一门户下只渲染一条、只高亮一条。
const visibleNavItems = computed(() => visibleNavItemsFor(session.portal))

const navGroups = computed(() => groupNavItems(visibleNavItems.value))

const activeNav = computed(() => activeNavItem(visibleNavItems.value, session.currentView)!)

const currentMemberLabel = computed(() => selectedMember.value?.display_name ?? '当前成员')
const currentHouseholdLabel = computed(
  () => session.households.find(item => item.id === session.selectedHouseholdId)?.name ?? '家庭空间',
)

const currentComponent = computed(() => VIEW_COMPONENTS[session.currentView])

const toastIcon: Record<string, string> = {
  success: 'check',
  error: 'alert',
  info: 'info',
}

/* ── 命令面板（Ctrl+K） ── */

const paletteRef = ref<InstanceType<typeof CommandPalette> | null>(null)
const accountSecurityOpen = ref(false)

/* ── 系统启动仪式：每次完成新的登录都播放（HCT-533） ── */

const bootVisible = ref(false)
let bootCycleActive = false

function showBootForLogin(): void {
  if (bootVisible.value || bootCycleActive) return
  bootCycleActive = true
  bootVisible.value = true
}

function completeBoot(): void {
  bootVisible.value = false
}

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
    if (status === 'ready') {
      prefetchViews()
      showBootForLogin()
      return
    }
    // 退出、会话过期或重新认证后开启下一次登录的启动仪式。
    bootCycleActive = false
    bootVisible.value = false
  },
  { immediate: true },
)

const ambientState = computed(() => {
  if (session.loadingScope) return 'ambient-loading'
  if (session.pendingReviewCount > 0) return 'ambient-attention'
  return 'ambient-steady'
})

/* ── 光标追光 ── */

const glowEl = ref<HTMLElement | null>(null)
let glowFrame = 0
let glowHandler: ((event: PointerEvent) => void) | null = null
let removeHealthRefreshListener: (() => void) | null = null

onMounted(() => {
  installRipple()
  removeHealthRefreshListener = onHealthDataRefresh(() => {
    if (session.portal === 'admin') void refreshPendingReviewCount()
  })

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
  removeHealthRefreshListener?.()
  if (glowHandler) window.removeEventListener('pointermove', glowHandler)
  cancelAnimationFrame(glowFrame)
})
</script>

<template>
  <div class="bg-wash" aria-hidden="true" />
  <div class="aurora" aria-hidden="true"><span /><span /><span /></div>
  <div class="fireflies" aria-hidden="true"><i /><i /><i /><i /><i /><i /><i /><i /><i /><i /></div>
  <div class="leaves" aria-hidden="true"><i /><i /><i /><i /></div>
  <CareAtlasBackdrop
    v-if="session.status === 'ready' && session.currentView !== 'bigscreen' && currentTheme === 'warm'"
  />
  <div ref="glowEl" class="cursor-glow" aria-hidden="true" />

  <VisualBootOverlay :visible="bootVisible" :capabilities="session.capabilities" @complete="completeBoot" />

  <main v-if="session.status !== 'ready'" lang="zh-CN">
    <WelcomeView />
  </main>

  <div v-else class="app-frame" :class="[ambientState, { mini: sidebarMini }]">
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
              <span
                v-if="item.view === 'review' && session.pendingReviewCount > 0"
                class="nav-badge"
                :title="`${session.pendingReviewCount} 条待复核`"
              >
                {{ session.pendingReviewCount > 9 ? '9+' : session.pendingReviewCount }}
              </span>
            </button>
          </li>
        </ul>
      </template>

      <div class="sidebar-foot">
        <!-- 常驻隐私声明：本地优先是本系统的核心承诺，需要在任何页面都能看到，
             不能只在首页侧栏或大屏出现。矮视口下由紧凑档缩排，不占额外行数。 -->
        <p class="privacy-note">
          <AppIcon name="lock" :size="15" />
          <span>{{ session.portal === 'admin' ? '健康数据默认只保存在本地。' : '健康信息只保存在家里 · 详见使用帮助' }}</span>
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
            v-if="session.portal === 'admin' && session.currentView !== 'members'"
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
              :title="session.portal === 'admin' ? '工具与主题' : '切换界面主题'"
              :aria-expanded="themeMenuOpen"
              @click="themeMenuOpen = !themeMenuOpen"
            >
              <AppIcon name="palette" :size="19" />
            </button>
            <div v-if="themeMenuOpen" class="theme-backdrop" @click="themeMenuOpen = false" />
            <div v-if="themeMenuOpen" class="theme-menu" role="menu">
              <template v-if="session.portal === 'admin'">
                <p class="theme-menu-label">管理工具</p>
                <button
                  type="button"
                  class="theme-option"
                  role="menuitem"
                  @click="paletteRef?.show(); themeMenuOpen = false"
                >
                  <span class="theme-name">
                    <strong>快速跳转</strong>
                    <span>Ctrl + K</span>
                  </span>
                </button>
                <p class="theme-tool-status">
                  <i :class="session.capabilities ? 'on' : 'off'" />
                  {{ session.capabilities ? `本地在线 · ${session.capabilities.phase}` : '本地状态未知' }}
                </p>
              </template>
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
          <span
            class="identity-chip"
            :class="{ admin: session.portal === 'admin' }"
            :title="session.portal === 'admin'
              ? `${currentHouseholdLabel} · 家庭管理员`
              : `${currentHouseholdLabel} · 当前成员`"
          >
            <AppIcon name="members" :size="16" />
            <span class="identity-person">
              <strong>{{ currentMemberLabel }}</strong>
              <small v-if="session.portal !== 'admin'">当前家庭成员</small>
            </span>
            <span class="role-tag" :class="{ caregiver: !session.isOwnerView }">
              {{ session.isOwnerView ? '家庭管理员后台' : session.portal === 'member' ? '家庭成员' : '照护者后台' }}
            </span>
            <button
              type="button"
              class="icon-button"
              title="修改账号密码"
              aria-label="修改账号密码"
              @click="accountSecurityOpen = true"
            >
              <AppIcon name="key" :size="17" />
            </button>
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

      <footer v-if="session.currentView !== 'digital-twin'" class="app-footer">
        {{ session.portal === 'admin' ? '家庭管理后台 · ' : '家庭成员前台 · ' }}健康信息仅供家庭记录参考 · 紧急情况请联系医生或当地急救服务
      </footer>
    </div>
  </div>

  <ConfirmDialog />
  <AccountSecurityDialog :open="accountSecurityOpen" @close="accountSecurityOpen = false" />
  <CommandPalette v-if="session.status === 'ready'" ref="paletteRef" :nav-items="visibleNavItems" />
  <GuardianPet v-if="session.status === 'ready'" />

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
