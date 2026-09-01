import { expect, test, type Page } from '@playwright/test'

const boundHousehold = {
  id: 'household-face-1',
  name: '爷爷奶奶家',
  members: [{ id: 'member-grandma', display_name: '奶奶', actor_id: 'grandma-account' }],
}

async function installWelcomeApi(page: Page, capabilities: string[]): Promise<void> {
  await page.route('**/api/v1/**', async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (request.method() === 'GET' && path === '/api/v1/meta/capabilities') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ phase: 'local', available: capabilities, unavailable: [] }),
      })
    }
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([]),
    })
  })
}

async function expectUnboundMemberGate(page: Page): Promise<void> {
  await expect(page.getByTestId('formal-login-method')).toHaveCount(0)
  await expect(page.getByTestId('member-unbound-gate')).toBeVisible()
  await expect(page.getByRole('heading', { name: '请先到管理后台' })).toBeVisible()
  await expect(page.getByText('成员前台只在管理后台保持登录时开放')).toBeVisible()
  const cta = page.getByRole('link', { name: '去管理后台登录' })
  await expect(cta).toBeVisible()
  await expect(cta).toHaveAttribute('href', 'http://127.0.0.1:5174/?portal=admin')
  await expect(page.getByRole('link', { name: '管理员登录' })).toHaveCount(0)
  await expect(page.getByRole('group', { name: '选择账号登录凭据' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '刷脸进入', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'PIN登录', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '账号密码', exact: true })).toHaveCount(0)
  await expect(page.locator('.face-family-summary')).toHaveCount(0)
  await expect(page.locator('.face-capture')).toHaveCount(0)
}

test('成员欢迎页未绑定家庭时提示去管理后台登录，不进入刷脸或 PIN', async ({ page }) => {
  await installWelcomeApi(page, ['api', 'face-recognition-local'])
  await page.goto('/?portal=member')
  await expectUnboundMemberGate(page)
})

test('历史本机家庭绑定在后台未登录时不开放刷脸', async ({ page }) => {
  await installWelcomeApi(page, ['api', 'face-recognition-local'])
  await page.addInitScript(
    ([key, value]) => {
      window.localStorage.setItem(key!, value!)
      document.cookie = `hct-face-family-household=${encodeURIComponent(value!)}; Path=/; SameSite=Lax`
    },
    ['hct:face-family-household', JSON.stringify(boundHousehold)],
  )
  await page.goto('/?portal=member')
  await expectUnboundMemberGate(page)
})

test('后台保持登录后本机家庭绑定才开放刷脸入口', async ({ page }) => {
  await page.route('**/api/v1/**', async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (request.method() === 'GET' && path === '/api/v1/meta/capabilities') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          phase: 'local',
          available: ['api', 'face-recognition-local'],
          unavailable: [],
          instance_id: 'boot-2',
        }),
      })
    }
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([]),
    })
  })
  await page.addInitScript(
    ([key, value]) => {
      window.localStorage.setItem(key!, value!)
      document.cookie = `hct-face-family-household=${encodeURIComponent(value!)}; Path=/; SameSite=Lax`
      document.cookie = `hct-admin-ready=${encodeURIComponent(JSON.stringify({
        instanceId: 'boot-2',
        householdId: 'household-face-1',
      }))}; Path=/; SameSite=Lax`
    },
    ['hct:face-family-household', JSON.stringify(boundHousehold)],
  )
  await page.goto('/?portal=member')
  await expect(page.getByRole('group', { name: '选择账号登录凭据' })).toBeVisible()
  await expect(page.getByRole('group', { name: '选择账号登录凭据' }).getByRole('button', { name: '刷脸进入' })).toHaveClass(/active/)
  await expect(page.getByRole('button', { name: 'PIN登录', exact: true })).toBeVisible()
  await expect(page.getByTestId('member-unbound-gate')).toHaveCount(0)
  await expect(page.locator('.face-family-summary')).toBeVisible()
  await expect(page.locator('.face-capture')).toBeVisible()
})

test('成员欢迎页本机已绑定但本次 API 进程后台未就绪时仍提示去管理后台', async ({ page }) => {
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (route.request().method() === 'GET' && path === '/api/v1/meta/capabilities') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          phase: 'local',
          available: ['api', 'face-recognition-local'],
          unavailable: [],
          instance_id: 'boot-2',
        }),
      })
    }
    return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
  })
  await page.addInitScript(
    ([key, value]) => {
      window.localStorage.setItem(key!, value!)
      document.cookie = `hct-face-family-household=${encodeURIComponent(value!)}; Path=/; SameSite=Lax`
    },
    ['hct:face-family-household', JSON.stringify(boundHousehold)],
  )
  await page.goto('/?portal=member')
  await expectUnboundMemberGate(page)
})
