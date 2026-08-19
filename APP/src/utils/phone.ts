/**
 * Normalize a phone number before it can be used in a tel: URL.
 *
 * The mobile app only needs a dial target; it must not accept arbitrary URL
 * schemes, extensions, or free-form text from local storage.
 */
export function normalizePhoneNumber(value: string): string | null {
  const trimmed = value.trim()
  if (!trimmed) return ''

  const compact = trimmed.replace(/[\s().-]/g, '')
  const normalized = compact.startsWith('00') ? `+${compact.slice(2)}` : compact
  const valid = normalized.startsWith('+')
    ? /^\+[1-9]\d{6,14}$/.test(normalized)
    : /^\d{7,15}$/.test(normalized)

  return valid ? normalized : null
}

export function isValidPhoneNumber(value: string): boolean {
  return normalizePhoneNumber(value) !== null
}
