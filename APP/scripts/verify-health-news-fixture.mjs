/**
 * 验证 MOB-165 健康资讯受控夹具的过期与失败边界。
 *
 * 脚本启动临时夹具、检查 stale 响应，再通过 /__control 切到 503，
 * 最后主动停止子进程。只校验合成数据，不连接外部资讯源。
 */

import { spawn } from 'node:child_process'
import { createServer } from 'node:net'
import { once } from 'node:events'
import { resolve } from 'node:path'

const host = '127.0.0.1'
const fixturePath = resolve('scripts/mob171-weak-network-fixture.mjs')

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

async function freePort() {
  const probe = createServer()
  probe.listen(0, host)
  await once(probe, 'listening')
  const port = probe.address().port
  probe.close()
  await once(probe, 'close')
  return port
}

async function waitForFixture(url, child) {
  const deadline = Date.now() + 5000
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${url}/health`)
      if (response.ok) return
    } catch {
      // 子进程尚未监听，继续轮询。
    }
    if (child.exitCode !== null) throw new Error(`fixture exited with code ${child.exitCode}`)
    await new Promise(resolvePromise => setTimeout(resolvePromise, 50))
  }
  throw new Error('fixture did not become ready within 5 seconds')
}

const port = await freePort()
const baseUrl = `http://${host}:${port}`
const child = spawn(process.execPath, [fixturePath, '--host', host, '--port', String(port), '--mode', 'news-stale'], {
  stdio: ['ignore', 'ignore', 'inherit'],
})

try {
  await waitForFixture(baseUrl, child)

  const staleResponse = await fetch(`${baseUrl}/api/v1/health-news`)
  const stale = await staleResponse.json()
  assert(staleResponse.status === 200, `expected stale status 200, received ${staleResponse.status}`)
  assert(stale.cache_status === 'stale', 'stale fixture must return cache_status=stale')
  assert(typeof stale.fetched_at === 'string' && stale.fetched_at.length > 0, 'stale fixture must include fetched_at')
  assert(Array.isArray(stale.items) && stale.items.length === 1, 'stale fixture must include one synthetic item')
  assert(stale.items[0].id === 'mob520-news-stale', 'stale fixture item id changed unexpectedly')

  const controlResponse = await fetch(`${baseUrl}/__control`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ mode: 'news-error' }),
  })
  assert(controlResponse.ok, `failed to switch fixture mode: ${controlResponse.status}`)

  const errorResponse = await fetch(`${baseUrl}/api/v1/health-news`)
  const error = await errorResponse.json()
  assert(errorResponse.status === 503, `expected error status 503, received ${errorResponse.status}`)
  assert(error.error?.code === 'HEALTH_NEWS_UNAVAILABLE', 'error fixture code changed unexpectedly')
  assert(typeof error.error?.request_id === 'string' && error.error.request_id.length > 0, 'error fixture must include request_id')
  assert(errorResponse.headers.get('x-request-id') === error.error.request_id, 'header/body request_id mismatch')

  console.log('MOB-165 health-news stale/error fixture verification passed.')
} finally {
  if (child.exitCode === null) child.kill('SIGTERM')
  await once(child, 'exit').catch(() => {})
}
