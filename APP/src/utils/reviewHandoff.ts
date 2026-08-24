export interface ReviewHandoffTarget {
  taskId: string
  url: string | null
  reason: string | null
}

export function trustedReviewTarget(taskId: string, configuredBase: string | undefined, currentOrigin: string): ReviewHandoffTarget {
  if (!taskId.trim()) return { taskId: '', url: null, reason: '复核任务标识不可用，当前无法交接。' }
  if (!configuredBase) return { taskId, url: null, reason: '尚未配置受控网页复核地址，请复制任务标识后在已登录的网页复核中心查询。' }

  try {
    const base = new URL(configuredBase)
    const current = new URL(currentOrigin)
    if (base.origin !== current.origin || base.protocol !== 'https:') {
      return { taskId, url: null, reason: '网页复核地址未通过可信来源校验，当前不会打开链接。' }
    }
    // Task id is the only navigation parameter. Session credentials, member id and candidate details never enter the URL.
    const target = new URL('/review', base.origin)
    target.searchParams.set('task', taskId)
    return { taskId, url: target.toString(), reason: null }
  } catch {
    return { taskId, url: null, reason: '网页复核地址格式无效，当前不会打开链接。' }
  }
}
