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
      label: '联机设置与紧急联系人',
      saved: true,
      note: '服务器地址、身份来源、访问目的、成员选择、紧急联系人称呼与电话',
    },
    {
      key: A11Y_STORAGE_KEY,
      label: '无障碍偏好',
      saved: true,
      note: '长辈模式、字号、对比度、语音播报、减少动效',
    },
    {
      key: PRIVACY_ACK_STORAGE_KEY,
      label: '隐私告知确认',
      saved: true,
      note: '仅记录已读版本与时间；清理本地设置时保留，避免反复弹窗',
    },
    { key: 'memory:credentials', label: '登录密码 / PIN / 会话凭据', saved: false, note: '只在本机内存，退出或刷新即消失，从不写入存储' },
    { key: 'memory:capabilities', label: '后端能力探测快照', saved: false, note: '仅运行时有效，切换上下文即丢弃' },
    { key: 'memory:runtime', label: '查询、任务、上传与识别运行状态', saved: false, note: '内存态，页面离开或会话切换即清理' },
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
    [SESSION_STORAGE_KEY, '联机设置与紧急联系人'],
    [A11Y_STORAGE_KEY, '无障碍偏好'],
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
