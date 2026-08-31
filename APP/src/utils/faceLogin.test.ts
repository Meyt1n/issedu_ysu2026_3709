import { describe, expect, it } from 'vitest'

import { faceLoginDisabledReason } from './faceLogin'

describe('刷脸登录 fail-closed 门控', () => {
  it('阈值未标定时始终关闭入口', () => {
    expect(faceLoginDisabledReason({ thresholdCalibrated: false })).toContain('阈值尚未完成现场标定')
  })

  it('设备不支持摄像头时回退到账号密码或 PIN', () => {
    expect(faceLoginDisabledReason({ thresholdCalibrated: true, cameraSupported: false })).toContain('账号密码或家庭 PIN')
  })

  it('拒绝摄像头权限时不重复索权并给出替代方式', () => {
    expect(faceLoginDisabledReason({ thresholdCalibrated: true, cameraPermission: 'denied' })).toContain('已停止刷脸流程')
  })

  it('所有前置条件满足时不产生阻断原因，供后续受控实现接入', () => {
    expect(faceLoginDisabledReason({ thresholdCalibrated: true, cameraSupported: true, cameraPermission: 'granted' })).toBe('')
  })
})
