<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

import AppIcon, { type IconName } from '@/components/AppIcon.vue'
import { useA11y } from '@/stores/accessibility'

interface TabItem {
  to: string
  label: string
  icon: IconName
}

const { settings } = useA11y()
const route = useRoute()

const NORMAL_TABS: TabItem[] = [
  { to: '/', label: '今日', icon: 'home' },
  { to: '/scan', label: '拍药盒', icon: 'camera' },
  { to: '/family', label: '家人', icon: 'family' },
  { to: '/alerts', label: '提醒', icon: 'bell' },
  { to: '/me', label: '我的', icon: 'user' },
]

/** 长辈模式：入口减到 4 个，突出求助。 */
const ELDER_TABS: TabItem[] = [
  { to: '/', label: '今日', icon: 'home' },
  { to: '/scan', label: '拍药盒', icon: 'camera' },
  { to: '/help', label: '求助', icon: 'phone' },
  { to: '/me', label: '我的', icon: 'user' },
]

const tabs = computed(() => (settings.elderMode ? ELDER_TABS : NORMAL_TABS))

function isActive(tab: TabItem): boolean {
  if (tab.to === '/') return route.path === '/'
  return route.path === tab.to || route.path.startsWith(`${tab.to}/`)
}
</script>

<template>
  <nav class="tabbar-wrap" aria-label="主导航">
    <div class="tabbar">
      <RouterLink
        v-for="tab in tabs"
        :key="tab.to"
        :to="tab.to"
        class="tabbar-item"
        :data-active="isActive(tab)"
        :aria-current="isActive(tab) ? 'page' : undefined"
      >
        <AppIcon :name="tab.icon" :size="settings.elderMode ? 27 : 22" />
        <span>{{ tab.label }}</span>
      </RouterLink>
    </div>
  </nav>
</template>

<style scoped>
.tabbar-wrap {
  position: fixed;
  bottom: calc(12px + env(safe-area-inset-bottom));
  left: 0;
  right: 0;
  z-index: 20;
  display: flex;
  justify-content: center;
  padding: 0 16px;
  pointer-events: none;
}

.tabbar {
  pointer-events: auto;
  display: grid;
  grid-auto-flow: column;
  grid-auto-columns: 1fr;
  gap: 2px;
  width: min(100%, 520px);
  background: var(--glass-bg);
  -webkit-backdrop-filter: blur(22px) saturate(1.6);
  backdrop-filter: blur(22px) saturate(1.6);
  border: 1px solid var(--glass-border);
  border-radius: var(--r-pill);
  padding: 7px;
  box-shadow: var(--shadow-float), inset 0 1px 0 var(--hilite);
}

.tabbar-item {
  min-height: calc(var(--tap) * 1.06);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  padding: 6px 4px;
  color: var(--c-ink-faint);
  text-decoration: none;
  font-size: 0.72rem;
  font-weight: 800;
  border-radius: var(--r-pill);
  transition: background var(--speed), color var(--speed), transform var(--speed) var(--ease-spring);
}
.tabbar-item:active { transform: scale(0.92); }

.tabbar-item[data-active='true'] {
  color: #fff;
  background: var(--grad-btn);
  box-shadow: 0 8px 18px -8px rgba(0, 0, 0, 0.55), inset 0 1px 0 rgba(255, 255, 255, 0.3);
}
.tabbar-item[data-active='true'] svg {
  animation: tab-pop 0.4s var(--ease-spring);
}
@keyframes tab-pop {
  0% { transform: scale(0.6); }
  60% { transform: scale(1.18); }
  100% { transform: scale(1); }
}

html[data-contrast='high'] .tabbar {
  background: #fff;
  border: 2px solid #000;
  box-shadow: none;
  -webkit-backdrop-filter: none;
  backdrop-filter: none;
}
html[data-contrast='high'] .tabbar-item[data-active='true'] {
  background: var(--c-brand);
  box-shadow: none;
  outline: 2px solid #000;
  outline-offset: -2px;
}
html[data-elder='on'] .tabbar-item { font-size: 0.88rem; }
</style>
