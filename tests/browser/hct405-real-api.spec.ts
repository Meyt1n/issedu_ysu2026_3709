import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

// HCT-405 real-API browser coverage: these tests drive the Vue frontend through
// the Vite proxy against a locally running FastAPI backend, with NO route mocks.
// All data is synthetic and namespaced per run; nothing is cleaned from other runs.
//
// Prerequisites (see docs/stories/HCT-405-core-e2e.md):
//   1. alembic upgrade head            (DATABASE_URL -> a disposable sqlite file)
//   2. uvicorn app.main:app on :8000   (PYTHONPATH=src/api;src)
//   3. REAL_API_E2E=1 npx playwright test tests/browser/hct405-real-api.spec.ts
//
// Without REAL_API_E2E the whole file is skipped so the default suite stays
// runnable in environments that only have the frontend toolchain.

const API_BASE = process.env.REAL_API_BASE ?? 'http://127.0.0.1:8000'

test.skip(!process.env.REAL_API_E2E, 'REAL_API_E2E is not set; skipping real-API browser coverage')

function runId(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

interface Bootstrap {
  ownerId: string
  caregiverId: string
  householdId: string
  memberId: string
  memberName: string
}

async function bootstrapHousehold(request: APIRequestContext, id: string): Promise<Bootstrap> {
  const ownerId = `e2e-owner-${id}`
  const caregiverId = `e2e-caregiver-${id}`
  const memberName = `Synthetic member ${id}`

  const householdResponse = await request.post(`${API_BASE}/api/v1/households`, {
    headers: { 'X-Actor-Id': ownerId },
    data: { name: `Synthetic household ${id}` },
  })
  expect(householdResponse.status(), 'household bootstrap must succeed').toBe(201)
  const household = await householdResponse.json()

  const memberResponse = await request.post(
    `${API_BASE}/api/v1/households/${household.id}/members`,
    {
      headers: { 'X-Actor-Id': ownerId },
      data: { display_name: memberName, role: 'SELF', actor_id: ownerId },
    },
  )
  expect(memberResponse.status(), 'member bootstrap must succeed').toBe(201)
  const member = await memberResponse.json()

  return { ownerId, caregiverId, householdId: household.id, memberId: member.id, memberName }
}

async function loadIdentity(page: Page, actorId: string): Promise<void> {
  await page.goto('/')
  await page.getByLabel('Development identity').fill(actorId)
  await page.getByRole('button', { name: 'Load households' }).click()
}

test('owner creates and revokes a grant; the API persists and audits every step', async ({ page, request }) => {
  const id = runId()
  const scope = await bootstrapHousehold(request, id)

  await loadIdentity(page, scope.ownerId)
  await expect(page.getByRole('heading', { name: 'Create grant' })).toBeVisible()

  await page.getByLabel('Caregiver identity', { exact: true }).fill(scope.caregiverId)
  await page.getByRole('button', { name: 'Create grant' }).click()
  await expect(
    page.getByText('Authorization created. The preview now reflects the new active scope.'),
  ).toBeVisible()

  // Reload: the grant must come back from the database, not from page state.
  await loadIdentity(page, scope.ownerId)
  await expect(page.getByRole('heading', { name: 'Create grant' })).toBeVisible()
  const grantRow = page.locator('.grant-row', { hasText: scope.caregiverId })
  await expect(grantRow).toContainText('health_events')

  await page.getByLabel('Preview caregiver identity').fill(scope.caregiverId)
  await expect(page.locator('.preview-panel')).toContainText('health_events')

  await grantRow.getByRole('button', { name: 'Revoke' }).click()
  await expect(
    page.getByText('Authorization revoked. It is removed from the caregiver preview immediately.'),
  ).toBeVisible()
  await expect(page.getByText('No active fields are granted to this caregiver.')).toBeVisible()

  // Locate the browser actions in the API audit trail (owner-only endpoint).
  const auditResponse = await request.get(
    `${API_BASE}/api/v1/households/${scope.householdId}/authorization-audits`,
    { headers: { 'X-Actor-Id': scope.ownerId } },
  )
  expect(auditResponse.status()).toBe(200)
  const audits: Array<{ operation: string; outcome: string }> = await auditResponse.json()
  const operations = audits.map(item => item.operation)
  expect(operations).toContain('CREATE')
  expect(operations).toContain('REVOKE')
})

test('a caregiver only sees the granted member scope, and revocation removes the household', async ({ page, request }) => {
  const id = runId()
  const scope = await bootstrapHousehold(request, id)

  const grantResponse = await request.post(
    `${API_BASE}/api/v1/households/${scope.householdId}/authorizations`,
    {
      headers: { 'X-Actor-Id': scope.ownerId },
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

  await loadIdentity(page, scope.caregiverId)
  await expect(
    page.getByText('Caregiver view: the API has already filtered this identity to the granted member scope.'),
  ).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Members available to this identity' })).toBeVisible()
  await expect(page.locator('.member-list')).toContainText(scope.memberName)
  // The owner-only grant editor must never render for a caregiver.
  await expect(page.getByRole('heading', { name: 'Create grant' })).toHaveCount(0)

  const revokeResponse = await request.post(
    `${API_BASE}/api/v1/households/${scope.householdId}/authorizations/${grant.id}/revoke`,
    {
      headers: { 'X-Actor-Id': scope.ownerId },
      data: { expected_version: grant.version },
    },
  )
  expect(revokeResponse.status()).toBe(200)

  await loadIdentity(page, scope.caregiverId)
  await expect(page.getByText('No household is visible to this identity.')).toBeVisible()
})

test('a confirmed manual event reaches the dashboard projection and timeline', async ({ page, request }) => {
  const id = runId()
  const scope = await bootstrapHousehold(request, id)

  const eventResponse = await request.post(
    `${API_BASE}/api/v1/households/${scope.householdId}/events`,
    {
      headers: { 'X-Actor-Id': scope.ownerId },
      data: {
        member_id: scope.memberId,
        event_type: 'WATER_INTAKE',
        source: 'MANUAL',
        confirmation_status: 'CONFIRMED',
        payload: { note: 'synthetic e2e evidence' },
        idempotency_key: `e2e-event-${id}`,
      },
    },
  )
  expect(eventResponse.status(), 'confirmed manual event must be accepted').toBe(201)

  await loadIdentity(page, scope.ownerId)
  await expect(page.getByText('1 confirmed events')).toBeVisible()
  const timeline = page.locator('.timeline-list')
  await expect(timeline).toContainText('WATER_INTAKE')
  await expect(timeline).toContainText('CONFIRMED')

  // Rule evaluation runs against the real rules engine and must not error.
  await page.getByRole('button', { name: 'Re-evaluate' }).click()
  await expect(page.getByText(/Risk evaluation completed\. \d+ signals? returned\./)).toBeVisible()
})

test('an unknown identity is shown no household and no health data', async ({ page }) => {
  await loadIdentity(page, `e2e-stranger-${runId()}`)
  await expect(page.getByText('No household is visible to this identity.')).toBeVisible()
  await expect(page.getByText(/confirmed events/)).toHaveCount(0)
})
