import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

// HCT-409 frontend accessibility acceptance: keyboard, focus visibility,
// form errors, contrast, responsive layout, and screen-reader landmarks.
// All data below is synthetic; no real health data is loaded.

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

const riskAlert = {
  rule_id: 'rule-hydration',
  level: 'WARNING',
  message: 'Synthetic hydration reminder signal',
  source_event_ids: ['event-1'],
  created_at: '2026-08-12T00:00:00Z',
}

const reviewTask = {
  id: 'review-1',
  vision_task_id: 'vision-1',
  household_id: household.id,
  member_id: member.id,
  status: 'PENDING_REVIEW',
  fusion_status: 'READY_FOR_FUSION',
  candidates: [{ drug_name: 'Synthetic medicine', confidence: 0.96, evidence: ['OCR'] }],
  selected_candidate: null,
  manual_payload: null,
  model_version: 'demo-model',
  rule_version: 'rules-v0',
  version: 1,
  confirmed_by: null,
  confirmed_at: null,
  created_at: '2026-08-12T02:00:00Z',
  updated_at: '2026-08-12T02:00:00Z',
}

async function installSyntheticApi(page: Page): Promise<void> {
  await page.route('**/api/v1/**', async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    const respond = (body: unknown, status = 200) => route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify(body),
    })

    if (request.method() === 'GET' && path === '/api/v1/households') return respond([household])
    if (request.method() === 'GET' && path.endsWith('/members')) return respond([member])
    if (request.method() === 'GET' && path.endsWith('/authorizations')) return respond([])
    if (request.method() === 'GET' && path.endsWith('/timeline')) return respond([])
    if (request.method() === 'GET' && path.endsWith('/plan-workbench')) {
      return respond({
        member_id: member.id,
        generated_at: '2026-08-12T02:00:00Z',
        plans: [{
          plan_event_id: 'plan-1',
          drug: 'Synthetic medicine',
          schedule: '每日一次',
          status: 'REMINDER',
          next_action_at: '2026-08-12T03:00:00Z',
          last_action: null,
          allowed_actions: ['CONFIRM', 'DEFER', 'SKIP'],
        }],
      })
    }
    if (request.method() === 'GET' && path.endsWith('/review-tasks')) return respond([reviewTask])
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
      return respond({
        member_id: member.id,
        alerts: [riskAlert],
        total: 1,
        severe_count: 0,
        warning_count: 1,
        ruleset_version: 'rules-v0',
        non_severe_budget: 10,
        suppressed_count: 2,
      })
    }
    if (request.method() === 'GET' && path.includes('/risks/')) {
      return respond({ alert: riskAlert, source_events: [] })
    }

    return respond({ detail: `Unexpected synthetic request: ${request.method()} ${path}` }, 500)
  })
}

async function loadOwnerView(page: Page): Promise<void> {
  await page.getByRole('button', { name: '开发演示' }).click()
  await page.getByLabel('开发身份标识').fill('owner-1')
  await page.getByRole('button', { name: '进入家庭空间' }).click()
  await expect(page.getByRole('heading', { name: '家庭总览' })).toBeVisible()
}

async function axeScan(page: Page) {
  await page.addStyleTag({
    content: '* { animation: none !important; transition: none !important; } .pipe-step.off, .channel-chip.off { opacity: 1 !important; }',
  })
  return new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze()
}

test.describe('axe automated WCAG 2.1 AA scans', () => {
  test('initial page has no violations', async ({ page }) => {
    await installSyntheticApi(page)
    await page.goto('/')
    const results = await axeScan(page)
    expect(results.violations).toEqual([])
  })

  test('loaded owner view has no violations', async ({ page }) => {
    await installSyntheticApi(page)
    await page.goto('/')
    await loadOwnerView(page)
    const results = await axeScan(page)
    expect(results.violations).toEqual([])
  })

  test('家庭健康首页汇总天气、用药、待确认事项和成员状态', async ({ page }) => {
    await installSyntheticApi(page)
    await page.goto('/')
    await loadOwnerView(page)

    await expect(page.getByRole('heading', { name: '今日用药' })).toBeVisible()
    await expect(page.getByRole('heading', { name: '待确认事项' })).toBeVisible()
    await expect(page.getByRole('heading', { name: '最近识别的药品' })).toBeVisible()
    await expect(page.getByRole('heading', { name: '家庭成员状态' })).toBeVisible()
    await expect(page.getByText('Synthetic medicine', { exact: true })).toHaveCount(2)
    await expect(page.getByText('识别候选，不是健康事实')).toBeVisible()
    await expect(page.locator('.ov-member strong')).toHaveText('Synthetic member')
  })

  test('risk view explains budget suppression from the server summary', async ({ page }) => {
    await installSyntheticApi(page)
    await page.goto('/')
    await loadOwnerView(page)
    await page.getByRole('button', { name: '用药安全', exact: true }).click()
    await expect(page.getByText(/2 条普通信号受每日预算 10 条限制/)).toBeVisible()
    await expect(page.getByText(/规则 rules-v0/)).toBeVisible()
  })

  test('offline error state has no violations', async ({ page }) => {
    await page.route('**/api/v1/households', route => route.abort('failed'))
    await page.goto('/')
    await page.getByRole('button', { name: '开发演示' }).click()
    await page.getByLabel('开发身份标识').fill('owner-1')
    await page.getByRole('button', { name: '进入家庭空间' }).click()
    await expect(page.getByRole('alert')).toContainText('本地 API 服务不可用')
    const results = await axeScan(page)
    expect(results.violations).toEqual([])
  })

  test('mobile viewport has no violations', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 })
    await installSyntheticApi(page)
    await page.goto('/')
    await loadOwnerView(page)
    const results = await axeScan(page)
    expect(results.violations).toEqual([])
  })
})

