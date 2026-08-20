import { describe, expect, it, vi } from 'vitest'

import { ApiClient } from './client'

describe('ApiClient authorization contract', () => {
  it('loads households and members through the shared identity headers', async () => {
    const requests: Array<{ url: string; headers: Headers }> = []
    const fetcher: typeof fetch = async (input, init) => {
      requests.push({ url: String(input), headers: new Headers(init?.headers) })
      return new Response(JSON.stringify([]), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      })
    }
    const client = new ApiClient({ baseUrl: 'http://local.test', fetcher })

    await client.listHouseholds({ actorId: 'owner', accessPurpose: 'family-care' })
    await client.listMembers('household-1', { actorId: 'owner', accessPurpose: 'family-care' })

    expect(requests.map(request => request.url)).toEqual([
      'http://local.test/api/v1/households',
      'http://local.test/api/v1/households/household-1/members',
    ])
    expect(requests[0]?.headers.get('X-Actor-Id')).toBe('owner')
    expect(requests[0]?.headers.get('X-Access-Purpose')).toBe('family-care')
    expect(requests[1]?.headers.get('Accept')).toBe('application/json')
  })

  it('preserves version conflict details for optimistic authorization edits', async () => {
    const fetcher: typeof fetch = async () =>
      new Response(
        JSON.stringify({
          error: {
            code: 'AUTHORIZATION_VERSION_CONFLICT',
            message: 'Authorization version changed',
            details: { expected_version: 1, actual_version: 2 },
            request_id: 'request-1',
          },
        }),
        { status: 409 },
      )
    const client = new ApiClient({ fetcher })

    await expect(
      client.updateAuthorization('household-1', 'authorization-1', {
        expected_version: 1,
        purpose: 'family-care',
      }),
    ).rejects.toMatchObject({
      status: 409,
      code: 'AUTHORIZATION_VERSION_CONFLICT',
      requestId: 'request-1',
    })
  })

  it('uses JSON credentials and keeps session tokens in the Authorization header', async () => {
    const requests: Array<{ url: string; init: RequestInit }> = []
    const client = new ApiClient({
      baseUrl: 'http://local.test',
      fetcher: async (input, init) => {
        requests.push({ url: String(input), init: init ?? {} })
        if (String(input).endsWith('/auth/login')) {
          return new Response(JSON.stringify({ actor_id: 'owner', session_token: 's'.repeat(40), expires_at: 123 }), { status: 200 })
        }
        return new Response(JSON.stringify({ status: 'logged_out' }), { status: 200 })
      },
    })

    const session = await client.login('owner', 'password-123')
    await client.logout(session.session_token)

    expect(requests[0]?.url).toBe('http://local.test/api/v1/auth/login')
    expect(requests[0]?.url).not.toContain('password-123')
    expect(JSON.parse(String(requests[0]?.init.body))).toEqual({ actor_id: 'owner', password: 'password-123' })
    expect(JSON.parse(String(requests[1]?.init.body))).toEqual({ session_token: 's'.repeat(40) })
  })

  it('prefers bearer session authentication and clears on a 401 callback', async () => {
    const headers: Headers[] = []
    const client = new ApiClient({
      fetcher: async (_input, init) => {
        headers.push(new Headers(init?.headers))
        return new Response(JSON.stringify({ detail: 'SESSION_INVALID' }), { status: 401 })
      },
    })
    const onUnauthorized = vi.fn()
    client.setUnauthorizedHandler(onUnauthorized)

    await expect(client.listHouseholds({ actorId: 'dev-actor', sessionToken: 's'.repeat(40) })).rejects.toMatchObject({ status: 401 })

    expect(headers[0]?.get('Authorization')).toBe(`Bearer ${'s'.repeat(40)}`)
    expect(headers[0]?.get('X-Actor-Id')).toBeNull()
    expect(onUnauthorized).toHaveBeenCalledOnce()
  })

  it('loads member risks and encodes a rule id for risk detail', async () => {
    const requests: string[] = []
    const fetcher: typeof fetch = async input => {
      requests.push(String(input))
      return new Response(JSON.stringify({
        member_id: 'member-1',
        alerts: [],
        total: 0,
        severe_count: 0,
        warning_count: 0,
      }), { status: 200 })
    }
    const client = new ApiClient({ baseUrl: 'http://local.test', fetcher })

    await client.listMemberRisks('household-1', 'member-1')
    await client.getRiskDetail('household-1', 'member-1', 'rule/with spaces')

    expect(requests).toEqual([
      'http://local.test/api/v1/households/household-1/members/member-1/risks',
      'http://local.test/api/v1/households/household-1/members/member-1/risks/rule%2Fwith%20spaces',
    ])
  })

  it('writes a risk acknowledgement with the idempotency header', async () => {
    const requests: Array<{ url: string; init: RequestInit }> = []
    const client = new ApiClient({
      baseUrl: 'http://local.test',
      fetcher: async (input, init) => {
        requests.push({ url: String(input), init: init ?? {} })
        return new Response(JSON.stringify({
          receipt_id: 'receipt-1',
          household_id: 'household-1',
          member_id: 'member-1',
          rule_id: 'expiry_check',
          rule_version: 'rules-v0',
          risk_fingerprint: 'a'.repeat(64),
          actor_id: 'owner',
          acknowledged_at: '2026-08-19T00:00:00Z',
          replayed: false,
        }), { status: 200 })
      },
    })

    await client.acknowledgeRisk(
      'household-1',
      'member-1',
      'expiry/check',
      { rule_version: 'rules-v0', risk_fingerprint: 'a'.repeat(64) },
      { actorId: 'owner', idempotencyKey: 'ack-1' },
    )

    expect(requests[0]?.url).toBe(
      'http://local.test/api/v1/households/household-1/members/member-1/risks/expiry%2Fcheck/acknowledge',
    )
    expect(requests[0]?.init.method).toBe('POST')
    expect(new Headers(requests[0]?.init.headers).get('Idempotency-Key')).toBe('ack-1')
  })

  it('loads the authorized member timeline through the API boundary', async () => {
    const fetcher: typeof fetch = async () => new Response(JSON.stringify([]), { status: 200 })
    const client = new ApiClient({ baseUrl: 'http://local.test', fetcher })
    const requests: string[] = []
    const recordingClient = new ApiClient({
      baseUrl: 'http://local.test',
      fetcher: async input => {
        requests.push(String(input))
        return fetcher(input)
      },
    })

    await client.listMemberTimeline('household-1', 'member-1')
    await recordingClient.listMemberTimeline('household-1', 'member-1')

    expect(requests).toEqual([
      'http://local.test/api/v1/households/household-1/members/member-1/timeline',
    ])
  })

  it('routes desktop workbenches, care-plan actions and rule run through the authorized API boundary', async () => {
    const requests: Array<{ url: string; method: string | undefined; headers: Headers }> = []
    const client = new ApiClient({
      baseUrl: 'http://local.test',
      fetcher: async (input, init) => {
        requests.push({
          url: String(input),
          method: init?.method,
          headers: new Headers(init?.headers),
        })
        return new Response(JSON.stringify([]), { status: 200 })
      },
    })
    const options = {
      actorId: 'caregiver',
      accessPurpose: 'family-care',
      idempotencyKey: 'e2e-plan-action-1',
    }

    await client.runMemberRules('household-1', 'member-1', options)
    await client.getPlanWorkbench('household-1', 'member-1', options)
    await client.getDashboardSummary('household-1', options)
    await client.confirmCarePlan('household-1', 'member-1', 'plan/1', options)
    await client.deferCarePlan('household-1', 'member-1', 'plan/1', 6, options)
    await client.skipCarePlan('household-1', 'member-1', 'plan/1', 'member declined', options)

    expect(requests.map(request => request.url)).toEqual([
      'http://local.test/api/v1/households/household-1/rules/run?member_id=member-1',
      'http://local.test/api/v1/households/household-1/members/member-1/plan-workbench',
      'http://local.test/api/v1/households/household-1/dashboard-summary',
      'http://local.test/api/v1/households/household-1/members/member-1/plans/confirm?plan_event_id=plan%2F1',
      'http://local.test/api/v1/households/household-1/members/member-1/plans/defer?plan_event_id=plan%2F1&delay_hours=6',
      'http://local.test/api/v1/households/household-1/members/member-1/plans/skip?plan_event_id=plan%2F1&reason=member%20declined',
    ])
    expect(requests.map(request => request.method)).toEqual(['POST', undefined, undefined, 'POST', 'POST', 'POST'])
    expect(requests.filter(request => request.method === 'POST').every(
      request => request.headers.get('Idempotency-Key') === 'e2e-plan-action-1',
    )).toBe(true)
  })

  it('uses browser multipart boundaries for quality checks and uploads', async () => {
    const requests: RequestInit[] = []
    const fetcher: typeof fetch = async (_input, init) => {
      requests.push(init ?? {})
      const body = init?.body as FormData
      const isQuality = body?.get('media_type') === 'image'
      return new Response(JSON.stringify(isQuality
        ? { decision: 'PASS', quality_receipt: 'receipt' }
        : { storage_key: 'stored.png', hash: 'a'.repeat(64), hash_algo: 'sha256' }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      })
    }
    const client = new ApiClient({ baseUrl: 'http://local.test', fetcher })
    const file = new File(['image'], 'box.png', { type: 'image/png' })

    await client.checkVisionQuality(file, { actorId: 'owner' })
    await client.uploadFile(file, { actorId: 'owner' })

    expect(requests).toHaveLength(2)
    for (const request of requests) {
      const headers = new Headers(request.headers)
      expect(headers.has('Content-Type')).toBe(false)
      expect(headers.get('X-Actor-Id')).toBe('owner')
      expect(request.body).toBeInstanceOf(FormData)
    }
  })

  it('converts a hung request into DEPENDENCY_UNAVAILABLE instead of pending forever', async () => {
    // 复现 dev 代理丢失响应的场景：fetch 永不 resolve，只能被超时信号中止。
    const fetcher: typeof fetch = (_input, init) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () => {
          reject(new DOMException('The operation was aborted.', 'AbortError'))
        })
      })
    const client = new ApiClient({ baseUrl: 'http://local.test', fetcher })

    await expect(
      client.listHouseholds({ actorId: 'owner', timeoutMs: 40 }),
    ).rejects.toMatchObject({
      status: 0,
      code: 'DEPENDENCY_UNAVAILABLE',
      message: expect.stringContaining('timed out'),
    })
  })

  it('propagates caller-initiated aborts without masking them as unavailability', async () => {
    const fetcher: typeof fetch = (_input, init) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () => {
          reject(new DOMException('The operation was aborted.', 'AbortError'))
        })
      })
    const client = new ApiClient({ baseUrl: 'http://local.test', fetcher })
    const controller = new AbortController()
    const pending = client.listHouseholds({ actorId: 'owner', signal: controller.signal })
    controller.abort()

    await expect(pending).rejects.toMatchObject({ name: 'AbortError' })
  })

  it('creates and cleans up vision tasks through encoded local API paths', async () => {
    const requests: Array<{ url: string; init: RequestInit }> = []
    const fetcher: typeof fetch = async (input, init) => {
      requests.push({ url: String(input), init: init ?? {} })
      return new Response(JSON.stringify({ deleted: true }), { status: 200 })
    }
    const client = new ApiClient({ baseUrl: 'http://local.test', fetcher })

    await client.createVisionTask({
      file_id: 'stored.png',
      member_id: 'member-1',
      quality_receipt: 'signed-receipt',
      idempotency_key: 'request-1',
    }, { actorId: 'owner' })
    await client.deleteUploadedFile('folder/name.png', { actorId: 'owner' })

    expect(requests[0]?.url).toBe('http://local.test/api/v1/vision-tasks')
    expect(requests[0]?.init.method).toBe('POST')
    expect(new Headers(requests[0]?.init.headers).get('Content-Type')).toBe('application/json')
    expect(requests[1]?.url).toBe('http://local.test/api/v1/files/folder%2Fname.png')
    expect(requests[1]?.init.method).toBe('DELETE')
  })

  it('requeues a failed vision task in place', async () => {
    const requests: Array<{ url: string; method: string | undefined }> = []
    const client = new ApiClient({
      baseUrl: 'http://local.test',
      fetcher: async (input, init) => {
        requests.push({ url: String(input), method: init?.method })
        return new Response(JSON.stringify({ status: 'queued' }), { status: 200 })
      },
    })

    await client.retryVisionTask('task/failed', { actorId: 'owner' })

    expect(requests).toEqual([{
      url: 'http://local.test/api/v1/vision-tasks/task%2Ffailed/retry',
      method: 'POST',
    }])
  })
})
