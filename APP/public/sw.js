const CACHE_NAME = 'hct-mobile-shell-v2'
const CACHE_PREFIX = 'hct-mobile-shell-'
const SHELL_VERSION = '2026.08.24'
const SHELL = ['/', '/manifest.webmanifest', '/icons/icon.svg', '/icons/icon-192.png', '/icons/icon-512.png', '/bg/ambient-light.jpg', '/bg/ambient-dark.jpg']
const STATIC_DESTINATIONS = ['script', 'style', 'image', 'font', 'manifest']

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(SHELL)))
})

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(key => key.startsWith(CACHE_PREFIX) && key !== CACHE_NAME).map(key => caches.delete(key))))
      .then(() => self.clients.matchAll({ type: 'window' }))
      .then(clients => clients.forEach(client => client.postMessage({ type: 'HCT_SHELL_VERSION', version: SHELL_VERSION }))),
  )
})

self.addEventListener('fetch', event => {
  const request = event.request
  if (request.method !== 'GET') return
  const url = new URL(request.url)
  if (url.origin !== self.location.origin) return
  if (url.pathname.startsWith('/api') || url.pathname.startsWith('/health')) return

  if (request.mode === 'navigate') {
    event.respondWith(fetch(request).catch(() => caches.match('/')))
    return
  }

  if (!STATIC_DESTINATIONS.includes(request.destination)) return
  event.respondWith(
    caches.match(request).then(cached => {
      if (cached) return cached
      return fetch(request).then(response => {
        if (response.ok) caches.open(CACHE_NAME).then(cache => cache.put(request, response.clone()))
        return response
      })
    }),
  )
})

self.addEventListener('message', event => {
  if (event.data?.type === 'HCT_ACTIVATE_UPDATE') {
    self.skipWaiting()
    return
  }
  if (event.data?.type === 'HCT_CLEAR_SHELL_CACHE') {
    event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key.startsWith(CACHE_PREFIX)).map(key => caches.delete(key)))))
  }
})