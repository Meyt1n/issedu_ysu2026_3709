import { describe, expect, it } from 'vitest'

import { validateServerBaseUrl } from './serverUrl'

describe('家庭服务器地址边界', () => {
  it('允许同源、局域网 HTTP 和 HTTPS，并规范化末尾斜杠', () => {
    expect(validateServerBaseUrl('')).toMatchObject({ ok: true, value: '' })
    expect(validateServerBaseUrl('http://192.168.1.10:8000/')).toMatchObject({
      ok: true,
      value: 'http://192.168.1.10:8000',
    })
    expect(validateServerBaseUrl('http://[fd00::1]:8000').ok).toBe(true)
    expect(validateServerBaseUrl('http://localhost:5173').ok).toBe(true)
    expect(validateServerBaseUrl('http://family.local:8000').ok).toBe(true)
    expect(validateServerBaseUrl('https://family.example.test/api').ok).toBe(true)
  })

  it('拒绝非 HTTP 协议、凭据、查询参数和公网明文 HTTP', () => {
    expect(validateServerBaseUrl('file:///tmp/server').ok).toBe(false)
    expect(validateServerBaseUrl('http://user:pass@192.168.1.10:8000').ok).toBe(false)
    expect(validateServerBaseUrl('https://family.example.test?token=secret').ok).toBe(false)
    expect(validateServerBaseUrl('http://example.com:8000').ok).toBe(false)
  })
})
