import { describe, expect, it } from 'vitest'

import { ApiClientError } from '../api/client'
import { describeScenarioError, describeSeedError } from './demoLab'

describe('demo lab error layering (HCT-452)', () => {
  it('guides non-demo actors to a demo identity instead of blaming the API', () => {
    const forbidden = new ApiClientError('DEMO_SEED_FORBIDDEN', {
      status: 403,
      code: 'FORBIDDEN_MEMBER',
    })

    const message = describeSeedError(forbidden)
    expect(message).toContain('demo-parent')
    expect(message).toContain('无权补种')
    expect(message).not.toContain('本地 API 服务不可用')
  })

  it('keeps other 403 errors on the generic permission copy', () => {
    const otherForbidden = new ApiClientError('SOMETHING_ELSE', {
      status: 403,
      code: 'FORBIDDEN_MEMBER',
    })
    expect(describeSeedError(otherForbidden)).toBe('当前账号没有执行此操作的权限。')
  })

  it('surfaces true unavailability with actionable startup guidance', () => {
    const offline = new ApiClientError('API service is unavailable', {
      status: 0,
      code: 'DEPENDENCY_UNAVAILABLE',
    })

    const message = describeSeedError(offline)
    expect(message).toContain('本地 API 服务不可用，本次没有改变任何数据。')
    expect(message).toContain('8000')
  })

  it('prefixes scenario loading failures so they are not mistaken for seed failures', () => {
    const offline = new ApiClientError('API service is unavailable', {
      status: 0,
      code: 'DEPENDENCY_UNAVAILABLE',
    })

    const message = describeScenarioError(offline)
    expect(message).toContain('课堂剧本加载失败')
    expect(message).toContain('本地 API 服务不可用')
  })
})
