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

    if (request.method() === 'POST' && path === '/api/v1/auth/pin-login') {
      const body = request.postDataJSON() as { actor_id?: string; household_id?: string }
      return respond({
        actor_id: body.actor_id,
        household_id: body.household_id,
        session_token: 'p'.repeat(48),
        expires_at: (Date.now() + 1_800_000) / 1000,
      })
    }

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
  return requests
}

test('成员前台保留正式 PIN 登录，并把成功会话送入成员门户', async ({ page }) => {
  const requests = await installPinLoginApi(page)
  await page.goto('/?portal=member')

  await expect(page.getByRole('group', { name: '选择账号登录凭据' })).toBeVisible()
  await expect(page.getByRole('button', { name: '数字密码' })).toBeVisible()
  await page.getByRole('button', { name: '数字密码' }).click()
  const householdField = page.getByPlaceholder('请输入家庭编号（请问家人）')
  await expect(householdField).toBeVisible()
  await householdField.fill(household.id)
  await page.getByPlaceholder('家人帮你设好的登录名').fill(member.actor_id)
  await page.locator('input[pattern="[0-9]{6}"]').fill('135790')
  await page.getByLabel('访问用途代码', { exact: true }).fill('family-care')
  await page.getByRole('button', { name: '登录成员前台' }).click()

  await expect(page.locator('.app-frame')).toBeVisible()
  await expect(page.getByText('家庭成员', { exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: '你好，奶奶' })).toBeVisible()
  await expect(page.locator('aside.sidebar').getByRole('button', { name: '人工复核' })).toHaveCount(0)
  await expect(page.getByText('欢迎回家')).toBeVisible()
  expect(requests.some(request => request.includes('POST /api/v1/auth/pin-login'))).toBe(true)
})
