import { createHash } from 'node:crypto'

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

const sourceBytes = Buffer.from('synthetic-image')
const sourceHash = createHash('sha256').update(sourceBytes).digest('hex')

const visionResult = {
  schema_version: 'vision-result-v1',
  source_sha256: sourceHash,
  source_digest_scope: 'uploaded_file_bytes',
  evidence: [
    {
      id: 'yolo-1', channel: 'yolo', original_value: 'package', normalized_value: 'package',
      region: { x: 0.1, y: 0.1, width: 0.8, height: 0.8, coordinate_space: 'normalized' },
      confidence: 0.93, producer_version: 'yolo-v1',
    },
    {
      id: 'ocr-1', channel: 'ocr', original_value: 'Synthetic medicine', normalized_value: 'Synthetic medicine',
      region: null, confidence: 0.91, producer_version: 'ocr-v1',
    },
    {
      id: 'barcode-1', channel: 'barcode', original_value: '6900000000001', normalized_value: '6900000000001',
      region: null, confidence: 0.96, producer_version: 'barcode-v1',
    },
  ],
  barcodes: [],
  fields: [],
  master_candidates: [{ record_id: 'master-1', reasons: ['NAME_EXACT'] }],
  missing_fields: [],
  findings: [],
  fusion_readiness: 'REVIEW',
  requires_human_confirmation: true,
  versions: {
    vision_model_version: 'yolo-v1',
    ocr_engine_version: 'ocr-v1',
    barcode_decoder_version: 'barcode-v1',
    master_data_version: 'master-v1',
  },
}

const reviewTask = {
  id: 'review-1',
  vision_task_id: 'vision-1',
  household_id: household.id,
  member_id: member.id,
  status: 'PENDING_REVIEW',
  fusion_status: 'MATCHED',
  candidates: [{ drug_name: 'Synthetic medicine', confidence: 0.91, evidence: ['OCR 文本一致'] }],
  selected_candidate: null,
  manual_payload: null,
  model_version: 'yolo-v1',
  rule_version: 'fusion-v1',
  version: 1,
  confirmed_by: null,
  confirmed_at: null,
  created_at: '2026-08-18T00:00:00Z',
  updated_at: '2026-08-18T00:00:00Z',
}

