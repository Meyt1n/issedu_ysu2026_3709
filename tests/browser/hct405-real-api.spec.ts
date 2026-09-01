import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

// HCT-405 real-API browser coverage: drive the current Vue portal against a locally
// running FastAPI backend with NO route mocks. Labels match the Chinese UI shipped
// with HCT-439/HCT-498 (正式账号密码 / Bearer 会话 / 侧栏导航).
//
// Prerequisites (see docs/stories/HCT-405-core-e2e.md):
//   1. alembic upgrade head
//   2. uvicorn app.main:app on :8000
//   3. REAL_API_E2E=1 npx playwright test tests/browser/hct405-real-api.spec.ts
//
// Skipped unless REAL_API_E2E=1 so default CI/browser jobs stay frontend-only.

const API_BASE = process.env.REAL_API_BASE ?? 'http://127.0.0.1:8000'

test.skip(!process.env.REAL_API_E2E, 'REAL_API_E2E is not set; skipping real-API browser coverage')

function runId(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

interface Bootstrap {
  ownerId: string
  ownerPassword: string
  ownerToken: string
  caregiverId: string
  caregiverPassword: string
  memberActorId: string
  memberPassword: string
  householdId: string
  memberId: string
  memberName: string
}

function navItem(page: Page, label: string) {
  return page.locator('aside.sidebar button.nav-item', { hasText: label })
}

async function enterFormalIdentity(page: Page, actorId: string, password: string): Promise<void> {
  await page.goto('/')
  await expect(page.getByRole('button', { name: '登录家庭空间' })).toBeVisible({ timeout: 20_000 })
  await page.getByLabel('正式账号', { exact: true }).fill(actorId)
  await page.getByLabel('密码', { exact: true }).fill(password)
  await page.getByRole('button', { name: '登录家庭空间' }).click()
  await expect(page.locator('.app-frame')).toBeVisible({ timeout: 20_000 })
}

async function provisionAccount(
  request: APIRequestContext,
  actorId: string,
  password: string,
): Promise<string> {
  const registered = await request.post(`${API_BASE}/api/v1/auth/register`, {
    data: { actor_id: actorId, password },
  })
  expect(registered.status(), `formal account ${actorId} must register`).toBe(201)
  const loggedIn = await request.post(`${API_BASE}/api/v1/auth/login`, {
    data: { actor_id: actorId, password },
  })
  expect(loggedIn.status(), `formal account ${actorId} must login`).toBe(200)
  return (await loggedIn.json()).session_token as string
}

async function bootstrapPortalHousehold(request: APIRequestContext, id: string): Promise<Bootstrap> {
  const ownerId = `e2e-owner-${id}`
  const caregiverId = `e2e-caregiver-${id}`
  const memberActorId = `e2e-member-${id}`
  const memberName = `合成成员 ${id}`
  const ownerPassword = `Owner-${id}-Pass!`
  const caregiverPassword = `Care-${id}-Pass!`
  const memberPassword = `Member-${id}-Pass!`
  const ownerToken = await provisionAccount(request, ownerId, ownerPassword)
  await provisionAccount(request, caregiverId, caregiverPassword)
  await provisionAccount(request, memberActorId, memberPassword)

  const householdResponse = await request.post(`${API_BASE}/api/v1/households`, {
    headers: { Authorization: `Bearer ${ownerToken}` },
    data: { name: `合成家庭 ${id}` },
  })
  expect(householdResponse.status(), 'household bootstrap must succeed').toBe(201)
  const household = await householdResponse.json()

  const memberResponse = await request.post(
    `${API_BASE}/api/v1/households/${household.id}/members`,
    {
      headers: { Authorization: `Bearer ${ownerToken}` },
      data: {
        display_name: memberName,
        role: 'DEPENDENT',
        actor_id: memberActorId,
      },
    },
  )
  expect(memberResponse.status(), 'member bootstrap must succeed').toBe(201)
  const member = await memberResponse.json()

  return {
    ownerId,
    ownerPassword,
    ownerToken,
    caregiverId,
    caregiverPassword,
    memberActorId,
    memberPassword,
    householdId: household.id,
    memberId: member.id,
    memberName,
  }
}

test('真实后端：授权 API 创建并撤回，审计链与服务端状态一致', async ({ request }) => {
  const id = runId()
  const scope = await bootstrapPortalHousehold(request, id)

  const grantResponse = await request.post(
    `${API_BASE}/api/v1/households/${scope.householdId}/authorizations`,
    {
      headers: { Authorization: `Bearer ${scope.ownerToken}` },
      data: {
        member_id: scope.memberId,
        grantee_actor_id: scope.caregiverId,
        data_fields: ['health_events'],
        actions: ['READ_EVENTS'],
        purpose: 'family-care',
        valid_until: new Date(Date.now() + 7 * 24 * 3600 * 1000).toISOString(),
      },
    },
  )
  expect(grantResponse.status()).toBe(201)
  const grant = await grantResponse.json()

  const revokeResponse = await request.post(
    `${API_BASE}/api/v1/households/${scope.householdId}/authorizations/${grant.id}/revoke`,
    { headers: { Authorization: `Bearer ${scope.ownerToken}` } },
  )
  expect(revokeResponse.status()).toBe(200)

  const auditResponse = await request.get(
    `${API_BASE}/api/v1/households/${scope.householdId}/authorization-audits`,
    { headers: { Authorization: `Bearer ${scope.ownerToken}` } },
  )
  expect(auditResponse.status()).toBe(200)
  const audits: Array<{ operation: string }> = await auditResponse.json()
  const operations = audits.map(item => item.operation)
  expect(operations).toContain('CREATE')
  expect(operations).toContain('REVOKE')

  const activeGrantsResponse = await request.get(
    `${API_BASE}/api/v1/households/${scope.householdId}/authorizations`,
    { headers: { Authorization: `Bearer ${scope.ownerToken}` } },
  )
  expect(activeGrantsResponse.status()).toBe(200)
  expect(await activeGrantsResponse.json()).toEqual([])
})

test('授权照护者进入成员前台且看不到后台入口；撤回后失去家庭可见性', async ({ page, request }) => {
  const id = runId()
  const scope = await bootstrapPortalHousehold(request, id)

  const grantResponse = await request.post(
    `${API_BASE}/api/v1/households/${scope.householdId}/authorizations`,
    {
      headers: { Authorization: `Bearer ${scope.ownerToken}` },
      data: {
        member_id: scope.memberId,
        grantee_actor_id: scope.caregiverId,
        data_fields: ['health_events'],
        actions: ['READ_EVENTS'],
        purpose: 'family-care',
        valid_until: new Date(Date.now() + 7 * 24 * 3600 * 1000).toISOString(),
      },
    },
  )
  expect(grantResponse.status()).toBe(201)
  const grant = await grantResponse.json()

  await enterFormalIdentity(page, scope.caregiverId, scope.caregiverPassword)
  await expect(page.getByText('家庭成员', { exact: true })).toBeVisible()
  await expect(navItem(page, '授权管理')).toHaveCount(0)
  await expect(page.getByText(scope.memberName)).toBeVisible()

  const revokeResponse = await request.post(
    `${API_BASE}/api/v1/households/${scope.householdId}/authorizations/${grant.id}/revoke`,
    {
      headers: { Authorization: `Bearer ${scope.ownerToken}` },
      data: { expected_version: grant.version },
    },
  )
  expect(revokeResponse.status()).toBe(200)

  await enterFormalIdentity(page, scope.caregiverId, scope.caregiverPassword)
  await expect(page.getByText(/还没有可见的家庭/)).toBeVisible()
})

test('绑定成员账号进入成员前台；已确认事件只出现在成员记录', async ({ page, request }) => {
  const id = runId()
  const scope = await bootstrapPortalHousehold(request, id)

  const eventResponse = await request.post(
    `${API_BASE}/api/v1/households/${scope.householdId}/events`,
    {
      headers: { Authorization: `Bearer ${scope.ownerToken}` },
      data: {
        member_id: scope.memberId,
        event_type: 'medication_added',
        source: 'MANUAL',
        confirmation_status: 'CONFIRMED',
        payload: { drug: '合成布洛芬' },
        idempotency_key: `e2e-portal-event-${id}`,
      },
    },
  )
  expect(eventResponse.status(), 'owner confirmed event must persist').toBe(201)

  await enterFormalIdentity(page, scope.memberActorId, scope.memberPassword)
  await expect(page.getByText('家庭成员', { exact: true })).toBeVisible()
  await expect(navItem(page, '人工复核')).toHaveCount(0)

  await navItem(page, '我的记录').click()
  await expect(page.getByRole('heading', { name: `${scope.memberName}的健康记录` })).toBeVisible()
  await expect(page.getByText('药品：合成布洛芬')).toBeVisible()
  await expect(page.getByText('这里只展示家人确认过的内容')).toBeVisible()
})

test('管理员确认过敏与药品后，成员前台显示需要留意的情况', async ({ page, request }) => {
  const id = runId()
  const scope = await bootstrapPortalHousehold(request, id)

  const allergy = await request.post(`${API_BASE}/api/v1/households/${scope.householdId}/events`, {
    headers: { Authorization: `Bearer ${scope.ownerToken}` },
    data: {
      member_id: scope.memberId,
      event_type: 'allergy_added',
      source: 'MANUAL',
      confirmation_status: 'CONFIRMED',
      payload: { allergy: 'aspirin' },
      idempotency_key: `e2e-allergy-${id}`,
    },
  })
  expect(allergy.status()).toBe(201)

  const drug = await request.post(`${API_BASE}/api/v1/households/${scope.householdId}/events`, {
    headers: { Authorization: `Bearer ${scope.ownerToken}` },
    data: {
      member_id: scope.memberId,
      event_type: 'medication_added',
      source: 'MANUAL',
      confirmation_status: 'CONFIRMED',
      payload: { drug: 'aspirin' },
      idempotency_key: `e2e-drug-${id}`,
    },
  })
  expect(drug.status()).toBe(201)

  await enterFormalIdentity(page, scope.memberActorId, scope.memberPassword)
  await expect(page.getByRole('heading', { name: '需要留意的情况' })).toBeVisible()
  await expect(page.getByText(/aspirin/i)).toBeVisible()
  await expect(page.getByText('请先问家人或医生')).toBeVisible()
  await expect(page.getByText('allergy_conflict')).toHaveCount(0)
  await expect(page.getByText('SEVERE')).toHaveCount(0)
})

test('未知正式账号看不到家庭与健康摘要', async ({ page, request }) => {
  const id = runId()
  const actorId = `e2e-stranger-${id}`
  const password = `Stranger-${id}-Pass!`
  await provisionAccount(request, actorId, password)
  await enterFormalIdentity(page, actorId, password)
  await expect(page.getByText(/还没有可见的家庭/)).toBeVisible()
  await expect(page.locator('.app-frame')).toHaveCount(0)
})
