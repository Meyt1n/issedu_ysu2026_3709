import { beforeEach, describe, expect, it } from 'vitest'

import { A11Y_STORAGE_KEY } from './accessibility'
import { clearLocalData, controlledWebHandoff, localStorageAvailable } from './privacy'
import { SESSION_STORAGE_KEY } from './session'

describe('移动端本地隐私清理', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('清除会话和无障碍持久配置，但不声称删除服务端事实', () => {
    localStorage.setItem(SESSION_STORAGE_KEY, '{"caregiverPhone":"13800000000"}')
    localStorage.setItem(A11Y_STORAGE_KEY, '{"elderMode":true}')

    expect(clearLocalData(localStorage)).toEqual({
      ok: true,
      message: '本机设置、联系人、服务器地址和运行时状态已清理；服务端健康事实未被修改。',
    })
    expect(localStorage.getItem(SESSION_STORAGE_KEY)).toBeNull()
    expect(localStorage.getItem(A11Y_STORAGE_KEY)).toBeNull()
  })

  it('存储不可用时返回失败，不虚报已删除', () => {
    const unavailable = {
      setItem: () => { throw new Error('blocked') },
      removeItem: () => { throw new Error('blocked') },
    } as unknown as Storage
    expect(localStorageAvailable(unavailable)).toBe(false)
    expect(clearLocalData(unavailable).ok).toBe(false)
  })

  it('只允许 HTTPS 服务器作为受控网页端交接入口', () => {
    expect(controlledWebHandoff('https://family.example.test/?token=ignored#privacy')).toBe('https://family.example.test')
    expect(controlledWebHandoff('http://192.168.1.10:8000')).toBe('')
    expect(controlledWebHandoff('')).toBe('/')
  })
})
