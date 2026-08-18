import { describe, expect, it } from 'vitest'

import { ApiClientError } from './client'
import { errorMessage, presentApiError } from './errors'

describe('移动端 API 错误用户文案', () => {
  it('网络失败提供可恢复提示', () => {
    expect(presentApiError(new ApiClientError('raw network error', { status: 0, code: 'DEPENDENCY_UNAVAILABLE' }))).toEqual({
      message: '家庭服务器暂时无法访问，请检查网络或服务器状态后重试。',
      action: 'retry',
      actionLabel: '重试',
    })
  })

  it.each([
    [401, '身份已失效或尚未配置，请到“我的”检查身份后重试。'],
    [403, '当前身份没有权限执行这项操作，请检查访问目的或联系家庭管理员。'],
    [404, '内容不存在、已被撤权或服务暂未提供，请刷新后重试。'],
    [409, '服务端数据已发生变化，当前页面可能已过期，请刷新后重试。'],
    [422, '提交内容未通过校验，请检查填写内容后重试。'],
  ])('按 HTTP %s 映射为不误导的文案', (status, message) => {
    const presentation = presentApiError(new ApiClientError('包含内部细节的服务端消息', {
      status,
      code: 'HTTP_ERROR',
    }))
    expect(presentation.message).toBe(message)
    expect(presentation.action).toBe(status === 403 || status === 401 ? 'settings' : 'retry')
    expect(presentation.message).not.toContain('内部细节')
  })

  it('兼容目标错误码而不依赖 HTTP 状态码', () => {
    expect(errorMessage(new ApiClientError('raw', { status: 400, code: 'RATE_LIMITED' }))).toBe('操作过于频繁，请稍后再试。')
    expect(errorMessage(new ApiClientError('raw', { status: 400, code: 'MODEL_UNAVAILABLE' }))).toContain('不会因此自动入库')
  })

  it('保留本地业务校验提示，未知异常使用兜底文案', () => {
    expect(errorMessage(new Error('跳过前请填写原因'))).toBe('跳过前请填写原因')
    expect(errorMessage({ unexpected: true })).toBe('请求未能完成，页面不会显示未经授权的健康数据。')
  })
})
