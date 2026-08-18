import { ApiClientError } from './client'

export type ErrorAction = 'retry' | 'settings'

export interface ErrorPresentation {
  message: string
  action: ErrorAction
  actionLabel: string
}

const GENERIC_MESSAGE = '请求未能完成，页面不会显示未经授权的健康数据。'

function retry(message: string): ErrorPresentation {
  return { message, action: 'retry', actionLabel: '重试' }
}

function settings(message: string): ErrorPresentation {
  return { message, action: 'settings', actionLabel: '检查设置' }
}

/**
 * 将 API/网络异常转换成不会泄露后端拒绝细节的用户文案。
 *
 * 仅 ApiClientError 使用状态码和服务端错误码；普通 Error 保留本地业务
 * 校验提示（例如“跳过前请填写原因”），未知异常则使用统一兜底文案。
 */
export function presentApiError(cause: unknown): ErrorPresentation {
  if (!(cause instanceof ApiClientError)) {
    if (cause instanceof Error && cause.message.trim()) {
      return retry(cause.message)
    }
    return retry(GENERIC_MESSAGE)
  }

  const code = cause.code.toUpperCase()
  if (code === 'SESSION_NOT_CONFIGURED') {
    return settings('联机模式还没有配置身份或访问目的，请到“我的”补充后重试。')
  }

  if (code === 'NO_HOUSEHOLD') {
    return settings('当前身份尚未关联可访问的家庭，请到“我的”检查身份，或联系家庭管理员。')
  }

  if (code === 'NO_MEMBERS') {
    return settings('当前家庭暂无可用成员，请检查家庭设置和授权范围。')
  }

  if (code === 'DEPENDENCY_UNAVAILABLE' || cause.status === 0) {
    return retry('家庭服务器暂时无法访问，请检查网络或服务器状态后重试。')
  }

  if (cause.status === 401 || code === 'UNAUTHENTICATED') {
    return settings('身份已失效或尚未配置，请到“我的”检查身份后重试。')
  }

  if (cause.status === 403 || code === 'FORBIDDEN_MEMBER' || code === 'CONSENT_REVOKED') {
    return settings('当前身份没有权限执行这项操作，请检查访问目的或联系家庭管理员。')
  }

  // 资源不存在、被撤权和服务尚未提供都可能使用 404，避免向用户泄露资源存在性。
  if (cause.status === 404 || code === 'NOT_FOUND' || code === 'RESOURCE_NOT_FOUND') {
    return retry('内容不存在、已被撤权或服务暂未提供，请刷新后重试。')
  }

  if (
    cause.status === 409 ||
    code.includes('CONFLICT') ||
    code === 'AUTHORIZATION_VERSION_CONFLICT' ||
    code === 'EVENT_ALREADY_SUPERSEDED' ||
    code === 'OUT_OF_ORDER'
  ) {
    return retry('服务端数据已发生变化，当前页面可能已过期，请刷新后重试。')
  }

  if (cause.status === 422 || code === 'VALIDATION_ERROR' || code === 'FILE_REJECTED') {
    return retry('提交内容未通过校验，请检查填写内容后重试。')
  }

  if (cause.status === 429 || code === 'RATE_LIMITED') {
    return retry('操作过于频繁，请稍后再试。')
  }

  if (code === 'MODEL_UNAVAILABLE') {
    return retry('本地识别服务暂时不可用，请稍后重试；健康数据不会因此自动入库。')
  }

  return retry(GENERIC_MESSAGE)
}

export function errorMessage(cause: unknown): string {
  return presentApiError(cause).message
}
