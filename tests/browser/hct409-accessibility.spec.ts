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
      })
    }
    if (request.method() === 'GET' && path.includes('/risks/')) {
      return respond({ alert: riskAlert, source_events: [] })
    }

    return respond({ detail: `Unexpected synthetic request: ${request.method()} ${path}` }, 500)
  })
}

async function loadOwnerView(page: Page): Promise<void> {
  await page.getByLabel('Development identity').fill('owner-1')
  await page.getByRole('button', { name: 'Load households' }).click()
  await expect(page.getByRole('heading', { name: 'Create grant' })).toBeVisible()
}

function axeScan(page: Page) {
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

  test('offline error state has no violations', async ({ page }) => {
    await page.route('**/api/v1/households', route => route.abort('failed'))
    await page.goto('/')
    await page.getByLabel('Development identity').fill('owner-1')
    await page.getByRole('button', { name: 'Load households' }).click()
    await expect(page.getByRole('alert')).toBeVisible()
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

    await page.keyboard.press('Tab')
    await expect(page.getByLabel('Development identity')).toBeFocused()
    await page.keyboard.type('owner-1')

    await page.keyboard.press('Tab')
    await expect(page.getByLabel('Access purpose code')).toBeFocused()

    await page.keyboard.press('Tab')
    await expect(page.getByRole('button', { name: 'Load households' })).toBeFocused()

    await page.keyboard.press('Enter')
    await expect(page.getByRole('heading', { name: 'Create grant' })).toBeVisible()
  })

  test('risk evidence disclosure is keyboard operable and announces state', async ({ page }) => {
    await installSyntheticApi(page)
    await page.goto('/')
    await loadOwnerView(page)

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

    const identity = page.getByLabel('Development identity')
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
  test('an empty identity submit reports the error via role=alert', async ({ page }) => {
    await installSyntheticApi(page)
    await page.goto('/')

    await page.getByRole('button', { name: 'Load households' }).click()
    await expect(page.getByRole('alert')).toContainText(
      'Enter a development identity before loading households.',
    )
  })

  test('the purpose field exposes its format hint and validity to assistive tech', async ({ page }) => {
    await installSyntheticApi(page)
    await page.goto('/')
    await loadOwnerView(page)

    const purpose = page.getByLabel('Purpose code', { exact: true })
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
    await expect(page.locator('main.workspace')).toHaveAttribute('lang', 'en')
    await expect(page.locator('.vision-quality-panel')).toHaveAttribute('lang', 'zh-CN')
  })
})
