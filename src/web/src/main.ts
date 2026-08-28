import { createApp } from 'vue'

import App from './App.vue'
import './style.css'
import { restoreSessionFromCookie } from './store'
import { initTheme } from './ui/themes'

async function bootstrap(): Promise<void> {
  initTheme()
  await restoreSessionFromCookie()
  createApp(App).mount('#app')
}

void bootstrap()
