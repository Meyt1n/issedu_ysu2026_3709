import { describe, expect, it } from 'vitest'

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

  it('routes the care-plan actions and rule run through the authorized API boundary', async () => {
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
    await client.confirmCarePlan('household-1', 'member-1', 'plan/1', options)
    await client.deferCarePlan('household-1', 'member-1', 'plan/1', 6, options)
    await client.skipCarePlan('household-1', 'member-1', 'plan/1', 'member declined', options)

    expect(requests.map(request => request.url)).toEqual([
      'http://local.test/api/v1/households/household-1/rules/run?member_id=member-1',
      'http://local.test/api/v1/households/household-1/members/member-1/plans/confirm?plan_event_id=plan%2F1',
      'http://local.test/api/v1/households/household-1/members/member-1/plans/defer?plan_event_id=plan%2F1&delay_hours=6',
      'http://local.test/api/v1/households/household-1/members/member-1/plans/skip?plan_event_id=plan%2F1&reason=member%20declined',
    ])
    expect(requests.map(request => request.method)).toEqual(['POST', 'POST', 'POST', 'POST'])
    expect(requests.every(request => request.headers.get('Idempotency-Key') === 'e2e-plan-action-1')).toBe(true)
  })
})
