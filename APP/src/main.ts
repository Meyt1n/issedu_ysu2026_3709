import { createApp } from 'vue'

import App from './App.vue'
import { router } from './router'
import { initAccessibility } from './stores/accessibility'
import { initPwaLifecycle } from './stores/pwa'
import './style.css'

// 先应用无障碍设置（字号/对比度/动效），再挂载应用，避免首屏样式跳变。
initAccessibility()

createApp(App).use(router).mount('#app')

// 离线外壳缓存（仅生产构建注册；API 响应绝不缓存，见 public/sw.js）。
// MOB-151：新版本默认等待，注册后由全局提示组件在用户确认时接管。
if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    initPwaLifecycle(navigator.serviceWorker as unknown as Parameters<typeof initPwaLifecycle>[0])
  })
}
