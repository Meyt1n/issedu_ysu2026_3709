import {
  couldBeVoiceCommandPrefix,
  matchVoiceCommand,
  VOICE_COMMAND_HINT,
  type VoiceCommandId,
} from './commands'
import { applyHotwordCorrections, endsWithContinuationCue, type HotwordPair } from './hotwords'
import {
  createSpeechRecognition,
  DEFAULT_WAKE_PHRASE,
  DICTATION_SILENCE_MS,
  isSpeechInputSupported,
  latestTranscriptFromEvent,
  queryMicrophonePermission,
  transcriptFromEvent,
  VOICE_RESTART_DELAY_MS,
  type SpeechRecognitionLike,
} from './recognition'
import { DEFAULT_VOICE_PREFERENCES, type VoicePreferences } from './prefs'
import {
  containsConfiguredWakePhrase,
  transcriptAfterConfiguredWakePhrase,
} from './wakePhrase'

export type DictationMode = 'off' | 'wake' | 'active' | 'paused' | 'ready' | 'command'

export interface DictationHandlers {
  onModeChange?: (mode: DictationMode) => void
  onPreview?: (text: string) => void
  onDraft?: (text: string) => void
  onError?: (message: string, fatal?: boolean) => void
  /** 静音结束：草稿已就绪，麦克风已停，适合聚焦发送按钮。 */
  onUtteranceComplete?: (draft: string) => void
  /** 需要一次用户手势才能开麦时回调（页面可展示大按钮）。 */
  onNeedGesture?: () => void
  /** 白名单语音指令（不含开放域意图）。 */
  onCommand?: (command: VoiceCommandId, draft: string) => void
}

export interface DictationControllerOptions {
  getHotwordExtras?: () => ReadonlyArray<HotwordPair>
  getPreferences?: () => Pick<
    VoicePreferences,
    'silenceMs' | 'continuationSilenceMs' | 'doubleWake' | 'wakePhrase' | 'voiceCommands'
  >
}

export interface DictationController {
  getMode: () => DictationMode
  getDraft: () => string
  getWakePhrase: () => string
  /** 已授权则直接唤醒聆听；否则触发 onNeedGesture。 */
  tryAutoStart: () => Promise<void>
  startWake: (draftPrefix?: string) => void
  /** 听写中暂停识别，保留草稿，便于手动改字。 */
  pause: () => void
  /** 从当前草稿继续听写（不重新等唤醒）。 */
  resumeDictation: () => void
  /** ready 态：清空本次口述并重新听写。 */
  redoDictation: () => void
  /** 在 ready 后聆听白名单指令。 */
  startCommandListen: () => void
  stop: () => void
  dispose: () => void
}

const WAKE_CONFIRM_MS = 2500

/**
 * 共享听写状态机：
 * off → wake → active → ready →（可选）command；active 可 pause/resume。
 */
