import { createRouter, createWebHashHistory } from 'vue-router'

import { useSpeech } from '@/composables/useSpeech'

export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', name: 'today', component: () => import('@/views/TodayView.vue'), meta: { title: '今日' } },
    { path: '/scan', name: 'scan', component: () => import('@/views/ScanView.vue'), meta: { title: '拍药盒' } },
    { path: '/family', name: 'family', component: () => import('@/views/FamilyView.vue'), meta: { title: '家人' } },
    {
      path: '/family/:memberId',
      name: 'member-detail',
      component: () => import('@/views/MemberDetailView.vue'),
      meta: { title: '成员档案' },
    },
    { path: '/alerts', name: 'alerts', component: () => import('@/views/AlertsView.vue'), meta: { title: '提醒' } },
    {
      path: '/alerts/:memberId/:ruleId',
      name: 'alert-detail',
      component: () => import('@/views/AlertDetailView.vue'),
      meta: { title: '风险依据' },
    },
    { path: '/help', name: 'help', component: () => import('@/views/HelpView.vue'), meta: { title: '紧急求助' } },
    { path: '/me', name: 'me', component: () => import('@/views/MeView.vue'), meta: { title: '我的' } },
    {
      path: '/me/accessibility',
      name: 'accessibility',
      component: () => import('@/views/AccessibilityView.vue'),
      meta: { title: '无障碍设置' },
    },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
  scrollBehavior() {
    return { top: 0 }
  },
})

router.afterEach(to => {
  const title = typeof to.meta.title === 'string' ? to.meta.title : ''
  document.title = title ? `${title} · 家健镜随身版` : '家健镜随身版'
  // 切换页面时停止上一页尚未播完的语音，避免播报串台。
  useSpeech().stop()
})
