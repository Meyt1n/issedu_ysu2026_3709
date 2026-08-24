<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { APP_SHELL_VERSION, getPwaSupportSnapshot, isOwnedShellCache } from '@/pwa/lifecycle'
import type { BeforeInstallPromptEvent } from '@/pwa/lifecycle'

const installEvent = ref<BeforeInstallPromptEvent | null>(null)
const updateRegistration = ref<ServiceWorkerRegistration | null>(null)
const updateReady = ref(false)
const recoveryOpen = ref(false)
const dismissed = ref(false)
const serviceWorkerSupported = ref('serviceWorker' in navigator)
const support = computed(() => getPwaSupportSnapshot(serviceWorkerSupported.value, Boolean(installEvent.value)))
const hasNotice = computed(() => !dismissed.value && (updateReady.value || recoveryOpen.value || support.value.capability === 'limited' || Boolean(installEvent.value)))

function onInstallPrompt(event: Event) { event.preventDefault(); installEvent.value = event as BeforeInstallPromptEvent; dismissed.value = false }
function onControllerChange() { window.location.reload() }
function observeRegistration(registration: ServiceWorkerRegistration) {
  updateRegistration.value = registration
  const observeWorker = (worker: ServiceWorker | null) => worker?.addEventListener('statechange', () => {
    if (worker.state === 'installed' && navigator.serviceWorker.controller) { updateReady.value = true; dismissed.value = false }
  })
  observeWorker(registration.installing)
  registration.addEventListener('updatefound', () => observeWorker(registration.installing))
  if (registration.waiting && navigator.serviceWorker.controller) updateReady.value = true
}
async function requestInstall() { const event = installEvent.value; if (!event) return; await event.prompt(); await event.userChoice; installEvent.value = null }
function applyUpdate() { updateRegistration.value?.waiting?.postMessage({ type: 'HCT_ACTIVATE_UPDATE' }) }
async function recoverShell() {
  if ('caches' in window) { const names = await caches.keys(); await Promise.all(names.filter(isOwnedShellCache).map(name => caches.delete(name))) }
  navigator.serviceWorker.controller?.postMessage({ type: 'HCT_CLEAR_SHELL_CACHE' })
  window.location.reload()
}
onMounted(() => { window.addEventListener('beforeinstallprompt', onInstallPrompt); if (!serviceWorkerSupported.value) return; navigator.serviceWorker.addEventListener('controllerchange', onControllerChange); navigator.serviceWorker.getRegistration('/').then(registration => registration && observeRegistration(registration)) })
onBeforeUnmount(() => { window.removeEventListener('beforeinstallprompt', onInstallPrompt); if (serviceWorkerSupported.value) navigator.serviceWorker.removeEventListener('controllerchange', onControllerChange) })
</script>

<template>
  <aside v-if="hasNotice" class="pwa-notice" aria-live="polite" aria-label="应用安装与更新状态">
    <div class="pwa-notice__copy">
      <strong v-if="updateReady">发现应用更新</strong><strong v-else-if="recoveryOpen">应用恢复</strong><strong v-else-if="installEvent">安装应用</strong><strong v-else>普通网页模式</strong>
      <p v-if="updateReady">请在没有正在提交的操作时刷新。刷新后将使用版本 {{ APP_SHELL_VERSION }}。</p>
      <p v-else-if="recoveryOpen">可清理本应用的静态外壳缓存并重新加载。不会清理服务端数据、健康事实或接口响应。</p>
      <p v-else>{{ support.message }}</p>
    </div>
    <div class="pwa-notice__actions">
      <button v-if="installEvent" type="button" class="pwa-notice__primary" @click="requestInstall">安装</button><button v-if="updateReady" type="button" class="pwa-notice__primary" @click="applyUpdate">刷新更新</button><button v-if="recoveryOpen" type="button" class="pwa-notice__primary" @click="recoverShell">清理并重新加载</button><button v-if="!recoveryOpen && serviceWorkerSupported" type="button" class="pwa-notice__secondary" @click="recoveryOpen = true">恢复</button><button type="button" class="pwa-notice__close" aria-label="关闭应用状态提示" @click="dismissed = true">关闭</button>
    </div>
  </aside>
</template>

<style scoped>
.pwa-notice { position: fixed; right: 16px; bottom: calc(96px + env(safe-area-inset-bottom)); left: 16px; z-index: 45; display: grid; gap: 10px; padding: 14px; background: var(--c-surface-solid); border: 1px solid var(--c-line-strong); border-radius: 10px; box-shadow: var(--shadow-float); }
.pwa-notice__copy { display: grid; gap: 3px; }.pwa-notice__copy strong { font-size: 0.95rem; }.pwa-notice__copy p { color: var(--c-ink-soft); font-size: 0.84rem; line-height: 1.5; }.pwa-notice__actions { display: flex; flex-wrap: wrap; gap: 8px; }.pwa-notice button { min-height: 42px; padding: 7px 11px; border: 1px solid var(--c-line-strong); border-radius: 8px; font-weight: 700; cursor: pointer; }.pwa-notice__primary { color: #fff; background: var(--c-brand); border-color: var(--c-brand) !important; }.pwa-notice__secondary, .pwa-notice__close { color: var(--c-brand); background: transparent; }html[data-elder='on'] .pwa-notice button { min-height: 56px; }html[data-contrast='high'] .pwa-notice { border: 2px solid #000; box-shadow: none; }
</style>