export function createDictationController(
  handlers: DictationHandlers = {},
  options: DictationControllerOptions = {},
): DictationController {
  let mode: DictationMode = 'off'
  let recognition: SpeechRecognitionLike | null = null
  let sessionId = 0
  let stopRequested = false
  let fatal = false
  let draftPrefix = ''
  let currentDraft = ''
  let restartTimer: ReturnType<typeof setTimeout> | null = null
  let silenceTimer: ReturnType<typeof setTimeout> | null = null
  let wakeConfirmTimer: ReturnType<typeof setTimeout> | null = null
  let wakeHits = 0
  let disposed = false

  function prefs() {
    return {
      ...DEFAULT_VOICE_PREFERENCES,
      ...options.getPreferences?.(),
    }
  }

  function wakePhrase(): string {
    return prefs().wakePhrase?.trim() || DEFAULT_WAKE_PHRASE
  }

  function setMode(next: DictationMode): void {
    mode = next
    handlers.onModeChange?.(next)
  }

  function clearTimers(): void {
    if (restartTimer) {
      clearTimeout(restartTimer)
      restartTimer = null
    }
    if (silenceTimer) {
      clearTimeout(silenceTimer)
      silenceTimer = null
    }
    if (wakeConfirmTimer) {
      clearTimeout(wakeConfirmTimer)
      wakeConfirmTimer = null
    }
  }

  function finishUtterance(): void {
    if (mode !== 'active') return
    clearTimers()
    const active = recognition
    recognition = null
    try {
      active?.stop()
    } catch {
      try {
        active?.abort()
      } catch {
        // ignore
      }
    }
    const draft = currentDraft.trim()
    setMode('ready')
    handlers.onPreview?.(draft ? `已记下：${draft}` : '已停止聆听，请确认后发送')
    handlers.onUtteranceComplete?.(draft)
    if (prefs().voiceCommands) {
      // 稍后再开指令聆听，避免把确认音吃进指令。
      setTimeout(() => {
        if (!disposed && mode === 'ready') startCommandListen()
      }, 400)
    }
  }

  function armSilenceTimer(): void {
    if (silenceTimer) clearTimeout(silenceTimer)
    const settings = prefs()
    const delay = endsWithContinuationCue(currentDraft)
      ? settings.continuationSilenceMs
      : settings.silenceMs
    silenceTimer = setTimeout(() => {
      silenceTimer = null
      finishUtterance()
    }, delay || DICTATION_SILENCE_MS)
  }

  function scheduleRestart(id: number): void {
    if (restartTimer) clearTimeout(restartTimer)
    restartTimer = setTimeout(() => {
      restartTimer = null
      if (disposed || id !== sessionId || stopRequested || fatal) return
      if (mode !== 'wake' && mode !== 'active' && mode !== 'command') return
      startRecognition(id)
    }, VOICE_RESTART_DELAY_MS)
  }

  function correct(text: string): string {
    return applyHotwordCorrections(text, options.getHotwordExtras?.() ?? [])
  }

  function acceptWake(): void {
    setMode('active')
    wakeHits = 0
    draftPrefix = currentDraft.trim() ? `${currentDraft.trim()} ` : draftPrefix
    handlers.onPreview?.('已唤醒，请说出问题')
  }

  function noteWakeHit(probe: string): boolean {
    const settings = prefs()
    const phrase = wakePhrase()
    if (!settings.doubleWake) {
      acceptWake()
      return true
    }
    wakeHits += 1
    if (wakeHits >= 2) {
      if (wakeConfirmTimer) {
        clearTimeout(wakeConfirmTimer)
        wakeConfirmTimer = null
      }
      acceptWake()
      return true
    }
    handlers.onPreview?.(`听到唤醒（${probe}），请再说一次「${phrase}」确认`)
    if (wakeConfirmTimer) clearTimeout(wakeConfirmTimer)
    wakeConfirmTimer = setTimeout(() => {
      wakeConfirmTimer = null
      wakeHits = 0
      if (mode === 'wake') {
        handlers.onPreview?.(`等待唤醒：请说「${phrase}」`)
      }
    }, WAKE_CONFIRM_MS)
    return false
  }

  function handleCommandTranscript(raw: string): void {
    const command = matchVoiceCommand(raw)
    if (!command) {
      handlers.onPreview?.(`未识别指令。${VOICE_COMMAND_HINT}`)
      return
    }
    handlers.onPreview?.(`指令：${command}`)
    handlers.onCommand?.(command, currentDraft.trim())
  }

  function startRecognition(id: number): void {
    if (!isSpeechInputSupported()) {
      fatal = true
      setMode('off')
      handlers.onError?.('当前设备不支持连续语音输入，请改用文字输入。', true)
      return
    }
    const next = createSpeechRecognition('zh-CN', {
      continuous: true,
      interimResults: true,
      maxAlternatives: 3,
    })
    if (!next) {
      fatal = true
      setMode('off')
      handlers.onError?.('当前设备不支持连续语音输入，请改用文字输入。', true)
      return
    }

    const phrase = wakePhrase()

    next.onstart = () => {
      if (id !== sessionId) return
      handlers.onError?.('')
    }
    next.onresult = (event) => {
      if (id !== sessionId) return
      const latest = latestTranscriptFromEvent(event)
      const transcript = transcriptFromEvent(event)
      if (!latest && !transcript) return

      if (mode === 'command') {
        const probe = latest || transcript
        // 仅在出现较完整短语时匹配，减少 interim 误触
        if (probe.trim().length < 2) return
        const command = matchVoiceCommand(probe) ?? matchVoiceCommand(transcript)
        if (command) {
          handleCommandTranscript(probe)
          return
        }
        if (couldBeVoiceCommandPrefix(probe) || couldBeVoiceCommandPrefix(transcript)) {
          handlers.onPreview?.(`正在听指令：${probe}`)
          return
        }
        // 非指令语音：回到听写态累加进草稿，禁止丢弃（页面收到 active 后应取消自动发送倒计时）。
        draftPrefix = currentDraft.trim() ? `${currentDraft.trim()} ` : ''
        setMode('active')
        handlers.onPreview?.('听到继续口述，已回到听写')
      }

      if (mode === 'wake') {
        const wakeProbe = latest || transcript
        if (
          !containsConfiguredWakePhrase(wakeProbe, phrase)
          && !containsConfiguredWakePhrase(transcript, phrase)
        ) {
          handlers.onPreview?.(`正在聆听：${wakeProbe || transcript}`)
          return
        }
        if (!noteWakeHit(wakeProbe || transcript)) return
      }

      if (mode !== 'active') return

      const spokenSource = containsConfiguredWakePhrase(transcript, phrase)
        ? transcript
        : containsConfiguredWakePhrase(latest, phrase)
          ? latest
          : transcript
      const spokenRaw = containsConfiguredWakePhrase(spokenSource, phrase)
        ? transcriptAfterConfiguredWakePhrase(spokenSource, phrase)
        : spokenSource.trim()
      const spoken = correct(spokenRaw)
      if (spoken) {
        currentDraft = `${draftPrefix}${spoken}`.trimStart()
        handlers.onDraft?.(currentDraft)
        handlers.onPreview?.(`正在输入：${spoken}`)
        armSilenceTimer()
      } else {
        handlers.onPreview?.('已唤醒，请说出问题')
        armSilenceTimer()
      }
    }
    next.onerror = (event) => {
      if (id !== sessionId) return
      const error = event.error ?? ''
      if (error === 'no-speech' || error === 'aborted') return
      if (error === 'not-allowed' || error === 'service-not-allowed') {
        fatal = true
        stopRequested = true
        setMode('off')
        handlers.onError?.('麦克风权限未开启，请允许后点按页面重试，或改用文字输入。', true)
        return
      }
      if (error === 'audio-capture') {
        fatal = true
        stopRequested = true
        setMode('off')
        handlers.onError?.('没有检测到可用麦克风，请检查设备或改用文字输入。', true)
        return
      }
      handlers.onError?.('语音识别暂时中断，正在重试；也可改用文字输入。')
    }
    next.onend = () => {
      if (id !== sessionId) return
      if (recognition === next) recognition = null
      if (mode === 'ready' || mode === 'off' || mode === 'paused') return
      if (!stopRequested && !fatal && (mode === 'wake' || mode === 'active' || mode === 'command')) {
        if (mode === 'active') {
          draftPrefix = currentDraft.trim() ? `${currentDraft.trim()} ` : ''
        }
        scheduleRestart(id)
      }
    }

    recognition = next
    try {
      next.start()
    } catch {
      if (id !== sessionId) return
      fatal = true
      stopRequested = true
      recognition = null
      setMode('off')
      handlers.onError?.('语音输入未能启动，请点按页面后重试或改用文字输入。', true)
    }
  }

  function stopRecognitionOnly(): void {
    stopRequested = true
    sessionId += 1
    clearTimers()
    const current = recognition
    recognition = null
    try {
      current?.abort()
    } catch {
      // ignore
    }
  }

  function stop(): void {
    stopRecognitionOnly()
    fatal = false
    wakeHits = 0
    setMode('off')
    handlers.onPreview?.('')
  }

  function pause(): void {
    if (mode !== 'active' && mode !== 'wake' && mode !== 'command') return
    stopRecognitionOnly()
    fatal = false
    setMode('paused')
    handlers.onPreview?.('已暂停听写，可改字后再点「继续说」')
  }

  function startWake(prefix = ''): void {
    if (disposed) return
    if (!isSpeechInputSupported()) {
      handlers.onError?.('当前浏览器/WebView 不支持语音输入，请改用文字。', true)
      handlers.onNeedGesture?.()
      return
    }
    stopRequested = false
    fatal = false
    wakeHits = 0
    clearTimers()
    const current = recognition
    recognition = null
    try {
      current?.abort()
    } catch {
      // ignore
    }
    draftPrefix = prefix.trim() ? `${prefix.trim()} ` : ''
    currentDraft = prefix.trim()
    const id = ++sessionId
    const phrase = wakePhrase()
    setMode('wake')
    handlers.onPreview?.(
      prefs().doubleWake
        ? `等待唤醒：请连说两遍「${phrase}」（或间隔再说一次确认）`
        : `等待唤醒：请说「${phrase}」`,
    )
    startRecognition(id)
  }

  function startCommandListen(): void {
    if (disposed) return
    if (!prefs().voiceCommands) return
    if (!isSpeechInputSupported()) return
    stopRequested = false
    fatal = false
    wakeHits = 0
    clearTimers()
    const current = recognition
    recognition = null
    try {
      current?.abort()
    } catch {
      // ignore
    }
    const id = ++sessionId
    setMode('command')
    handlers.onPreview?.(VOICE_COMMAND_HINT)
    startRecognition(id)
  }

  function resumeDictation(): void {
    if (disposed) return
    if (!isSpeechInputSupported()) {
      handlers.onNeedGesture?.()
      return
    }
    stopRequested = false
    fatal = false
    wakeHits = 0
    clearTimers()
    const current = recognition
    recognition = null
    try {
      current?.abort()
    } catch {
      // ignore
    }
    draftPrefix = currentDraft.trim() ? `${currentDraft.trim()} ` : ''
    const id = ++sessionId
    setMode('active')
    handlers.onPreview?.('继续说，说完后会自动停下')
    startRecognition(id)
  }

  function redoDictation(): void {
    currentDraft = ''
    draftPrefix = ''
    handlers.onDraft?.('')
    resumeDictation()
  }

  async function tryAutoStart(): Promise<void> {
    if (disposed) return
    if (!isSpeechInputSupported()) {
      handlers.onNeedGesture?.()
      return
    }
    const permission = await queryMicrophonePermission()
    if (permission === 'granted') {
      startWake(currentDraft)
      return
    }
    if (permission === 'denied') {
      handlers.onError?.('麦克风权限被拒绝，请在系统设置中允许后重试，或改用文字输入。', true)
      handlers.onNeedGesture?.()
      return
    }
    handlers.onNeedGesture?.()
  }

  function dispose(): void {
    disposed = true
    stop()
  }

  return {
    getMode: () => mode,
    getDraft: () => currentDraft,
    getWakePhrase: () => wakePhrase(),
    tryAutoStart,
    startWake,
    pause,
    resumeDictation,
    redoDictation,
    startCommandListen,
    stop,
    dispose,
  }
}
