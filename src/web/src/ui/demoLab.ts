import { ApiClientError } from '../api/client'
import { formatError } from '../store'

/**
 * 演示造数页的错误分层（HCT-452）：
 * - 身份不符（403 DEMO_SEED_FORBIDDEN）说明 API 是好的，必须引导换演示身份，
 *   而不是让通用权限文案或「API 不可用」误导用户去查服务；
 * - 其余错误交给全局 formatError，让真正的断链/超时保留可操作的启动提示。
 */
export function describeSeedError(cause: unknown): string {
  if (
    cause instanceof ApiClientError &&
    cause.status === 403 &&
    cause.message === 'DEMO_SEED_FORBIDDEN'
  ) {
    return (
      '当前身份无权补种演示数据：请改用 demo-parent（或其它 demo- / test- 前缀）演示身份登录后重试。' +
      'API 服务本身工作正常，本次没有改变任何数据。'
    )
  }
  return formatError(cause)
}

/**
 * 课堂剧本加载失败与「补种失败」是两件事：剧本列表是只读接口，
 * 失败时不能占用造数卡片的红条，否则用户会误以为补种改坏了数据。
 */
export function describeScenarioError(cause: unknown): string {
  return `课堂剧本加载失败：${formatError(cause)}`
}
