import { AuthAdapterError } from './auth'
import { ApiClientError } from './client'

export type ErrorAction = 'retry' | 'settings'

export interface ErrorPresentation {
  message: string
  action: ErrorAction
  actionLabel: string
  /** 服务端 X-Request-ID（MOB-144）；缺失时为 null，展示层标注“回执信息不可用”。 */
  requestId: string | null
}

const GENERIC_MESSAGE = '请求未能完成，页面不会显示未经授权的健康数据。'

function retry(message: string, requestId: string | null = null): ErrorPresentation {
  return { message, action: 'retry', actionLabel: '重试', requestId }
}

function settings(message: string, requestId: string | null = null): ErrorPresentation {
  return { message, action: 'settings', actionLabel: '检查设置', requestId }
}

/**
 * 鉴权与二次确认错误码的统一文案。
 *
 * `ApiClientError` 和 `AuthAdapterError` 共用这张表，避免适配器抛出的错误
 * 绕过文案映射、把内部消息直接显示给用户。返回 null 表示不是鉴权类错误码。
 */
function presentAuthCode(code: string): ErrorPresentation | null {
  if (code === 'AUTH_FAILED' || code === 'AUTH_LOCKED') {
    return settings('登录信息不正确或暂时无法验证，请稍后重试。')
  }
  if (code === 'AUTH_UNAVAILABLE') {
    return retry('家庭服务器暂时无法验证身份，请稍后重试。')
  }
  if (code === 'SESSION_EXPIRED' || code === 'AUTH_REVOKED') {
    return settings('登录会话已失效，请重新登录后重试。')
  }
  if (code === 'STEP_UP_REQUIRED') {
    return settings('该操作需要 PIN 或二维码二次确认，请完成确认后重试。')
  }
  if (code === 'STEP_UP_NOT_CONFIGURED') {
    return settings('还没有为这个家庭设置 PIN，请在下面的“设置或更新家庭 PIN”里设置后再发起二次确认。')
  }
  if (code === 'STEP_UP_HOUSEHOLD_REQUIRED') {
    return settings('这个身份在多个家庭设置过 PIN，请先确认要操作的家庭。')
  }
  if (code === 'STEP_UP_EXPIRED' || code === 'STEP_UP_REPLAY') {
    return retry('二次确认已过期或已经使用，请重新发起该操作。')
  }
  if (code === 'STEP_UP_FAILED') {
    return retry('二次确认未通过，请检查 PIN 后重试。')
  }
  return null
}

/**
 * 将 API/网络异常转换成不会泄露后端拒绝细节的用户文案。
 *
 * `ApiClientError` 与 `AuthAdapterError` 走错误码映射；普通 Error 保留本地业务
 * 校验提示（例如“跳过前请填写原因”），未知异常则使用统一兜底文案。
 */
function presentApiErrorInternal(cause: unknown): ErrorPresentation {
  if (cause instanceof AuthAdapterError) {
    return presentAuthCode(cause.code) ?? retry(cause.message.trim() || GENERIC_MESSAGE)
  }

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

  if (code === 'HOUSEHOLD_NOT_SELECTED') {
    return settings('当前身份可以访问多个家庭，请到“我的 → 数据来源”选择要查看的家庭。')
  }

  if (code === 'HOUSEHOLD_UNAVAILABLE') {
    return settings('之前选择的家庭已不可用（可能已被撤权或删除）。为保护隐私，页面不会自动切到另一个家庭，请重新选择。')
  }

  const authPresentation = presentAuthCode(code)
  if (authPresentation) return authPresentation

  if (code === 'AUTHORIZATION_REVERIFICATION_REQUIRED' || code === 'AUTHORIZATION_EXPIRED' || code === 'CONSENT_REVOKED') {
    return settings('授权可能已到期、被撤回或访问范围已变化。为保护隐私，已清除本地页面数据；请到“我的”重新验证身份与访问目的。')
  }

  if (code === 'TIME_WINDOW_VIOLATION') {
    return retry('当前不在服务端允许的操作时间窗内，任务状态未改变。请按提示的下一允许时间操作；紧急情况请联系家人或专业人员。', cause.requestId)
  }

  if (code === 'REQUEST_TIMEOUT') {
    return retry('请求超时，服务器没有在限定时间内响应；结果未知，请稍后重试（重试会复用幂等键，不会重复写入）。', cause.requestId)
  }

  if (code === 'DEPENDENCY_UNAVAILABLE' || cause.status === 0) {
    return retry('家庭服务器暂时无法访问，请检查网络或服务器状态后重试。', cause.requestId)
  }

  if (code === 'INVALID_HEALTH_RESPONSE') {
    return retry('家庭服务器返回的健康检查格式无效，请检查服务器地址或服务版本。', cause.requestId)
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

/**
 * MOB-144：任何 ApiClientError 的展示都携带服务端请求标识，
 * 供用户报障时定位服务端日志；缺失时保持 null，展示层如实标注。
 */
export function presentApiError(cause: unknown): ErrorPresentation {
  const presentation = presentApiErrorInternal(cause)
  if (presentation.requestId === null && cause instanceof ApiClientError && cause.requestId) {
    return { ...presentation, requestId: cause.requestId }
  }
  return presentation
}

function isConnectionTimeout(cause: unknown): boolean {
  return cause instanceof ApiClientError
    && (cause.code.toUpperCase() === 'REQUEST_TIMEOUT' || cause.status === 408)
}

function isServerSlow(cause: unknown): boolean {
  if (!(cause instanceof ApiClientError)) return false
  const code = cause.code.toUpperCase()
  return cause.status === 504 || code === 'GATEWAY_TIMEOUT' || code === 'SERVER_TIMEOUT'
}

/**
 * 列表场景的上下文文案：不改变 MOB-112 的通用错误码映射，
 * 只在列表保留可用内容或需要解释超时来源时补充用户可执行的下一步。
 */
export function presentListApiError(
  cause: unknown,
  options: { partial?: boolean } = {},
): ErrorPresentation {
  const presentation = presentApiError(cause)
  if (options.partial) {
    if (isConnectionTimeout(cause)) {
      return {
        ...presentation,
        message: '部分数据连接超时，已保留可用内容；请检查网络后重试补齐。',
        action: 'retry',
        actionLabel: '重试补齐',
      }
    }
    if (isServerSlow(cause)) {
      return {
        ...presentation,
        message: '部分数据处理较慢，已保留可用内容；请稍后重试补齐。',
        action: 'retry',
        actionLabel: '重试补齐',
      }
    }
    if (presentation.action === 'settings') {
      return {
        ...presentation,
        message: '部分数据未能加载，可能需要检查联机身份或授权设置。',
      }
    }
    return {
      ...presentation,
      message: '部分数据未能加载，已保留可用内容；请点击“重试补齐”。',
      action: 'retry',
      actionLabel: '重试补齐',
    }
  }

  if (isConnectionTimeout(cause)) {
    return {
      ...presentation,
      message: '连接等待超时，列表还没有收到完整响应；请检查网络或服务器地址后重试。',
    }
  }
  if (isServerSlow(cause)) {
    return {
      ...presentation,
      message: '服务端处理较慢，本次列表没有完成；请稍后重试或检查家庭服务器状态。',
    }
  }
  return presentation
}

export function errorMessage(cause: unknown): string {
  return presentApiError(cause).message
}
