/**
 * MOB-171 受控弱网验收夹具。
 *
 * 只提供虚构的家庭、成员、计划和风险响应，默认绑定 127.0.0.1；
 * 真机联调时可显式传 --host 0.0.0.0，并且只应在可信局域网临时运行。
 * 通过 POST /__control 切换场景，GET /__stats 查看请求计数；夹具不写磁盘。
 *
 * 用法：node scripts/mob171-weak-network-fixture.mjs --host 0.0.0.0 --port 8000
 * 场景：ok | loading | timeout | slow | empty | partial | news-stale | news-error
 */

import http from 'node:http'

const args = process.argv.slice(2)
function arg(flag, fallback) {
  const index = args.indexOf(flag)
  return index >= 0 && args[index + 1] ? args[index + 1] : fallback
}

const host = arg('--host', '127.0.0.1')
const port = Number(arg('--port', '8000'))
const allowedModes = new Set(['ok', 'loading', 'timeout', 'slow', 'empty', 'partial', 'news-stale', 'news-error'])
let mode = allowedModes.has(arg('--mode', 'ok')) ? arg('--mode', 'ok') : 'ok'
const requestCounts = new Map()
const requestIds = new Map()
const requestLog = []

const householdId = 'mob171-household-synthetic'
const memberId = 'mob171-member-synthetic'
const now = '2026-09-01T02:00:00.000Z'

const household = {
  id: householdId,
  name: 'MOB-171 合成家庭',
  created_by: 'mob171-synthetic-actor',
  created_at: now,
  time_zone: 'Asia/Shanghai',
}

const member = {
  id: memberId,
  household_id: householdId,
  display_name: '成员A（合成）',
  role: 'DEPENDENT',
  actor_id: null,
  created_at: now,
}

const timeline = [
  {
    id: 'mob171-plan-synthetic',
    household_id: householdId,
    member_id: memberId,
    sequence_no: 1,
    event_type: 'plan_created',
    source: 'MOB171_SYNTHETIC',
    confirmation_status: 'CONFIRMED',
    payload: { drug: '演示计划（合成）', schedule: '仅用于弱网验证', due_time: '08:00', level: 'GENERAL' },
    evidence: {},
    created_by: 'mob171-synthetic-actor',
    occurred_at: now,
    recorded_at: now,
    created_at: now,
  },
]

const risks = {
  member_id: memberId,
  alerts: [{
    rule_id: 'mob171-risk-synthetic',
    level: 'INFO',
    message: 'MOB-171 合成风险占位，仅用于弱网列表验收。',
    source_event_ids: ['mob171-plan-synthetic'],
    created_at: now,
    rule_version: 'mob171-synthetic-v1',
  }],
  total: 1,
  severe_count: 0,
  warning_count: 0,
  ruleset_version: 'mob171-synthetic-v1',
  non_severe_budget: 10,
  suppressed_count: 0,
}

const capabilities = {
  phase: 'mob171-synthetic',
  available: [],
  unavailable: ['all-live-data'],
}

function writeJson(response, status, payload, requestId) {
  response.writeHead(status, {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'Accept, Content-Type, X-Access-Purpose, X-Actor-Id',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Cache-Control': 'no-store',
    'Content-Type': 'application/json; charset=utf-8',
    'X-Request-ID': requestId,
  })
  response.end(JSON.stringify(payload))
}

function bump(path, context = null) {
  const count = (requestCounts.get(path) ?? 0) + 1
  requestCounts.set(path, count)
  const id = `mob171-${path.replaceAll('/', '-') || 'root'}-${count}`
  requestIds.set(path, id)
  requestLog.push({ path, count, mode, ...(context ? { context } : {}) })
  return id
}

function body(request) {
  return new Promise(resolve => {
    let text = ''
    request.on('data', chunk => { text += chunk })
    request.on('end', () => {
      try { resolve(text ? JSON.parse(text) : {}) } catch { resolve({}) }
    })
  })
}

function shouldDelay(path) {
  if (!['/api/v1/households', `/api/v1/households/${householdId}/members`, `/api/v1/households/${householdId}/members/${memberId}/timeline`, `/api/v1/households/${householdId}/members/${memberId}/risks`].includes(path)) return false
  return mode === 'loading' || mode === 'timeout'
}

function delayForMode() {
  return mode === 'timeout' ? 20_000 : 8_000
}

