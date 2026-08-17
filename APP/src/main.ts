import { createApp } from 'vue'

import App from './App.vue'
import { router } from './router'
import { initAccessibility } from './stores/accessibility'
import './style.css'

// 先应用无障碍设置（字号/对比度/动效），再挂载应用，避免首屏样式跳变。
initAccessibility()

createApp(App).use(router).mount('#app')

// 离线外壳缓存（仅生产构建注册；API 响应绝不缓存，见 public/sw.js）。
if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {
      // 注册失败（如不支持的 WebView）时静默降级为在线模式。
    })
  })
}
