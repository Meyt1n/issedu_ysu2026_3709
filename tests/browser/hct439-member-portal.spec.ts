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
          level: 'SEVERE',
          message: '请和家人一起核对这条记录',
          source_event_ids: ['event-confirmed-1'],
          created_at: '2026-08-24T08:00:00Z',
          rule_version: 'demo-rules-v1',
          risk_fingerprint: 'risk-fingerprint-1',
          acknowledgement: null,
        }],
        total: 1,
        severe_count: 1,
        warning_count: 0,
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
  await expect(page.getByText('家庭成员', { exact: true })).toBeVisible()
  await expect(page.locator('.identity-chip')).not.toContainText('grandma-account')
  await expect(page.locator('aside.sidebar').getByRole('button', { name: '我的家庭' })).toBeVisible()
  await expect(page.locator('aside.sidebar').getByRole('button', { name: '拍照录药' })).toBeVisible()
  await expect(page.locator('aside.sidebar').getByRole('button', { name: '我的记录' })).toBeVisible()
  await expect(page.locator('aside.sidebar').getByRole('button', { name: '使用帮助' })).toBeVisible()
  await expect(page.locator('aside.sidebar').getByRole('button', { name: '授权管理' })).toHaveCount(0)
  await expect(page.locator('aside.sidebar').getByRole('button', { name: '人工复核' })).toHaveCount(0)
  await expect(page.getByText('教学演示系统')).toHaveCount(0)
  await expect(page.getByRole('heading', { name: '需要留意的情况' })).toBeVisible()
  await expect(page.getByText('请和家人一起核对这条记录')).toBeVisible()
  await expect(page.getByText('不要自行停药或加药')).toBeVisible()
  await expect(page.getByText('重要', { exact: true })).toBeVisible()
  await expect(page.getByText('allergy_conflict')).toHaveCount(0)
  await expect(page.getByText('SEVERE')).toHaveCount(0)

  await page.evaluate(() => {
    localStorage.setItem('hct-vision-tasks:grandma-account', JSON.stringify(['member-task-1']))
  })
  await page.locator('aside.sidebar').getByRole('button', { name: '我的家庭', exact: true }).click()
  await expect(page.getByRole('heading', { name: '等待家人确认的照片' })).toBeVisible()
  await expect(page.getByText('正在看照片', { exact: true }).first()).toBeVisible()
  await page.locator('aside.sidebar').getByRole('button', { name: '拍照录药', exact: true }).click()
  await expect(page.getByRole('heading', { name: '把药盒拍清楚就可以了' })).toBeVisible()
  await expect(page.getByText('正在看照片', { exact: true }).first()).toBeVisible()

  await page.locator('aside.sidebar').getByRole('button', { name: '我的记录', exact: true }).click()
  await expect(page.getByRole('heading', { name: '奶奶的健康记录' })).toBeVisible()
  await expect(page.getByText('药品：布洛芬缓释胶囊')).toBeVisible()
  await expect(page.getByText('这里只展示家人确认过的内容')).toBeVisible()
})

/* ── HCT-439 阶段四/六：成员拍照 → 待确认 → 管理员确认 → 前台可见（mock API 全链路 UI 演示，
   不代表真实 OCR/复核后端已验收；后端交接由契约测试与 HCT-405 主线负责） ── */

const FAKE_SHA256 = 'a'.repeat(64)
const TINY_PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==',
  'base64',
)

interface CaptureFlowState {
  taskCreated: boolean
  taskStatus: 'queued' | 'succeeded'
  adminConfirmed: boolean
}

function captureTask(state: CaptureFlowState) {
  return {
    id: 'flow-task-1',
    household_id: household.id,
    member_id: member.id,
    file_id: 'flow-photo-1.png',
    task_type: 'ocr',
    status: state.taskStatus,
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
    input_digest: FAKE_SHA256,
    created_by: member.actor_id,
    created_at: '2026-08-25T08:00:00Z',
  }
}