async function installSyntheticApi(page: Page, terminal: 'failed' | 'succeeded'): Promise<{ calls: string[] }> {
  let taskStatus = 'queued'
  let listCalls = 0
  let reviewStatus = 'PENDING_REVIEW'
  const calls: string[] = []

  await page.route('**/api/v1/**', async route => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    calls.push(`${request.method()} ${path}`)
    const respond = (body: unknown, status = 200) => route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify(body),
    })

    if (request.method() === 'GET' && path === '/api/v1/households') return respond([household])
    if (request.method() === 'GET' && path.endsWith('/members')) return respond([member])
    if (request.method() === 'GET' && path.endsWith('/timeline')) return respond([])
    if (request.method() === 'GET' && path.endsWith('/state')) {
      return respond({ member_id: member.id, household_id: household.id, state: { events_count: 0 }, last_event_id: null, last_sequence: 0, version: 1, state_hash: null, updated_at: '2026-08-18T00:00:00Z' })
    }
    if (request.method() === 'GET' && path === '/api/v1/meta/capabilities') {
      return respond({ phase: 'local', available: ['api'], unavailable: ['ollama'] })
    }
    if (request.method() === 'GET' && path.endsWith('/risks')) {
      return respond({ member_id: member.id, alerts: [], total: 0, severe_count: 0, warning_count: 0 })
    }
    if (request.method() === 'GET' && path.endsWith('/review-tasks')) {
      return respond([{ ...reviewTask, status: reviewStatus }])
    }
    if (request.method() === 'GET' && path === '/api/v1/vision-tasks') {
      listCalls += 1
      if (listCalls > 1 && terminal === 'succeeded') taskStatus = 'succeeded'
      if (listCalls > 1 && terminal === 'failed') taskStatus = 'failed'
      return respond([{
        id: 'vision-1', household_id: 'system', member_id: member.id, file_id: 'stored.png', task_type: 'ocr',
        status: taskStatus,
        error_code: taskStatus === 'failed' ? 'MODEL_INFERENCE_ERROR' : null,
        error_message: taskStatus === 'failed' ? 'synthetic worker crashed' : null,
        error_detail: taskStatus === 'failed' ? {
          code: 'MODEL_INFERENCE_ERROR', message: 'synthetic worker crashed', retryable: true,
          next_action: '请确认 worker 正常运行后重新处理。',
        } : null,
        result: taskStatus === 'succeeded' ? visionResult : null,
        model_version: 'yolo-v1', model_threshold: 0.25, schema_version: 'vision-result-v1', code_version: 'hct-416',
        data_version: 'master-v1', preprocess_version: 'quality-v1', input_digest: sourceHash, created_by: 'owner-1', created_at: '2026-08-18T00:00:00Z',
      }])
    }
    if (request.method() === 'GET' && path === '/api/v1/vision-tasks/vision-1') {
      listCalls += 1
      if (listCalls > 1) taskStatus = terminal
      return respond({
        id: 'vision-1', household_id: 'system', member_id: member.id, file_id: 'stored.png', task_type: 'ocr',
        status: taskStatus,
        error_code: taskStatus === 'failed' ? 'MODEL_INFERENCE_ERROR' : null,
        error_message: taskStatus === 'failed' ? 'synthetic worker crashed' : null,
        error_detail: taskStatus === 'failed' ? {
          code: 'MODEL_INFERENCE_ERROR', message: 'synthetic worker crashed', retryable: true,
          next_action: '请确认 worker 正常运行后重新处理。',
        } : null,
        result: taskStatus === 'succeeded' ? visionResult : null,
        model_version: 'yolo-v1', model_threshold: 0.25, schema_version: 'vision-result-v1', code_version: 'hct-416',
        data_version: 'master-v1', preprocess_version: 'quality-v1', input_digest: sourceHash, created_by: 'owner-1', created_at: '2026-08-18T00:00:00Z',
      })
    }
    if (request.method() === 'POST' && path === '/api/v1/vision-quality/check') {
      return respond({
        schema_version: 'vision-quality-result-v1', config_version: 'quality-v1', media_type: 'image', decision: 'PASS', allow_downstream: true,
        source: { source_id: 'synthetic', sha256: sourceHash, digest_scope: 'uploaded_file_bytes' }, metrics: {}, thresholds: {}, reasons: [], retake_prompts: [], correction: null, frames: [], limitations: [], quality_receipt: 'r'.repeat(32),
      })
    }
    if (request.method() === 'POST' && path === '/api/v1/files/upload') {
      return respond({ original_name: 'box.png', storage_key: 'stored.png', size_bytes: sourceBytes.length, hash_algo: 'sha256', hash: sourceHash, extension: '.png' }, 201)
    }
    if (request.method() === 'POST' && path === '/api/v1/vision-tasks') {
      return respond({ id: 'vision-1', household_id: 'system', member_id: member.id, file_id: 'stored.png', task_type: 'ocr', status: 'queued', error_code: null, error_message: null, error_detail: null, result: null, model_version: null, model_threshold: null, schema_version: null, code_version: null, data_version: null, preprocess_version: 'quality-v1', input_digest: sourceHash, created_by: 'owner-1', created_at: '2026-08-18T00:00:00Z' }, 201)
    }
    if (request.method() === 'POST' && path === '/api/v1/vision-tasks/vision-1/retry') {
      taskStatus = 'queued'
      return respond({ id: 'vision-1', household_id: 'system', member_id: member.id, file_id: 'stored.png', task_type: 'ocr', status: 'queued', error_code: null, error_message: null, error_detail: null, result: null, model_version: 'yolo-v1', model_threshold: 0.25, schema_version: 'vision-result-v1', code_version: 'hct-416', data_version: 'master-v1', preprocess_version: 'quality-v1', input_digest: sourceHash, created_by: 'owner-1', created_at: '2026-08-18T00:00:00Z' })
    }
    if (request.method() === 'POST' && path.endsWith('/review-tasks/review-1/confirm')) {
      reviewStatus = 'CONFIRMED'
      return respond({ ...reviewTask, status: reviewStatus, selected_candidate: reviewTask.candidates[0], confirmed_by: 'owner-1', confirmed_at: '2026-08-18T01:00:00Z', version: 2 })
    }
    return respond({ detail: `Unexpected synthetic request: ${request.method()} ${path}` }, 500)
  })

  return { calls }
}

