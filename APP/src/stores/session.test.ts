import { describe, expect, it } from 'vitest'

import { DEFAULT_SESSION, normalizeSession } from './session'

describe('会话设置规范化', () => {
  it('异常输入回退默认值（演示模式）', () => {
    expect(normalizeSession(null)).toEqual(DEFAULT_SESSION)
    expect(normalizeSession(42)).toEqual(DEFAULT_SESSION)
    expect(normalizeSession({ dataMode: 'cloud' }).dataMode).toBe('demo')
  })

  it('保留合法的联机配置', () => {
    const session = normalizeSession({
      dataMode: 'live',
      serverBaseUrl: 'http://192.168.1.10:8000',
      actorId: 'dev-actor',
      caregiverPhone: '13800000000',
    })
    expect(session.dataMode).toBe('live')
    expect(session.serverBaseUrl).toBe('http://192.168.1.10:8000')
    expect(session.actorId).toBe('dev-actor')
    expect(session.accessPurpose).toBe('family-care')
    expect(session.caregiverPhone).toBe('13800000000')
  })
})
