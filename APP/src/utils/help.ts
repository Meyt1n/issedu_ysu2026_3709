import { normalizePhoneNumber } from './phone'

export type HelpCallTarget = 'emergency' | 'caregiver'

export type PhoneCapability = 'available' | 'unavailable'

/** A tel: intent does not prove the current host can complete a phone call. */
export function detectPhoneCapability(userAgent = ''): PhoneCapability {
  const normalized = userAgent.toLowerCase()
  if (!normalized) return 'unavailable'
  return /android|iphone|ipad|ipod|mobile/.test(normalized) ? 'available' : 'unavailable'
}

export function getHelpDialHref(target: HelpCallTarget, caregiverPhone = ''): string {
  if (target === 'emergency') return 'tel:120'
  const phone = normalizePhoneNumber(caregiverPhone) ?? ''
  return phone ? `tel:${phone}` : ''
}
