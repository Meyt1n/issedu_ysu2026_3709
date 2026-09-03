/**
 * 视觉微调配置
 *
 * 用于微调各个背景图片的显示效果，避免直接修改 CSS
 */

export interface ImageTuning {
  /** 图片位置: 'center' | 'top' | 'bottom' | 'left' | 'right' 或组合 'center top' */
  position?: string
  /** 图片不透明度: 0-1 */
  opacity?: number
  /** 亮度调整: 0.5-2，默认 1 */
  brightness?: number
  /** 饱和度调整: 0-2，默认 1 */
  saturation?: number
  /** 对比度调整: 0-2，默认 1 */
  contrast?: number
}

/**
 * 首页卡片图片微调
 *
 * 根据实际图片内容调整显示效果
 */
export const OVERVIEW_CARD_TUNING: Record<string, ImageTuning> = {
  // 待确认事项
  'pending-tasks': {
    position: 'center',
    opacity: 0.45,
    brightness: 1.15,
    saturation: 0.98,
  },

  // 今日用药
  'medication-schedule': {
    position: 'center',
    opacity: 0.45,
    brightness: 1.15,
    saturation: 0.98,
  },

  // 最近识别
  'recent-scans': {
    position: 'center',
    opacity: 0.45,
    brightness: 1.15,
    saturation: 0.98,
  },

  // 家庭成员
  'family-members': {
    position: 'center',
    opacity: 0.45,
    brightness: 1.15,
    saturation: 0.98,
  },

  // 近期变化
  'recent-changes': {
    position: 'center',
    opacity: 0.45,
    brightness: 1.15,
    saturation: 0.98,
  },
}

/**
 * 健康新闻图片微调
 */
export const HEALTH_NEWS_TUNING: ImageTuning = {
  position: 'center right',
  opacity: 1,
  brightness: 1.08,
  saturation: 1.02,
  contrast: 0.98,
}

/**
 * 生成 CSS filter 字符串
 */
export function buildFilter(tuning: ImageTuning): string {
  const filters: string[] = []

  if (tuning.brightness !== undefined) {
    filters.push(`brightness(${tuning.brightness})`)
  }

  if (tuning.saturation !== undefined) {
    filters.push(`saturate(${tuning.saturation})`)
  }

  if (tuning.contrast !== undefined) {
    filters.push(`contrast(${tuning.contrast})`)
  }

  return filters.join(' ') || 'none'
}

/**
 * 获取内联样式对象
 */
export function getImageStyle(tuning: ImageTuning): Record<string, string> {
  const style: Record<string, string> = {}

  if (tuning.position) {
    style.objectPosition = tuning.position
  }

  if (tuning.opacity !== undefined) {
    style.opacity = String(tuning.opacity)
  }

  const filter = buildFilter(tuning)
  if (filter !== 'none') {
    style.filter = filter
  }

  return style
}
