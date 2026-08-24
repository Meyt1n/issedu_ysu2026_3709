/* 家健镜随身版离线 Service Worker（本地优先）：
   - 预缓存应用外壳；带 hash 的静态资产 cache-first；
   - 页面导航 network-first、离线回退外壳；
   - /api 与 /health 永不缓存（健康数据不落缓存）；
   - MOB-151：新版本默认等待（不静默切换），仅当页面在用户确认后
     发送 SKIP_WAITING 消息才接管，避免写操作中途换版本。 */

const CACHE_NAME = 'hct-mobile-shell-v3'
const SHELL = [
  '/',
  '/manifest.webmanifest',
  '/icons/icon.svg',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
  '/icons/icon-maskable-192.png',
  '/icons/icon-maskable-512.png',
  '/bg/ambient-light.jpg',
  '/bg/ambient-dark.jpg',
]

self.addEventListener('install', event => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then(cache => cache.addAll(SHELL)),
  )
})

self.addEventListener('message', event => {
  if (event.data && event.data.type === 'SKIP_WAITING') self.skipWaiting()
})

self.addEventListener('activate', event => {
  event.waitUntil(
    caches
      .keys()
      .then(keys => Promise.all(keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key))))
      .then(() => self.clients.claim()),
  )
})

function offlineShellResponse() {
  return new Response(
    '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>离线状态</title><body><main><h1>当前无法连接网络</h1><p>请恢复网络后重试。紧急情况请使用身边可用电话拨打 120 或联系家人。</p><p>为保护隐私，应用不会显示或缓存旧的健康页面数据。</p></main></body></html>',
    { headers: { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' } },
  )
}
self.addEventListener('fetch', event => {
  const request = event.request
  if (request.method !== 'GET') return

  const url = new URL(request.url)
  if (url.origin !== self.location.origin) return
  // 健康数据与接口响应绝不缓存。
  if (url.pathname.startsWith('/api') || url.pathname.startsWith('/health')) return

  // 页面导航：网络优先，离线回退缓存的外壳。
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then(response => {
          const copy = response.clone()
          caches.open(CACHE_NAME).then(cache => cache.put('/', copy))
          return response
        })
        .catch(() => caches.match('/').then(cached => cached ?? offlineShellResponse())),
    )
    return
  }

  // 静态资产：缓存优先，未命中回源并写入缓存。
  event.respondWith(
    caches.match(request).then(cached => {
      if (cached) return cached
      return fetch(request).then(response => {
        if (response.ok) {
          const copy = response.clone()
          caches.open(CACHE_NAME).then(cache => cache.put(request, copy))
        }
        return response
      })
    }),
  )
})
