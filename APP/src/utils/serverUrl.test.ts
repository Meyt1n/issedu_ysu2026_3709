import { describe, expect, it } from 'vitest'

import { validateServerBaseUrl } from './serverUrl'

const debugPolicy = { allowPrivateHttp: true }
const releasePolicy = { allowPrivateHttp: false }

describe('家庭服务器地址边界', () => {
  it('允许同源、局域网 HTTP 和 HTTPS，并规范化末尾斜杠', () => {
    expect(validateServerBaseUrl('')).toMatchObject({ ok: true, value: '' })
    expect(validateServerBaseUrl('http://192.168.1.10:8000/', debugPolicy)).toMatchObject({
      ok: true,
      value: 'http://192.168.1.10:8000',
    })
    expect(validateServerBaseUrl('http://[fd00::1]:8000', debugPolicy).ok).toBe(true)
    expect(validateServerBaseUrl('http://localhost:5173', debugPolicy).ok).toBe(true)
    expect(validateServerBaseUrl('http://family.local:8000', debugPolicy).ok).toBe(true)
    expect(validateServerBaseUrl('https://family.example.test/api', releasePolicy).ok).toBe(true)
  })

  it('拒绝非 HTTP 协议、凭据、查询参数和公网明文 HTTP', () => {
    expect(validateServerBaseUrl('file:///tmp/server').ok).toBe(false)
    expect(validateServerBaseUrl('http://user:pass@192.168.1.10:8000').ok).toBe(false)
    expect(validateServerBaseUrl('https://family.example.test?token=secret').ok).toBe(false)
    expect(validateServerBaseUrl('http://example.com:8000').ok).toBe(false)
  })

  it('发布策略拒绝私网明文 HTTP，Android Debug 策略显式允许', () => {
    expect(validateServerBaseUrl('http://192.168.1.10:8000', releasePolicy)).toMatchObject({
      ok: false,
      message: expect.stringContaining('只允许 HTTPS'),
    })
    expect(validateServerBaseUrl('http://192.168.1.10:8000', debugPolicy).ok).toBe(true)
  })
})
