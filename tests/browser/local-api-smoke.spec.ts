import { expect, test, type Page } from '@playwright/test'

/**
 * 真实后端联调冒烟：走「新身份 → 创建家庭 → 手工记录健康事实 → 时间线与当前事实可见」全链路。
 *
 * 只在本地 API（http://127.0.0.1:8000）可达时运行，CI 或未启动后端时自动跳过；
 * 每次运行使用全新身份，不依赖也不污染既有演示数据。
 */

const API_HEALTH = 'http://127.0.0.1:8000/health'

async function localApiAvailable(): Promise<boolean> {
  try {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), 2000)
    const response = await fetch(API_HEALTH, { signal: controller.signal })
    clearTimeout(timer)
    return response.ok
  } catch {
    return false
  }
}

async function enterAsNewOwner(page: Page, actorId: string): Promise<void> {
  await page.goto('/')
  await expect(page.getByRole('button', { name: '进入家庭空间' })).toBeVisible({ timeout: 20_000 })
  await page.getByLabel('开发身份标识').fill(actorId)
  await page.getByRole('button', { name: '进入家庭空间' }).click()
}

test('真实后端：创建家庭并记录一条健康事实的完整闭环', async ({ page }) => {
  test.skip(!(await localApiAvailable()), '本地 API 不可达，跳过真实后端冒烟')

  const actorId = `smoke-${Date.now()}`
  await enterAsNewOwner(page, actorId)

  // 新身份没有家庭：进入创建家庭流程
  await expect(page.getByRole('heading', { name: '创建你的家庭' })).toBeVisible()
  await page.getByLabel('家庭名称').fill('冒烟测试家庭')
  await page.getByLabel('成员一（本人）').fill('冒烟爷爷')
  await page.getByRole('button', { name: '创建家庭并进入' }).click()

  // 客户端有 15s 超时兜底：偶发代理抖动会显示可恢复的错误，重试一次（写请求带幂等键，安全）
  const enteredMarker = page.locator('aside.sidebar button.nav-item', { hasText: '授权管理' })
  const createError = page.locator('.welcome-form-card .notice.error')
  await expect(enteredMarker.or(createError)).toBeVisible({ timeout: 25_000 })
  if (!(await enteredMarker.isVisible())) {
    await page.getByRole('button', { name: '创建家庭并进入' }).click()
    await expect(enteredMarker).toBeVisible({ timeout: 25_000 })
  }

  await expect(page.locator('.app-frame')).toBeVisible()

  // 顶栏家庭上下文指向新家庭
  await expect(page.locator('.topbar .context-select select option:checked')).toHaveText(/冒烟测试家庭/)

  // 成员档案：手工记录一条「新增药品」事实
  await page.locator('aside.sidebar button.nav-item', { hasText: '成员档案' }).click()
  await expect(page.getByRole('heading', { name: '补一条健康事实' })).toBeVisible()
  await page.getByLabel('药品名称').fill('阿莫西林胶囊')
  await page.getByRole('button', { name: '确认并记录' }).click()
  await expect(page.getByText('已记录「新增药品」。')).toBeVisible()

  // 事件写入后：时间线与当前事实投影都能看到
  await expect(page.getByText(/1 条已确认记录/)).toBeVisible()
  await expect(page.locator('.fact-group', { hasText: '在用药品' })).toContainText('阿莫西林胶囊')
})
