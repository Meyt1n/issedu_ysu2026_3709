import { expect, test, type Page } from '@playwright/test'

import { submitFormalLogin } from './support/formalLogin'

/**
 * HCT-455 总览排版修复（图二 / 图三 / 图四）。
 *
 * 用与用户截图一致的数据形态（两位成员、多条识别待复核、单条天气建议）
 * 在 1280×800 视口断言：
 * - 图二：天气「生活安排」建议横排渲染，不被压成一字一行的窄列；
 * - 图三：「家庭成员状态」成员格子完整渲染（姓名/角色/状态签/事件数），
 *   分区编号沿阅读顺序严格递增（01→05，不再出现 04 下面还有 01）；
 * - 图四：管理后台侧栏分组收进一屏，不出现内容溢出（无滚动条）。
 */

const household = {
  id: 'household-hct455',
  name: '排版测试家庭',
  created_by: 'parent-admin',
  created_at: '2026-08-15T00:00:00Z',
}

const members = [
  {
    id: 'member-grandma',
    household_id: household.id,
    display_name: '奶奶',
    role: 'DEPENDENT',
    actor_id: 'grandma-account',
    created_at: '2026-08-15T00:00:00Z',
  },
  {
    id: 'member-owner',
    household_id: household.id,
    display_name: '爸爸',
    role: 'SELF',
    actor_id: 'parent-admin',
    created_at: '2026-08-15T00:00:00Z',
  },
]

const reviewTasks = Array.from({ length: 13 }, (_, index) => ({
  id: `review-${index}`,
  household_id: household.id,
  member_id: 'member-grandma',
  status: 'PENDING_REVIEW',
  fusion_status: 'CONFLICT',
  payload: { candidates: [{ drug_name: `候选药品-${index + 1}` }] },
  proposed_event: { payload: { drug_name: `候选药品-${index + 1}` } },
  created_at: '2026-08-15T08:00:00Z',
  updated_at: '2026-08-15T08:00:00Z',
}))

async function installOverviewApi(page: Page): Promise<void> {
  await page.route('**/api/v1/**', async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    const respond = (body: unknown, status = 200) =>
      route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })

    if (request.method() === 'POST' && path === '/api/v1/auth/login') {
      return respond({
        actor_id: 'parent-admin',
        session_token: 'o'.repeat(48),
        expires_at: (Date.now() + 1_800_000) / 1000,
      })
    }
    if (request.method() === 'POST' && path === '/api/v1/auth/logout') return respond({ status: 'ok' })
    if (request.method() === 'GET' && path === '/api/v1/households') return respond([household])
    if (request.method() === 'GET' && path.endsWith('/members')) return respond(members)
    if (request.method() === 'GET' && path === '/api/v1/meta/capabilities') {
      return respond({
        phase: 'P0-foundation',
        available: ['manual-health-event', 'household-member', 'review-task'],
        unavailable: ['vision-inference', 'llm-cloud', 'external-web'],
      })
    }
    if (request.method() === 'GET' && path.endsWith('/plan-workbench')) {
      return respond({ member_id: 'member-grandma', generated_at: '2026-08-26T08:00:00Z', plans: [] })
    }
    if (request.method() === 'GET' && path.endsWith('/risks')) {
      return respond({ member_id: 'member-grandma', alerts: [], total: 0, severe_count: 0, warning_count: 0 })
    }
    if (request.method() === 'GET' && path.includes('/review-tasks')) return respond(reviewTasks)
    if (request.method() === 'GET' && path.endsWith('/state')) {
      return respond({
        member_id: 'member-grandma',
        household_id: household.id,
        state: { events_count: 1 },
        last_event_id: 'event-1',
        last_sequence: 1,
        version: 1,
        state_hash: null,
        updated_at: '2026-08-15T09:00:00Z',
      })
    }
    if (request.method() === 'GET' && path.startsWith('/api/v1/weather/')) {
      return respond({
        status: 'ok',
        cache_status: 'fresh',
        temperature: 22,
        condition: 'cloudy',
        humidity: 97,
        wind: '东北风 · 3级',
        observed_at: '2026-08-26T08:46:00Z',
        scope: 'district',
        action_cards: [
          { rule_id: 'humidity-high', level: 'info', message: '空气湿度较高：可适时除湿并保持室内物品干燥。' },
        ],
      })
    }
    if (request.method() === 'GET' && path.startsWith('/api/v1/health-news')) {
      return respond({ status: 'local_only', items: [] })
    }
    return respond([])
  })
}

