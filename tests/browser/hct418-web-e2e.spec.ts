import { expect, test, type Page } from '@playwright/test'

const household = {
  id: 'e2e-household',
  name: 'Synthetic E2E household',
  created_by: 'e2e-owner',
  created_at: '2026-08-19T00:00:00Z',
}

const member = {
  id: 'e2e-member',
  household_id: household.id,
  display_name: 'Synthetic E2E member',
  role: 'SELF',
  actor_id: 'e2e-owner',
  created_at: '2026-08-19T00:00:00Z',
}

const candidate = {
  drug_name: 'Synthetic medicine',
  dosage: '0.25g',
  frequency: '每日一次',
  confidence: 0.94,
  evidence: ['ocr:drug-name'],
}

const visionTask = {
  id: 'e2e-vision-task',
  household_id: household.id,
  member_id: member.id,
  file_id: 'e2e-uploaded-image.png',
  task_type: 'ocr',
  status: 'succeeded',
  error_code: null,
  error_message: null,
  result: {
    schema_version: 'evidence-v1',
    source_sha256: 'a'.repeat(64),
    source_digest_scope: 'uploaded_file_bytes',
    evidence: [{
      id: 'ocr:drug-name', channel: 'ocr', original_value: 'Synthetic medicine',
      normalized_value: 'Synthetic medicine', region: null, confidence: 0.94,
      producer_version: 'synthetic-ocr-v1',
    }],
    barcodes: [],
    fields: [],
    master_candidates: [],
    missing_fields: [],
    findings: [],
    fusion_readiness: 'READY_FOR_FUSION',
    requires_human_confirmation: true,
    versions: { ocr: 'synthetic-ocr-v1' },
  },
  model_version: 'synthetic-yolo-v1',
  model_threshold: 0.25,
  schema_version: 'evidence-v1',
  code_version: 'synthetic-code-v1',
  data_version: 'synthetic-data-v1',
  preprocess_version: 'synthetic-preprocess-v1',
  input_digest: 'a'.repeat(64),
  created_by: 'e2e-owner',
  created_at: '2026-08-19T00:00:00Z',
}

function reviewTask(status: 'PENDING_REVIEW' | 'CONFIRMED' = 'PENDING_REVIEW') {
  return {
    id: 'e2e-review-task',
    vision_task_id: visionTask.id,
    household_id: household.id,
    member_id: member.id,
    status,
    fusion_status: 'MATCHED',
    candidates: status === 'PENDING_REVIEW' ? [candidate] : [],
    selected_candidate: status === 'CONFIRMED' ? candidate : null,
    manual_payload: null,
    model_version: 'synthetic-yolo-v1',
    rule_version: 'synthetic-rule-v1',
    version: status === 'CONFIRMED' ? 2 : 1,
    confirmed_by: status === 'CONFIRMED' ? 'e2e-owner' : null,
    confirmed_at: status === 'CONFIRMED' ? '2026-08-19T01:00:00Z' : null,
    created_at: '2026-08-19T00:00:00Z',
    updated_at: '2026-08-19T01:00:00Z',
  }
}

const document = {
  id: 'e2e-document',
  title: 'Synthetic care guide',
  source: 'Synthetic source',
  license: 'internal',
  version: '2026.08',
  content_hash: 'b'.repeat(64),
  permission_scope: {},
  status: 'active',
  effective_from: null,
  effective_until: null,
  created_by: 'e2e-owner',
  created_at: '2026-08-19T00:00:00Z',
}

const modelBinding = {
  id: 'e2e-binding',
  model_id: 'synthetic-model-v1',
  dataset_version: 'synthetic-dataset-v1',
  export_manifest_id: null,
  fixed_set_hash: 'c'.repeat(64),
  release_status: 'inactive',
  safety_thresholds: { map50: 0.8 },
  comparison_report_hash: null,
  approved_by: null,
  approved_at: null,
  revoked_by: null,
  revoked_at: null,
  created_by: 'e2e-owner',
  created_at: '2026-08-19T00:00:00Z',
  updated_at: '2026-08-19T00:00:00Z',
}

