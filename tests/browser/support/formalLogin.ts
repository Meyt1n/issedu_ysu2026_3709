import type { Page } from '@playwright/test'

export const FORMAL_TEST_PASSWORD = 'password-123'

/**
 * Install the minimum formal-session endpoints used by UI-only browser specs.
 * Register this after a broad API v1 wildcard route so the auth-specific handler
 * wins without reintroducing the removed X-Actor-Id browser path.
 */
export async function mockFormalSessionApi(page: Page): Promise<void> {
  const sessions = new Map<string, string>()

  await page.route('**/api/v1/auth/**', async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    const respond = (body: unknown, status = 200) => route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify(body),
    })

    if (request.method() === 'POST' && path === '/api/v1/auth/login') {
      const body = request.postDataJSON() as { actor_id?: string }
      const actorId = body.actor_id?.trim() ?? ''
      const token = `formal-${actorId}-${'s'.repeat(48)}`
      sessions.set(token, actorId)
      return respond({
        actor_id: actorId,
        session_token: token,
        expires_at: Math.floor(Date.now() / 1000) + 3600,
      })
    }

    if (request.method() === 'POST' && path === '/api/v1/auth/session') {
      const token = request.headers().authorization?.replace(/^Bearer\s+/i, '') ?? ''
      const actorId = sessions.get(token)
      return actorId
        ? respond({ actor_id: actorId, expires_at: Math.floor(Date.now() / 1000) + 3600 })
        : respond({ detail: 'SESSION_INVALID' }, 401)
    }

    if (request.method() === 'POST' && path === '/api/v1/auth/logout') {
      return respond({ status: 'logged_out' })
    }

    return respond({ detail: 'NOT_FOUND' }, 404)
  })
}

export async function submitFormalLogin(
  page: Page,
  actorId: string,
  purpose = 'family-care',
): Promise<void> {
  await page.getByLabel('正式账号', { exact: true }).fill(actorId)
  await page.getByLabel('密码', { exact: true }).fill(FORMAL_TEST_PASSWORD)
  await page.getByLabel('访问用途代码', { exact: true }).fill(purpose)
  await page.getByRole('button', { name: /^登录(?:成员前台|管理后台|家庭空间)$/ }).click()
}
