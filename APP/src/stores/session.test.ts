import { describe, expect, it } from 'vitest'

import { DEFAULT_SESSION, normalizeSession, sessionContextKey } from './session'

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

  it('启动时清理不可信服务器地址和联系人号码', () => {
    const session = normalizeSession({
      serverBaseUrl: 'http://example.com:8000',
      caregiverPhone: 'javascript:alert(1)',
    })
    expect(session.serverBaseUrl).toBe('')
    expect(session.caregiverPhone).toBe('')
  })

  it('身份、访问目的或服务器变化时会产生不同联机指纹', () => {
    const base = sessionContextKey({
      dataMode: 'live',
      serverBaseUrl: 'http://family.local',
      actorId: 'actor-a',
      accessPurpose: 'family-care',
    })
    expect(sessionContextKey({ dataMode: 'live', serverBaseUrl: 'http://family.local', actorId: 'actor-b', accessPurpose: 'family-care' })).not.toBe(base)
    expect(sessionContextKey({ dataMode: 'live', serverBaseUrl: 'http://family.local', actorId: 'actor-a', accessPurpose: 'other-purpose' })).not.toBe(base)
    expect(sessionContextKey({ dataMode: 'live', serverBaseUrl: 'http://other.local', actorId: 'actor-a', accessPurpose: 'family-care' })).not.toBe(base)
  })
})
