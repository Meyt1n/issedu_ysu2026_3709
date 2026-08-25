import { expect, test, type Page } from '@playwright/test'

const household = {
  id: 'household-member-1',
  name: '爷爷奶奶家',
  created_by: 'parent-admin',
  created_at: '2026-08-24T00:00:00Z',
}

const member = {
  id: 'member-grandma',
  household_id: household.id,
  display_name: '奶奶',
  role: 'DEPENDENT',
  actor_id: 'grandma-account',
  created_at: '2026-08-24T00:00:00Z',
}

async function installMemberApi(page: Page): Promise<void> {
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
    if (request.method() === 'GET' && path.endsWith('/timeline')) {
      return respond([{
        id: 'event-confirmed-1',
        household_id: household.id,
        member_id: member.id,
        sequence_no: 1,
        event_type: 'plan_confirmed',
        source: 'MANUAL',
        confirmation_status: 'CONFIRMED',
        payload: { drug: '布洛芬缓释胶囊' },
        evidence: {},
        created_by: 'parent-admin',
        confirmed_by: 'parent-admin',
        occurred_at: '2026-08-24T08:00:00Z',
        recorded_at: '2026-08-24T08:00:00Z',
        correlation_id: 'corr-1',
        created_at: '2026-08-24T08:00:00Z',
      }])
    }
    if (request.method() === 'GET' && path.endsWith('/plan-workbench')) {
      return respond({
        member_id: member.id,
        generated_at: '2026-08-24T08:00:00Z',
        plans: [{
          plan_event_id: 'plan-1',
          drug: '布洛芬缓释胶囊',
          schedule: '每日一次',
          status: 'REMINDER',
          next_action_at: '2026-08-24T12:00:00Z',
          last_action: null,
          allowed_actions: [],
        }],
      })
    }
    if (request.method() === 'GET' && path.endsWith('/risks')) {
      return respond({
        member_id: member.id,
        alerts: [{
          rule_id: 'allergy_conflict',
          level: 'WARNING',
          message: '请和家庭管理员一起核对这条记录。',
          source_event_ids: ['event-confirmed-1'],
          created_at: '2026-08-24T08:00:00Z',
          rule_version: 'demo-rules-v1',
          risk_fingerprint: 'risk-fingerprint-1',
          acknowledgement: null,
        }],
        total: 1,
        severe_count: 0,
        warning_count: 1,
      })
    }
    if (request.method() === 'GET' && path.endsWith('/vision-tasks')) {
      return respond([{
        id: 'member-task-1',
        household_id: household.id,
        member_id: member.id,
        file_id: 'member-photo-1.jpg',
        task_type: 'medicine',
        status: 'running',
        error_code: null,
        error_message: null,
        error_detail: null,
        result: null,
        model_version: null,
        model_threshold: null,
        schema_version: null,
        code_version: null,
        data_version: null,
        preprocess_version: null,
        input_digest: null,
        created_by: member.actor_id,
        created_at: '2026-08-24T08:00:00Z',
      }])
    }
    if (request.method() === 'GET' && path === '/api/v1/vision-tasks/member-task-1') {
      return respond({
        id: 'member-task-1',
        household_id: household.id,
        member_id: member.id,
        file_id: 'member-photo-1.jpg',
        task_type: 'medicine',
        status: 'running',
        error_code: null,
        error_message: null,
        error_detail: null,
        result: null,
        model_version: null,
        model_threshold: null,
        schema_version: null,
        code_version: null,
        data_version: null,
        preprocess_version: null,
        input_digest: null,
        created_by: member.actor_id,
        created_at: '2026-08-24T08:00:00Z',
      })
    }
    if (request.method() === 'GET' && path === '/api/v1/meta/capabilities') {
      return respond({ phase: 'local', available: ['api'], unavailable: ['ollama'] })
    }
    return respond({ detail: `Unexpected member portal request: ${request.method()} ${path}` }, 500)
  })
}

test('家庭成员进入前台，只看到自己的照护入口和已确认记录', async ({ page }) => {
  await installMemberApi(page)
  await page.goto('/')
  await page.getByLabel('开发身份标识').fill('grandma-account')
  await page.getByRole('button', { name: '进入家庭空间' }).click()

  await expect(page.locator('.app-frame')).toBeVisible()
  await expect(page.getByText('家庭成员前台', { exact: true })).toBeVisible()
  await expect(page.locator('.identity-chip')).not.toContainText('grandma-account')
  await expect(page.locator('aside.sidebar').getByRole('button', { name: '我的家庭' })).toBeVisible()
  await expect(page.locator('aside.sidebar').getByRole('button', { name: '拍照录药' })).toBeVisible()
  await expect(page.locator('aside.sidebar').getByRole('button', { name: '我的记录' })).toBeVisible()
  await expect(page.locator('aside.sidebar').getByRole('button', { name: '授权管理' })).toHaveCount(0)
  await expect(page.locator('aside.sidebar').getByRole('button', { name: '人工复核' })).toHaveCount(0)
  await expect(page.getByText('教学演示系统')).toHaveCount(0)
  await expect(page.getByRole('heading', { name: '需要留意的情况' })).toBeVisible()
  await expect(page.getByText('请和家庭管理员一起核对这条记录。')).toBeVisible()
  await expect(page.getByText('allergy_conflict')).toHaveCount(0)

  await page.evaluate(() => {
    localStorage.setItem('hct-vision-tasks:grandma-account', JSON.stringify(['member-task-1']))
  })
  await page.locator('aside.sidebar').getByRole('button', { name: '拍照录药', exact: true }).click()
  await expect(page.getByRole('heading', { name: '把药盒拍清楚就可以了' })).toBeVisible()
  await expect(page.getByText('正在识别', { exact: true })).toBeVisible()

  await page.locator('aside.sidebar').getByRole('button', { name: '我的记录', exact: true }).click()
  await expect(page.getByRole('heading', { name: '奶奶的健康记录' })).toBeVisible()
  await expect(page.getByText('药品：布洛芬缓释胶囊')).toBeVisible()
  await expect(page.getByText('这里只展示家庭管理员确认过的内容')).toBeVisible()
})
