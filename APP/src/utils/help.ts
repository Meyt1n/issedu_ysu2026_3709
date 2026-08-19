import { normalizePhoneNumber } from './phone'

export type HelpCallTarget = 'emergency' | 'caregiver'

export interface HelpCallConfirmation {
  href: string
  title: string
  description: string
  confirmLabel: string
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
