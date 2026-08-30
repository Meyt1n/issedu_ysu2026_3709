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

async function expectFormalOnlyLogin(page: Page): Promise<void> {
  await expect(page.getByTestId('formal-login-method')).toContainText('正式账号密码登录')
  await expect(page.getByLabel('正式账号', { exact: true })).toBeVisible()
  await expect(page.getByLabel('密码', { exact: true })).toBeVisible()
  await expect(page.locator('.face-family-summary')).toHaveCount(0)
  await expect(page.locator('.face-capture')).toHaveCount(0)
  await expect(page.getByRole('button', { name: /刷脸|人脸|数字密码|PIN/ })).toHaveCount(0)
}

test('HCT-498 即使本地人脸模型就绪，欢迎页也只保留正式账号密码登录', async ({ page }) => {
  await installWelcomeApi(page, ['api', 'face-recognition-local'])
  await page.goto('/?portal=member')
  await expectFormalOnlyLogin(page)
})

test('历史本机家庭绑定不会重新暴露人脸登录入口', async ({ page }) => {
  await installWelcomeApi(page, ['api', 'face-recognition-local'])
  await page.addInitScript(
    ([key, value]) => {
      window.localStorage.setItem(key!, value!)
      document.cookie = `hct-face-family-household=${encodeURIComponent(value!)}; Path=/; SameSite=Lax`
    },
    ['hct:face-family-household', JSON.stringify(boundHousehold)],
  )
  await page.goto('/?portal=member')
  await expectFormalOnlyLogin(page)
})
