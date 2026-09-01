import { expect, test, type Page } from '@playwright/test'

import { seedBoundHousehold, submitFormalLogin } from './support/formalLogin'

/**
 * HCT-453 前后台分端口登录入口。
 *
 * 生产形态是两个端口（成员前台 5173/8080、管理后台 5174/8081）；
 * 本套用例通过 `?portal=member|admin` 查询覆盖在同一 dev server 上
 * 复现两种入口模式（portalEntry.ts 的解析优先级保证两者等价），
 * 断言：入口品牌、成员刷脸/PIN、管理员账号密码、入口/门户不匹配拦截与跨端指引。
 */

const household = {
  id: 'household-entry-1',
  name: '入口测试家庭',
  created_by: 'parent-admin',
  created_at: '2026-08-25T00:00:00Z',
}

const ownerMember = {
  id: 'member-owner',
  household_id: household.id,
  display_name: '爸爸',
  role: 'SELF',
  actor_id: 'parent-admin',
  created_at: '2026-08-25T00:00:00Z',
}

const grandmaMember = {
  id: 'member-grandma',
  household_id: household.id,
  display_name: '奶奶',
  role: 'DEPENDENT',
  actor_id: 'grandma-account',
  created_at: '2026-08-25T00:00:00Z',
}

async function installEntryApi(page: Page): Promise<void> {
  await page.route('**/api/v1/**', async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    const respond = (body: unknown, status = 200) => route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify(body),
    })

    if (request.method() === 'POST' && path === '/api/v1/auth/login') {
      const submitted = request.postDataJSON() as { actor_id?: string } | null
      const actorId = submitted?.actor_id ?? 'parent-admin'
      return respond({
        actor_id: actorId,
        session_token: 'o'.repeat(48),
        expires_at: (Date.now() + 1_800_000) / 1000,
      })
    }
    if (request.method() === 'POST' && path === '/api/v1/auth/change-password') {
      return respond({
        actor_id: 'parent-admin',
        session_token: 'n'.repeat(48),
        expires_at: (Date.now() + 1_800_000) / 1000,
      })
    }
    if (request.method() === 'POST' && path === '/api/v1/auth/recover-password') {
      return respond({
        actor_id: 'parent-admin',
        household_id: household.id,
        session_token: 'r'.repeat(48),
        expires_at: (Date.now() + 1_800_000) / 1000,
      })
    }
    if (request.method() === 'POST' && path === '/api/v1/auth/pin-login') {
      const submitted = request.postDataJSON() as { actor_id?: string; household_id?: string } | null
      return respond({
        actor_id: submitted?.actor_id ?? grandmaMember.actor_id,
        household_id: submitted?.household_id ?? household.id,
        session_token: 'p'.repeat(48),
        expires_at: (Date.now() + 1_800_000) / 1000,
      })
    }
    if (request.method() === 'POST' && path === '/api/v1/auth/logout') {
      return respond({ status: 'logged_out' })
    }
    if (request.method() === 'GET' && path === '/api/v1/households') {
      return respond([household])
    }
    if (request.method() === 'GET' && path.endsWith('/members')) {
      return respond([ownerMember, grandmaMember])
    }
    if (request.method() === 'GET' && path === '/api/v1/meta/capabilities') {
      return respond({ phase: 'local', available: ['api'], unavailable: ['ollama'] })
    }
    if (request.method() === 'GET' && path.endsWith('/plan-workbench')) {
      return respond({ member_id: grandmaMember.id, generated_at: '2026-08-25T08:00:00Z', plans: [] })
    }
    if (request.method() === 'GET' && path.endsWith('/risks')) {
      return respond({ member_id: grandmaMember.id, alerts: [], total: 0, severe_count: 0, warning_count: 0 })
    }
    if (request.method() === 'GET' && path.endsWith('/state')) {
      return respond({
        member_id: ownerMember.id,
        household_id: household.id,
        state: { events_count: 0 },
        last_event_id: null,
        last_sequence: 0,
        version: 1,
        state_hash: null,
        updated_at: '2026-08-25T00:00:00Z',
      })
    }
    if (request.method() === 'GET' && path.startsWith('/api/v1/weather/')) {
      return respond({ status: 'unavailable', cache_status: 'none', action_cards: [] })
    }
    // 时间线、任务、复核、授权等一律空集，聚焦入口行为。
    return respond([])
  })
}

test('成员前台入口未绑定家庭时展示个人前台品牌，并引导去管理后台注册', async ({ page }) => {
  await installEntryApi(page)
  await page.goto('/?portal=member')

  await expect(page.getByRole('heading', { name: /我的健康日常/ }).first()).toBeVisible()
  await expect(page.getByText('成员前台 · 每位家人自己的健康日常')).toHaveCount(0)
  await expect(page.getByText('成员前台 · 个人身份')).toHaveCount(0)
  await expect(page.getByTestId('formal-login-method')).toHaveCount(0)
  await expect(page.getByLabel('访问用途代码', { exact: true })).toHaveCount(0)
  await expect(page.getByTestId('member-unbound-gate')).toBeVisible()
  await expect(page.getByRole('heading', { name: '请先到管理后台' })).toBeVisible()
  await expect(page.getByRole('link', { name: '去管理后台登录' })).toHaveAttribute(
    'href',
    'http://127.0.0.1:5174/?portal=admin',
  )
  await expect(page.getByRole('link', { name: '管理员登录' })).toHaveCount(0)
  await expect(page.getByRole('group', { name: '选择账号登录凭据' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '刷脸进入', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'PIN登录', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '数字密码' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '账号密码', exact: true })).toHaveCount(0)
  await expect(page.getByLabel('家庭管理员账号', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: /注册本地账号/ })).toHaveCount(0)
  await expect(page.getByTestId('member-portal-entry-guide')).toHaveCount(0)
})