async function signInAsAdmin(page: Page): Promise<void> {
  await page.setViewportSize({ width: 1280, height: 800 })
  await installOverviewApi(page)
  await page.goto('/?portal=admin')
  await submitFormalLogin(page, 'parent-admin')
  await expect(page.locator('.app-frame')).toBeVisible()
  await expect(page.locator('.weather-action-panel')).toBeVisible()
}

test('图二：天气建议横排渲染，不再被压成竖排窄列', async ({ page }) => {
  await signInAsAdmin(page)

  const advice = page.locator('.weather-advice').first()
  await expect(advice).toBeVisible()
  await expect(advice).toContainText('空气湿度较高')

  const box = (await advice.boundingBox())!
  // 竖排故障时该卡宽度不足 100px、高度超过 200px；横排后应明显宽于高。
  expect(box.width).toBeGreaterThan(240)
  expect(box.height).toBeLessThan(120)
})

test('图三：家庭成员状态完整渲染，分区编号沿阅读顺序递增', async ({ page }) => {
  await signInAsAdmin(page)

  await expect(page.getByRole('button', { name: '管理授权', exact: true })).toHaveCount(0)

  const membersCard = page.locator('.home-dashboard-members')
  await membersCard.scrollIntoViewIfNeeded()
  const rows = page.locator('.home-dashboard-member')
  await expect(rows).toHaveCount(2)
  await expect(rows.nth(0)).toContainText('奶奶')
  await expect(rows.nth(0)).toContainText('被照护成员')
  await expect(rows.nth(0)).toContainText('1 条已同步事件')
  await expect(rows.nth(0).locator('.pill')).toContainText('有已同步记录')
  await expect(rows.nth(1)).toContainText('爸爸')

  // 卡片不得再被压成只剩标题的白条（修复前整卡仅约 46px 高）。
  const cardBox = (await membersCard.boundingBox())!
  expect(cardBox.height).toBeGreaterThan(150)

  // 分区编号在 DOM（即阅读）顺序中严格递增，且纵向位置同样递增。
  // 健康日历已迁入家庭大屏，首页只保留 01→05 五个摘要分区。
  const seen = await page.locator('.sec-no').evaluateAll(nodes =>
    nodes.map(node => ({
      no: node.textContent?.trim() ?? '',
      top: node.getBoundingClientRect().top,
    })),
  )
  expect(seen.map(item => item.no)).toEqual(['01', '02', '03', '04', '05'])
  for (let index = 1; index < seen.length; index += 1) {
    expect(seen[index]!.top).toBeGreaterThanOrEqual(seen[index - 1]!.top)
  }
})

test('图四：管理后台侧栏在 1280×800 下五组导航收进一屏，无滚动条', async ({ page }) => {
  await signInAsAdmin(page)

  const sidebar = page.locator('aside.sidebar')
  await expect(sidebar.getByRole('button', { name: '家庭总览' })).toBeVisible()
  await expect(sidebar.getByRole('button', { name: '知识文档' })).toHaveCount(0)
  await expect(sidebar.getByRole('button', { name: '演示造数' })).toHaveCount(0)
  await expect(sidebar.getByRole('button', { name: '模型实验室' })).toHaveCount(0)
  await expect(sidebar.getByRole('button', { name: '授权管理' })).toHaveCount(0)
  await expect(sidebar.getByText('账户安全')).toBeVisible()
  await expect(sidebar.getByText('家庭洞察')).toBeVisible()
  await expect(sidebar.getByText('健康数据默认只保存在本地。')).toBeVisible()
  await expect(sidebar.getByRole('button', { name: '收起导航' })).toBeVisible()

  const metrics = await sidebar.evaluate(el => ({
    scrollHeight: el.scrollHeight,
    clientHeight: el.clientHeight,
    scrollbarWidth: getComputedStyle(el).scrollbarWidth,
  }))
  // 首选：完全不溢出；同时滚动条按 CSS 声明隐藏（极矮窗口的兜底）。
  expect(metrics.scrollHeight).toBeLessThanOrEqual(metrics.clientHeight)
  expect(metrics.scrollbarWidth).toBe('none')
})
