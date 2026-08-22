/**
 * MOB-132：视觉任务终态本地提醒。
 *
 * 只使用浏览器/系统的本地通知能力，且必须用户显式开启；
 * 通知文案不携带健康数据、任务编号、成员或照片信息——
 * 只告诉用户"任务已结束，回到应用查看"。无权限或环境不支持时
 * 返回明确状态，页面只保留站内状态展示，绝不声称已发送远程推送。
 */

export type VisionNoticeSupport = 'granted' | 'denied' | 'default' | 'unsupported'

export function visionNoticeSupport(): VisionNoticeSupport {
  if (typeof window === 'undefined' || typeof Notification === 'undefined') return 'unsupported'
  if (Notification.permission === 'granted') return 'granted'
  if (Notification.permission === 'denied') return 'denied'
  return 'default'
}

/** 请求通知权限；只能在用户手势（如开关点击）里调用。 */
export async function requestVisionNoticePermission(): Promise<VisionNoticeSupport> {
  if (typeof window === 'undefined' || typeof Notification === 'undefined') return 'unsupported'
  try {
    return (await Notification.requestPermission()) as VisionNoticeSupport
  } catch {
    return 'denied'
  }
}

export type VisionNoticeResult = 'shown' | 'denied' | 'unsupported'

export function notifyVisionTaskTerminal(kind: 'succeeded' | 'failed'): VisionNoticeResult {
  if (typeof window === 'undefined' || typeof Notification === 'undefined') return 'unsupported'
  if (Notification.permission !== 'granted') return 'denied'
  const title = kind === 'succeeded' ? '药盒识别已完成' : '药盒识别未完成'
  try {
    new Notification(title, {
      body: '请回到应用查看任务状态与下一步；通知不包含任何健康数据。',
      tag: 'homecare-vision-task',
    })
    return 'shown'
  } catch {
    return 'denied'
  }
}
