/**
 * MOB-144：请求回执追踪（本机诊断）。
 *
 * 内存环形缓冲，只记录可定位审计所需的最小信息：
 * method、脱敏 path（去 query）、结局、HTTP 状态、服务端 X-Request-ID、
 * 时间，以及写请求的幂等键与响应中的事件/任务 ID。
 * 不记录健康正文、URL query、token、密码或 PIN；不落盘；
 * 会话切换/登出时由 data/index 的清理注册表统一清空。
 */

export type RequestOutcome = 'success' | 'client-error' | 'server-error' | 'unreachable' | 'timeout'

export interface RequestTraceEntry {
  seq: number
  method: string
  /** 已去除 query 的路径（query 可能携带非必要上下文，不进诊断）。 */
  path: string
  outcome: RequestOutcome
  status: number | null
  /** 服务端 X-Request-ID；缺失时为 null，展示层必须标注"回执信息不可用"。 */
  requestId: string | null
  at: string
  /** 写请求的幂等键（内部关联标识，非凭据）。同一键多次出现即重试。 */
  idempotencyKey?: string
  /** 响应体携带的事件/任务 ID（仅当服务端返回时记录）。 */
  receiptId?: string
}

const MAX_ENTRIES = 30
const entries: RequestTraceEntry[] = []
let seq = 0

function sanitizePath(path: string): string {
  const withoutQuery = path.split('?')[0] ?? path
  return withoutQuery.slice(0, 200)
}

export function recordRequestTrace(input: {
  method: string
  path: string
  outcome: RequestOutcome
  status?: number | null
  requestId?: string | null
  at?: string
  idempotencyKey?: string
  receiptId?: string
}): RequestTraceEntry {
  seq += 1
  const entry: RequestTraceEntry = {
    seq,
    method: input.method,
    path: sanitizePath(input.path),
    outcome: input.outcome,
    status: input.status ?? null,
    requestId: input.requestId?.trim() ? input.requestId : null,
    at: input.at ?? new Date().toISOString(),
    ...(input.idempotencyKey ? { idempotencyKey: input.idempotencyKey } : {}),
    ...(input.receiptId ? { receiptId: input.receiptId } : {}),
  }
  entries.unshift(entry)
  if (entries.length > MAX_ENTRIES) entries.length = MAX_ENTRIES
  return entry
}

export function requestTraces(): readonly RequestTraceEntry[] {
  return entries
}

/** 会话/身份变化时清空，旧身份的标识与上下文不残留。 */
export function clearRequestTraces(): void {
  entries.length = 0
}

export function requestOutcomeLabel(outcome: RequestOutcome): string {
  switch (outcome) {
    case 'success': return '成功'
    case 'client-error': return '被拒绝'
    case 'server-error': return '服务端错误'
    case 'unreachable': return '网络不可达'
    case 'timeout': return '超时'
  }
}
