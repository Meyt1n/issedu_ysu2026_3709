import { SESSION_STORAGE_KEY } from './session'
import { A11Y_STORAGE_KEY } from './accessibility'
import { PRIVACY_ACK_STORAGE_KEY } from './privacy'

/**
 * MOB-146：本地数据清单与清理。
 *
 * 只有两个设置键会持久化（会话设置、无障碍偏好）＋隐私告知确认；
 * 凭据、能力快照、查询/任务运行态与健康数据从不落盘。
 * 清理逐键校验结果：存储不可用或键仍存在都算失败，绝不声称已删除。
 */

export interface LocalDataItem {
  key: string
  label: string
  saved: boolean
  note: string
}

export function localDataInventory(): LocalDataItem[] {
  return [
    {
      key: SESSION_STORAGE_KEY,
      label: '连接与紧急联系人',
      saved: true,
      note: '服务器地址、成员选择、联系人称呼与电话',
    },
    {
      key: A11Y_STORAGE_KEY,
      label: '无障碍设置',
      saved: true,
      note: '长辈模式、字号、对比度、语音播报与动效',
    },
    {
      key: PRIVACY_ACK_STORAGE_KEY,
      label: '隐私确认',
      saved: true,
      note: '仅记录已读版本与时间',
    },
    { key: 'memory:credentials', label: '登录信息', saved: false, note: '仅在当前运行期间使用' },
    { key: 'memory:capabilities', label: '服务状态', saved: false, note: '仅在当前运行期间使用' },
    { key: 'memory:runtime', label: '临时运行数据', saved: false, note: '离开页面或切换账户后清除' },
    { key: 'memory:health', label: '健康数据与照片', saved: false, note: '不在本机持久化；照片仅拍摄识别用途，不自动保存' },
  ]
}

export interface LocalDataClearResult {
  ok: boolean
  failures: string[]
  cleared: string[]
}

/** 清理会话设置与无障碍偏好（保留隐私告知确认）；逐键验证，失败如实上报。 */
export function clearLocalData(): LocalDataClearResult {
  const failures: string[] = []
  const cleared: string[] = []
  let storage: Storage | null = null
  try {
    storage = typeof window === 'undefined' ? null : window.localStorage
  } catch {
    storage = null
  }
  if (!storage) {
    return { ok: false, failures: ['浏览器存储当前不可用（可能是隐私模式），无法清理'], cleared }
  }
  const targets: Array<[string, string]> = [
    [SESSION_STORAGE_KEY, '连接与紧急联系人'],
    [A11Y_STORAGE_KEY, '无障碍设置'],
  ]
  for (const [key, label] of targets) {
    try {
      storage.removeItem(key)
      if (storage.getItem(key) === null) {
        cleared.push(label)
      } else {
        failures.push(`${label}：清理后仍存在，未删除`)
      }
    } catch {
      failures.push(`${label}：存储写入被拒绝（隐私模式或权限限制），未删除`)
    }
  }
  return { ok: failures.length === 0, failures, cleared }
}
