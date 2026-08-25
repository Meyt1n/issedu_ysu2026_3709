/**
 * HCT-439 成员前台状态文案映射。
 *
 * 成员前台面向长辈，只允许出现生活化文案；任何后台技术状态码
 * （queued/running/succeeded、MATCHED/CONFLICT/UNKNOWN/REVIEW 等）
 * 都必须映射为可理解的中文短语，未知状态一律落到兜底文案，
 * 绝不把内部代码原样透出。`confirmed` 表示该照片对应的健康事件
 * 已由家庭管理员确认（来自时间线证据），优先于任务自身状态。
 */
export function memberVisionStatusLabel(
  status: string | null | undefined,
  confirmed = false,
): string {
  if (confirmed) return '家人已确认'
  if (status === 'queued' || status === 'running') return '正在看照片'
  if (
    status === 'succeeded'
    || status === 'REVIEW_REQUIRED'
    || status === 'PENDING_REVIEW'
    || status === 'REVIEW'
  ) {
    return '已交给家人，等待确认'
  }
  if (status === 'CONFLICT') return '信息和药盒不太一样，等家人核对'
  if (status === 'UNKNOWN') return '暂时认不出药名，等家人帮忙'
  if (status === 'cancelled') return '已取消'
  if (status === 'failed' || status === 'timeout') return '没看清楚，请重新拍一张'
  return '没看清楚，请重新拍一张'
}

export function memberVisionStatusHint(
  status: string | null | undefined,
  confirmed = false,
): string {
  if (confirmed) return '家人已经核对过，药品信息已记进家庭本子。'
  if (status === 'queued' || status === 'running') return '照片正在家里处理，请稍等一会儿。'
  if (
    status === 'succeeded'
    || status === 'REVIEW_REQUIRED'
    || status === 'PENDING_REVIEW'
    || status === 'REVIEW'
  ) {
    return '家人确认后，你就能在「我的记录」里看到它。'
  }
  if (status === 'CONFLICT') return '家人会对照药盒再看一遍，请耐心等待。'
  if (status === 'UNKNOWN') return '家人可能会请你重新拍一张，或帮你手写记下。'
  if (status === 'cancelled') return '这张照片没有记进家庭本子，可以重新拍。'
  if (status === 'failed' || status === 'timeout') return '请换一个光线好、字清楚的角度再拍一次。'
  return '请换一个光线好、字清楚的角度再拍一次。'
}

/** 待处理判断：仍在本机处理中的任务。 */
export function isMemberTaskActive(status: string | null | undefined): boolean {
  return status === 'queued' || status === 'running'
}

/**
 * 需要重拍：失败/超时/取消，以及无法映射为「处理中 / 等待家人」的未知状态。
 * 与 memberVisionStatusLabel 的兜底文案保持一致，避免出现「没看清楚」却仍显示「看看进度」。
 */
export function isMemberTaskNeedsRetake(status: string | null | undefined): boolean {
  if (isMemberTaskActive(status)) return false
  if (
    status === 'succeeded'
    || status === 'REVIEW_REQUIRED'
    || status === 'PENDING_REVIEW'
    || status === 'REVIEW'
    || status === 'CONFLICT'
    || status === 'UNKNOWN'
  ) {
    return false
  }
  return true
}
