/**
 * 仅用于草稿展示的领域近音/口误纠偏，不改变上传到 API 的音频（本仓库本就不上传音频）。
 * 成员名应由调用方通过 extraPairs / memberNameHotwordPairs 注入，避免写死真实姓名。
 */
const BASE_HOTWORD_PAIRS: ReadonlyArray<readonly [RegExp, string]> = [
  [/用药提心|用药题醒|用药蹄醒/g, '用药提醒'],
  [/药盒子|药合|药盒纸/g, '药盒'],
  [/今天的任务|今填任务/g, '今日任务'],
  [/健康事件|健慷事件/g, '健康事件'],
  [/家庭服务器|家廷服务器/g, '家庭服务器'],
  [/风险依据|风显依据/g, '风险依据'],
  [/紧急求助|紧及求助/g, '紧急求助'],
  [/本地助手|本底助手/g, '本地助手'],
]

export type HotwordPair = readonly [RegExp | string, string]

export function applyHotwordCorrections(
  text: string,
  extraPairs: ReadonlyArray<HotwordPair> = [],
): string {
  let next = text
  for (const [pattern, replacement] of BASE_HOTWORD_PAIRS) {
    next = next.replace(pattern, replacement)
  }
  for (const [pattern, replacement] of extraPairs) {
    const regex = typeof pattern === 'string'
      ? new RegExp(pattern.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'g')
      : pattern
    next = next.replace(regex, replacement)
  }
  return next
}

/**
 * 根据成员显示名生成近音草稿纠偏对（不持久化真实姓名到共享模块常量）。
 * 仅做常见 ASR 口误替换：同音字、漏字、加语气词等轻量近似。
 */
export function memberNameHotwordPairs(displayNames: readonly string[]): HotwordPair[] {
  const pairs: HotwordPair[] = []
  const seen = new Set<string>()
  for (const raw of displayNames) {
    const name = raw.trim()
    if (name.length < 2 || name.length > 12) continue
    if (seen.has(name)) continue
    seen.add(name)
    const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    // 中间插入语气/停顿词时仍纠回完整名
    if (name.length >= 2) {
      const chars = [...name]
      const loose = chars.map((ch) => ch.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('[的地得啊呀]?')
      pairs.push([new RegExp(loose, 'g'), name])
    }
    // 常见同音替换（极小集合，避免误伤）
    const variants = new Set<string>()
    variants.add(name.replace(/燕/g, '严').replace(/莹/g, '迎').replace(/芳/g, '方'))
    variants.add(name.replace(/明/g, '名').replace(/丽/g, '利').replace(/强/g, '墙'))
    for (const variant of variants) {
      if (variant === name) continue
      const vEscaped = variant.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
      pairs.push([new RegExp(vEscaped, 'g'), name])
    }
    void escaped
  }
  return pairs
}

/** 听写续说提示：句末出现时延长静音阈值，降低误截断。 */
export const CONTINUATION_CUES = ['还有', '然后', '以及', '另外', '还有个', '还有一个'] as const

export function endsWithContinuationCue(text: string): boolean {
  const trimmed = text.trim()
  if (!trimmed) return false
  return CONTINUATION_CUES.some((cue) => trimmed.endsWith(cue) || new RegExp(`${cue}[，、,\\s]*$`).test(trimmed))
}