test.describe('keyboard path and focus visibility', () => {
  test('the identity form is operable with keyboard only', async ({ page }) => {
    await installSyntheticApi(page)
    await page.goto('/')

    // 正式账号登录排在第一位并默认选中（HCT-448：正式登录为主视觉），开发演示为次要入口。
    await page.keyboard.press('Tab')
    await expect(page.getByRole('button', { name: '正式账号登录' })).toBeFocused()
    await page.keyboard.press('Tab')
    await expect(page.getByRole('button', { name: '开发演示' })).toBeFocused()
    await page.keyboard.press('Enter')
    await page.keyboard.press('Tab')
    await expect(page.getByLabel('开发身份标识')).toBeFocused()
    await page.keyboard.type('owner-1')

    await page.keyboard.press('Tab')
    await expect(page.getByLabel('访问用途代码')).toBeFocused()

    await page.keyboard.press('Tab')
    await expect(page.getByRole('button', { name: '进入家庭空间' })).toBeFocused()

    await page.keyboard.press('Enter')
    await expect(page.getByRole('heading', { name: '家庭总览' })).toBeVisible()
  })

  test('risk evidence disclosure is keyboard operable and announces state', async ({ page }) => {
    await installSyntheticApi(page)
    await page.goto('/')
    await loadOwnerView(page)

    await page.getByRole('button', { name: '用药安全', exact: true }).click()
    await expect(page.getByRole('heading', { name: '风险信号与依据' })).toBeVisible()

    const toggle = page.getByRole('button', { name: /Synthetic hydration reminder signal/ })
    await expect(toggle).toHaveAttribute('aria-expanded', 'false')
    await toggle.focus()
    await page.keyboard.press('Enter')
    await expect(toggle).toHaveAttribute('aria-expanded', 'true')
    await page.keyboard.press('Enter')
    await expect(toggle).toHaveAttribute('aria-expanded', 'false')
  })

  test('focused controls render a visible focus indicator', async ({ page }) => {
    await installSyntheticApi(page)
    await page.goto('/')

    await page.getByRole('button', { name: '开发演示' }).click()
    const identity = page.getByLabel('开发身份标识')
    await identity.focus()
    const outline = await identity.evaluate(element => {
      const style = window.getComputedStyle(element)
      return { style: style.outlineStyle, width: style.outlineWidth }
    })
    expect(outline.style).not.toBe('none')
    expect(Number.parseFloat(outline.width)).toBeGreaterThanOrEqual(2)
  })
})

test.describe('form errors', () => {
  test('an empty identity cannot be submitted', async ({ page }) => {
    await installSyntheticApi(page)
    await page.goto('/')

    await page.getByRole('button', { name: '开发演示' }).click()
    await expect(page.getByRole('button', { name: '进入家庭空间' })).toBeDisabled()
  })

  test('the purpose field exposes its format hint and validity to assistive tech', async ({ page }) => {
    await installSyntheticApi(page)
    await page.goto('/')

    await page.getByRole('button', { name: '开发演示' }).click()
    const purpose = page.getByLabel('访问用途代码')
    await expect(purpose).toHaveAttribute('aria-describedby', 'purpose-format-hint')
    await expect(purpose).toHaveAttribute('aria-invalid', 'false')

    await purpose.fill('无效 purpose ！')
    await expect(purpose).toHaveAttribute('aria-invalid', 'true')
  })
})

test.describe('responsive layout', () => {
  test('a 375px viewport does not overflow horizontally', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 })
    await installSyntheticApi(page)
    await page.goto('/')
    await loadOwnerView(page)

    const overflow = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }))
    expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.clientWidth)
  })
})

test.describe('screen reader structure', () => {
  test('the page exposes one main landmark, a top-level heading, and language markers', async ({ page }) => {
    await installSyntheticApi(page)
    await page.goto('/')

    await expect(page.getByRole('main')).toHaveCount(1)
    await expect(page.getByRole('heading', { level: 1 })).toHaveCount(1)
    await expect(page.locator('html')).toHaveAttribute('lang', 'zh-CN')
    await expect(page.locator('main')).toHaveAttribute('lang', 'zh-CN')
  })
})
