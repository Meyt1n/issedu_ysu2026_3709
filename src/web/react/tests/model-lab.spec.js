import { expect, test } from '@playwright/test'

const stateKey = 'hct407-rollback-demo-v1'

test.beforeEach(async ({ page }) => {
  await page.goto('/#/模型实验室')
  await page.evaluate(key => window.localStorage.removeItem(key), stateKey)
  await page.reload()
})

test('实验登记不能被家庭运行时调用', async ({ page }) => {
  await expect(page.getByRole('heading', { name: '模型实验室', level: 1 })).toBeVisible()
  await expect(page.getByText('当前没有 APPROVED 模型')).toBeVisible()
  await expect(page.getByText('vision_model_version=unavailable')).toBeVisible()
  await expect(page.getByRole('button', { name: '未批准，禁止调用' })).toHaveCount(2)
  await expect(page.getByRole('button', { name: '未批准，禁止调用' }).first()).toBeDisabled()
})

test('同一候选输入集展示退化、失败类别和发布阻断', async ({ page }) => {
  await page.getByRole('tab', { name: '版本指标' }).click()
  await expect(page.getByText('同一候选 test 输入集 · 不是获批固定集')).toBeVisible()
  await expect(page.getByText('变慢 25.727ms')).toBeVisible()
  await expect(page.getByText('2/2 误检')).toHaveCount(2)
  await expect(page.getByText('PARTIAL_UNTRACKED_ORIGINAL_CODE')).toBeVisible()
})

test('回滚演练要求权限和二次确认，并在刷新后恢复', async ({ page }) => {
  await page.getByRole('tab', { name: '回滚状态' }).click()
  await page.getByRole('button', { name: '开始演练' }).click()
  const dialog = page.getByRole('dialog', { name: '二次确认回滚演练' })
  const execute = dialog.getByRole('button', { name: '执行幂等演练' })
  await expect(execute).toBeDisabled()
  await dialog.getByRole('checkbox').check()
  await dialog.getByPlaceholder('ROLLBACK').fill('ROLLBACK')
  await execute.click()
  await expect(page.getByText('未调用后端、未切换真实运行时', { exact: false })).toBeVisible()

  await page.reload()
  await page.getByRole('tab', { name: '回滚状态' }).click()
  await expect(page.getByText('DEMO-RB-vision-unavailable')).toBeVisible()
  await expect(page.getByText('DEMO_ONLY')).toBeVisible()
})

test('空、错误、离线和未授权状态不显示登记详情', async ({ page }) => {
  const stateSelect = page.getByLabel('状态演练')
  for (const [value, text] of [['empty', '暂无已登记实验'], ['error', '登记校验失败'], ['offline', '离线只读'], ['unauthorized', '无模型管理员权限']]) {
    await stateSelect.selectOption(value)
    await expect(page.getByText(text, { exact: true })).toBeVisible()
    await expect(page.locator('.registry-table')).toHaveCount(0)
    await page.getByRole('button', { name: '恢复正常演示' }).click()
  }
})