test('管理后台入口展示全家管理品牌，并只提供账号密码', async ({ page }) => {
  await installEntryApi(page)
  await page.goto('/?portal=admin')

  await expect(page.getByRole('heading', { name: /家庭档案与授权/ })).toBeVisible()
  await expect(page.getByText('家庭管理后台 · 成员档案 / 复核 / 授权')).toHaveCount(0)
  await expect(page.getByText('管理后台 · 全家管理')).toHaveCount(0)

  await expect(page.getByTestId('formal-login-method')).toHaveCount(0)
  await expect(page.getByLabel('正式账号', { exact: true })).toBeVisible()
  await expect(page.getByLabel('密码', { exact: true })).toBeVisible()
  await expect(page.getByLabel('访问用途代码', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '进入管理后台', exact: true })).toBeVisible()
  await expect(page.getByRole('group', { name: '选择账号登录凭据' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '刷脸进入' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: /注册本地账号/ })).toBeVisible()

  const crossLink = page.getByRole('link', { name: '家人登录' })
  await expect(crossLink).toBeVisible()
  await expect(crossLink).toHaveAttribute('href', 'http://127.0.0.1:5173/?portal=member')
})

test('管理后台主按钮始终可点，密码错误在卡片内提示', async ({ page }) => {
  await installEntryApi(page)
  await page.route('**/api/v1/auth/login', async route => {
    await route.fulfill({
      status: 401,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'AUTH_FAILED' }),
    })
  })
  await page.goto('/?portal=admin')

  const submit = page.getByRole('button', { name: '进入管理后台', exact: true })
  await expect(submit).toBeEnabled()
  await submit.click()
  await expect(page.locator('.welcome-form-card').getByRole('alert')).toContainText('请输入')

  await expect(page.getByText(/至少 8 位，需同时包含英文字母和数字/)).toHaveCount(0)

  await page.getByLabel('正式账号', { exact: true }).fill('demo-parent')
  await page.getByLabel('密码', { exact: true }).fill('onlyletters')
  await expect(submit).toBeEnabled()
  await submit.click()
  await expect(page.locator('.welcome-form-card').getByRole('alert')).toContainText('账号或密码不正确')
  await expect(page.locator('.welcome-form-card').getByRole('alert')).not.toContainText('英文字母')

  await page.getByLabel('密码', { exact: true }).fill('WrongPass1')
  await expect(submit).toBeEnabled()
  await submit.click()
  await expect(page.locator('.welcome-form-card').getByRole('alert')).toContainText('账号或密码不正确')
})

test('管理后台可用本人六位数字密码重置忘记的正式密码', async ({ page }) => {
  await installEntryApi(page)
  await page.goto('/?portal=admin')

  await page.getByTestId('forgot-password').click()
  await expect(page.getByRole('heading', { name: '忘记密码' })).toBeVisible()
  await expect(page.getByLabel('本人六位数字密码', { exact: true })).toBeVisible()
  await page.getByLabel('正式账号', { exact: true }).fill('parent-admin')
  await page.getByLabel('家庭编号', { exact: true }).fill(household.id)
  await page.getByLabel('本人六位数字密码', { exact: true }).fill('042006')
  await page.getByLabel('新密码', { exact: true }).fill('new-password-456')
  await page.getByLabel('再次输入新密码', { exact: true }).fill('new-password-456')

  const submitted = page.waitForRequest(request =>
    request.method() === 'POST'
    && new URL(request.url()).pathname === '/api/v1/auth/recover-password')
  await page.getByRole('button', { name: '重置密码并登录' }).click()
  const request = await submitted

  expect(request.postDataJSON()).toEqual({
    actor_id: 'parent-admin',
    household_id: household.id,
    pin: '042006',
    new_password: 'new-password-456',
  })
  expect(request.url()).not.toContain('042006')
  await expect(page.locator('.app-frame')).toBeVisible()
})

