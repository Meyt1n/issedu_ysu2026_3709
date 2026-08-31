import { expect, test, type Page } from '@playwright/test'

const boundHousehold = { id: 'household-face-1', name: '爷爷奶奶家' }

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

async function expectMemberCredentialLogin(page: Page): Promise<void> {
  await expect(page.getByTestId('formal-login-method')).toHaveCount(0)
  await expect(page.getByRole('group', { name: '选择账号登录凭据' })).toBeVisible()
  await expect(page.getByRole('button', { name: '刷脸进入', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '账号密码', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '数字密码' })).toHaveCount(0)
  await expect(page.locator('.face-family-summary')).toHaveCount(0)
  await expect(page.locator('.face-capture')).toHaveCount(0)
}

test('成员欢迎页提供刷脸与账号密码，不再把 PIN 当作登录方式', async ({ page }) => {
  await installWelcomeApi(page, ['api', 'face-recognition-local'])
  await page.goto('/?portal=member')
  await expectMemberCredentialLogin(page)
})

test('历史本机家庭绑定仍可恢复刷脸登录入口', async ({ page }) => {
  await installWelcomeApi(page, ['api', 'face-recognition-local'])
  await page.addInitScript(
    ([key, value]) => {
      window.localStorage.setItem(key!, value!)
      document.cookie = `hct-face-family-household=${encodeURIComponent(value!)}; Path=/; SameSite=Lax`
    },
    ['hct:face-family-household', JSON.stringify(boundHousehold)],
  )
  await page.goto('/?portal=member')
  await expect(page.getByRole('group', { name: '选择账号登录凭据' })).toBeVisible()
  await expect(page.getByRole('button', { name: '刷脸进入', exact: true })).toHaveClass(/active/)
  await expect(page.locator('.face-family-summary')).toBeVisible()
  await expect(page.locator('.face-capture')).toBeVisible()
})
