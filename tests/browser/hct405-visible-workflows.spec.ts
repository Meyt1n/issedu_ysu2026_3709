import { expect, test, type Page } from '@playwright/test'

const household = {
  id: 'household-1',
  name: 'Synthetic household',
  created_by: 'owner-1',
  created_at: '2026-08-12T00:00:00Z',
}

const member = {
  id: 'member-1',
  household_id: household.id,
  display_name: 'Synthetic member',
  role: 'SELF',
  actor_id: 'owner-1',
  created_at: '2026-08-12T00:00:00Z',
}

async function installSyntheticApi(page: Page): Promise<void> {
  let authorization = {
    id: 'grant-1',
    household_id: household.id,
    member_id: member.id,
    grantor_actor_id: 'owner-1',
    grantee_actor_id: 'caregiver-1',
    data_fields: ['health_events'],
    actions: ['READ_EVENTS'],
    purpose: 'family-care',
    valid_from: '2026-08-12T00:00:00Z',
    valid_until: '2030-08-12T00:00:00Z',
    revoked_at: null as string | null,
    version: 1,
    created_at: '2026-08-12T00:00:00Z',
    updated_at: '2026-08-12T00:00:00Z',
  }
  let hasAuthorization = false

  await page.route('**/api/v1/**', async route => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    const respond = (body: unknown, status = 200) => route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify(body),
    })

    if (request.method() === 'GET' && path === '/api/v1/households') return respond([household])
    if (request.method() === 'GET' && path.endsWith('/members')) return respond([member])
    if (request.method() === 'GET' && path.endsWith('/authorizations')) {
      return respond(hasAuthorization && !authorization.revoked_at ? [authorization] : [])
    }
    if (request.method() === 'GET' && path.endsWith('/audits')) return respond([])
    if (request.method() === 'GET' && path.endsWith('/relationship-graph')) {
      return respond({
        member_id: member.id,
        generated_at: '2026-08-20T02:00:00Z',
        events_count: 1,
        last_event_id: 'event-1',
        nodes: [{
          id: 'drug:event-1',
          category: 'drug',
          label: '合成药品',
          source_event_id: 'event-1',
          source_recorded_at: '2026-08-20T01:00:00Z',
          source_created_by: 'owner-1',
        }],
      })
    }
    if (request.method() === 'GET' && path.endsWith('/timeline')) return respond([])
    if (request.method() === 'GET' && path.endsWith('/plan-workbench')) {
      return respond({
        member_id: member.id,
        generated_at: '2026-08-20T02:00:00Z',
        plans: [{
          plan_event_id: 'plan-1',
          drug: '合成药品',
          schedule: '每日一次',
          status: 'REMINDER',
          next_action_at: '2026-08-20T03:00:00Z',
          last_action: null,
          allowed_actions: ['CONFIRM', 'DEFER', 'SKIP'],
        }],
      })
    }
    if (request.method() === 'GET' && path.endsWith('/dashboard-summary')) {
      return respond({
        generated_at: '2026-08-20T02:00:00Z',
        member_count: 1,
        events_today: 2,
        events_total: 5,
        severe_count: 0,
        warning_count: 1,
        info_count: 1,
        pending_reviews: 1,
        pending_outbox: 0,
        week_series: [
          { day: '2026-08-14', count: 0 }, { day: '2026-08-15', count: 0 },
          { day: '2026-08-16', count: 0 }, { day: '2026-08-17', count: 0 },
          { day: '2026-08-18', count: 1 }, { day: '2026-08-19', count: 2 },
          { day: '2026-08-20', count: 2 },
        ],
      })
    }
    if (request.method() === 'GET' && path.endsWith('/state')) {
      return respond({
        member_id: member.id,
        household_id: household.id,
        state: { events_count: 0 },
        last_event_id: null,
        last_sequence: 0,
        version: 1,
        state_hash: null,
        updated_at: '2026-08-12T00:00:00Z',
      })
    }
    if (request.method() === 'GET' && path === '/api/v1/meta/capabilities') {
      return respond({ phase: 'local', available: ['api'], unavailable: ['ollama'] })
    }
    if (request.method() === 'GET' && path.endsWith('/risks')) {
      return respond({ member_id: member.id, alerts: [], total: 0, severe_count: 0, warning_count: 0 })
    }
    if (request.method() === 'GET' && (path.endsWith('/plans') || path.endsWith('/tasks') || path.endsWith('/review-tasks'))) {
      return respond([])
    }
    if (request.method() === 'GET' && path.startsWith('/api/v1/weather/')) {
      return respond({
        status: 'ok',
        cache_status: 'miss',
        location_scope: 'city',
        ruleset_version: 'weather-actions-v1',
        source_observed_at: '2026-08-18T01:00:00Z',
        fetched_at: '2026-08-18T01:01:00Z',
        disclaimer: '环境行动建议仅供日常生活安排参考，不构成诊断或用药建议。',
        temperature: 37,
        humidity: 62,
        condition: 'sunny',
        wind: '2级',
        aqi: 80,
        action_cards: [{
          rule_id: 'heat-high',
          level: 'warning',
          message: '高温提醒：建议减少长时间户外活动，及时补充饮水并留意室内通风。',
        }],
      })
    }
    if (request.method() === 'POST' && path.endsWith('/authorizations')) {
      hasAuthorization = true
      return respond(authorization, 201)
    }
    if (request.method() === 'POST' && path.endsWith('/revoke')) {
      authorization = { ...authorization, revoked_at: '2026-08-12T01:00:00Z', version: 2 }
      return respond(authorization)
    }

    return respond({ detail: `Unexpected synthetic request: ${request.method()} ${path}` }, 500)
  })
}

