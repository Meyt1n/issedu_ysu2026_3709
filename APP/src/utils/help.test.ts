import { describe, expect, it } from 'vitest'

import { detectPhoneCapability, getHelpDialHref } from './help'

describe('求助拨号', () => {
  it('急救电话直接返回固定号码', () => {
    expect(getHelpDialHref('emergency')).toBe('tel:120')
  })

  it('家人电话去除空格并直接返回拨号地址', () => {
    expect(getHelpDialHref('caregiver', '138 0000 0000')).toBe('tel:13800000000')
    expect(getHelpDialHref('caregiver', '')).toBe('')
  })
  it('识别可拨号设备', () => {
    expect(detectPhoneCapability('Mozilla/5.0 (Windows NT 10.0; Win64; x64)')).toBe('unavailable')
    expect(detectPhoneCapability('Mozilla/5.0 (Linux; Android 14; Pixel)')).toBe('available')
  })
})
