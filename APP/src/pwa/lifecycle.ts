export const SHELL_CACHE_PREFIX = 'hct-mobile-shell-'
export const APP_SHELL_VERSION = '2026.08.24'

export type PwaCapability = 'ready' | 'installable' | 'limited'

export interface PwaSupportSnapshot {
  serviceWorker: boolean
  installPrompt: boolean
  capability: PwaCapability
  message: string
}

export interface BeforeInstallPromptEvent extends Event {
  prompt(): Promise<void>
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed'; platform: string }>
}

export function getPwaSupportSnapshot(serviceWorkerSupported: boolean, installPromptAvailable: boolean): PwaSupportSnapshot {
  if (!serviceWorkerSupported) return { serviceWorker: false, installPrompt: false, capability: 'limited', message: '当前浏览器不支持离线外壳和更新提示，应用将以普通网页方式运行。' }
  if (installPromptAvailable) return { serviceWorker: true, installPrompt: true, capability: 'installable', message: '此设备支持安装为应用，可在需要时选择安装。' }
  return { serviceWorker: true, installPrompt: false, capability: 'ready', message: '可使用浏览器菜单中的“安装应用”或“添加到主屏幕”完成安装。' }
}

export function isOwnedShellCache(cacheName: string): boolean { return cacheName.startsWith(SHELL_CACHE_PREFIX) }

export function isSafeStaticRequest(url: URL, destination: RequestDestination): boolean {
  if (url.pathname.startsWith('/api') || url.pathname.startsWith('/health')) return false
  return ['script', 'style', 'image', 'font', 'manifest'].includes(destination)
}
