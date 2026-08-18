import { describe, expect, it } from 'vitest'

import { getHelpCallConfirmation } from './help'

describe('求助拨号确认文案', () => {
  it('急救电话包含安全边界和固定号码', () => {
    expect(getHelpCallConfirmation('emergency')).toMatchObject({
      href: 'tel:120',
      title: '确认拨打急救电话',
      confirmLabel: '确认拨打 120',
    })
    expect(getHelpCallConfirmation('emergency').description).toContain('不会判断病情')
  })

  it('家人电话去除空格并保留严重情况升级提示', () => {
    expect(getHelpCallConfirmation('caregiver', '138 0000 0000', '女儿 王芳')).toMatchObject({
      href: 'tel:13800000000',
      title: '确认联系家人',
    })
    expect(getHelpCallConfirmation('caregiver', '138 0000 0000', '女儿 王芳').description).toContain('120')
  })
})
