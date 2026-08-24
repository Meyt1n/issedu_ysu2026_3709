import { describe, expect, it } from 'vitest'

import { isValidPhoneNumber, normalizePhoneNumber } from './phone'

describe('紧急联系人号码校验', () => {
  it('保留国际区号并移除常见分隔符', () => {
    expect(normalizePhoneNumber('+86 138-0000-0000')).toBe('+8613800000000')
    expect(normalizePhoneNumber('0086 (138) 0000 0000')).toBe('+8613800000000')
  })

  it('接受本地号码和空值，拒绝注入内容与异常长度', () => {
    expect(normalizePhoneNumber('138 0000 0000')).toBe('13800000000')
    expect(normalizePhoneNumber('')).toBe('')
    expect(normalizePhoneNumber('tel:120')).toBeNull()
    expect(normalizePhoneNumber('123')).toBeNull()
    expect(normalizePhoneNumber('+00 13800000000')).toBeNull()
    expect(isValidPhoneNumber('13800000000')).toBe(true)
    expect(isValidPhoneNumber('not-a-number')).toBe(false)
  })
})
