import {
  pickPreferredChineseVoice,
  waitForVoices,
  type SpeechSynthesisLike,
  type SpeechVoiceLike,
} from './tts'

export interface VoicePackReport {
  supported: boolean
  total: number
  chinese: number
  preferredName: string | null
  preferredNatural: boolean
  names: string[]
  guidance: string
}

function synth(): SpeechSynthesisLike | null {
  if (typeof window === 'undefined') return null
  return (window.speechSynthesis as SpeechSynthesisLike | undefined) ?? null
}

function looksNatural(name: string): boolean {
  return /natural|neural|premium|enhanced|晓晓|云希|婷婷|xiaoxiao|yunxi|ting/i.test(name)
}

/** 设置页/演示前自检：列出中文音色并提示是否缺少 Natural 包。 */
export async function inspectChineseVoicePacks(): Promise<VoicePackReport> {
  const engine = synth()
  if (!engine || typeof SpeechSynthesisUtterance === 'undefined') {
    return {
      supported: false,
      total: 0,
      chinese: 0,
      preferredName: null,
      preferredNatural: false,
      names: [],
      guidance: '当前环境不支持语音播报。请改用屏幕文字，或更换支持 Web Speech 的浏览器/WebView。',
    }
  }

  // 预热
  try {
    engine.getVoices?.()
  } catch {
    // ignore
  }
  const voices = await waitForVoices(engine, 1000)
  const chineseVoices = voices.filter((voice) => /^zh/i.test(voice.lang))
  const preferred = pickPreferredChineseVoice(chineseVoices)
  const preferredNatural = preferred ? looksNatural(preferred.name) : false
  const names = chineseVoices.map((voice: SpeechVoiceLike) => `${voice.name} (${voice.lang}${voice.localService ? ', 本地' : ''})`)

  let guidance = ''
  if (chineseVoices.length === 0) {
    guidance = '未发现中文语音包。请到系统“文字转语音/语音”设置安装简体中文，说明见仓库 docs/demo/中文语音包与听感准备说明.md。'
  } else if (!preferredNatural) {
    guidance = `已找到 ${chineseVoices.length} 条中文语音，但缺少 Natural/晓晓等自然音色（当前优选：${preferred?.name ?? '无'}）。听感可能偏机械，请安装 Natural 类语音包后再演示。`
  } else {
    guidance = `音色就绪：优选「${preferred?.name}」。可进行朗读验收。`
  }

  return {
    supported: true,
    total: voices.length,
    chinese: chineseVoices.length,
    preferredName: preferred?.name ?? null,
    preferredNatural,
    names,
    guidance,
  }
}
