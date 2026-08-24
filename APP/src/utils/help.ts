import { normalizePhoneNumber } from './phone'

export type HelpCallTarget = 'emergency' | 'caregiver'

export interface HelpCallConfirmation {
  href: string
  title: string
  description: string
  confirmLabel: string
}

export type PhoneCapability = 'available' | 'unavailable'

/** A tel: intent does not prove the current host can complete a phone call. */
export function detectPhoneCapability(userAgent = ''): PhoneCapability {
  const normalized = userAgent.toLowerCase()
  if (!normalized) return 'unavailable'
  return /android|iphone|ipad|ipod|mobile/.test(normalized) ? 'available' : 'unavailable'
}

export function offlineRiskSpeechMessage(): string {
  return '当前没有网络，无法读取实时风险提醒。应用不会朗读旧缓存或虚构提醒；如情况紧急，请直接拨打 120 或联系家人。'
}
export function getHelpCallConfirmation(
  target: HelpCallTarget,
  caregiverPhone = '',
  caregiverName = '',
): HelpCallConfirmation {
  if (target === 'emergency') {
    return {
      href: 'tel:120',
      title: '确认拨打急救电话',
      description: '仅在真实紧急情况下拨打 120。家健镜不会判断病情，请以急救服务和医生的判断为准。',
      confirmLabel: '确认拨打 120',
    }
  }

  const phone = normalizePhoneNumber(caregiverPhone) ?? ''
  return {
    href: `tel:${phone}`,
    title: '确认联系家人',
    description: `即将拨打${caregiverName ? `“${caregiverName}”` : '紧急联系人'}。如果情况严重，请同时联系 120。`,
    confirmLabel: '确认拨打家人电话',
  }
}
