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
      return respond({ member_id: member.id, alerts: [], total: 0, severe_count: 0, warning_count: 0 })
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

test('owner creates a grant and revocation removes its visible caregiver scope', async ({ page }) => {
  await installSyntheticApi(page)
  await page.goto('/')

  await page.getByLabel('Development identity').fill('owner-1')
  await page.getByRole('button', { name: 'Load households' }).click()
  await expect(page.getByRole('heading', { name: 'Create grant' })).toBeVisible()

  await page.getByLabel('Caregiver identity', { exact: true }).fill('caregiver-1')
  await page.getByRole('button', { name: 'Create grant' }).click()
  await expect(page.getByText('Authorization created. The preview now reflects the new active scope.')).toBeVisible()

  await page.getByLabel('Preview caregiver identity').fill('caregiver-1')
  const previewPanel = page.locator('.preview-panel')
  await expect(previewPanel).toContainText('health_events')

  await page.getByRole('button', { name: 'Revoke' }).click()
  await expect(page.getByText('Authorization revoked. It is removed from the caregiver preview immediately.')).toBeVisible()
  await expect(page.getByText('No active fields are granted to this caregiver.')).toBeVisible()
})

test('unavailable local API does not render a household or health summary', async ({ page }) => {
  await page.route('**/api/v1/households', route => route.abort('failed'))
  await page.goto('/')

  await page.getByLabel('Development identity').fill('owner-1')
  await page.getByRole('button', { name: 'Load households' }).click()

  await expect(page.getByRole('alert')).toContainText('The local API is unavailable. No data was changed.')
  await expect(page.getByRole('heading', { name: 'Synthetic member' })).toHaveCount(0)
  await expect(page.getByText(/confirmed events/)).toHaveCount(0)
})

test('visible UI keeps the local-only and no-promotion safety boundary', async ({ page }) => {
  await page.goto('/')

  await expect(page.getByText('Local-only health data')).toBeVisible()
  await expect(page.locator('body')).not.toContainText(/buy medicine|purchase|online consultation|advertisement|commission/i)
})
