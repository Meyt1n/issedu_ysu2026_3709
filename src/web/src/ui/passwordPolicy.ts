/** Formal account password policy (HCT-512). Mirrors `app.password_policy`. */

export const FORMAL_PASSWORD_HINT = '至少 8 位，需同时包含英文字母和数字'

export function formalPasswordMeetsPolicy(password: string): boolean {
  return (
    password.length >= 8
    && password.length <= 256
    && /[A-Za-z]/.test(password)
    && /\d/.test(password)
  )
}
