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
  if (confirmed) return '已确认'
  if (status === 'queued' || status === 'running') return '正在识别'
  if (status === 'succeeded') return '已提交，等待家人确认'
  if (status === 'cancelled') return '已取消'
  return '识别失败，请重新拍照'
}

export function memberVisionStatusHint(
  status: string | null | undefined,
  confirmed = false,
): string {
  if (confirmed) return '家庭管理员已确认，药品信息已进入家庭记录。'
  if (status === 'queued' || status === 'running') return '照片正在本机处理中，请稍等。'
  if (status === 'succeeded') return '管理员确认后，你就能在“我的记录”里看到它。'
  if (status === 'cancelled') return '这张照片没有进入家庭记录，可以重新拍摄。'
  return '请换一个光线好、文字清楚的角度再拍一次。'
}

/** 待处理判断：仍在本机识别中的任务。 */
export function isMemberTaskActive(status: string | null | undefined): boolean {
  return status === 'queued' || status === 'running'
}
