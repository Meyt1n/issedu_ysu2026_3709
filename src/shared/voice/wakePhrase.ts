import { DEFAULT_WAKE_PHRASE, normalizeVoiceText } from './recognition'

/** 常见 ASR 近音字表：仅用于唤醒匹配，不写入健康数据。 */
const CHAR_ALIASES: Readonly<Record<string, readonly string[]>> = {
  // 唤醒词相关
  小: ['晓', '筱', '效', '孝', '肖', '笑'],
  燕: ['严', '研', '嫣', '延', '言', '烟', '炎', '盐', '颜'],
  家: ['加', '佳', '嘉'],
  健: ['建', '剑', '键', '渐'],
  镜: ['静', '净', '敬', '境'],
  助: ['住', '注', '著'],
  手: ['首', '守', '受'],
  阿: ['啊', '呵'],
  宝: ['保', '堡', '饱'],
  贝: ['备', '背', '被'],

  // 医疗健康高频词
  血: ['穴', '学', '雪', '削'],
  压: ['押', '呀', '鸭', '压'],
  糖: ['塘', '堂', '唐', '汤'],
  尿: ['鸟', '溺'],
  药: ['要', '腰', '摇', '耀'],
  病: ['并', '冰', '饼'],
  症: ['正', '证', '整'],
  状: ['壮', '撞', '装'],
  痛: ['通', '同', '桐'],
  疼: ['腾', '藤', '疼'],
  头: ['投', '偷', '透'],
  心: ['新', '辛', '欣'],
  肝: ['干', '甘', '杆'],
  肺: ['费', '废', '肺'],
  胃: ['为', '位', '卫'],

  // 数字（医疗场景常用）
  一: ['1', '壹', '依', '伊', '医'],
  二: ['2', '贰', '儿', '尔', '耳'],
  三: ['3', '叁', '散', '山', '删'],
  四: ['4', '肆', '死', '寺', '思'],
  五: ['5', '伍', '午', '武', '舞'],
  六: ['6', '陆', '路', '鹿', '录'],
  七: ['7', '柒', '期', '齐', '妻'],
  八: ['8', '捌', '吧', '巴', '爸'],
  九: ['9', '玖', '久', '酒', '就'],
  十: ['10', '拾', '时', '实', '石'],
  百: ['佰', '白', '摆'],
  千: ['仟', '迁', '签'],

  // 家庭成员
  爸: ['八', '吧', '巴'],
  妈: ['马', '吗', '麻', '骂'],
  爷: ['也', '夜', '业'],
  奶: ['乃', '耐'],
  哥: ['歌', '割', '个'],
  姐: ['解', '街', '借'],
  弟: ['第', '地', '帝'],
  妹: ['每', '美', '媚'],
}

export const WAKE_PHRASE_PRESETS = [
  { id: 'xiaoyan', label: '小燕小燕（默认，需连说两遍）', phrase: '小燕小燕' },
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