function navItem(page: Page, label: string) {
  return page.locator('aside.sidebar button.nav-item', { hasText: label })
}

function viewHeading(page: Page) {
  return page.locator('.view-stage h2.hero-greeting')
}

async function enterFamilySpace(page: Page): Promise<void> {
  await page.goto('/')
  await expect(page.getByRole('button', { name: '进入家庭空间' })).toBeVisible({ timeout: 20_000 })
  await page.getByLabel('开发身份标识').fill('owner-1')
  await page.getByRole('button', { name: '进入家庭空间' }).click()
  await expect(page.locator('.app-frame')).toBeVisible({ timeout: 20_000 })
  await expect(navItem(page, '授权管理')).toBeVisible()
}

test('家庭总览显著展示简洁的环境行动卡', async ({ page }) => {
  await installSyntheticApi(page)
  await enterFamilySpace(page)

  const panel = page.getByRole('region', { name: '今天的环境提醒' })
  await expect(panel).toBeVisible()
  await expect(panel.getByText('37°')).toBeVisible()
  await expect(panel.getByText(/高温提醒：建议减少长时间户外活动/)).toBeVisible()
  await expect(panel.getByText('城市级范围天气')).toBeVisible()
  await expect(panel.getByText(/更新于 08月18日 09:00/)).toBeVisible()
  await expect(panel.getByText('规则 weather-actions-v1')).toHaveCount(0)
  await expect(panel.getByText(/不构成诊断或用药建议/)).toBeVisible()

  const refreshed = page.waitForResponse(response =>
    response.url().includes('/api/v1/weather/action-cards'),
  )
  await panel.getByRole('button', { name: '刷新天气' }).click()
  await refreshed
  await expect(panel.getByText(/更新于/)).toBeVisible()
})

test('管理员创建授权后撤回，照护者可见范围立即清空', async ({ page }) => {
  await installSyntheticApi(page)
  await enterFamilySpace(page)

  // 进入家庭空间后，侧栏必须保持本地数据承诺
  await expect(page.getByText('家庭健康数据默认不出网，全部保存在本地可信域。')).toBeVisible()

  await navItem(page, '授权管理').click()
  await expect(viewHeading(page)).toHaveText('授权管理')
  await expect(page.getByRole('heading', { name: '新建授权' })).toBeVisible()

  await page.getByLabel('照护者身份标识').fill('caregiver-1')
  await page.getByRole('button', { name: '创建授权' }).click()
  await expect(page.getByText('授权已创建，默认遵循最小权限原则。')).toBeVisible()

  // 照护者预览：授权元数据可见（不加载健康事件内容）
  await page.getByLabel('输入照护者身份查看其可见范围').fill('caregiver-1')
  await expect(page.getByText(/可见字段：health_events/)).toBeVisible()

  // 撤回需要经过确认弹窗，防止误触
  await page.getByRole('button', { name: '撤回授权' }).first().click()
  const dialog = page.getByRole('alertdialog')
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: '撤回授权' }).click()

  await expect(page.getByText('授权已撤回，对应照护者立即失去访问权限。')).toBeVisible()
  await expect(page.getByText('该照护者当前没有任何有效授权字段。')).toBeVisible()
})