async function enterFamilySpace(page: Page): Promise<void> {
  await page.goto('/')
  await expect(page.getByRole('button', { name: '进入家庭空间' })).toBeVisible({ timeout: 20_000 })
  // The welcome page label differs slightly between development builds; both
  // labels refer to the same local identity field.
  await page.getByLabel(/(?:开发|调试)身份标识/).fill('owner-1')
  await page.getByRole('button', { name: '进入家庭空间' }).click()
  await expect(page.locator('.app-frame')).toBeVisible({ timeout: 20_000 })
}

async function createSyntheticTask(page: Page): Promise<void> {
  await page.locator('input[type="file"]').setInputFiles({ name: 'box.png', mimeType: 'image/png', buffer: sourceBytes })
  await page.getByRole('button', { name: '检查图片质量' }).click()
  await expect(page.getByText(/图片质量通过/)).toBeVisible()
  await page.getByRole('button', { name: /通过并创建识别任务/ }).click()
  await expect(page.getByText(/本地识别任务已创建/)).toBeVisible()
}

test('HCT-489 失败任务显示人话原因并支持原地重新处理', async ({ page }) => {
  const { calls } = await installSyntheticApi(page, 'failed')
  await enterFamilySpace(page)
  await page.getByRole('button', { name: '视觉扫描' }).click()
  await createSyntheticTask(page)

  const taskCard = page.locator('section.card').filter({ hasText: '本机创建的识别任务' }).last()
  await taskCard.getByRole('button', { name: '刷新' }).click()
  await expect(taskCard).toContainText('识别没有完成')
  await expect(taskCard).toContainText('这次识别过程中遇到了问题')
  await expect(taskCard).toContainText('请确认本地服务正常后点击“重新处理”')
  await expect(taskCard).not.toContainText('MODEL_INFERENCE_ERROR')
  await expect(taskCard).not.toContainText('synthetic worker crashed')
  await taskCard.getByRole('button', { name: '重新处理' }).click()
  await expect(page.getByText('任务已重新排队')).toBeVisible()
  expect(calls.filter(call => call.includes('/vision-tasks/vision-1/retry'))).toHaveLength(1)
})

test('识别完成进入复核，确认后只通过服务端状态刷新', async ({ page }) => {
  const { calls } = await installSyntheticApi(page, 'succeeded')
  await enterFamilySpace(page)
  await page.getByRole('button', { name: '视觉扫描' }).click()
  await createSyntheticTask(page)

  const taskCard = page.locator('section.card').filter({ hasText: '本机创建的识别任务' }).last()
  await taskCard.getByRole('button', { name: '刷新' }).click()
  await expect(page.locator('.view-stage h2.hero-greeting')).toHaveText('人工复核中心')
  await expect(page.getByText('Synthetic medicine')).toBeVisible()
  await expect(page.getByText('待复核药品')).toBeVisible()
  await page.getByRole('button', { name: '确认保存' }).first().click()
  await page.locator('form.review-panel-form').getByRole('button', { name: '确认保存' }).click()
  await expect(page.getByText(/已处理的复核/)).toBeVisible()
  expect(calls.some(call => call.includes('/review-tasks/review-1/confirm'))).toBe(true)
  expect(calls.some(call => call.includes('/health-events'))).toBe(false)
})
