export type ServerUrlValidation = {
  ok: true
  value: string
} | {
  ok: false
  message: string
}

function isPrivateIpv4(hostname: string): boolean {
  const parts = hostname.split('.').map(Number)
  if (parts.length !== 4 || parts.some(part => !Number.isInteger(part) || part < 0 || part > 255)) return false
  const [first, second] = parts
  return first === 10
    || (first === 172 && second >= 16 && second <= 31)
    || (first === 192 && second === 168)
    || (first === 169 && second === 254)
    || (first === 127)
}

function isPrivateIpv6(hostname: string): boolean {
  const value = hostname.replace(/^\[|\]$/g, '').toLowerCase()
  return value === '::1'
    || value.startsWith('fc')
    || value.startsWith('fd')
    || /^(fe[89ab])/.test(value)
}

function isLocalHost(hostname: string): boolean {
  const value = hostname.toLowerCase()
  return value === 'localhost'
    || value.endsWith('.local')
    || isPrivateIpv4(value)
    || isPrivateIpv6(value)
}

/**
 * Validate the family-server base URL.
 *
 * Same-origin (empty) is valid. Plain HTTP is intentionally restricted to
 * loopback/family-LAN names; production public endpoints must use HTTPS.
 */
export function validateServerBaseUrl(value: string): ServerUrlValidation {
  const trimmed = value.trim()
  if (!trimmed) return { ok: true, value: '' }

  let parsed: URL
  try {
    parsed = new URL(trimmed)
  } catch {
    return { ok: false, message: '请输入完整的家庭服务器地址，例如 http://192.168.1.10:8000。' }
  }

  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    return { ok: false, message: '服务器地址只能使用 HTTP 或 HTTPS。' }
  }
  if (parsed.username || parsed.password) {
    return { ok: false, message: '服务器地址不能包含账号或密码。' }
  }
  if (parsed.search || parsed.hash) {
    return { ok: false, message: '服务器地址不能包含查询参数或片段。' }
  }
  if (parsed.protocol === 'http:' && !isLocalHost(parsed.hostname)) {
    return { ok: false, message: '明文 HTTP 只允许家庭局域网或本机地址；公网地址请使用 HTTPS。' }
  }

  return { ok: true, value: parsed.toString().replace(/\/$/, '') }
}
