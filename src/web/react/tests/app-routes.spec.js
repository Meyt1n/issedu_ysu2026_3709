import { expect, test } from '@playwright/test'

test('登录与注册入口保持可用', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: '欢迎回来，家健镜' })).toBeVisible()
  await page.getByRole('button', { name: '开始创建' }).click()
  await expect(page.getByRole('heading', { name: '创建您的家庭账户' })).toBeVisible()
  await page.getByRole('button', { name: '返回登录' }).click()
  await expect(page.getByRole('heading', { name: '欢迎回来，家健镜' })).toBeVisible()
})

test('十个核心页面均可通过 hash 路由访问', async ({ page }) => {
  const routes = [
    ['控制面板', '家庭健康概览'],
    ['家庭成员/父亲', '张建国'],
    ['视觉扫描中心', '视觉扫描中心'],
    ['复核中心', '人工复核中心'],
    ['家庭健康图谱', '家庭健康图谱'],
    ['用药安全中心', '用药安全中心'],
    ['健康计划中心', '健康计划中心'],
    ['本地健康助手', '本地健康助手'],
    ['家庭健康大屏', '家庭健康大屏'],
    ['模型实验室', '模型实验室'],
  ]

  for (const [hash, text] of routes) {
    await page.goto(`/#/${hash}`)
    await expect(page.locator('body')).toContainText(text)
  }
})
