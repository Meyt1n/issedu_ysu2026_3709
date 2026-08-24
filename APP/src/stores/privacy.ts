import { ref } from 'vue'

/**
 * MOB-146：版本化隐私告知。
 *
 * 首次使用或隐私版本更新时展示适老、可读、可播报的告知；
 * 确认结果只记录版本号与时间（非健康数据）。写入失败时
 * 不声称已确认——下次启动会再次展示（fail-closed）。
 */

export const PRIVACY_NOTICE_VERSION = '2026-08-23.1'
export const PRIVACY_ACK_STORAGE_KEY = 'hct-mobile.privacy-ack.v1'

export interface PrivacyNoticeSection {
  title: string
  lines: string[]
}

export const PRIVACY_NOTICE_SECTIONS: PrivacyNoticeSection[] = [
  {
    title: '演示与联机模式',
    lines: [
      '默认是演示模式：所有成员、任务、风险和药品都是虚构教学数据，不连接任何服务器。',
      '切换到"家庭服务器（联机）"后，应用只访问你在设置里填写的家庭服务器地址；健康数据不出家庭可信网络。',
    ],
  },
  {
    title: '访问目的',
    lines: [
      '联机时按"访问目的"（如 family-care 家庭照护）读取数据；服务端按授权逐次校验字段、动作和期限。',
      '更改目的或身份后，之前的查询结果和缓存会被清空。',
    ],
  },
  {
    title: '设备能力',
    lines: [
      '相机/相册：仅用于拍摄药盒照片做识别，照片先过质量检查，识别候选必须人工确认。',
      '通知：仅在你主动开启后，用于视觉任务完成的本地提醒；内容不含健康数据。',
      '拨号：仅在"求助"页经你确认后拨打紧急联系人电话。',
    ],
  },
  {
    title: '本机保存了什么',
    lines: [
      '保存：界面与无障碍偏好、联机设置（服务器地址、身份来源、成员选择）、紧急联系人。',
      '不保存：登录密码、PIN、会话凭据（只在内存）、健康数据、照片、查询与任务运行状态。',
    ],
  },
  {
    title: '健康数据边界',
    lines: [
      '应用不做诊断、处方、停药、换药或剂量判断；药品识别结果永远需要人工确认。',
      '导出、删除、撤回家庭健康数据在网页端由家庭主人办理；清理本机设置不影响服务端事实。',
    ],
  },
]

export interface PrivacyAck {
  version: string
  acknowledgedAt: string
}

function readStorage(): Storage | null {
  try {
    return typeof window === 'undefined' ? null : window.localStorage
  } catch {
    return null
  }
}

export function readPrivacyAck(): PrivacyAck | null {
  const storage = readStorage()
  if (!storage) return null
  try {
    const text = storage.getItem(PRIVACY_ACK_STORAGE_KEY)
    if (!text) return null
    const parsed = JSON.parse(text) as Partial<PrivacyAck>
    if (typeof parsed.version !== 'string' || typeof parsed.acknowledgedAt !== 'string') return null
    return { version: parsed.version, acknowledgedAt: parsed.acknowledgedAt }
  } catch {
    return null
  }
}

export function privacyNoticeRequired(): boolean {
  return readPrivacyAck()?.version !== PRIVACY_NOTICE_VERSION
}

/** 记录确认；返回是否写入成功（失败=下次仍会展示，不声称已确认）。 */
export function acknowledgePrivacyNotice(now: Date = new Date()): boolean {
  const storage = readStorage()
  if (!storage) return false
  try {
    storage.setItem(PRIVACY_ACK_STORAGE_KEY, JSON.stringify({
      version: PRIVACY_NOTICE_VERSION,
      acknowledgedAt: now.toISOString(),
    } satisfies PrivacyAck))
    return readPrivacyAck()?.version === PRIVACY_NOTICE_VERSION
  } catch {
    return false
  }
}

/** 供界面响应式使用：确认/重置时推进。 */
const ackGeneration = ref(0)

export function usePrivacyNotice() {
  const required = () => {
    void ackGeneration.value
    return privacyNoticeRequired()
  }
  const acknowledge = (): boolean => {
    const ok = acknowledgePrivacyNotice()
    ackGeneration.value += 1
    return ok
  }
  return { required, acknowledge }
}

/** 把告知合成一段可播报文本（适老语音路径）。 */
export function privacyNoticeSpeechText(): string {
  return PRIVACY_NOTICE_SECTIONS
    .map(section => `${section.title}。${section.lines.join('。')}`)
    .join('。\n')
}
