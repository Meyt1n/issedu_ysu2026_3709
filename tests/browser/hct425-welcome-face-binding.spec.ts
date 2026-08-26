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

async function openSessionLogin(page: Page): Promise<void> {
  await page.goto('/')
  await page.getByRole('button', { name: '正式账号登录' }).click()
}

test('账号密码与家庭 PIN 模式不显示本机人脸绑定提示', async ({ page }) => {
  await installWelcomeApi(page, ['api'])
  await openSessionLogin(page)

  await page.getByRole('button', { name: '账号密码' }).click()
  await expect(page.getByRole('textbox', { name: /本地账号/ })).toBeVisible()
  await expect(page.locator('.face-family-summary')).toHaveCount(0)
  await expect(page.getByText('本机还没有开启人脸登录')).toHaveCount(0)

  await page.getByRole('button', { name: '家庭 PIN' }).click()
  await expect(page.getByRole('textbox', { name: /你的登录名/ })).toBeVisible()
  await expect(page.locator('.face-family-summary')).toHaveCount(0)
})

test('人脸模式未绑定时显示简短引导并隐藏摄像头采集区', async ({ page }) => {
  await installWelcomeApi(page, ['api', 'face-recognition-local'])
  await openSessionLogin(page)

  await page.getByRole('button', { name: '人脸识别' }).click()
  await expect(page.getByText('本机还没有开启人脸登录')).toBeVisible()
  await expect(page.getByText('先用账号密码进入，再到「人脸凭证」页绑定本机家庭。')).toBeVisible()
  await expect(page.locator('.face-capture')).toHaveCount(0)

  await page.getByRole('button', { name: '改用账号密码登录' }).click()
  await expect(page.getByRole('textbox', { name: /本地账号/ })).toBeVisible()
  await expect(page.locator('.face-family-summary')).toHaveCount(0)
})

test('人脸模式已绑定时显示家庭名、不跨家说明和采集区', async ({ page }) => {
  await installWelcomeApi(page, ['api', 'face-recognition-local'])
  await page.addInitScript(
    ([key, value]) => window.localStorage.setItem(key!, value!),
    ['hct:face-family-household', JSON.stringify(boundHousehold)],
  )
  await openSessionLogin(page)

  await expect(page.locator('.face-family-summary')).toContainText(boundHousehold.name)
  await expect(page.getByText('只在这个家庭里认人，不会跨家搜索。')).toBeVisible()
  await expect(page.getByRole('button', { name: '改用账号密码登录' })).toHaveCount(0)
  await expect(page.locator('.face-capture')).toBeVisible()
})

test('另一个本地端口写入的同主机家庭绑定可用于成员端人脸登录', async ({ page }) => {
  await installWelcomeApi(page, ['api', 'face-recognition-local'])
  await page.addInitScript(
    ([key, value]) => {
      window.localStorage.removeItem(key!)
      document.cookie = `hct-face-family-household=${encodeURIComponent(value!)}; Path=/; SameSite=Lax`
    },
    ['hct:face-family-household', JSON.stringify(boundHousehold)],
  )
  await openSessionLogin(page)

  await expect(page.locator('.face-family-summary')).toContainText(boundHousehold.name)
  await expect(page.getByText('只在这个家庭里认人，不会跨家搜索。')).toBeVisible()
  await expect(page.getByText('本机还没有开启人脸登录')).toHaveCount(0)
  await expect(page.locator('.face-capture')).toBeVisible()
})
