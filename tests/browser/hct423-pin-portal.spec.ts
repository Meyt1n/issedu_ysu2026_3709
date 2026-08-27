import { expect, test, type Page } from '@playwright/test'

const household = {
  id: 'household-pin-1',
  name: 'PIN 登录家庭',
  created_by: 'parent-admin',
  created_at: '2026-08-25T00:00:00Z',
}

const member = {
  id: 'member-grandma-pin',
  household_id: household.id,
  display_name: '奶奶',
  role: 'DEPENDENT',
  actor_id: 'grandma-pin',
  created_at: '2026-08-25T00:00:00Z',
}

async function installPinLoginApi(page: Page): Promise<void> {
  await page.route('**/api/v1/**', async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    const respond = (body: unknown, status = 200) => route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify(body),
    })

    if (request.method() === 'GET' && path === '/api/v1/households') {
      return respond([household])
    }
    if (request.method() === 'GET' && path.endsWith('/members')) {
      return respond([member])
    }
    if (request.method() === 'POST' && path === '/api/v1/auth/pin-login') {
      return respond({
        actor_id: member.actor_id,
        household_id: household.id,
        session_token: 'p'.repeat(48),
        expires_at: Math.floor(Date.now() / 1000) + 3600,
      })
    }
    if (request.method() === 'GET' && path.endsWith('/plan-workbench')) {
      return respond({ member_id: member.id, generated_at: '2026-08-25T08:00:00Z', plans: [] })
    }
    if (request.method() === 'GET' && path.endsWith('/timeline')) {
      return respond([])
    }
    if (request.method() === 'GET' && path.endsWith('/risks')) {
      return respond({ member_id: member.id, alerts: [], total: 0, severe_count: 0, warning_count: 0 })
    }
    if (request.method() === 'GET' && path.endsWith('/vision-tasks')) {
      return respond([])
    }
    if (request.method() === 'GET' && path === '/api/v1/meta/capabilities') {
      return respond({ phase: 'local', available: ['api'], unavailable: ['ollama'] })
    }
    return respond({ detail: `Unexpected pin portal request: ${request.method()} ${path}` }, 500)
  })
}

test('PIN 登录后自动进入成员前台并显示成员姓名', async ({ page }) => {
  await installPinLoginApi(page)
  await page.goto('/')
  await page.getByRole('button', { name: '家庭账号登录' }).click()
  await page.getByRole('button', { name: '数字密码' }).click()
  await page.getByRole('textbox', { name: /你的登录名/ }).fill(member.actor_id)
  const householdSelect = page.locator('select').filter({ has: page.locator(`option[value="${household.id}"]`) })
  await expect(householdSelect).toBeVisible({ timeout: 5000 })
  await householdSelect.selectOption(household.id)
  await expect(page.getByText('将以 奶奶 的身份进入。')).toBeVisible()
  await page.getByLabel('六位数字密码').fill('135790')
  await page.getByRole('button', { name: '用数字密码进入' }).click()

  await expect(page.locator('.app-frame')).toBeVisible()
  await expect(page.getByText('家庭成员', { exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: '你好，奶奶' })).toBeVisible()
  await expect(page.locator('aside.sidebar').getByRole('button', { name: '人工复核' })).toHaveCount(0)
  await expect(page.getByText('欢迎回家')).toBeVisible()
})
