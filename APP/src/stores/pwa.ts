/**
 * MOB-151：PWA 安装、更新提示与缓存恢复生命周期。
 *
 * 更新原则：Service Worker 新版本默认等待（sw.js 不再静默 skipWaiting），
 * 只有用户在提示里确认后页面才发送 SKIP_WAITING，提交中的任务不会被
 * 中途换版打断；刷新后版本以“关于”里的构建信息行定位。
 *
 * 恢复原则：只清理 hct-mobile-shell 前缀的外壳缓存；/api、/health 与
 * 任何服务端健康事实从不进入缓存，恢复动作也不触碰它们。
 */
import { ref } from 'vue'

export const SHELL_CACHE_PREFIX = 'hct-mobile-shell'

export interface ServiceWorkerLike {
  state?: string
  postMessage(message: { type: 'SKIP_WAITING' }): void
  addEventListener?(type: string, listener: () => void): void
}

export interface RegistrationLike {
  installing: ServiceWorkerLike | null
  waiting: ServiceWorkerLike | null
  update(): Promise<void>
  addEventListener(type: string, listener: () => void): void
}

export interface ServiceWorkerContainerLike {
  controller: ServiceWorkerLike | null
  register(url: string): Promise<RegistrationLike>
  addEventListener(type: string, listener: () => void): void
}

export interface CacheStorageLike {
  keys(): Promise<string[]>
  delete(name: string): Promise<boolean>
}

export interface InstallPromptEventLike extends Event {
  prompt(): Promise<void>
}

/** 发现已安装并在等待的新版本（提示由全局组件渲染）。 */
export const updateReady = ref(false)
/** 用户已确认，正在等待新版本接管并刷新。 */
export const updateApplying = ref(false)

let activeRegistration: RegistrationLike | null = null
let deferredInstallPrompt: InstallPromptEventLike | null = null

/** 安装入口被用户关闭后不再自动出现（能力说明保留在“我的”页）。 */
export const installDismissed = ref(false)

export function resetPwaLifecycleState(): void {
  updateReady.value = false
  updateApplying.value = false
  deferredInstallPrompt = null
  activeRegistration = null
  installDismissed.value = false
}

/** 单个 worker 进入 installed 且已有控制器（即非首次安装）→ 更新就绪。 */
export function markUpdateReadyWhenInstalled(
  worker: ServiceWorkerLike,
  hasController: boolean,
  onReady: () => void,
): void {
  const check = () => {
    if (worker.state === 'installed' && hasController) onReady()
  }
  check()
  worker.addEventListener?.('statechange', check)
}

/** 监听注册实例：新 worker 装好、或已有等待中的 worker 时提示更新。 */
export function watchRegistrationForUpdates(
  registration: RegistrationLike,
  hasController: boolean,
  onReady: () => void,
): void {
  registration.addEventListener('updatefound', () => {
    const worker = registration.installing
    if (worker) markUpdateReadyWhenInstalled(worker, hasController, onReady)
  })
  if (registration.waiting && hasController) onReady()
}

/**
 * 用户确认后应用更新：通知等待中的 worker 接管，控制器切换时刷新一次。
 * 刷新有一次性护栏，controllerchange 重复触发不会连环 reload。
 */
export function applyPendingUpdate(
  container: ServiceWorkerContainerLike,
  registration: RegistrationLike | null,
  reload: () => void = () => window.location.reload(),
): boolean {
  const waiting = registration?.waiting
  if (!waiting || updateApplying.value) return false
  updateApplying.value = true
  let reloaded = false
  container.addEventListener('controllerchange', () => {
    if (reloaded) return
    reloaded = true
    reload()
  })
  waiting.postMessage({ type: 'SKIP_WAITING' })
  return true
}

/** 只删除外壳前缀缓存，返回被清理的名字；API/健康缓存不受影响。 */
export async function recoverShellCaches(
  cacheStorage: CacheStorageLike,
  prefix: string = SHELL_CACHE_PREFIX,
): Promise<string[]> {
  const names = await cacheStorage.keys()
  const shellNames = names.filter(name => name.startsWith(prefix))
  await Promise.all(shellNames.map(name => cacheStorage.delete(name)))
  return shellNames
}

export function captureInstallPrompt(event: InstallPromptEventLike): void {
  deferredInstallPrompt = event
}

export function canPromptInstall(): boolean {
  return deferredInstallPrompt !== null
}

/** 触发系统安装引导；不可用时返回 unavailable，由页面显示手动引导。 */
export async function triggerInstallPrompt(): Promise<'prompted' | 'unavailable'> {
  if (!deferredInstallPrompt) return 'unavailable'
  await deferredInstallPrompt.prompt()
  deferredInstallPrompt = null
  return 'prompted'
}

export function dismissInstallEntry(): void {
  installDismissed.value = true
}

/** 浏览器不支持 Service Worker 时保持普通 Web 路径，并说明能力限制。 */
export function serviceWorkerSupported(): boolean {
  return typeof navigator !== 'undefined' && 'serviceWorker' in navigator
}

export function pwaSupportSpeechText(): string {
  return serviceWorkerSupported()
    ? '当前浏览器支持离线外壳与安装能力。'
    : '当前浏览器或 WebView 不支持离线外壳，应用将以普通网页方式运行：需要网络才能加载数据，求助页的静态急救号码仍可查看。'
}

/** 生产环境入口：注册 SW、监听更新与系统安装事件（失败静默降级为在线模式）。 */
export function initPwaLifecycle(
  container: ServiceWorkerContainerLike | undefined,
  win: Pick<Window, 'addEventListener'> = window,
): void {
  if (!container) return
  container
    .register('/sw.js')
    .then(registration => {
      activeRegistration = registration
      watchRegistrationForUpdates(registration, container.controller !== null, () => {
        updateReady.value = true
      })
    })
    .catch(() => {
      // 注册失败（如不支持的 WebView）时静默降级为在线模式。
    })
  win.addEventListener('beforeinstallprompt', event => {
    event.preventDefault()
    captureInstallPrompt(event as InstallPromptEventLike)
  })
}

/** 供全局更新提示组件使用；避免组件直接持有注册实例。 */
export function currentRegistration(): RegistrationLike | null {
  return activeRegistration
}

export function currentContainer(): ServiceWorkerContainerLike | undefined {
  return 'serviceWorker' in navigator
    ? (navigator.serviceWorker as unknown as ServiceWorkerContainerLike)
    : undefined
}
