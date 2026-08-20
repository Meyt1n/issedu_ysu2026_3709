import { describe, expect, it } from 'vitest'

import {
  DEFAULT_SESSION,
  isDevActorEnabled,
  normalizeSession,
  sessionContextKey,
  setDevActorEnabledForTests,
} from './session'

describe('会话设置规范化', () => {
  it('异常输入回退默认值（演示模式 + 正式鉴权）', () => {
    expect(normalizeSession(null)).toEqual(DEFAULT_SESSION)
    expect(normalizeSession(42)).toEqual(DEFAULT_SESSION)
    expect(normalizeSession({ dataMode: 'cloud' }).dataMode).toBe('demo')
    expect(DEFAULT_SESSION.authMode).toBe('real')
  })

  it('保留合法的联机配置', () => {
    const session = normalizeSession({
      dataMode: 'live',
      serverBaseUrl: 'http://192.168.1.10:8000',
      authMode: 'dev-actor',
      actorId: 'dev-actor',
      caregiverPhone: '13800000000',
    })
    expect(session.dataMode).toBe('live')
    expect(session.serverBaseUrl).toBe('http://192.168.1.10:8000')
    expect(session.authMode).toBe('dev-actor')
    expect(session.actorId).toBe('dev-actor')
    expect(session.accessPurpose).toBe('family-care')
    expect(session.caregiverPhone).toBe('13800000000')
  })

  it('正式鉴权模式不保留开发期身份', () => {
    const session = normalizeSession({ dataMode: 'live', actorId: 'dev-actor' })
    expect(session.authMode).toBe('real')
    expect(session.actorId).toBe('')
  })

  it('未开启开发配置时已保存的 dev-actor 强制回退到正式鉴权', () => {
    expect(isDevActorEnabled()).toBe(true)
    setDevActorEnabledForTests(false)
    try {
      const session = normalizeSession({
        dataMode: 'live',
        authMode: 'dev-actor',
        actorId: 'dev-actor',
      })
      expect(session.authMode).toBe('real')
      expect(session.actorId).toBe('')
    } finally {
      setDevActorEnabledForTests(true)
    }
  })

  it('启动时清理不可信服务器地址和联系人号码', () => {
    const session = normalizeSession({
      serverBaseUrl: 'http://example.com:8000',
      caregiverPhone: 'javascript:alert(1)',
    })
    expect(session.serverBaseUrl).toBe('')
    expect(session.caregiverPhone).toBe('')
  })

  it('身份、访问目的、服务器或身份来源变化时会产生不同联机指纹', () => {
    const base = sessionContextKey({
      dataMode: 'live',
      serverBaseUrl: 'http://family.local',
      authMode: 'dev-actor',
      actorId: 'actor-a',
      accessPurpose: 'family-care',
    })
    expect(sessionContextKey({ dataMode: 'live', serverBaseUrl: 'http://family.local', authMode: 'dev-actor', actorId: 'actor-b', accessPurpose: 'family-care' })).not.toBe(base)
    expect(sessionContextKey({ dataMode: 'live', serverBaseUrl: 'http://family.local', authMode: 'dev-actor', actorId: 'actor-a', accessPurpose: 'other-purpose' })).not.toBe(base)
    expect(sessionContextKey({ dataMode: 'live', serverBaseUrl: 'http://other.local', authMode: 'dev-actor', actorId: 'actor-a', accessPurpose: 'family-care' })).not.toBe(base)
    expect(sessionContextKey({ dataMode: 'live', serverBaseUrl: 'http://family.local', authMode: 'real', actorId: 'actor-a', accessPurpose: 'family-care' })).not.toBe(base)
  })
})