const server = http.createServer(async (request, response) => {
  const url = new URL(request.url ?? '/', `http://${host}`)
  const path = url.pathname

  if (request.method === 'OPTIONS') {
    writeJson(response, 204, {}, 'mob171-options')
    return
  }

  if (request.method === 'POST' && path === '/__control') {
    const input = await body(request)
    if (typeof input.mode !== 'string' || !allowedModes.has(input.mode)) {
      writeJson(response, 400, { detail: 'mode must be one of ok/loading/timeout/slow/empty/partial/news-stale/news-error' }, 'mob171-control-error')
      return
    }
    mode = input.mode
    requestCounts.clear()
    requestIds.clear()
    requestLog.length = 0
    writeJson(response, 200, { mode, synthetic: true }, 'mob171-control')
    return
  }

  if (request.method === 'GET' && path === '/__stats') {
    writeJson(response, 200, { mode, counts: Object.fromEntries(requestCounts), request_ids: Object.fromEntries(requestIds), request_log: requestLog, synthetic: true }, 'mob171-stats')
    return
  }

  if (request.method !== 'GET') {
    writeJson(response, 404, { detail: 'not found' }, 'mob171-not-found')
    return
  }

  const requestId = bump(path, url.searchParams.get('context'))
  if (shouldDelay(path)) {
    setTimeout(() => respond(path, response, requestId), delayForMode())
    return
  }
  respond(path, response, requestId, url.searchParams.get('context'))
})

function respond(path, response, requestId, context = null) {
  if (mode === 'slow' && (path.endsWith('/timeline') || path.endsWith('/risks'))) {
    writeJson(response, 504, { error: { code: 'GATEWAY_TIMEOUT', message: 'synthetic service slow', request_id: requestId } }, requestId)
    return
  }

  if (mode === 'empty' && (path === '/api/v1/households' || path.endsWith('/members'))) {
    writeJson(response, 200, [], requestId)
    return
  }

  // Today 页先取成员待办、再取快照，最后单独取周趋势；只让趋势失败，
  // 以验证 Promise.allSettled 保留已成功的任务/风险并展示“重试补齐”。
  if (mode === 'partial' && path.endsWith('/timeline') && context === 'weekly-trend') {
    writeJson(response, 504, { error: { code: 'GATEWAY_TIMEOUT', message: 'synthetic trend service slow', request_id: requestId } }, requestId)
    return
  }

  if (path === '/health') {
    writeJson(response, 200, { status: 'ok', service: 'mob171-synthetic-fixture', version: 'mob171-v1' }, requestId)
    return
  }
  if (path === '/api/v1/meta/capabilities') {
    writeJson(response, 200, capabilities, requestId)
    return
  }
  if (path === '/api/v1/households') {
    writeJson(response, 200, [household], requestId)
    return
  }
  if (path === `/api/v1/households/${householdId}/members`) {
    writeJson(response, 200, [member], requestId)
    return
  }
  if (path === `/api/v1/households/${householdId}/authorizations`) {
    // 合成夹具以 Owner 视角运行；返回空授权列表，避免把验收夹具的
    // 404 误判为真实撤权并触发客户端授权边界清空成员上下文。
    writeJson(response, 200, [], requestId)
    return
  }
  if (path === `/api/v1/households/${householdId}/members/${memberId}/timeline`) {
    writeJson(response, 200, timeline, requestId)
    return
  }
  if (path === `/api/v1/households/${householdId}/members/${memberId}/risks`) {
    writeJson(response, 200, risks, requestId)
    return
  }
  if (path === '/api/v1/health-news') {
    if (mode === 'news-error') {
      writeJson(response, 503, {
        error: {
          code: 'HEALTH_NEWS_UNAVAILABLE',
          message: 'MOB-520 synthetic health news failure',
          request_id: requestId,
        },
      }, requestId)
      return
    }
    if (mode === 'news-stale') {
      writeJson(response, 200, {
        status: 'stale',
        cache_status: 'stale',
        season: 'synthetic',
        generated_at: now,
        fetched_at: '2026-08-01T02:00:00.000Z',
        disclaimer: 'MOB-520 synthetic stale-cache fixture（仅用于移动端验收）',
        degraded_reason: '资讯源暂不可用，当前展示家庭服务器保留的过期缓存。',
        items: [{
          id: 'mob520-news-stale',
          kind: 'remote',
          title: 'MOB-520 合成过期缓存资讯',
          summary: '该条目专用于验证过期标识、缓存时间和刷新入口。',
          tag: '缓存验收',
          chat_prompt: '请解释 MOB-520 合成过期缓存资讯。',
          source: 'remote_whitelist',
          source_name: 'MOB-520 synthetic allowlist',
          source_url: null,
          published_at: '2026-08-01T01:00:00.000Z',
          fetched_at: '2026-08-01T02:00:00.000Z',
        }],
      }, requestId)
      return
    }
    writeJson(response, 200, { status: 'local_only', cache_status: 'fresh', season: 'synthetic', generated_at: now, fetched_at: now, disclaimer: 'MOB-171 synthetic fixture', items: [] }, requestId)
    return
  }
  writeJson(response, 404, { detail: 'not found' }, requestId)
}

server.listen(port, host, () => {
  console.log(JSON.stringify({ status: 'listening', host, port, mode, synthetic: true }))
})

function shutdown() {
  server.close(() => process.exit(0))
}
process.on('SIGINT', shutdown)
process.on('SIGTERM', shutdown)
