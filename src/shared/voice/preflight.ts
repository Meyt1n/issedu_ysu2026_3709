import { isSpeechInputSupported, isSpeechOutputSupported, queryMicrophonePermission } from './recognition'
import { inspectChineseVoicePacks, type VoicePackReport } from './voiceReport'

export interface VoicePreflightReport {
  speechInput: boolean
  speechOutput: boolean
  microphone: 'granted' | 'denied' | 'prompt' | null
  voices: VoicePackReport
  serverReachable: boolean | null
  serverDetail: string
  guidance: string[]
}

export interface VoicePreflightOptions {
  /** 可选：探测家庭服务器 /health，仅用于演示排障，不上传音频。 */
  serverBaseUrl?: string
  fetcher?: typeof fetch
  timeoutMs?: number
}

async function probeServer(
  baseUrl: string,
  fetcher: typeof fetch,
  timeoutMs: number,
): Promise<{ ok: boolean; detail: string }> {
  const url = baseUrl.replace(/\/$/, '') + '/health'
  const controller = typeof AbortController !== 'undefined' ? new AbortController() : null
  const timer = controller ? setTimeout(() => controller.abort(), timeoutMs) : null
  try {
    const response = await fetcher(url, {
      method: 'GET',
      signal: controller?.signal,
      headers: { Accept: 'application/json' },
    })
    if (!response.ok) {
      return { ok: false, detail: `健康检查返回 HTTP ${response.status}` }
    }
    return { ok: true, detail: '家庭服务器 /health 可达' }
  } catch (cause) {
    const aborted = controller?.signal.aborted === true
    return {
      ok: false,
      detail: aborted ? '健康检查超时' : `无法连接：${cause instanceof Error ? cause.message : '网络错误'}`,
    }
  } finally {
    if (timer) clearTimeout(timer)
  }
}

/** 演示前一键自检：麦权限、音色、可选服务器连通。 */
export async function runVoicePreflight(options: VoicePreflightOptions = {}): Promise<VoicePreflightReport> {
  const speechInput = isSpeechInputSupported()
  const speechOutput = isSpeechOutputSupported()
  const microphone = await queryMicrophonePermission()
  const voices = await inspectChineseVoicePacks()
  let serverReachable: boolean | null = null
  let serverDetail = '未配置服务器地址（跳过连通检查）'
  if (options.serverBaseUrl?.trim()) {
    const probe = await probeServer(
      options.serverBaseUrl.trim(),
      options.fetcher ?? globalThis.fetch.bind(globalThis),
      options.timeoutMs ?? 4000,
    )
    serverReachable = probe.ok
    serverDetail = probe.detail
  }

  const guidance: string[] = []
  if (!speechInput) guidance.push('当前环境无 SpeechRecognition，请改用文字输入或更换 WebView/浏览器。')
  if (microphone === 'denied') guidance.push('麦克风权限被拒绝：请到系统设置允许后重试。')
  if (microphone === 'prompt' || microphone === null) {
    guidance.push('麦克风尚未授权：进入助手页后需点按一次允许开麦。')
  }
  if (!speechOutput) guidance.push('不支持语音播报：请阅读文字回答。')
  else if (!voices.preferredNatural) guidance.push(voices.guidance)
  if (serverReachable === false) guidance.push(`服务器连通失败：${serverDetail}`)
  if (guidance.length === 0) {
    guidance.push('基础检查通过。请再试说「小燕小燕」做一次唤醒手感验收。')
  }

  return {
    speechInput,
    speechOutput,
    microphone,
    voices,
    serverReachable,
    serverDetail,
    guidance,
  }
}