async function installCaptureFlowApi(page: Page, state: CaptureFlowState): Promise<void> {
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
    if (request.method() === 'GET' && path === '/api/v1/meta/capabilities') {
      return respond({ phase: 'local', available: ['api'], unavailable: ['ollama'] })
    }
    if (request.method() === 'GET' && path.endsWith('/plan-workbench')) {
      return respond({ member_id: member.id, generated_at: '2026-08-25T08:00:00Z', plans: [] })
    }
    if (request.method() === 'GET' && path.endsWith('/risks')) {
      return respond({ member_id: member.id, alerts: [], total: 0, severe_count: 0, warning_count: 0 })
    }
    if (request.method() === 'GET' && path.endsWith('/timeline')) {
      // 管理员确认前，成员时间线不包含这张照片对应的健康事件。
      if (!state.adminConfirmed) return respond([])
      return respond([{
        id: 'event-flow-1',
        household_id: household.id,
        member_id: member.id,
        sequence_no: 1,
        event_type: 'medication_added',
        source: 'VISION_REVIEW',
        confirmation_status: 'CONFIRMED',
        payload: { drug: '阿司匹林肠溶片' },
        evidence: { vision_task_id: 'flow-task-1' },
        created_by: 'parent-admin',
        confirmed_by: 'parent-admin',
        occurred_at: '2026-08-25T09:00:00Z',
        recorded_at: '2026-08-25T09:00:00Z',
        correlation_id: 'corr-flow-1',
        created_at: '2026-08-25T09:00:00Z',
      }])
    }
    if (request.method() === 'POST' && path === '/api/v1/vision-quality/check') {
      return respond({
        schema_version: 'vision-quality-v1',
        config_version: 'mock-quality-v1',
        media_type: 'image',
        decision: 'PASS',
        allow_downstream: true,
        source: { source_id: 'source-1', sha256: FAKE_SHA256, digest_scope: 'file' },
        metrics: {},
        thresholds: {},
        reasons: [],
        retake_prompts: [],
        correction: null,
        frames: [],
        limitations: [],
        quality_receipt: 'receipt-'.padEnd(64, 'x'),
      })
    }
    if (request.method() === 'POST' && path === '/api/v1/files/upload') {
      return respond({
        original_name: 'flow-photo-1.png',
        storage_key: 'flow-photo-1.png',
        size_bytes: TINY_PNG.length,
        hash_algo: 'sha256',
        hash: FAKE_SHA256,
        extension: '.png',
      }, 201)
    }
    if (request.method() === 'POST' && path === '/api/v1/vision-tasks') {
      state.taskCreated = true
      return respond(captureTask(state), 201)
    }
    if (request.method() === 'GET' && path.endsWith('/vision-tasks')) {
      return respond(state.taskCreated ? [captureTask(state)] : [])
    }
    if (request.method() === 'GET' && path === '/api/v1/vision-tasks/flow-task-1') {
      return respond(captureTask(state))
    }
    return respond({ detail: `Unexpected capture flow request: ${request.method()} ${path}` }, 500)
  })
}

test('成员拍照提交后可见待确认状态，管理员确认后前台出现已确认记录', async ({ page }) => {
  const state: CaptureFlowState = { taskCreated: false, taskStatus: 'queued', adminConfirmed: false }
  await installCaptureFlowApi(page, state)
  await page.goto('/')
  await page.getByLabel('开发身份标识').fill('grandma-account')
  await page.getByRole('button', { name: '进入家庭空间' }).click()
  await expect(page.locator('.app-frame')).toBeVisible()

  // 成员提交照片：检查照片 → 交给家人。
  await page.locator('aside.sidebar').getByRole('button', { name: '拍照录药', exact: true }).click()
  await expect(page.getByRole('heading', { name: '把药盒拍清楚就可以了' })).toBeVisible()
  await page.locator('input[type="file"]').setInputFiles({
    name: 'flow-photo-1.png',
    mimeType: 'image/png',
    buffer: TINY_PNG,
  })
  await page.getByRole('button', { name: '检查照片' }).click()
  await expect(page.getByText('照片清楚，可以交给家人确认。')).toBeVisible()
  await page.getByRole('button', { name: '交给家人确认' }).click()
  await expect(page.getByRole('strong').filter({ hasText: '照片已交给家人' })).toBeVisible()

  // 待确认状态只出现生活化文案，不出现 OCR 原始结果或内部状态码。
  await expect(page.getByText('正在看照片', { exact: true }).first()).toBeVisible()
  await expect(page.locator('.member-capture-status')).not.toContainText('queued')
  await expect(page.locator('.member-capture-status')).not.toContainText('flow-task-1')

  // 本机识别完成 → 等待家人确认（轮询自动刷新）。
  state.taskStatus = 'succeeded'
  await expect(page.getByText('已交给家人，等待确认')).toBeVisible({ timeout: 15_000 })

  // 首页固定块同步展示待确认照片，无需进入拍照页。
  await page.locator('aside.sidebar').getByRole('button', { name: '我的家庭', exact: true }).click()
  await expect(page.getByRole('heading', { name: '等待家人确认的照片' })).toBeVisible()
  await expect(page.getByText('已交给家人，等待确认')).toBeVisible()

  // 模拟管理员在后台确认：时间线出现带 vision_task_id 证据的已确认事件。
  state.adminConfirmed = true
  await page.locator('aside.sidebar').getByRole('button', { name: '我的家庭', exact: true }).click()
  await page.locator('aside.sidebar').getByRole('button', { name: '拍照录药', exact: true }).click()
  await expect(page.getByText('家人已确认', { exact: true })).toBeVisible()
  await expect(page.getByText('家人已经核对过，药品信息已记进家庭本子。')).toBeVisible()

  // 成员在“我的记录”里看到确认后的药品，且没有任何后台技术词。
  await page.locator('aside.sidebar').getByRole('button', { name: '我的记录', exact: true }).click()
  await expect(page.getByText('药品：阿司匹林肠溶片')).toBeVisible()
  await expect(page.locator('.view-stage')).not.toContainText('OCR')
  await expect(page.locator('.view-stage')).not.toContainText('vision_task_id')
})
