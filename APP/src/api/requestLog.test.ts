import { beforeEach, describe, expect, it } from 'vitest'

import { clearRequestTraces, recordRequestTrace, requestOutcomeLabel, requestTraces } from './requestLog'

describe('请求回执追踪（MOB-144）', () => {
  beforeEach(() => {
    clearRequestTraces()
  })

  it('记录条目并去除 URL query，空白 requestId 归一为 null', () => {
    recordRequestTrace({
      method: 'POST',
      path: '/api/v1/auth/pin?leak=1',
      outcome: 'client-error',
      status: 409,
      requestId: '  ',
    })

    const entries = requestTraces()
    expect(entries).toHaveLength(1)
    expect(entries[0]).toMatchObject({
      method: 'POST',
      path: '/api/v1/auth/pin',
      outcome: 'client-error',
      status: 409,
      requestId: null,
    })
    expect(entries[0]!.at).toBeTruthy()
  })

  it('只保留最近 30 条，新条目在前', () => {
    for (let i = 0; i < 35; i += 1) {
      recordRequestTrace({ method: 'GET', path: `/api/v1/x/${i}`, outcome: 'success', status: 200, requestId: `r${i}` })
    }
    const entries = requestTraces()
    expect(entries).toHaveLength(30)
    expect(entries[0]!.path).toBe('/api/v1/x/34')
    expect(entries[29]!.path).toBe('/api/v1/x/5')
  })

  it('写请求附带幂等键与回执对象；clear 后为空', () => {
    recordRequestTrace({
      method: 'POST',
      path: '/api/v1/households/h1/members/m1/plans/confirm',
      outcome: 'success',
      status: 200,
      requestId: 'req-1',
      idempotencyKey: 'confirm:p1',
      receiptId: 'event-9',
    })
    expect(requestTraces()[0]).toMatchObject({ idempotencyKey: 'confirm:p1', receiptId: 'event-9' })

    clearRequestTraces()
    expect(requestTraces()).toHaveLength(0)
  })

  it('结局标签覆盖全部枚举', () => {
    expect(requestOutcomeLabel('success')).toBe('成功')
    expect(requestOutcomeLabel('client-error')).toBe('被拒绝')
    expect(requestOutcomeLabel('server-error')).toBe('服务端错误')
    expect(requestOutcomeLabel('unreachable')).toBe('网络不可达')
    expect(requestOutcomeLabel('timeout')).toBe('超时')
  })
})
