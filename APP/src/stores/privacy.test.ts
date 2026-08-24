import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  PRIVACY_ACK_STORAGE_KEY,
  PRIVACY_NOTICE_VERSION,
  acknowledgePrivacyNotice,
  controlledWebHandoff,
  privacyNoticeRequired,
  privacyNoticeSpeechText,
  readPrivacyAck,
} from './privacy'

describe('版本化隐私告知与受控网页交接（MOB-146）', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('首次使用需要展示；确认后记录版本与时间', () => {
    expect(privacyNoticeRequired()).toBe(true)

    expect(acknowledgePrivacyNotice(new Date('2026-08-24T08:00:00Z'))).toBe(true)
    expect(privacyNoticeRequired()).toBe(false)
    const ack = readPrivacyAck()
    expect(ack).toMatchObject({ version: PRIVACY_NOTICE_VERSION, acknowledgedAt: '2026-08-24T08:00:00.000Z' })
  })

  it('隐私版本更新后再次展示；已读其他版本不算当前版本', () => {
    localStorage.setItem(PRIVACY_ACK_STORAGE_KEY, JSON.stringify({
      version: '2020-01-01.0',
      acknowledgedAt: '2020-01-01T00:00:00Z',
    }))
    expect(privacyNoticeRequired()).toBe(true)
  })

  it('确认写入失败时返回 false（不声称已确认，下次仍展示）', () => {
    const setter = vi.spyOn(localStorage, 'setItem').mockImplementation(() => {
      throw new DOMException('quota', 'QuotaExceededError')
    })
    expect(acknowledgePrivacyNotice()).toBe(false)
    expect(privacyNoticeRequired()).toBe(true)
    setter.mockRestore()
  })

  it('损坏的确认记录按未确认处理；告知可合成播报文本', () => {
    localStorage.setItem(PRIVACY_ACK_STORAGE_KEY, '{not-json')
    expect(privacyNoticeRequired()).toBe(true)

    const spoken = privacyNoticeSpeechText()
    expect(spoken).toContain('演示与联机模式')
    expect(spoken).toContain('健康数据边界')
  })

  it('只允许 HTTPS 服务器作为受控网页端交接入口', () => {
    expect(controlledWebHandoff('https://family.example.test/?token=ignored#privacy')).toBe('https://family.example.test')
    expect(controlledWebHandoff('http://192.168.1.10:8000')).toBe('')
    expect(controlledWebHandoff('')).toBe('/')
  })
})
