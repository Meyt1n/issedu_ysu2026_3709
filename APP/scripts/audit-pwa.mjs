import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'

const root = process.cwd()
const publicDir = path.join(root, 'public')
const distDir = path.join(root, 'dist')
const swSource = fs.readFileSync(path.join(publicDir, 'sw.js'), 'utf8')
const mainSource = fs.readFileSync(path.join(root, 'src', 'main.ts'), 'utf8')
const manifest = JSON.parse(fs.readFileSync(path.join(publicDir, 'manifest.webmanifest'), 'utf8'))

function assert(condition, message) { if (!condition) throw new Error(`PWA audit failed: ${message}`) }
function existsInDist(urlPath) { return fs.existsSync(path.join(distDir, urlPath === '/' ? 'index.html' : urlPath.replace(/^\//, ''))) }

assert(fs.existsSync(distDir), 'run npm run build before auditing')
assert(fs.existsSync(path.join(distDir, 'sw.js')), 'missing built Service Worker')
assert(mainSource.includes("navigator.serviceWorker.register('/sw.js')"), 'production entry does not register /sw.js')
assert(mainSource.includes('import.meta.env.PROD'), 'Service Worker registration is not production-only')
assert(manifest.start_url === '/', 'manifest start_url must be /')
assert(manifest.display === 'standalone', 'manifest display must be standalone')
assert(manifest.orientation === 'portrait', 'manifest orientation must be portrait')
assert(manifest.theme_color && manifest.background_color && manifest.name && manifest.short_name, 'manifest release metadata is incomplete')
assert(Array.isArray(manifest.icons) && manifest.icons.length >= 3, 'manifest needs SVG fallback plus release icons')
for (const icon of manifest.icons) assert(existsInDist(icon.src), `missing manifest icon ${icon.src}`)
assert(manifest.icons.some(icon => icon.type === 'image/png' && icon.sizes === '192x192'), 'missing 192px PNG icon')
assert(manifest.icons.some(icon => icon.type === 'image/png' && icon.sizes === '512x512'), 'missing 512px PNG icon')

const shellMatch = swSource.match(/const SHELL = \[(.*?)\]/s)
assert(shellMatch, 'missing shell pre-cache list')
const shell = [...shellMatch[1].matchAll(/'([^']+)'/g)].map(match => match[1])
for (const resource of shell) assert(existsInDist(resource), `missing shell resource ${resource}`)
assert(swSource.includes("const CACHE_PREFIX = 'hct-mobile-shell-'"), 'missing owned cache prefix')
assert(swSource.includes("if (url.pathname.startsWith('/api') || url.pathname.startsWith('/health')) return"), 'API and health endpoints are not excluded')
assert(swSource.includes("if (request.method !== 'GET') return"), 'non-GET requests are not excluded')
assert(swSource.includes("if (url.origin !== self.location.origin) return"), 'cross-origin requests are not excluded')
assert(swSource.includes("if (!STATIC_DESTINATIONS.includes(request.destination)) return"), 'cache lacks static-resource allowlist')
assert(swSource.includes("event.data?.type === 'HCT_ACTIVATE_UPDATE'"), 'missing explicit update activation message')
assert(swSource.includes('self.skipWaiting()'), 'missing user-approved activation')
assert(!swSource.includes('self.clients.claim()'), 'worker must not silently claim active pages')
const installBlock = swSource.slice(swSource.indexOf("self.addEventListener('install'"), swSource.indexOf("self.addEventListener('activate'"))
assert(!installBlock.includes('skipWaiting'), 'install handler must not silently activate an update')
assert(swSource.includes("event.data?.type === 'HCT_CLEAR_SHELL_CACHE'"), 'missing shell-only recovery message')
console.log(`PWA audit passed: ${shell.length} shell resources, ${manifest.icons.length} manifest icons.`)