async function installSyntheticApi(page: Page, qualityDecision: 'PASS' | 'RETAKE' = 'PASS'): Promise<string[]> {
  const requests: string[] = []
  let currentReview = reviewTask()
  let documents: typeof document[] = []

  await page.route('**/api/v1/**', async route => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    requests.push(`${request.method()} ${path}`)

    const respond = (body: unknown, status = 200) => route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify(body),
    })

    if (request.method() === 'GET' && path === '/api/v1/households') return respond([household])
    if (request.method() === 'GET' && path.endsWith('/members')) return respond([member])
    if (request.method() === 'GET' && path.endsWith('/authorizations')) return respond([])
    if (request.method() === 'GET' && path === '/api/v1/meta/capabilities') {
      return respond({ phase: 'local', available: ['api'], unavailable: ['ollama'] })
    }
    if (request.method() === 'GET' && path.endsWith('/timeline')) return respond([])
    if (request.method() === 'GET' && path.endsWith('/state')) {
      return respond({ member_id: member.id, household_id: household.id, state: { events_count: currentReview.status === 'CONFIRMED' ? 1 : 0 }, last_event_id: null, last_sequence: 0, version: 1, state_hash: null, updated_at: '2026-08-19T00:00:00Z' })
    }
    if (request.method() === 'GET' && path.endsWith('/risks')) return respond({ member_id: member.id, alerts: [], total: 0, severe_count: 0, warning_count: 0 })
    if (request.method() === 'GET' && (path.endsWith('/plans') || path.endsWith('/tasks'))) return respond([])
    if (request.method() === 'GET' && path.startsWith('/api/v1/weather/')) return respond({ status: 'unavailable', cache_status: 'none', action_cards: [] })

    if (request.method() === 'POST' && path === '/api/v1/vision-quality/check') {
      return respond({
        schema_version: 'quality-v1', config_version: 'synthetic-quality-v1', media_type: 'image',
        decision: qualityDecision, allow_downstream: qualityDecision === 'PASS',
        source: { source_id: 'synthetic-file', sha256: 'a'.repeat(64), digest_scope: 'uploaded_file_bytes' },
        metrics: { sharpness: { value: 0.95, passed: qualityDecision === 'PASS', unit: 'score', threshold: { min: 0.8 } } },
        thresholds: { sharpness_min: 0.8 }, reasons: qualityDecision === 'PASS' ? [] : ['synthetic blur'],
        retake_prompts: qualityDecision === 'PASS' ? [] : ['请保持药盒平整并重新拍摄'], correction: null, frames: [],
        limitations: [], quality_receipt: qualityDecision === 'PASS' ? 'synthetic-quality-receipt' : null,
      })
    }
    if (request.method() === 'POST' && path === '/api/v1/files/upload') return respond({ original_name: 'package.png', storage_key: visionTask.file_id, size_bytes: 8, hash_algo: 'sha256', hash: 'a'.repeat(64), extension: '.png' }, 201)
    if (request.method() === 'DELETE' && path.includes('/files/')) return respond({ deleted: true })
    if (request.method() === 'POST' && path === '/api/v1/vision-tasks') return respond(visionTask, 201)
    if (request.method() === 'GET' && path === `/api/v1/vision-tasks/${visionTask.id}`) return respond(visionTask)
    if (request.method() === 'GET' && path.endsWith('/review-tasks')) return respond([currentReview])
    if (request.method() === 'POST' && path.endsWith('/confirm')) {
      currentReview = reviewTask('CONFIRMED')
      return respond(currentReview)
    }
    if (request.method() === 'POST' && path.endsWith('/correct')) return respond(currentReview)

    if (request.method() === 'GET' && path === '/api/v1/assistant/tools') return respond({ tools: [], count: 0 })
    if (request.method() === 'POST' && path === '/api/v1/assistant/chat') {
      return respond({
        answer: '根据本地合成证据，当前仅能确认需要人工核对。',
        sources: ['Synthetic care guide · 2026.08 · chunk-1'],
        citations: [{ document_id: document.id, version: document.version, chunk_id: 'chunk-1' }],
        suggested_questions: ['这条证据来自哪个版本？'], confidence: 'medium', escalate: false,
        degraded: false, degrade_reason: null, model: 'synthetic-model-v1', route: 'local',
      })
    }
    if (request.method() === 'GET' && path === '/api/v1/knowledge/documents') return respond(documents)
    if (request.method() === 'POST' && path === '/api/v1/knowledge/documents') {
      documents = [document]
      return respond(document, 201)
    }
    if (request.method() === 'POST' && path === '/api/v1/knowledge/retrieve') {
      return respond({ query: 'synthetic', results: [{ chunk_id: 'chunk-1', document_id: document.id, document_title: document.title, text: 'Synthetic evidence fragment', score: 0.91, locator: 'p1' }], total: 1, query_id: 'synthetic-query', degraded: false, degrade_reason: null })
    }
    if (request.method() === 'GET' && path === '/api/v1/model-version-bindings') return respond([modelBinding])
    if (request.method() === 'GET' && path === '/api/v1/meta/active-model-version') return respond({ active_model_version: 'config-synthetic-v0', source: 'config' })
    if (request.method() === 'GET' && path.endsWith('/comparison')) return respond({ binding_id: modelBinding.id, comparison_report_hash: null, model_id: modelBinding.model_id, dataset_version: modelBinding.dataset_version, fixed_set_hash: modelBinding.fixed_set_hash, safety_thresholds: modelBinding.safety_thresholds })
    if (request.method() === 'POST' && path.endsWith('/activate')) return respond({ detail: 'RELEASE_BLOCKED' }, 409)
    if (request.method() === 'POST' && path.endsWith('/rollback')) return respond({ ...modelBinding, release_status: 'revoked' })

    return respond([])
  })

  return requests
}

