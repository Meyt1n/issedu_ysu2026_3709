import { expect, test, type Page } from '@playwright/test'

import { mockFormalSessionApi, submitFormalLogin } from './support/formalLogin'

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

async function installPinLoginApi(page: Page): Promise<string[]> {
  const requests: string[] = []
  await page.route('**/api/v1/**', async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    requests.push(`${request.method()} ${path}`)
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
  await mockFormalSessionApi(page)
  return requests
}

test('HCT-498 不再暴露 PIN 主登录，成员改用正式账号密码进入', async ({ page }) => {
  const requests = await installPinLoginApi(page)
  await page.goto('/?portal=member')
  await expect(page.getByRole('button', { name: /数字密码|PIN/ })).toHaveCount(0)
  await expect(page.getByLabel('六位数字密码')).toHaveCount(0)
  await submitFormalLogin(page, member.actor_id)

  await expect(page.locator('.app-frame')).toBeVisible()
  await expect(page.getByText('家庭成员', { exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: '你好，奶奶' })).toBeVisible()
  await expect(page.locator('aside.sidebar').getByRole('button', { name: '人工复核' })).toHaveCount(0)
  await expect(page.getByText('欢迎回家')).toBeVisible()
  expect(requests.some(request => request.includes('/auth/pin-login'))).toBe(false)
})
