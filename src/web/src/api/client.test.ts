import { describe, expect, it, vi } from 'vitest'

import { ApiClient, DEMO_SEED_TIMEOUT_MS, FACE_REQUEST_TIMEOUT_MS } from './client'

describe('ApiClient authorization contract', () => {
  it('registers face credentials as multipart without exposing secrets in the URL', async () => {
    const requests: Array<{ url: string; init: RequestInit }> = []
    const client = new ApiClient({
      baseUrl: 'http://local.test',
      fetcher: async (input, init) => {
        requests.push({ url: String(input), init: init ?? {} })
        return new Response(JSON.stringify({
          id: 'credential-1',
          household_id: 'household-1',
          actor_id: 'owner',
          algorithm_version: 'opencv-haar-grayscale-v1',
          feature_version: 'face-template-v1',
          credential_version: 1,
          consent_version: 'face-registration-consent-v1',
          status: 'ACTIVE',
          created_by: 'owner',
          consented_at: '2026-08-21T00:00:00Z',
          revoked_at: null,
          created_at: '2026-08-21T00:00:00Z',
        }), { status: 201 })
      },
    })
    const file = new File(['pixels'], 'face.png', { type: 'image/png' })

    await client.registerFaceCredential('household/1', file, {
      consent: true,
      targetActorId: 'owner',
      confirmationMethod: 'pin',
      confirmationCode: '123456',
    }, { sessionToken: 's'.repeat(40) })

    expect(requests[0]?.url).toBe('http://local.test/api/v1/households/household%2F1/face-credentials')
    expect(requests[0]?.url).not.toContain('123456')
    const headers = new Headers(requests[0]?.init.headers)
    expect(headers.get('Authorization')).toBe(`Bearer ${'s'.repeat(40)}`)
    expect(headers.get('Content-Type')).toBeNull()
    const body = requests[0]?.init.body as FormData
    expect(body.get('consent')).toBe('true')
    expect(body.get('confirmation_code')).toBe('123456')
    expect(body.get('file')).toBeInstanceOf(File)
  })

  it('encodes face credential list and delete paths', async () => {
    const requests: string[] = []
    const client = new ApiClient({
      baseUrl: 'http://local.test',
      fetcher: async input => {
        requests.push(String(input))
        return new Response(JSON.stringify([]), { status: 200 })
      },
    })
    await client.listFaceCredentials('household/1')
    await client.deleteFaceCredential('household/1', 'credential/1')
    expect(requests).toEqual([
      'http://local.test/api/v1/households/household%2F1/face-credentials',
      'http://local.test/api/v1/households/household%2F1/face-credentials/credential%2F1',
    ])
  })

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

  it('changes and recovers passwords through body-only credential requests', async () => {
    const requests: Array<{ url: string; init: RequestInit }> = []
    const client = new ApiClient({
      baseUrl: 'http://local.test',
      fetcher: async (input, init) => {
        requests.push({ url: String(input), init: init ?? {} })
        return new Response(JSON.stringify({
          actor_id: 'owner',
          household_id: 'household-1',
          session_token: 'n'.repeat(40),
          expires_at: 123,
        }), { status: 200 })
      },
    })

    await client.changePassword('current-password', 'new-password', {
      sessionToken: 's'.repeat(40),
      suppressUnauthorizedHandler: true,
    })
    await client.recoverPassword('owner', 'household-1', '042006', 'recovered-password')

    expect(requests[0]?.url).toBe('http://local.test/api/v1/auth/change-password')
    expect(requests[0]?.url).not.toContain('current-password')
    expect(new Headers(requests[0]?.init.headers).get('Authorization')).toBe(`Bearer ${'s'.repeat(40)}`)
    expect(JSON.parse(String(requests[0]?.init.body))).toEqual({
      current_password: 'current-password',
      new_password: 'new-password',
    })
    expect(requests[1]?.url).toBe('http://local.test/api/v1/auth/recover-password')
    expect(requests[1]?.url).not.toContain('042006')
    expect(JSON.parse(String(requests[1]?.init.body))).toEqual({
      actor_id: 'owner',
      household_id: 'household-1',
      pin: '042006',
      new_password: 'recovered-password',
    })
  })

  it('does not clear a live session when current-password confirmation fails', async () => {
    const client = new ApiClient({
      fetcher: async () =>
        new Response(JSON.stringify({ detail: 'AUTH_FAILED' }), { status: 401 }),
    })
    const onUnauthorized = vi.fn()
    client.setUnauthorizedHandler(onUnauthorized)

    await expect(client.changePassword('wrong-password', 'new-password', {
      sessionToken: 's'.repeat(40),
      suppressUnauthorizedHandler: true,
    })).rejects.toMatchObject({ status: 401 })

    expect(onUnauthorized).not.toHaveBeenCalled()
  })

  it('creates a face challenge and sends frames as multipart without URL secrets', async () => {
    const requests: Array<{ url: string; init: RequestInit }> = []
    const client = new ApiClient({
      baseUrl: 'http://local.test',
      fetcher: async (input, init) => {
        requests.push({ url: String(input), init: init ?? {} })
        if (String(input).endsWith('/face-challenge')) {
          return new Response(JSON.stringify({ challenge_id: 'c'.repeat(32), expires_at: 123 }), { status: 200 })
        }
        return new Response(JSON.stringify({ actor_id: 'owner', household_id: 'home', session_token: 's'.repeat(40), expires_at: 123 }), { status: 200 })
      },
    })
    const challenge = await client.createFaceChallenge('home/1', 'owner')
    const frame = new File(['frame'], 'frame.jpg', { type: 'image/jpeg' })
    const session = await client.loginWithFace('home/1', 'owner', challenge.challenge_id, [frame, frame])

    expect(session.household_id).toBe('home')
    expect(requests[0]?.url).toBe('http://local.test/api/v1/auth/face-challenge')
    expect(JSON.parse(String(requests[0]?.init.body))).toEqual({ household_id: 'home/1', actor_id: 'owner' })
    expect(requests[1]?.url).toBe('http://local.test/api/v1/auth/face-login')
    expect(requests[1]?.url).not.toContain(challenge.challenge_id)
    expect(new Headers(requests[1]?.init.headers).get('Content-Type')).toBeNull()
    const body = requests[1]?.init.body as FormData
    expect(body.getAll('frames')).toHaveLength(2)
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

  it('loads persistent member vision task status within the household scope', async () => {
    const requests: string[] = []
    const client = new ApiClient({
      baseUrl: 'http://local.test',
      fetcher: async input => {
        requests.push(String(input))
        return new Response('[]', { status: 200 })
      },
    })

    await client.listMemberVisionTasks('household/1', 'member 1')

    expect(requests).toEqual([
      'http://local.test/api/v1/households/household%2F1/vision-tasks?member_id=member%201',
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

  it('routes desktop workbenches, graph projection, care-plan actions and rule run through the authorized API boundary', async () => {
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
    await client.getRelationshipGraph('household-1', 'member-1', options)
    await client.getPlanWorkbench('household-1', 'member-1', options)
    await client.getDashboardSummary('household-1', options)
    await client.confirmCarePlan('household-1', 'member-1', 'plan/1', options)
    await client.deferCarePlan('household-1', 'member-1', 'plan/1', 6, options)
    await client.skipCarePlan('household-1', 'member-1', 'plan/1', 'member declined', options)
    await client.missCarePlan('household-1', 'member-1', 'plan/1', 'forgot', options)

    expect(requests.map(request => request.url)).toEqual([
      'http://local.test/api/v1/households/household-1/rules/run?member_id=member-1',
      'http://local.test/api/v1/households/household-1/members/member-1/relationship-graph',
      'http://local.test/api/v1/households/household-1/members/member-1/plan-workbench',
      'http://local.test/api/v1/households/household-1/dashboard-summary',
      'http://local.test/api/v1/households/household-1/members/member-1/plans/confirm?plan_event_id=plan%2F1',
      'http://local.test/api/v1/households/household-1/members/member-1/plans/defer?plan_event_id=plan%2F1&delay_hours=6',
      'http://local.test/api/v1/households/household-1/members/member-1/plans/skip?plan_event_id=plan%2F1&reason=member%20declined',
      'http://local.test/api/v1/households/household-1/members/member-1/plans/missed?plan_event_id=plan%2F1&reason=forgot',
    ])
    expect(requests.map(request => request.method)).toEqual(['POST', undefined, undefined, undefined, 'POST', 'POST', 'POST', 'POST'])
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

  it('converts a hung request into REQUEST_TIMEOUT instead of pending forever', async () => {
    // 复现 dev 代理丢失响应的场景：fetch 永不 resolve，只能被超时信号中止。
    // 超时必须与「连不上 API」区分：服务端可能仍在处理（HCT-424 误报根因）。
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
      code: 'REQUEST_TIMEOUT',
      message: expect.stringContaining('timed out'),
    })
  })

  it('classifies an empty-body 500 from the dev proxy as DEPENDENCY_UNAVAILABLE', async () => {
    // 复现 API 未启动的标准 dev 场景：Vite 代理对 ECONNREFUSED 返回 500 且响应体为空。
    const fetcher: typeof fetch = async () =>
      new Response('', { status: 500, headers: { 'content-type': 'text/plain' } })
    const client = new ApiClient({ baseUrl: 'http://local.test', fetcher })

    await expect(
      client.seedFormalDemoHealth({ actorId: 'demo-parent' }),
    ).rejects.toMatchObject({
      status: 500,
      code: 'DEPENDENCY_UNAVAILABLE',
    })
  })

  it('classifies an nginx 502 gateway page as DEPENDENCY_UNAVAILABLE', async () => {
    const fetcher: typeof fetch = async () =>
      new Response('<html><body>502 Bad Gateway</body></html>', {
        status: 502,
        headers: { 'content-type': 'text/html' },
      })
    const client = new ApiClient({ baseUrl: 'http://local.test', fetcher })

    await expect(
      client.listClassroomScenarios({ actorId: 'demo-parent' }),
    ).rejects.toMatchObject({
      status: 502,
      code: 'DEPENDENCY_UNAVAILABLE',
    })
  })

  it('keeps real backend 5xx errors distinct from gateway unavailability', async () => {
    // FastAPI 崩溃返回带正文的 500，业务降级返回 JSON 信封的 503：都不是「API 未启动」。
    const crashClient = new ApiClient({
      baseUrl: 'http://local.test',
      fetcher: async () =>
        new Response('Internal Server Error', {
          status: 500,
          headers: { 'content-type': 'text/plain' },
        }),
    })
    await expect(crashClient.listHouseholds({ actorId: 'owner' })).rejects.toMatchObject({
      status: 500,
      code: 'HTTP_ERROR',
    })

    const degradedClient = new ApiClient({
      baseUrl: 'http://local.test',
      fetcher: async () =>
        new Response(JSON.stringify({ detail: 'FACE_AUTH_UNAVAILABLE' }), { status: 503 }),
    })
    await expect(degradedClient.listHouseholds({ actorId: 'owner' })).rejects.toMatchObject({
      status: 503,
      message: 'FACE_AUTH_UNAVAILABLE',
    })
  })

  it('applies the extended idempotent-seed timeout but honours caller overrides', async () => {
    // 补种默认超时必须高于普通请求（种子 20+ 事件且幂等可重试），
    // 同时调用方仍可为测试/特殊场景显式覆盖。
    expect(DEMO_SEED_TIMEOUT_MS).toBeGreaterThan(15_000)

    const fetcher: typeof fetch = (_input, init) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () => {
          reject(new DOMException('The operation was aborted.', 'AbortError'))
        })
      })
    const client = new ApiClient({ baseUrl: 'http://local.test', fetcher })

    await expect(
      client.seedFormalDemoHealth({ actorId: 'demo-parent', timeoutMs: 40 }),
    ).rejects.toMatchObject({
      status: 0,
      code: 'REQUEST_TIMEOUT',
      message: 'API request timed out after 40ms',
    })
  })

  it('keeps DEPENDENCY_UNAVAILABLE for connection failures that are not timeouts', async () => {
    const fetcher: typeof fetch = async () => {
      throw new TypeError('Failed to fetch')
    }
    const client = new ApiClient({ baseUrl: 'http://local.test', fetcher })

    await expect(client.listHouseholds({ actorId: 'owner' })).rejects.toMatchObject({
      status: 0,
      code: 'DEPENDENCY_UNAVAILABLE',
      message: 'API service is unavailable',
    })
  })

  it('gives face register and login multipart calls the longer face timeout', async () => {
    // HCT-424：人脸三帧请求首次可能触发服务端模型下载，默认 15 秒会误中止
    // 并显示「本地 API 不可用」；这里只放宽人脸调用，其它请求保持默认。
    const timeoutSpy = vi.spyOn(AbortSignal, 'timeout')
    try {
      const fetcher: typeof fetch = async input => new Response(
        JSON.stringify(String(input).includes('face-credentials')
          ? { id: 'credential-1', status: 'ACTIVE' }
          : { actor_id: 'owner', household_id: 'home', session_token: 's'.repeat(40), expires_at: 123 }),
        { status: String(input).includes('face-credentials') ? 201 : 200 },
      )
      const client = new ApiClient({ baseUrl: 'http://local.test', fetcher })
      const frame = new File(['frame'], 'frame.jpg', { type: 'image/jpeg' })

      await client.registerFaceCredential('home-1', [frame, frame, frame], {
        consent: true,
        confirmationMethod: 'pin',
        confirmationCode: '123456',
      }, { sessionToken: 's'.repeat(40) })
      await client.loginWithFace('home-1', 'owner', 'c'.repeat(32), [frame, frame])
      await client.loginWithFamilyFace('home-1', 'c'.repeat(32), [frame, frame])
      await client.listHouseholds({ actorId: 'owner' })

      expect(timeoutSpy.mock.calls.map(call => call[0])).toEqual([
        FACE_REQUEST_TIMEOUT_MS,
        FACE_REQUEST_TIMEOUT_MS,
        FACE_REQUEST_TIMEOUT_MS,
        15_000,
      ])
    } finally {
      timeoutSpy.mockRestore()
    }
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

  it('sends household-scoped PIN credentials and uses the bearer session for PIN setup', async () => {
    const requests: Array<{ url: string; init: RequestInit }> = []
    const client = new ApiClient({
      baseUrl: 'http://local.test',
      fetcher: async (input, init) => {
        requests.push({ url: String(input), init: init ?? {} })
        const response = String(input).endsWith('/auth/pin-login')
          ? { actor_id: 'owner', household_id: 'household-1', session_token: 's'.repeat(40), expires_at: 123 }
          : { status: 'pin_configured', household_id: 'household-1' }
        return new Response(JSON.stringify(response), { status: 200 })
      },
    })

    const loggedIn = await client.loginWithPin('household-1', 'owner', '042006')
    await client.setPin('household-1', '042006', { sessionToken: loggedIn.session_token })
    await client.setPin('household-1', '135790', { sessionToken: loggedIn.session_token }, 'grandma')

    expect(JSON.parse(String(requests[0]?.init.body))).toEqual({
      household_id: 'household-1',
      actor_id: 'owner',
      pin: '042006',
    })
    expect(new Headers(requests[1]?.init.headers).get('Authorization')).toBe(`Bearer ${'s'.repeat(40)}`)
    expect(JSON.parse(String(requests[1]?.init.body))).toEqual({ household_id: 'household-1', pin: '042006' })
    expect(JSON.parse(String(requests[2]?.init.body))).toEqual({
      household_id: 'household-1',
      pin: '135790',
      actor_id: 'grandma',
    })
  })

  it('lists which household logins already have a PIN without sending a PIN', async () => {
    const client = new ApiClient({
      baseUrl: 'http://local.test',
      fetcher: async input => {
        expect(String(input)).toBe('http://local.test/api/v1/households/home%2F1/pin-status')
        return new Response(
          JSON.stringify({ household_id: 'home/1', configured_actor_ids: ['owner', 'grandma'] }),
          { status: 200 },
        )
      },
    })

    await expect(client.listPinStatus('home/1', { sessionToken: 's'.repeat(40) })).resolves.toEqual({
      household_id: 'home/1',
      configured_actor_ids: ['owner', 'grandma'],
    })
  })
})

describe('ApiClient assistant UX operations', () => {
  it('parses evidence previews before the final streamed response', async () => {
    const encoder = new TextEncoder()
    const previews: unknown[] = []
    let requestBody: Record<string, unknown> = {}
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode(
          'event: evidence_preview\ndata: {"query_type":"MEDICATION_SAFETY","database_tools":["get_member_state"],"knowledge_titles":["审核资料"],"knowledge_count":1,"external_count":0,"rule_tools":["get_applied_rules"]}\n\n',
        ))
        controller.enqueue(encoder.encode(
          'event: done\ndata: {"response":{"answer":"已核对","sources":[],"confidence":"high","escalate":false,"degraded":false,"degrade_reason":null}}\n\n',
        ))
        controller.close()
      },
    })
    const client = new ApiClient({
      baseUrl: 'http://local.test',
      fetcher: async (_input, init) => {
        requestBody = JSON.parse(String(init?.body))
        return new Response(stream, {
          status: 200,
          headers: { 'content-type': 'text/event-stream' },
        })
      },
    })

    const reply = await client.assistantChatStream(
      {
        messages: [{ role: 'user', content: '请核对用药安全' }],
        agent_mode: 'multi_agent',
        assistant_session_id: 'session-1',
      },
      { onEvidencePreview: preview => previews.push(preview) },
    )

    expect(requestBody.assistant_session_id).toBe('session-1')
    expect(previews).toEqual([{
      query_type: 'MEDICATION_SAFETY',
      database_tools: ['get_member_state'],
      knowledge_titles: ['审核资料'],
      knowledge_count: 1,
      external_count: 0,
      rule_tools: ['get_applied_rules'],
    }])
    expect(reply.answer).toBe('已核对')
  })

  it('exposes a distinguishable cancellation without a completed response', async () => {
    const onCancelled = vi.fn()
    const encoder = new TextEncoder()
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('event: cancelled\ndata: {"code":"CANCELLED"}\n\n'))
        controller.close()
      },
    })
    const client = new ApiClient({
      baseUrl: 'http://local.test',
      fetcher: async () => new Response(stream, {
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
      }),
    })

    await expect(client.assistantChatStream(
      { messages: [{ role: 'user', content: '停止' }], agent_mode: 'multi_agent' },
      { onCancelled },
    )).rejects.toMatchObject({
      code: 'CANCELLED',
      message: expect.stringContaining('CANCELLED'),
    })
    expect(onCancelled).toHaveBeenCalledOnce()
  })

  it('loads query-free search metrics and clears one assistant session cache', async () => {
    const requests: Array<{ url: string; body: unknown }> = []
    const client = new ApiClient({
      baseUrl: 'http://local.test',
      fetcher: async (input, init) => {
        requests.push({
          url: String(input),
          body: init?.body ? JSON.parse(String(init.body)) : null,
        })
        return new Response(JSON.stringify(
          String(input).endsWith('/web-search/ops')
            ? {
                web_search_enabled: true,
                web_search_ready: true,
                web_search_provider: 'searxng',
                cache_ttl_seconds: 120,
                min_interval_seconds: 1,
                cache_entries: 2,
                cache_hits: 3,
                cache_misses: 1,
                cache_hit_rate: 0.75,
                rate_limited_hits: 0,
                searches: 1,
              }
            : { assistant_session_id: 'session-1', cleared_entries: 2 },
        ), { status: 200 })
      },
    })

    const snapshot = await client.getAssistantWebSearchOps()
    const cleared = await client.clearAssistantSessionCache('session-1')

    expect(snapshot.cache_hit_rate).toBe(0.75)
    expect(cleared.cleared_entries).toBe(2)
    expect(requests).toEqual([
      { url: 'http://local.test/api/v1/assistant/web-search/ops', body: null },
      {
        url: 'http://local.test/api/v1/assistant/session-cache/clear',
        body: { assistant_session_id: 'session-1' },
      },
    ])
  })
})
