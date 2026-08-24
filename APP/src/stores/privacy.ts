import { clearRequestTraces } from '@/api/requestLog'
import { resetAccessibility, A11Y_STORAGE_KEY } from '@/stores/accessibility'
import { requireReauth } from '@/stores/auth'
import { clearCapabilities } from '@/stores/capabilities'
import { resetSession, SESSION_STORAGE_KEY, useSession } from '@/stores/session'

export const PRIVACY_NOTICE_VERSION = '2026-08-24'

export interface LocalDataEntry {
  id: 'accessibility' | 'session' | 'runtime'
  label: string
  detail: string
  persistence: '本机持久化' | '仅当前运行时'
  sensitive: boolean
}

export const LOCAL_DATA_ENTRIES: readonly LocalDataEntry[] = [
  {
    id: 'accessibility',
    label: '无障碍偏好',
    detail: '长辈模式、字号、主题、高对比度、语音和动效设置。',
    persistence: '本机持久化',
    sensitive: false,
  },
  {
    id: 'session',
    label: '会话配置',
    detail: '演示/联机模式、服务器地址、访问目的、当前家庭/成员标识和紧急联系人。',
    persistence: '本机持久化',
    sensitive: true,
  },
  {
    id: 'runtime',
    label: '运行时状态',
    detail: '能力快照、Provider 缓存、请求回执和上传草稿；不写入本机持久存储。',
    persistence: '仅当前运行时',
    sensitive: true,
  },
]

export interface LocalDataClearResult {
  ok: boolean
  message: string
}

export function localStorageAvailable(storage: Storage | undefined = typeof localStorage === 'undefined' ? undefined : localStorage): boolean {
  if (!storage) return false
  try {
    const probe = 'hct-mobile.storage-probe'
    storage.setItem(probe, '1')
    storage.removeItem(probe)
    return true
  } catch {
    return false
  }
}

/** 清理移动端本地配置和当前运行时，不触碰服务端健康事实。 */
export function clearLocalData(storage: Storage | undefined = typeof localStorage === 'undefined' ? undefined : localStorage): LocalDataClearResult {
  const storageReady = localStorageAvailable(storage)

  // 先清内存状态和响应式状态；reset* 会短暂写默认值，之后再移除持久 key。
  resetSession()
  resetAccessibility()
  clearCapabilities()
  clearRequestTraces()
  requireReauth('signed-out')

  if (!storageReady || !storage) {
    return { ok: false, message: '本机存储不可用；运行时状态已清理，但应用不能声称持久设置已删除。' }
  }

  try {
    storage.removeItem(SESSION_STORAGE_KEY)
    storage.removeItem(A11Y_STORAGE_KEY)
    return { ok: true, message: '本机设置、联系人、服务器地址和运行时状态已清理；服务端健康事实未被修改。' }
  } catch {
    return { ok: false, message: '本机设置清理未能完成；为保护隐私，应用不会声称已删除，请关闭应用后重试。' }
  }
}

export function controlledWebHandoff(baseUrl: string): string {
  const trimmed = baseUrl.trim()
  if (!trimmed) return '/'
  try {
    const url = new URL(trimmed)
    if (url.protocol !== 'https:') return ''
    url.search = ''
    url.hash = ''
    return url.toString().replace(/\/$/, '')
  } catch {
    return ''
  }
}

export function usePrivacy() {
  const { session } = useSession()
  return { session, entries: LOCAL_DATA_ENTRIES, noticeVersion: PRIVACY_NOTICE_VERSION }
}
