import { expect, test, type Page } from '@playwright/test'

import { submitFormalLogin } from './support/formalLogin'

const household = {
  id: 'session-household',
  name: 'Synthetic session household',
  created_by: 'session-owner',
  created_at: '2026-08-19T00:00:00Z',
}

const member = {
  id: 'session-member',
  household_id: household.id,
  display_name: 'Synthetic session member',
  role: 'SELF',
  actor_id: 'session-owner',
  created_at: '2026-08-19T00:00:00Z',
}

async function installSessionApi(
  page: Page,
  expireDuringScope = false,
  expiresInMs = 1_800_000_000_000,
): Promise<{ requests: string[]; businessHeaders: Array<Record<string, string>> }> {
  const requests: string[] = []
  const businessHeaders: Array<Record<string, string>> = []
  let scopeRequestCount = 0

  await page.route('**/api/v1/**', async route => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    requests.push(`${request.method()} ${path}`)

    const respond = (body: unknown, status = 200) => route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify(body),
    })

    if (request.method() === 'POST' && path === '/api/v1/auth/login') {
      return respond({
        actor_id: 'session-owner',
        session_token: 's'.repeat(48),
        expires_at: (Date.now() + expiresInMs) / 1000,
      })
    }
    if (request.method() === 'POST' && path === '/api/v1/auth/logout') return respond({ status: 'logged_out' })
    if (request.method() === 'GET' && path === '/api/v1/households') {
      businessHeaders.push(request.headers())
      return respond([household])
    }
    if (request.method() === 'GET' && path.endsWith('/members')) {
      scopeRequestCount += 1
      if (expireDuringScope && scopeRequestCount === 1) return respond({ detail: 'AUTH_REQUIRED' }, 401)
      return respond([member])
    }
    if (request.method() === 'GET' && path.endsWith('/authorizations')) return respond([])
    if (request.method() === 'GET' && path === '/api/v1/meta/capabilities') {
      return respond({ phase: 'local', available: ['api'], unavailable: ['ollama'] })
    }
    if (request.method() === 'GET' && path.endsWith('/timeline')) return respond([])
    if (request.method() === 'GET' && path.endsWith('/state')) {
      return respond({
        member_id: member.id,
        household_id: household.id,
        state: { events_count: 0 },
        last_event_id: null,
        last_sequence: 0,
        version: 1,
        state_hash: null,
        updated_at: '2026-08-19T00:00:00Z',
      })
    }
    if (request.method() === 'GET' && path.endsWith('/risks')) {
      return respond({ member_id: member.id, alerts: [], total: 0, severe_count: 0, warning_count: 0 })
    }
    if (request.method() === 'GET' && (path.endsWith('/plans') || path.endsWith('/tasks') || path.endsWith('/review-tasks'))) {
      return respond([])
    }
    if (request.method() === 'GET' && path.startsWith('/api/v1/weather/')) {
      return respond({ status: 'unavailable', cache_status: 'none', action_cards: [] })
    }
    return respond([])
  })

  return { requests, businessHeaders }
}

async function chooseFormalLogin(page: Page): Promise<void> {
  await page.goto('/')
  await submitFormalLogin(page, 'session-owner')
}

test('正式登录使用 Bearer 会话，登出后清空家庭界面', async ({ page }) => {
  const { requests, businessHeaders } = await installSessionApi(page)
  await chooseFormalLogin(page)

  await expect(page.locator('.app-frame')).toBeVisible()
  await expect(page.getByText('session-owner')).toBeVisible()
  await page.getByRole('button', { name: '退出当前身份' }).click()

  await expect(page.locator('.app-frame')).toHaveCount(0)
  await expect(page.getByRole('heading', { name: '登录' })).toBeVisible()
  expect(requests).toContain('POST /api/v1/auth/login')
  expect(requests).toContain('POST /api/v1/auth/logout')
  expect(requests.some(path => path.includes('password-123'))).toBe(false)
  expect(businessHeaders.length).toBeGreaterThan(0)
  expect(businessHeaders.every(headers => headers.authorization?.startsWith('Bearer '))).toBe(true)
  expect(businessHeaders.every(headers => headers['x-actor-id'] === undefined)).toBe(true)
})

test('受保护请求返回 401 时清除会话和成员上下文', async ({ page }) => {
  await installSessionApi(page, true)
  await chooseFormalLogin(page)

  await expect(page.locator('.app-frame')).toHaveCount(0)
  await expect(page.getByRole('alert')).toContainText('会话已过期或已被撤销，请重新登录。')
  await expect(page.getByText('Synthetic session member')).toHaveCount(0)
})

test('正式会话到期后网页自动清除家庭上下文', async ({ page }) => {
  await installSessionApi(page, false, 1200)
  await chooseFormalLogin(page)

  await expect(page.locator('.app-frame')).toBeVisible()
  await expect(page.getByRole('alert')).toContainText('\u4f1a\u8bdd\u5df2\u8fc7\u671f\u6216\u5df2\u88ab\u64a4\u9500')
  await expect(page.locator('.app-frame')).toHaveCount(0)
})