async function enterFamilySpace(page: Page): Promise<void> {
  await page.goto('/')
  await page.getByLabel('开发身份标识').fill('e2e-owner')
  await page.getByRole('button', { name: '进入家庭空间' }).click()
  await expect(page.locator('.app-frame')).toBeVisible()
}

function navItem(page: Page, label: string) {
  return page.locator('aside.sidebar button.nav-item', { hasText: label })
}

test('扫描质量门控到人工确认：候选不先写入健康事实', async ({ page }) => {
  const requests = await installSyntheticApi(page)
  await enterFamilySpace(page)
  await navItem(page, '视觉扫描').click()

  await page.locator('input[type=file]').setInputFiles({ name: 'package.png', mimeType: 'image/png', buffer: Buffer.from('synthetic') })
  await page.getByRole('button', { name: '检查图片质量' }).click()
  await expect(page.locator('.notice.ok[role="status"]')).toContainText('图片质量通过')
  await page.getByRole('button', { name: '通过并创建识别任务' }).click()
  await expect(page.getByText('本地识别任务已创建', { exact: true })).toBeVisible()
  expect(requests).toContain('POST /api/v1/vision-quality/check')
  expect(requests).toContain('POST /api/v1/vision-tasks')
  expect(requests.some(path => path.includes('/events'))).toBe(false)

  await navItem(page, '人工复核').click()
  await expect(page.getByText('识别结果仅为候选')).toBeVisible()
  await expect(page.getByText('Synthetic medicine')).toBeVisible()
  await page.getByRole('button', { name: '确认候选' }).click()
  await page.getByRole('button', { name: '提交' }).click()
  await expect(page.getByText(/确认候选「Synthetic medicine」/)).toBeVisible()
})

test('质量门控失败时不给下游上传和任务创建机会', async ({ page }) => {
  const requests = await installSyntheticApi(page, 'RETAKE')
  await enterFamilySpace(page)
  await navItem(page, '视觉扫描').click()
  await page.locator('input[type=file]').setInputFiles({ name: 'blur.png', mimeType: 'image/png', buffer: Buffer.from('synthetic') })
  await page.getByRole('button', { name: '检查图片质量' }).click()
  await expect(page.locator('.notice.warn[role="status"]')).toContainText('需要重新拍摄')
  await expect(page.getByRole('button', { name: '通过并创建识别任务' })).toHaveCount(0)
  expect(requests.some(path => path === 'POST /api/v1/files/upload')).toBe(false)
  expect(requests.some(path => path === 'POST /api/v1/vision-tasks')).toBe(false)
})

