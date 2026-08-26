import { expect, test, type Page } from '@playwright/test'

/**
 * HCT-453 前后台分端口登录入口。
 *
 * 生产形态是两个端口（成员前台 5173/8080、管理后台 5174/8081）；
 * 本套用例通过 `?portal=member|admin` 查询覆盖在同一 dev server 上
 * 复现两种入口模式（portalEntry.ts 的解析优先级保证两者等价），
 * 断言：入口品牌、凭据默认值、入口/门户不匹配拦截与跨端指引。
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
    if (request.method() === 'POST' && path === '/api/v1/auth/pin-login') {
      return respond({
        actor_id: grandmaMember.actor_id,
        household_id: household.id,
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

test('成员前台入口展示个人前台品牌：人脸/PIN 为主，密码收进「其他方式」', async ({ page }) => {
  await installEntryApi(page)
  await page.goto('/?portal=member')

  // HCT-455：成员前台是「一位家人自己的个人前台」，不是后台账号系统。
  await expect(page.getByRole('heading', { name: /我的健康日常/ }).first()).toBeVisible()
  await expect(page.getByText('成员前台 · 每位家人自己的健康日常')).toBeVisible()
  await expect(page.getByText('成员前台 · 个人身份')).toBeVisible()
  await expect(page.getByText(/以家人自己的身份进入/)).toBeVisible()

  // 凭据 tab 只保留人脸识别 / 家庭 PIN；账号密码退到「其他方式」次级入口。
  const credentialGroup = page.getByRole('group', { name: '选择账号登录凭据' })
  const tabs = credentialGroup.getByRole('button')
  await expect(tabs).toHaveCount(2)
  await expect(tabs.nth(0)).toHaveText('人脸识别')
  await expect(tabs.nth(1)).toHaveText('家庭 PIN')
  await expect(credentialGroup.getByRole('button', { name: '家庭 PIN' })).toHaveClass(/active/)
  await expect(page.getByLabel('六位数字 PIN')).toBeVisible()
  await expect(page.getByRole('button', { name: '其他方式：用账号密码登录' })).toBeVisible()
  await expect(page.getByRole('button', { name: '进入我的前台' })).toBeVisible()

  // 跨端指引指向管理后台端口，并显式带上 ?portal=admin 覆盖。
  const crossLink = page.getByRole('link', { name: /我是家庭管理员，去管理后台/ })
  await expect(crossLink).toBeVisible()
  await expect(crossLink).toHaveAttribute('href', 'http://127.0.0.1:5174/?portal=admin')
})

test('管理后台入口展示全家管理品牌，账号密码为主', async ({ page }) => {
  await installEntryApi(page)
  await page.goto('/?portal=admin')

  await expect(page.getByRole('heading', { name: /家庭管理后台/ })).toBeVisible()
  await expect(page.getByText('家庭管理后台 · 成员档案 / 复核 / 授权')).toBeVisible()
  await expect(page.getByText('管理后台 · 全家管理')).toBeVisible()

  const credentialGroup = page.getByRole('group', { name: '选择账号登录凭据' })
  const tabs = credentialGroup.getByRole('button')
  await expect(tabs).toHaveCount(1)
  await expect(tabs.nth(0)).toHaveText('账号密码')
  await expect(credentialGroup.getByRole('button', { name: '账号密码' })).toHaveClass(/active/)
  await expect(credentialGroup.getByRole('button', { name: '家庭 PIN' })).toHaveCount(0)
  await expect(credentialGroup.getByRole('button', { name: '人脸识别' })).toHaveCount(0)
  await expect(page.getByLabel('本地账号')).toBeVisible()
  await expect(page.getByText('管理员推荐使用账号密码')).toBeVisible()
  await expect(page.getByRole('button', { name: '进入管理后台' })).toBeVisible()

  const crossLink = page.getByRole('link', { name: /我是家庭成员，回成员前台/ })
  await expect(crossLink).toBeVisible()
  await expect(crossLink).toHaveAttribute('href', 'http://127.0.0.1:5173/?portal=member')
})

test('成员前台与管理后台的欢迎页明显不同（标语、徽标、主按钮互不出现）', async ({ page }) => {
  await installEntryApi(page)

  await page.goto('/?portal=member')
  await expect(page.getByRole('heading', { name: /我的健康日常/ }).first()).toBeVisible()
  await expect(page.getByRole('heading', { name: /管好一家人的健康档案/ })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '进入管理后台' })).toHaveCount(0)

  await page.goto('/?portal=admin')
  await expect(page.getByRole('heading', { name: /管好一家人的健康档案/ })).toBeVisible()
  await expect(page.getByRole('heading', { name: /我的健康日常/ })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '进入我的前台' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '其他方式：用账号密码登录' })).toHaveCount(0)
})

test('成员前台入口拦截管理员账号：登出并指向管理后台，不渲染后台界面', async ({ page }) => {
  await installEntryApi(page)
  await page.goto('/?portal=member')

  // 成员前台没有账号密码 tab：管理员只能通过「其他方式」找到密码登录。
  await page.getByRole('button', { name: '其他方式：用账号密码登录' }).click()
  await page.getByLabel('本地账号').fill('parent-admin')
  await page.getByLabel('密码').fill('synthetic-password-123')
  await page.getByRole('button', { name: '进入我的前台' }).click()

  // 不落在管理后台：无应用框架、无后台导航。
  await expect(page.getByRole('alert')).toContainText('这是家庭成员前台入口')
  await expect(page.locator('.app-frame')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '人工复核' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '家庭总览' })).toHaveCount(0)

  const crossLink = page.getByRole('link', { name: '去管理后台登录' })
  await expect(crossLink).toBeVisible()
  await expect(crossLink).toHaveAttribute('href', 'http://127.0.0.1:5174/?portal=admin')
})

test('管理后台入口拦截成员账号：登出并指向成员前台，不渲染前台界面', async ({ page }) => {
  await installEntryApi(page)
  await page.goto('/?portal=admin')

  // 管理后台不再提供家人使用的 PIN / 人脸入口；用成员账号密码验证入口锁仍会拒绝。
  await page.getByLabel('本地账号').fill(grandmaMember.actor_id)
  await page.getByLabel('密码').fill('synthetic-password-123')
  await page.getByRole('button', { name: '进入管理后台' }).click()

  await expect(page.getByRole('alert')).toContainText('这是家庭管理后台入口')
  await expect(page.locator('.app-frame')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '拍照录药' })).toHaveCount(0)

  const crossLink = page.getByRole('link', { name: '回成员前台登录' })
  await expect(crossLink).toBeVisible()
  await expect(crossLink).toHaveAttribute('href', 'http://127.0.0.1:5173/?portal=member')
})

test('成员前台入口放行成员账号并落在成员首页，只见成员导航', async ({ page }) => {
  await installEntryApi(page)
  await page.goto('/?portal=member')

  await page.getByRole('textbox', { name: /你的登录名/ }).fill(grandmaMember.actor_id)
  const householdSelect = page.locator('select').filter({ has: page.locator(`option[value="${household.id}"]`) })
  await expect(householdSelect).toBeVisible({ timeout: 5000 })
  await householdSelect.selectOption(household.id)
  await page.getByLabel('六位数字 PIN').fill('135790')
  await page.getByRole('button', { name: '进入我的前台' }).click()

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

  await page.getByLabel('本地账号').fill('parent-admin')
  await page.getByLabel('密码').fill('synthetic-password-123')
  await page.getByRole('button', { name: '进入管理后台' }).click()

  await expect(page.locator('.app-frame')).toBeVisible()
  await expect(page.locator('aside.sidebar').getByRole('button', { name: '家庭总览' })).toBeVisible()
  await expect(page.locator('aside.sidebar').getByRole('button', { name: '人工复核' })).toBeVisible()
  await expect(page.getByText('家庭管理后台', { exact: false }).first()).toBeVisible()
})
