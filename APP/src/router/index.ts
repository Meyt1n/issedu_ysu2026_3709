import { createRouter, createWebHashHistory } from 'vue-router'
import { nextTick } from 'vue'

import { useSpeech } from '@/composables/useSpeech'
import { useAuth } from '@/stores/auth'
import { useSession } from '@/stores/session'
import { focusRouteMain } from '@/utils/accessibility'

export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', name: 'today', component: () => import('@/views/TodayView.vue'), meta: { title: '今日', requiresLiveAuth: true } },
    { path: '/scan', name: 'scan', component: () => import('@/views/ScanView.vue'), meta: { title: '拍药盒', requiresLiveAuth: true } },
    { path: '/family', name: 'family', component: () => import('@/views/FamilyView.vue'), meta: { title: '家人', requiresLiveAuth: true, adminOnly: true } },
    {
      path: '/family/:memberId',
      name: 'member-detail',
      component: () => import('@/views/MemberDetailView.vue'),
      meta: { title: '成员档案', requiresLiveAuth: true, adminOnly: true },
    },
    { path: '/alerts', name: 'alerts', component: () => import('@/views/AlertsView.vue'), meta: { title: '提醒', requiresLiveAuth: true, adminOnly: true } },
    {
      path: '/alerts/:memberId/:ruleId',
      name: 'alert-detail',
      component: () => import('@/views/AlertDetailView.vue'),
      meta: { title: '风险依据', requiresLiveAuth: true, adminOnly: true },
    },
    // 求助页只用本机联系人，断网或未登录时仍必须可用。
    { path: '/help', name: 'help', component: () => import('@/views/HelpView.vue'), meta: { title: '紧急求助' } },
    {
      path: '/assistant',
      name: 'assistant',
      component: () => import('@/views/AssistantView.vue'),
      meta: { title: '语音助手', requiresLiveAuth: true },
    },
    {
      path: '/knowledge',
      name: 'knowledge-library',
      component: () => import('@/views/KnowledgeLibraryView.vue'),
      meta: { title: '知识条目', requiresLiveAuth: true, adminOnly: true },
    },
    {
      path: '/knowledge/:docId',
      name: 'knowledge-document',
      component: () => import('@/views/KnowledgeDocumentView.vue'),
      meta: { title: '知识条目', requiresLiveAuth: true, adminOnly: true },
    },
    { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue'), meta: { title: '登录' } },
    { path: '/me', name: 'me', component: () => import('@/views/MeView.vue'), meta: { title: '我的' } },
    {
      path: '/me/accessibility',
      name: 'accessibility',
      component: () => import('@/views/AccessibilityView.vue'),
      meta: { title: '无障碍设置' },
    },
    {
      path: '/me/voice-check',
      name: 'voice-check',
      component: () => import('@/views/VoiceCheckView.vue'),
      meta: { title: '语音自检' },
    },
    {
      path: '/me/privacy',
      name: 'privacy',
      component: () => import('@/views/PrivacyView.vue'),
      meta: { title: '本地数据管理' },
    },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
  scrollBehavior() {
    return { top: 0 }
  },
})

/**
 * 联机 + 正式鉴权模式下，未登录或会话失效的页面一律先去登录页。
 * 「我的」「无障碍」「求助」保持可达：用户需要它们改设置、切回演示模式或紧急拨号。
 */
router.beforeEach(to => {
  const { session } = useSession()
  if (to.meta.adminOnly === true && session.mobileRole === 'member') {
    return { name: 'today' }
  }
  if (to.meta.requiresLiveAuth !== true) return true
  if (session.dataMode !== 'live' || session.authMode !== 'real') return true
  const { auth } = useAuth()
  if (auth.status === 'authenticated') return true
  return { name: 'login', query: { redirect: to.fullPath } }
})


router.afterEach(to => {
  const title = typeof to.meta.title === 'string' ? to.meta.title : ''
  document.title = title ? `${title} · 家健镜随身版` : '家健镜随身版'
  // 切换页面时停止上一页尚未播完的语音，避免播报串台。
  useSpeech().stop()
  // SPA 路由不会像原生页面加载一样重置读屏焦点；将焦点移到新页面主区域并播报页面名。
  void nextTick(() => focusRouteMain(title || '家健镜随身版'))
})