test('助手和知识文档链路显示本地依据，并保留受控检索结果', async ({ page }) => {
  await installSyntheticApi(page)
  await enterFamilySpace(page)

  await navItem(page, '知识文档').click()
  await page.locator('label.field').filter({ hasText: '标题' }).locator('input').fill('Synthetic care guide')
  await page.locator('label.field').filter({ hasText: '来源' }).locator('input').fill('Synthetic source')
  await page.locator('label.field').filter({ hasText: '正文（自动分块）' }).locator('textarea').fill('Synthetic evidence fragment')
  await page.getByRole('button', { name: '登记知识文档' }).click()
  await expect(page.getByText('Synthetic care guide')).toBeVisible()
  const retrievalCard = page.locator('section.card').filter({ hasText: '试试知识能否被找到' })
  await retrievalCard.locator('textarea').fill('synthetic')
  await retrievalCard.getByRole('button', { name: '检索' }).click()
  await expect(page.getByText('Synthetic evidence fragment')).toBeVisible()
  await expect(page.getByText('《Synthetic care guide》')).toBeVisible()

  await navItem(page, '本地助手').click()
  await expect(page.getByRole('heading', { name: '本地证据助手' })).toBeVisible()
  await page.locator('textarea[placeholder^="例如：最近的用药提醒"]').fill('这条证据依据什么？')
  await page.getByRole('button', { name: '发送' }).click()
  await expect(page.getByText('根据本地合成证据')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText(/依据：Synthetic care guide/)).toBeVisible()
  await expect(page.getByRole('button', { name: '这条证据来自哪个版本？' })).toBeVisible()
})

test('模型实验室展示发布阻断，不把候选版本伪装成已发布', async ({ page }) => {
  await installSyntheticApi(page)
  await enterFamilySpace(page)
  await navItem(page, '模型实验室').click()
  await expect(page.getByText('synthetic-model-v1')).toBeVisible()
  await expect(page.getByText('缺少对照报告')).toBeVisible()
  await page.getByRole('button', { name: '发布此版本' }).click()
  await expect(page.locator('.toast.error')).toContainText('数据已在其它位置被修改，请刷新后再试。')
  await expect(page.getByText('来自配置回退（无已发布绑定）')).toBeVisible()
})

test('离线时不进入家庭空间，也不渲染旧健康摘要', async ({ page }) => {
  await page.route('**/api/v1/households', route => route.abort('failed'))
  await page.goto('/')
  await page.getByLabel('开发身份标识').fill('e2e-owner')
  await page.getByRole('button', { name: '进入家庭空间' }).click()
  await expect(page.getByRole('alert')).toContainText('本地 API 服务不可用')
  await expect(page.locator('.app-frame')).toHaveCount(0)
  await expect(page.getByText('Synthetic E2E member')).toHaveCount(0)
})

test('空数据、未授权和服务异常都显示恢复入口', async ({ page }) => {
  await page.route('**/api/v1/households', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([]),
  }))
  await page.goto('/')
  await page.getByLabel('开发身份标识').fill('e2e-empty')
  await page.getByRole('button', { name: '进入家庭空间' }).click()
  await expect(page.getByRole('heading', { name: '创建你的家庭' })).toBeVisible()
  await expect(page.locator('.app-frame')).toHaveCount(0)

  await page.reload()
  await page.unroute('**/api/v1/households')
  await page.route('**/api/v1/households', async route => route.fulfill({
    status: 401,
    contentType: 'application/json',
    body: JSON.stringify({ detail: 'AUTH_REQUIRED' }),
  }))
  await page.getByLabel('开发身份标识').fill('e2e-unauthorized')
  await page.getByRole('button', { name: '进入家庭空间' }).click()
  await expect(page.getByRole('alert')).toContainText('需要先填写开发身份')

  await page.reload()
  await page.unroute('**/api/v1/households')
  await page.route('**/api/v1/households', async route => route.fulfill({
    status: 504,
    contentType: 'application/json',
    body: JSON.stringify({ detail: 'UPSTREAM_TIMEOUT' }),
  }))
  await page.getByLabel('开发身份标识').fill('e2e-timeout')
  await page.getByRole('button', { name: '进入家庭空间' }).click()
  await expect(page.getByRole('alert')).toContainText('请求未能完成')
})
