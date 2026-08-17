/* 家健镜随身版离线 Service Worker（本地优先）：
   - 预缓存应用外壳；带 hash 的静态资产 cache-first；
   - 页面导航 network-first、离线回退外壳；
   - /api 与 /health 永不缓存（健康数据不落缓存）。 */

const CACHE_NAME = 'hct-mobile-shell-v1'
const SHELL = ['/', '/manifest.webmanifest', '/icons/icon.svg', '/bg/ambient-light.jpg', '/bg/ambient-dark.jpg']

self.addEventListener('install', event => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then(cache => cache.addAll(SHELL))
      .then(() => self.skipWaiting()),
  )
})

self.addEventListener('activate', event => {
  event.waitUntil(
    caches
      .keys()
      .then(keys => Promise.all(keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key))))
      .then(() => self.clients.claim()),
  )
})

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
        .catch(() => caches.match('/')),
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
