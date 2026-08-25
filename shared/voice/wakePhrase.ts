import { DEFAULT_WAKE_PHRASE, normalizeVoiceText } from './recognition'

/** 常见 ASR 近音字表：仅用于唤醒匹配，不写入健康数据。 */
const CHAR_ALIASES: Readonly<Record<string, readonly string[]>> = {
  小: ['晓', '筱'],
  燕: ['严', '研', '嫣', '延', '言', '烟'],
  家: ['加', '佳'],
  健: ['建', '剑'],
  镜: ['静', '净', '敬'],
  助: ['住', '注'],
  手: ['首'],
  阿: ['啊'],
  宝: ['保'],
  贝: ['备'],
}

export const WAKE_PHRASE_PRESETS = [
  { id: 'xiaoyan', label: '小燕小燕（默认）', phrase: '小燕小燕' },
  { id: 'homecare', label: '家健镜', phrase: '家健镜' },
  { id: 'assistant', label: '小助手', phrase: '小助手' },
] as const

const MIN_LEN = 2
const MAX_LEN = 8

/** 规范化用户输入的唤醒词：去空白标点，仅保留可见字。 */
export function sanitizeWakePhraseInput(raw: string): string {
  return raw
    .normalize('NFKC')
    .replace(/[\s，。！？；：、,.!?;:'"“”‘’（）()[\]{}<>《》·•\-_/\\]+/g, '')
    .trim()
}

export function validateWakePhrase(raw: string): { ok: true; phrase: string } | { ok: false; message: string } {
  const phrase = sanitizeWakePhraseInput(raw)
  if (phrase.length < MIN_LEN) {
    return { ok: false, message: `唤醒词至少 ${MIN_LEN} 个字` }
  }
  if (phrase.length > MAX_LEN) {
    return { ok: false, message: `唤醒词最多 ${MAX_LEN} 个字` }
  }
  const chinese = [...phrase].filter((ch) => /[\u4e00-\u9fff]/.test(ch)).length
  if (chinese < MIN_LEN) {
    return { ok: false, message: '请使用中文唤醒词，便于识别' }
  }
  return { ok: true, phrase }
}

function aliasGroup(char: string): string[] {
  const group = new Set<string>([char])
  for (const alt of CHAR_ALIASES[char] ?? []) group.add(alt)
  for (const [canon, alts] of Object.entries(CHAR_ALIASES)) {
    if (canon === char || alts.includes(char)) {
      group.add(canon)
      for (const alt of alts) group.add(alt)
    }
  }
  return [...group]
}

/** 将文本中的近音字映射到当前唤醒词用字，便于匹配自定义词。 */
export function canonicalizeForWakePhrase(text: string, phrase: string): string {
  const target = sanitizeWakePhraseInput(phrase) || DEFAULT_WAKE_PHRASE
  const replacement = new Map<string, string>()
  for (const ch of target) {
    for (const alt of aliasGroup(ch)) replacement.set(alt, ch)
  }
  const compact = normalizeVoiceText(text)
  return [...compact].map((ch) => replacement.get(ch) ?? ch).join('')
}

export function wakePhrasePatternSource(phrase: string): string {
  const target = sanitizeWakePhraseInput(phrase) || DEFAULT_WAKE_PHRASE
  return [...target]
    .map((char) => {
      const group = aliasGroup(char).map((item) => item.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
      return group.length > 1 ? `[${group.join('')}]` : group[0]!
    })
    .join('[\\s，。！？；：、,.!?;:\'"“”‘’（）()[\\]{}<>《》]*')
}

export function containsConfiguredWakePhrase(text: string, phrase: string): boolean {
  const target = sanitizeWakePhraseInput(phrase) || DEFAULT_WAKE_PHRASE
  const source = wakePhrasePatternSource(target)
  const pattern = new RegExp(source, 'iu')
  if (pattern.test(text)) return true
  const canonicalText = canonicalizeForWakePhrase(text, target)
  const canonicalPhrase = canonicalizeForWakePhrase(target, target)
  return canonicalText.includes(canonicalPhrase)
}

export function transcriptAfterConfiguredWakePhrase(text: string, phrase: string): string {
  const target = sanitizeWakePhraseInput(phrase) || DEFAULT_WAKE_PHRASE
  const source = wakePhrasePatternSource(target)
  const pattern = new RegExp(source, 'iu')
  const direct = pattern.exec(text)
  if (direct && direct.index !== undefined) {
    return text
      .slice(direct.index + direct[0].length)
      .replace(/^[\s，。！？；：、,.!?;:'"“”‘’（）()[\]{}<>《》]+/, '')
      .trim()
  }
  const canonicalText = canonicalizeForWakePhrase(text, target)
  const canonicalPhrase = canonicalizeForWakePhrase(target, target)
  const index = canonicalText.indexOf(canonicalPhrase)
  if (index < 0) return ''
  const trailing = canonicalText.slice(index + canonicalPhrase.length)
  if (!trailing) return ''
  const rawCompact = text.replace(/[\s，。！？；：、,.!?;:'"“”‘’（）()[\]{}<>《》]/g, '')
  return rawCompact.slice(Math.max(0, rawCompact.length - trailing.length)).trim()
}
