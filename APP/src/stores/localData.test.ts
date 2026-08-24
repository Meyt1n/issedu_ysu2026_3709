import { beforeEach, describe, expect, it, vi } from 'vitest'

import { A11Y_STORAGE_KEY } from './accessibility'
import { clearLocalData, localDataInventory } from './localData'
import { PRIVACY_ACK_STORAGE_KEY } from './privacy'
import { SESSION_STORAGE_KEY } from './session'

describe('本地数据清单与清理（MOB-146）', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('清单区分"本机保存"与"不保存"，且覆盖凭据/能力快照/健康数据', () => {
    const items = localDataInventory()
    const saved = items.filter(item => item.saved).map(item => item.label)
    const notSaved = items.filter(item => !item.saved).map(item => item.label)

    expect(saved).toEqual(['联机设置与紧急联系人', '无障碍偏好', '隐私告知确认'])
    expect(notSaved.join()).toContain('会话凭据')
    expect(notSaved.join()).toContain('能力探测快照')
    expect(notSaved.join()).toContain('健康数据')
  })

  it('清理删除会话与无障碍键并保留隐私确认；结果如实列出', () => {
    localStorage.setItem(SESSION_STORAGE_KEY, '{}')
    localStorage.setItem(A11Y_STORAGE_KEY, '{}')
    localStorage.setItem(PRIVACY_ACK_STORAGE_KEY, '{"version":"x","acknowledgedAt":"y"}')

    const result = clearLocalData()

    expect(result.ok).toBe(true)
    expect(result.cleared).toEqual(['联机设置与紧急联系人', '无障碍偏好'])
    expect(localStorage.getItem(SESSION_STORAGE_KEY)).toBeNull()
    expect(localStorage.getItem(A11Y_STORAGE_KEY)).toBeNull()
    expect(localStorage.getItem(PRIVACY_ACK_STORAGE_KEY)).not.toBeNull()
  })

  it('removeItem 抛错时 fail-closed：不声称已删除，逐项列出失败', () => {
    localStorage.setItem(SESSION_STORAGE_KEY, '{}')
    const remover = vi.spyOn(localStorage, 'removeItem').mockImplementation(() => {
      throw new DOMException('denied', 'SecurityError')
    })

    const result = clearLocalData()

    expect(result.ok).toBe(false)
    expect(result.failures).toHaveLength(2)
    expect(result.failures[0]).toContain('未删除')
    remover.mockRestore()
  })

  it('removeItem 无效果（键仍存在）时同样 fail-closed', () => {
    localStorage.setItem(SESSION_STORAGE_KEY, '{}')
    const remover = vi.spyOn(localStorage, 'removeItem').mockImplementation(() => {})

    const result = clearLocalData()

    expect(result.ok).toBe(false)
    expect(result.failures.some(message => message.includes('清理后仍存在'))).toBe(true)
    remover.mockRestore()
  })
})