test('登录后可修改密码并保持在新会话中', async ({ page }) => {
  await installEntryApi(page)
  await page.goto('/?portal=admin')
  await submitFormalLogin(page, 'parent-admin')
  await expect(page.locator('.app-frame')).toBeVisible()

  await page.getByRole('button', { name: '修改账号密码' }).click()
  const dialog = page.getByRole('dialog', { name: '修改正式账号密码' })
  await expect(dialog).toBeVisible()
  await dialog.getByLabel('当前密码', { exact: true }).fill('password-123')
  await dialog.getByLabel('新密码', { exact: true }).fill('new-password-456')
  await dialog.getByLabel('再次输入新密码', { exact: true }).fill('new-password-456')

  const submitted = page.waitForRequest(request =>
    request.method() === 'POST'
    && new URL(request.url()).pathname === '/api/v1/auth/change-password')
  await dialog.getByRole('button', { name: '确认修改' }).click()
  const request = await submitted

  expect(request.postDataJSON()).toEqual({
    current_password: 'password-123',
    new_password: 'new-password-456',
  })
  expect(request.headers().authorization).toBe(`Bearer ${'o'.repeat(48)}`)
  await expect(dialog).toBeHidden()
  await expect(page.getByText('密码已修改，其他设备上的旧会话已退出。')).toBeVisible()
  await expect(page.locator('.app-frame')).toBeVisible()
})

test('成员前台与管理后台的欢迎页明显不同（标语、徽标、主按钮互不出现）', async ({ page }) => {
  await installEntryApi(page)

  await page.goto('/?portal=member')
  await expect(page.getByRole('heading', { name: /我的健康日常/ }).first()).toBeVisible()
  await expect(page.getByRole('heading', { name: /家庭档案与授权/ })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '进入管理后台', exact: true })).toHaveCount(0)

  await page.goto('/?portal=admin')
  await expect(page.getByRole('heading', { name: /家庭档案与授权/ })).toBeVisible()
  await expect(page.getByRole('heading', { name: /我的健康日常/ })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '进入前台', exact: true })).toHaveCount(0)
})

test('成员前台入口用 PIN 选人进入成员首页且不渲染后台', async ({ page }) => {
  await seedBoundHousehold(page, household, [grandmaMember])
  await installEntryApi(page)
  await page.goto('/?portal=member')

  await page.getByRole('button', { name: 'PIN登录', exact: true }).click()
  await expect(page.locator('.app-frame')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '人工复核' })).toHaveCount(0)
  await expect(page.getByRole('option', { name: '奶奶' })).toBeVisible()
  await page.getByRole('option', { name: '奶奶' }).click()
  await page.getByLabel('六位数字密码', { exact: true }).fill('135790')
  await page.getByRole('button', { name: '进入前台', exact: true }).click()

  await expect(page.locator('.app-frame')).toBeVisible()
  await expect(page.getByRole('heading', { name: '你好，奶奶' })).toBeVisible()
  await expect(page.locator('aside.sidebar').getByRole('button', { name: '人工复核' })).toHaveCount(0)
})

test('管理后台入口拦截成员账号：登出并指向成员前台，不渲染前台界面', async ({ page }) => {
  await installEntryApi(page)
  await page.goto('/?portal=admin')

  await submitFormalLogin(page, grandmaMember.actor_id)

  await expect(page.getByRole('alert')).toContainText('这是管理后台')
  await expect(page.getByRole('alert')).toContainText('成员前台')
  await expect(page.locator('.app-frame')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '拍照录药' })).toHaveCount(0)

  const crossLink = page.getByRole('link', { name: '去成员前台' })
  await expect(crossLink).toBeVisible()
  await expect(crossLink).toHaveAttribute('href', 'http://127.0.0.1:5173/?portal=member')
})

test('成员前台入口放行已绑定家人的 PIN 并落在成员首页，只见成员导航', async ({ page }) => {
  await seedBoundHousehold(page, household, [grandmaMember])
  await installEntryApi(page)
  await page.goto('/?portal=member')

  await page.getByRole('button', { name: 'PIN登录', exact: true }).click()
  await page.getByRole('option', { name: '奶奶' }).click()
  await page.getByLabel('六位数字密码', { exact: true }).fill('135790')
  await page.getByRole('button', { name: '进入前台', exact: true }).click()

  await expect(page.locator('.app-frame')).toBeVisible()
  await expect(page.getByRole('heading', { name: '你好，奶奶' })).toBeVisible()
  // 成员首页 + 成员导航（HCT-439）：不出现任何管理后台导航项。
  await expect(page.locator('aside.sidebar').getByRole('button', { name: '我的家庭' })).toBeVisible()
  await expect(page.locator('aside.sidebar').getByRole('button', { name: '人工复核' })).toHaveCount(0)
  await expect(page.locator('aside.sidebar').getByRole('button', { name: '家庭总览' })).toHaveCount(0)
  await expect(page.locator('aside.sidebar').getByRole('button', { name: '授权管理' })).toHaveCount(0)
})

test('管理后台入口放行管理员账号并落在家庭总览', async ({ page }) => {
  await installEntryApi(page)
  await page.goto('/?portal=admin')

  await submitFormalLogin(page, 'parent-admin')

  await expect(page.locator('.app-frame')).toBeVisible()
  await expect(page.locator('aside.sidebar').getByRole('button', { name: '家庭总览' })).toBeVisible()
  await expect(page.locator('aside.sidebar').getByRole('button', { name: '人工复核' })).toBeVisible()
  await expect(page.getByText('家庭管理后台', { exact: false }).first()).toBeVisible()
})