test('命令面板 Ctrl+K 可以在十二个视图之间快速跳转', async ({ page }) => {
  await installSyntheticApi(page)
  await enterFamilySpace(page)

  await page.keyboard.press('Control+k')
  const palette = page.getByRole('dialog', { name: '命令面板' })
  await expect(palette).toBeVisible()

  await palette.getByLabel('搜索命令').fill('授权')
  await page.keyboard.press('Enter')
  await expect(palette).toHaveCount(0)
  await expect(viewHeading(page)).toHaveText('授权管理')

  // 顶栏按钮同样可以打开；无匹配时给出无导流的空态提示
  await page.getByRole('button', { name: /快速跳转/ }).click()
  await palette.getByLabel('搜索命令').fill('购药')
  await expect(palette.getByText(/没有匹配「购药」的命令/)).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(palette).toHaveCount(0)
})

test('健康计划页只展示服务端返回的照护待办', async ({ page }) => {
  await installSyntheticApi(page)
  await enterFamilySpace(page)

  await navItem(page, '健康计划').click()
  await expect(viewHeading(page)).toHaveText('健康计划中心')
  await expect(page.getByText('合成药品')).toBeVisible()
  await expect(page.getByText('待提醒')).toBeVisible()
  await expect(page.getByText(/下次处理/)).toBeVisible()
})

test('家庭健康图谱只消费服务端脱敏关系投影', async ({ page }) => {
  await installSyntheticApi(page)
  await enterFamilySpace(page)

  const graph = page.waitForResponse(response => response.url().includes('/relationship-graph'))
  await navItem(page, '健康图谱').click()
  await graph
  await expect(viewHeading(page)).toHaveText('家庭健康图谱')
  await expect(page.getByRole('img', { name: 'Synthetic member的健康关系图谱' })).toBeVisible()
  await expect(page.getByText('合成药品')).toBeVisible()
})

test('家庭大屏使用脱敏聚合接口而非成员逐项汇总', async ({ page }) => {
  await installSyntheticApi(page)
  await enterFamilySpace(page)

  const summary = page.waitForResponse(response => response.url().includes('/dashboard-summary'))
  await navItem(page, '家庭大屏').click()
  await summary
  await expect(page.getByRole('heading', { name: '家庭大屏', level: 1 })).toBeVisible()
  await expect(page.getByText('累计 5 条已确认事实')).toBeVisible()
})

test('本地 API 不可用时不进入家庭空间，也不渲染任何健康摘要', async ({ page }) => {
  await page.route('**/api/v1/households', route => route.abort('failed'))
  await page.goto('/')

  await page.getByLabel('开发身份标识').fill('owner-1')
  await page.getByRole('button', { name: '进入家庭空间' }).click()

  await expect(page.getByRole('alert')).toContainText('本地 API 服务不可用，本次没有改变任何数据。')
  await expect(page.locator('.app-frame')).toHaveCount(0)
  await expect(page.getByText('Synthetic member')).toHaveCount(0)
})

test('可见界面始终保持本地优先与无导流安全边界', async ({ page }) => {
  await page.goto('/')

  await expect(page.getByText('健康数据默认保存在本地家庭可信域')).toBeVisible()
  await expect(page.getByText('家庭健康记录仅供日常参考，不提供诊断、处方或用药决策；紧急情况请联系医生或当地急救服务。')).toBeVisible()
  await expect(page.locator('body')).not.toContainText(
    /购药入口|立即购买|去问诊|在线咨询|广告推荐|buy medicine|purchase|online consultation|advertisement|commission/i,
  )
})
