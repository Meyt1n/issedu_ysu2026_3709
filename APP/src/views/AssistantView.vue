<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'

import { activeProvider } from '@/data'
import type { MemberSummary } from '@/data/types'
import AppIcon from '@/components/AppIcon.vue'
import { ApiClientError } from '@/api/client'
import type { AssistantResponse, EvidencePreview } from '@/api/types'
import { createLiveApiClient } from '@/data'
import {
  AUTO_SEND_PRESETS,
  clearChatSession,
  createAutoSendScheduler,
  createDictationController,
  getSpeakingIndex,
  getSpeakingSegments,
  isSpeechInputSupported,
  jumpSpeakingSegment,
  loadVoicePreferences,
  memberNameHotwordPairs,
  loadChatSession,
  saveChatSession,
  saveVoicePreferences,
  sessionEntryToStored,
  skipSpeakingSegment,
  speakText,
  stopSpeaking,
  validateWakePhrase,
  WAKE_PHRASE_PRESETS,
  type DictationController,
  type DictationMode,
  type StoredChatEntry,
  type VoiceCommandId,
  type VoicePreferences,
} from '@/composables/useVoiceInput'
import { useA11y } from '@/stores/accessibility'
import { useSession } from '@/stores/session'

interface ChatEntry {
  role: 'user' | 'assistant'
  content: string
  degraded?: boolean
  degradeReason?: string | null
  sources?: string[]
  suggestedQuestions?: string[]
  queryType?: string | null
  networkUsed?: boolean
  agentTraceSummary?: string
}

const PHASE_LABELS: Record<string, string> = {
  routing: '正在识别问题类型…',
  retrieving: '正在核对档案与本地资料…',
  searching: '正在获取脱敏联网参考…',
  generating: '正在本机生成回答…',
  validating: '正在校验引用与安全边界…',
}

const { session } = useSession()
const { settings } = useA11y()

const history = ref<ChatEntry[]>([])
const draft = ref('')
const sending = ref(false)
const sendError = ref('')
const voiceError = ref('')
const voicePreview = ref('')
const voiceMode = ref<DictationMode>('off')
const speakingIndex = ref<number | null>(null)
const speakingProgress = ref('')
const needMicGesture = ref(false)
const chatEnd = ref<HTMLElement | null>(null)
const orchestrationPhase = ref<string | null>(null)
const allowNetworkSearch = ref(false)
const liveEvidencePreview = ref<EvidencePreview | null>(null)
const cancelStatus = ref('')

function createAssistantSessionId(): string {
  return globalThis.crypto?.randomUUID?.()
    ?? `app-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 18)}`
}

const assistantSessionId = ref(createAssistantSessionId())
const draftInput = ref<HTMLTextAreaElement | null>(null)
const sendButton = ref<HTMLButtonElement | null>(null)
const memberSummaries = ref<MemberSummary[]>([])
const speakingSegmentIndex = ref(0)
const voicePrefs = ref<VoicePreferences>(loadVoicePreferences())
const wakePhraseDraft = ref(voicePrefs.value.wakePhrase)
const voiceSendHint = ref('')

const speechInputSupported = isSpeechInputSupported()
const wakePhrase = computed(() => voicePrefs.value.wakePhrase)

const sendConfirmGate = createAutoSendScheduler({
  onArmed: (delayMs) => {
    const sec = Math.round(delayMs / 1000)
    voiceSendHint.value = `无新输入，约 ${sec} 秒后自动发送；可说「取消」或「继续说」`
    if (loadVoicePreferences().confirmSound) speakText(`${sec} 秒后发送，可说取消`)
  },
  onTick: (remainMs) => {
    if (remainMs <= 0) return
    const sec = Math.max(1, Math.ceil(remainMs / 1000))
    voiceSendHint.value = `无新输入，${sec} 秒后自动发送；可说「取消」「继续说」，或说「发送吧」立即发送`
  },
  onAutoSend: (content) => {
    voiceSendHint.value = ''
    if (content.trim() && !sending.value) void send(content)
  },
  onCancelled: () => {
    voiceSendHint.value = '已取消自动发送'
  },
})
const memberHotwordExtras = computed(() =>
  memberNameHotwordPairs(memberSummaries.value.map(member => member.name)),
)
const listening = computed(() =>
  voiceMode.value === 'wake' || voiceMode.value === 'active' || voiceMode.value === 'command',
)
const liveMode = computed(() => session.dataMode === 'live')
const serverLabel = computed(() => session.serverBaseUrl.trim() || '（未填写服务器地址）')
const assistantReady = computed(() => liveMode.value && Boolean(session.serverBaseUrl.trim()))
const thinkingText = computed(() => {
  if (orchestrationPhase.value && PHASE_LABELS[orchestrationPhase.value]) {
    return PHASE_LABELS[orchestrationPhase.value]
  }
  return '正在本机分析…'
})

const voiceStatusLabel = computed(() => {
  if (voiceMode.value === 'wake') return `正在聆听唤醒词：「${wakePhrase.value}」`
  if (voiceMode.value === 'active') return '已唤醒，识别中的文字会实时填入草稿'
  if (voiceMode.value === 'ready' || voiceMode.value === 'command') {
    return voiceSendHint.value || '说完后会倒计时自动发送；可说取消、继续说，或发送吧立即发送'
  }
  return needMicGesture.value ? '点按下方按钮一次以开启麦克风聆听' : ''
})

let activeSendController: AbortController | null = null
// 「结束回复」：abort 请求但保留当前已显示内容，不再有新输出（决策 4B）。
let keepPartialReply = false

function cancelActiveSend(): void {
  if (activeSendController) {
    activeSendController.abort()
    activeSendController = null
  }
}

function finishReplyEarly(): void {
  if (!activeSendController) return
  keepPartialReply = true
  cancelActiveSend()
}

function isAssistantCancellation(cause: unknown): boolean {
  return cause instanceof ApiClientError
    && (cause.code === 'CANCELLED' || cause.message.includes('CANCELLED'))
}

const evidencePreviewText = computed(() => {
  const preview = liveEvidencePreview.value
  if (!preview) return ''
  const parts = [
    `档案 ${preview.database_tools.length} 项`,
    `规则 ${preview.rule_tools.length} 项`,
    `本地资料 ${preview.knowledge_count} 条`,
  ]
  if (preview.external_count) parts.push(`外部参考 ${preview.external_count} 条`)
  return `已找到可核对依据：${parts.join(' · ')}。预览不含健康正文。`
})

watch(
  () => [
    session.dataMode,
    session.serverBaseUrl,
    session.actorId,
    session.currentHouseholdId,
    session.currentMemberId,
  ],
  (_current, previous) => {
    if (!previous) return
    cancelActiveSend()
    assistantSessionId.value = createAssistantSessionId()
    liveEvidencePreview.value = null
    cancelStatus.value = ''
  },
)

const voiceButtonLabel = computed(() => {
  if (voiceMode.value === 'wake') return '等待唤醒'
  if (voiceMode.value === 'active') return '停止语音'
  if (voiceMode.value === 'ready' || voiceMode.value === 'command') return '重新聆听'
  return needMicGesture.value ? '允许麦克风并聆听' : '开启唤醒'
})

const autoSendPresetId = computed(() => {
  const match = AUTO_SEND_PRESETS.find(preset => preset.delayMs === voicePrefs.value.autoSendDelayMs)
  return match?.id ?? 'custom'
})

let dictation: DictationController | null = null

function scrollToEnd(): void {
  void nextTick(() => chatEnd.value?.scrollIntoView({ block: 'end', behavior: 'smooth' }))
}

function requestOptions() {
  return {
    actorId: session.actorId || undefined,
    accessPurpose: session.accessPurpose || undefined,
  }
}

function persistChatSession(): void {
  saveChatSession(
    session.actorId,
    session.currentHouseholdId,
    session.currentMemberId,
    history.value.map((entry) => sessionEntryToStored(entry)),
  )
}

function restoreChatSession(entries: StoredChatEntry[]): void {
  history.value = entries.map((entry) => ({
    role: entry.role,
    content: entry.content,
    degraded: entry.degraded,
    degradeReason: entry.degradeReason,
    sources: entry.sources,
    suggestedQuestions: entry.suggestedQuestions,
  }))
  scrollToEnd()
}

function applyWakePreset(phrase: string): void {
  wakePhraseDraft.value = phrase
  saveWakePhrase()
}

function applyAutoSendPreset(presetId: string): void {
  const preset = AUTO_SEND_PRESETS.find(item => item.id === presetId)
  if (!preset) return
  voicePrefs.value = saveVoicePreferences({ autoSendDelayMs: preset.delayMs })
  sendConfirmGate.reset()
  voiceSendHint.value = ''
}

function saveWakePhrase(): void {
  const checked = validateWakePhrase(wakePhraseDraft.value)
  if (!checked.ok) {
    voiceError.value = checked.message
    wakePhraseDraft.value = voicePrefs.value.wakePhrase
    return
  }
  voiceError.value = ''
  voicePrefs.value = saveVoicePreferences({ wakePhrase: checked.phrase })
  wakePhraseDraft.value = checked.phrase
  if (listening.value || voiceMode.value === 'command' || voiceMode.value === 'ready') {
    void beginWakeListening()
  }
}

function repeatLastAnswer(): void {
  const last = [...history.value].reverse().find(entry => entry.role === 'assistant' && entry.content.trim())
  if (!last) {
    voiceError.value = '还没有可朗读的回答。'
    return
  }
  const index = history.value.lastIndexOf(last)
  toggleSpeech(index, last.content)
}

function armAutoSend(draftText?: string): void {
  const delay = loadVoicePreferences().autoSendDelayMs
  if (!delay || delay <= 0) {
    voiceSendHint.value = '已听完，请确认后点发送；也可说「发送吧」立即发送'
    return
  }
  sendConfirmGate.start(draftText ?? draft.value, delay)
}

function handleVoiceCommand(command: VoiceCommandId): void {
  if (command === 'confirm_send') {
    if (!draft.value.trim() || sending.value) {
      voiceError.value = '没有可发送的草稿。'
      return
    }
    sendConfirmGate.reset()
    voiceSendHint.value = ''
    void send()
    return
  }
  if (command === 'cancel_send') {
    sendConfirmGate.cancel()
    return
  }
  if (command === 'repeat_answer') {
    sendConfirmGate.cancel()
    repeatLastAnswer()
    return
  }
  if (command === 'stop_speaking') {
    stopSpeaking()
    speakingIndex.value = null
    speakingProgress.value = ''
    return
  }
  if (command === 'redo_dictation') {
    sendConfirmGate.reset()
    ensureDictation().redoDictation()
    return
  }
  if (command === 'resume_dictation') {
    sendConfirmGate.cancel()
    ensureDictation().resumeDictation()
  }
}

function ensureDictation(): DictationController {
  if (dictation) return dictation
  dictation = createDictationController({
    onModeChange: (mode) => {
      voiceMode.value = mode
      if (mode === 'active') {
        // 续说回到听写态（含指令期非指令语音回流）：取消倒计时，避免草稿被中途发出。
        sendConfirmGate.reset()
        voiceSendHint.value = ''
      }
    },
    onPreview: (text) => {
      voicePreview.value = text
    },
    onDraft: (text) => {
      draft.value = text
    },
    onError: (message) => {
      voiceError.value = message
    },
    onNeedGesture: () => {
      needMicGesture.value = true
    },
    onUtteranceComplete: (utteranceDraft) => {
      needMicGesture.value = false
      void nextTick(() => sendButton.value?.focus())
      armAutoSend(utteranceDraft || draft.value)
    },
    onCommand: (command) => {
      handleVoiceCommand(command)
    },
  }, {
    getHotwordExtras: () => memberHotwordExtras.value,
    getPreferences: () => loadVoicePreferences(),
  })
  return dictation
}

function onDraftFocus(): void {
  if (voiceMode.value === 'active' || voiceMode.value === 'wake') {
    ensureDictation().pause()
  }
  sendConfirmGate.cancel()
}

function editDraftLine(): void {
  sendConfirmGate.cancel()
  ensureDictation().pause()
  void nextTick(() => draftInput.value?.focus())
}

function redoVoiceDraft(): void {
  sendConfirmGate.reset()
  ensureDictation().redoDictation()
}

function jumpSpeechSegment(index: number): void {
  if (jumpSpeakingSegment(index)) {
    speakingSegmentIndex.value = getSpeakingIndex()
  }
}

const activeSpeakingSegments = computed(() =>
  speakingIndex.value !== null ? [...getSpeakingSegments()] : [],
)

async function loadMemberHotwords(): Promise<void> {
  try {
    memberSummaries.value = await activeProvider().listMembers()
  } catch {
    memberSummaries.value = []
  }
}

function stopVoiceInput(): void {
  dictation?.stop()
  voicePreview.value = ''
  needMicGesture.value = false
  sendConfirmGate.reset()
  voiceSendHint.value = ''
}

async function beginWakeListening(): Promise<void> {
  if (!speechInputSupported) {
    voiceError.value = '当前浏览器/WebView 不支持语音输入，请改用文字。'
    return
  }
  if (speakingIndex.value !== null) {
    stopSpeaking()
    speakingIndex.value = null
    speakingProgress.value = ''
  }
  needMicGesture.value = false
  voiceError.value = ''
  ensureDictation().startWake(draft.value)
}

async function bootstrapVoice(): Promise<void> {
  if (!speechInputSupported) return
  await ensureDictation().tryAutoStart()
}

function toggleVoiceInput(): void {
  if (voiceMode.value === 'wake' || voiceMode.value === 'active') {
    stopVoiceInput()
    return
  }
  void beginWakeListening()
}

function startReplySpeech(index: number, content: string, resumeListeningAfter: boolean): boolean {
  speakingProgress.value = ''
  speakingSegmentIndex.value = 0
  const started = speakText(content, {
    onFinished: () => {
      if (speakingIndex.value === index) {
        speakingIndex.value = null
        speakingProgress.value = ''
        speakingSegmentIndex.value = 0
      }
      // 播报真正结束后再回到唤醒聆听，避免开麦把播报掐断。
      if (resumeListeningAfter && !sending.value && !needMicGesture.value) {
        void beginWakeListening()
      }
    },
    onProgress: (progress) => {
      speakingSegmentIndex.value = progress.index
      speakingProgress.value = `正在朗读 ${progress.index + 1}/${progress.total}`
    },
  })
  if (started) speakingIndex.value = index
  return started
}

function toggleSpeech(index: number, content: string): void {
  if (speakingIndex.value === index) {
    stopSpeaking()
    speakingIndex.value = null
    speakingProgress.value = ''
    return
  }
  if (listening.value) stopVoiceInput()
  if (!startReplySpeech(index, content, false)) {
    voiceError.value = '当前无法语音播报，请阅读文字回答。可先安装 Natural 类中文语音包。'
  }
}

function skipCurrentSpeechSegment(): void {
  skipSpeakingSegment()
}

function applySuggested(question: string): void {
  draft.value = question
  stopVoiceInput()
}

function resendAsMedicationSafety(replyIndex: number): void {
  for (let index = replyIndex - 1; index >= 0; index -= 1) {
    const entry = history.value[index]
    if (entry?.role === 'user') {
      void send(entry.content, 'MEDICATION_SAFETY')
      return
    }
  }
}

function summarizeAgentTrace(reply: AssistantResponse): string | undefined {
  const traces = reply.agent_trace ?? []
  if (!traces.length) return undefined
  const completed = traces.filter((item) => item.status === 'completed').length
  const skipped = traces.filter((item) => item.status === 'skipped').length
  const parts = [`本地分析 ${completed} 步完成`]
  if (skipped) parts.push(`${skipped} 步跳过`)
  if (reply.network_used) parts.push('含脱敏联网参考')
  return parts.join(' · ')
}

function applyAssistantReply(entryIndex: number, reply: AssistantResponse): void {
  const entry = history.value[entryIndex]
  if (!entry) return
  entry.content = reply.answer
  entry.degraded = reply.degraded
  entry.degradeReason = reply.degrade_reason
  entry.sources = reply.sources
  entry.suggestedQuestions = (reply.suggested_questions ?? []).filter(
    (item) => typeof item === 'string' && item.trim(),
  )
  entry.queryType = reply.query_type
  entry.networkUsed = reply.network_used
  entry.agentTraceSummary = summarizeAgentTrace(reply)
  if (reply.degraded) {
    sendError.value = reply.degrade_reason
      ? `回答已降级：${reply.degrade_reason}`
      : '回答已降级，请稍后重试或检查家庭服务器与模型服务。'
  }
  persistChatSession()
  scrollToEnd()
  if (settings.voiceBroadcast && reply.answer.trim()) {
    if (listening.value) stopVoiceInput()
    // 播报完成后由 startReplySpeech 的 onFinished 回到唤醒聆听，避免被 send() 收尾掐断。
    startReplySpeech(entryIndex, reply.answer, true)
  }
}

/** 取消/结束回复的收尾：结束回复保留已显示内容，普通停止移除未完成气泡。 */
function settleCancelledReply(entryIndex: number, streamingEntry: ChatEntry): void {
  const entry = history.value[entryIndex]
  if (keepPartialReply && entry === streamingEntry && entry.content.trim()) {
    cancelStatus.value = '已结束回复，保留已生成的内容'
  } else {
    if (entry === streamingEntry) history.value.splice(entryIndex, 1)
    cancelStatus.value = '已停止'
  }
  keepPartialReply = false
  persistChatSession()
  scrollToEnd()
}

async function send(text?: string, queryTypeOverride?: string): Promise<void> {
  const content = (text ?? draft.value).trim()
  if (!content || sending.value) return

  cancelActiveSend()
  stopVoiceInput()
  stopSpeaking()
  speakingIndex.value = null
  speakingProgress.value = ''
  keepPartialReply = false

  history.value.push({ role: 'user', content })
  persistChatSession()
  draft.value = ''
  sending.value = true
  sendError.value = ''
  cancelStatus.value = ''
  liveEvidencePreview.value = null
  orchestrationPhase.value = 'routing'
  scrollToEnd()

  if (!liveMode.value) {
    history.value.push({
      role: 'assistant',
      content:
        '当前是演示模式，助手不会连接家庭服务器。请到「我的」切换为「家庭服务器（联机）」，填写电脑后端地址（例如 http://192.168.x.x:8000）后再提问。',
      degraded: true,
      degradeReason: 'demo_mode',
    })
    persistChatSession()
    sending.value = false
    orchestrationPhase.value = null
    scrollToEnd()
    if (!needMicGesture.value) void beginWakeListening()
    return
  }

  if (!session.serverBaseUrl.trim()) {
    history.value.push({
      role: 'assistant',
      content: '尚未填写家庭服务器地址。请到「我的」填写电脑上 FastAPI 的局域网地址后再试。',
      degraded: true,
      degradeReason: 'missing_server',
    })
    persistChatSession()
    sending.value = false
    orchestrationPhase.value = null
    scrollToEnd()
    if (!needMicGesture.value) void beginWakeListening()
    return
  }

  const client = createLiveApiClient()
  if (!client) {
    history.value.push({
      role: 'assistant',
      content: '当前登录会话不可用，请先在「我的」完成联机登录后再使用助手。',
      degraded: true,
      degradeReason: 'auth_required',
    })
    persistChatSession()
    sending.value = false
    orchestrationPhase.value = null
    scrollToEnd()
    if (!needMicGesture.value) void beginWakeListening()
    return
  }

  const controller = new AbortController()
  activeSendController = controller
  const messages = history.value.map((entry) => ({ role: entry.role, content: entry.content }))
  const chatInput = {
    messages,
    max_tokens: 1024,
    agent_mode: 'multi_agent' as const,
    allow_network_search: allowNetworkSearch.value,
    query_type_override: queryTypeOverride,
    assistant_session_id: assistantSessionId.value,
  }
  const householdId = session.currentHouseholdId || undefined
  const memberId = session.currentMemberId || undefined
  const requestOpts = { ...requestOptions(), signal: controller.signal }

  // 流式展示：token 直接写入这条气泡；结束回复/停止时按需保留或移除。
  const streamingEntry: ChatEntry = { role: 'assistant', content: '' }
  history.value.push(streamingEntry)
  const entryIndex = history.value.length - 1

  let streamStarted = false
  let streamCancelled = false

  try {
    try {
      const reply = await client.assistantChatStream(
        chatInput,
        {
          onStatus: (phase) => {
            orchestrationPhase.value = phase || 'retrieving'
          },
          onToken: (token) => {
            if (!token) return
            streamStarted = true
            streamingEntry.content += token
            orchestrationPhase.value = 'generating'
            scrollToEnd()
          },
          onEvidencePreview: (preview) => {
            liveEvidencePreview.value = preview
            scrollToEnd()
          },
          onCancelled: () => {
            streamCancelled = true
          },
        },
        householdId,
        memberId,
        requestOpts,
      )
      applyAssistantReply(entryIndex, reply)
    } catch (streamError) {
      if (controller.signal.aborted || streamCancelled || isAssistantCancellation(streamError)) {
        settleCancelledReply(entryIndex, streamingEntry)
        return
      }
      if (streamStarted && streamingEntry.content.trim()) {
        streamingEntry.content = streamingEntry.content.trim()
        streamingEntry.degraded = true
        streamingEntry.degradeReason = 'stream_incomplete'
        sendError.value = '流式连接中断，已保留已生成内容。'
        persistChatSession()
        scrollToEnd()
        return
      }
      const reply = await client.assistantChat(chatInput, householdId, memberId, requestOpts)
      applyAssistantReply(entryIndex, reply)
    }
  } catch (cause) {
    if (controller.signal.aborted || isAssistantCancellation(cause)) {
      settleCancelledReply(entryIndex, streamingEntry)
    } else {
      const message =
        cause instanceof ApiClientError
          ? cause.message
          : '家庭服务器暂时无法回答。请确认电脑后端已启动，且手机与电脑在同一局域网。'
      sendError.value = message
      const fallbackContent =
        '本地模型或其依赖当前不可用，无法生成回答。家庭事实、任务与提醒不受影响，可直接在对应页面查看。'
      const entry = history.value[entryIndex]
      if (entry === streamingEntry) {
        entry.content = fallbackContent
        entry.degraded = true
        entry.degradeReason = 'request_failed'
      } else {
        history.value.push({
          role: 'assistant',
          content: fallbackContent,
          degraded: true,
          degradeReason: 'request_failed',
        })
      }
      persistChatSession()
      scrollToEnd()
    }
  } finally {
    if (activeSendController === controller) activeSendController = null
    sending.value = false
    orchestrationPhase.value = null
    liveEvidencePreview.value = null
    // 自动播报进行中时不开麦回听（开麦会停止朗读）；播完由 onFinished 回听。
    if (!needMicGesture.value && speakingIndex.value === null) void beginWakeListening()
  }
}

function stopGenerating(): void {
  cancelActiveSend()
}

function clearChat(): void {
  cancelActiveSend()
  stopVoiceInput()
  stopSpeaking()
  speakingIndex.value = null
  speakingProgress.value = ''
  history.value = []
  assistantSessionId.value = createAssistantSessionId()
  draft.value = ''
  sendError.value = ''
  voiceError.value = ''
  cancelStatus.value = ''
  liveEvidencePreview.value = null
  orchestrationPhase.value = null
  clearChatSession(session.actorId, session.currentHouseholdId, session.currentMemberId)
}

function onVisibilityChange(): void {
  if (document.visibilityState === 'hidden') stopVoiceInput()
}

watch(
  () => [session.actorId, session.currentHouseholdId, session.currentMemberId] as const,
  ([actorId, householdId, memberId]) => {
    stopVoiceInput()
    stopSpeaking()
    speakingIndex.value = null
    restoreChatSession(loadChatSession(actorId, householdId, memberId))
  },
  { immediate: true },
)

onMounted(() => {
  void loadMemberHotwords()
  void bootstrapVoice()
  document.addEventListener('visibilitychange', onVisibilityChange)
})

onBeforeUnmount(() => {
  cancelActiveSend()
  document.removeEventListener('visibilitychange', onVisibilityChange)
  dictation?.dispose()
  dictation = null
  stopSpeaking()
})
</script>

<template>
  <main id="main" class="page assistant-page" tabindex="-1">
    <header class="page-header">
      <div>
        <p class="eyebrow">随身助手</p>
        <h1>语音提问</h1>
        <p class="lede">
          进入本页后会自动尝试聆听；首次需点按允许麦克风，再说「{{ wakePhrase }}」。
          说完静音后会倒计时自动发送；等待时可说「取消」「继续说」，或说「发送吧」立即发送。
        </p>
      </div>
      <RouterLink class="ghost-link" to="/me/voice-check">语音自检</RouterLink>
      <RouterLink class="ghost-link" to="/me">联机设置</RouterLink>
    </header>

    <section class="card status-card" aria-label="连接状态">
      <p>
        <strong>{{ liveMode ? '联机' : '演示' }}</strong>
        · 服务器 {{ serverLabel }}
      </p>
      <p class="meta-line">
        {{
          liveMode
            ? '联机后走本地多智能体流式接口；识别文字确认发送才请求家庭服务器，音频不会上传。'
            : '演示模式不调用后端。切换联机并填写电脑局域网地址后即可对话。'
        }}
      </p>
      <p v-if="assistantReady && liveMode" class="meta-line">
        家庭 {{ session.currentHouseholdId || '未选' }} · 成员 {{ session.currentMemberId || '未选' }}
        · 会话按身份/家庭/成员隔离（仅本标签页）
      </p>
      <label v-if="liveMode" class="network-toggle">
        <input v-model="allowNetworkSearch" type="checkbox" :disabled="sending" />
        允许本次脱敏联网参考（需家庭服务器已开启搜索）
      </label>
    </section>

    <section class="card chat-card" aria-label="对话">
      <div v-if="history.length === 0" class="empty-hint">
        还没有对话。可以打字提问，或开启语音唤醒。助手不做诊断、处方或剂量判断。
      </div>
      <article
        v-for="(entry, index) in history"
        v-show="entry.role === 'user' || entry.content.length > 0"
        :key="`${entry.role}-${index}`"
        class="bubble"
        :data-role="entry.role"
      >
        <p class="bubble-role">{{ entry.role === 'user' ? '我' : '助手' }}</p>
        <p class="bubble-text">{{ entry.content }}</p>
        <p v-if="entry.degraded" class="meta-line">降级说明：{{ entry.degradeReason || '受控降级' }}</p>
        <p v-if="entry.agentTraceSummary" class="meta-line">{{ entry.agentTraceSummary }}</p>
        <p v-if="entry.networkUsed" class="meta-line">含外部参考 · 需人工确认，不作诊断</p>
        <div v-if="entry.role === 'assistant' && entry.content" class="bubble-actions">
          <button
            v-if="sending && index === history.length - 1"
            type="button"
            class="btn btn-secondary"
            title="停止生成新的内容，保留上面已显示的回答"
            @click="finishReplyEarly"
          >
            结束回复
          </button>
          <button
            type="button"
            class="btn btn-secondary"
            :aria-pressed="speakingIndex === index"
            @click="toggleSpeech(index, entry.content)"
          >
            {{ speakingIndex === index ? '停止朗读' : '朗读回答' }}
          </button>
          <button
            type="button"
            class="btn btn-secondary"
            :disabled="sending"
            @click="resendAsMedicationSafety(index)"
          >
            按用药安全再查一次
          </button>
          <button
            v-if="speakingIndex === index && speakingProgress"
            type="button"
            class="btn btn-secondary"
            @click="skipCurrentSpeechSegment"
          >
            {{ speakingProgress }} · 跳过本句
          </button>
          <div
            v-if="speakingIndex === index && activeSpeakingSegments.length > 1"
            class="speech-segment-chips"
            aria-label="朗读分段跳转"
          >
            <button
              v-for="(segment, segmentIndex) in activeSpeakingSegments"
              :key="`${segmentIndex}-${segment.slice(0, 12)}`"
              type="button"
              class="chip"
              :class="{ active: speakingSegmentIndex === segmentIndex }"
              @click="jumpSpeechSegment(segmentIndex)"
            >
              第 {{ segmentIndex + 1 }} 句
            </button>
          </div>
        </div>
        <div v-if="entry.suggestedQuestions?.length" class="suggestions">
          <button
            v-for="question in entry.suggestedQuestions"
            :key="question"
            type="button"
            class="chip"
            @click="applySuggested(question)"
          >
            {{ question }}
          </button>
        </div>
      </article>
      <div ref="chatEnd" />
    </section>

    <p v-if="sending && evidencePreviewText" class="evidence-preview-line" role="status" aria-live="polite">
      {{ evidencePreviewText }}
    </p>
    <p v-if="sending" class="thinking-line" role="status" aria-live="polite">{{ thinkingText }}</p>
    <p v-if="cancelStatus" class="meta-line" role="status" aria-live="polite">{{ cancelStatus }}</p>
    <p v-if="sendError" class="error-line" role="alert">{{ sendError }}</p>
    <p v-if="voiceError" class="error-line" role="status">{{ voiceError }}</p>
    <p v-if="needMicGesture && !listening" class="voice-status" role="status">
      需要一次点按开启麦克风后，才会自动等待「{{ wakePhrase }}」。
    </p>
    <p v-if="voicePreview" class="voice-preview" role="status">{{ voicePreview }}</p>
    <p v-if="voiceStatusLabel" class="voice-status" role="status">{{ voiceStatusLabel }}</p>
    <p v-if="voiceSendHint && voiceMode === 'command'" class="voice-send-hint" role="status">
      {{ voiceSendHint }}
    </p>

    <form class="composer card" @submit.prevent="send()">
      <label class="sr-only" for="assistant-draft">问题草稿</label>
      <textarea
        id="assistant-draft"
        ref="draftInput"
        v-model="draft"
        rows="3"
        placeholder="输入问题，或语音唤醒后口述…"
        :disabled="sending"
        @focus="onDraftFocus"
      />
      <div v-if="voiceMode === 'ready'" class="ready-actions" role="group" aria-label="口述确认">
        <button ref="sendButton" type="submit" class="btn btn-primary btn-large" :disabled="sending || !draft.trim()">
          发送
        </button>
        <button type="button" class="btn btn-secondary" @click="editDraftLine">
          改一句
        </button>
        <button type="button" class="btn btn-secondary" @click="redoVoiceDraft">
          重说
        </button>
      </div>
      <div v-else class="composer-actions">
        <button
          type="button"
          class="btn btn-secondary mic-btn"
          :class="{ listening, active: voiceMode === 'active' }"
          :disabled="sending || !speechInputSupported"
          :aria-pressed="listening"
          :aria-label="listening ? '停止语音唤醒' : voiceButtonLabel"
          :title="speechInputSupported ? '进入页面自动聆听；首次需点按允许麦克风' : '当前不支持语音输入'"
          @click="toggleVoiceInput"
        >
          <AppIcon name="mic" :size="22" />
          {{ voiceButtonLabel }}
        </button>
        <button type="button" class="btn btn-secondary" :disabled="sending || history.length === 0" @click="clearChat">
          清空
        </button>
        <button
          v-if="sending"
          type="button"
          class="btn btn-secondary"
          @click="stopGenerating"
        >
          停止
        </button>
        <button ref="sendButton" type="submit" class="btn btn-primary" :disabled="sending || !draft.trim()">
          {{ sending ? '分析中…' : '发送' }}
        </button>
      </div>
    </form>

    <section class="card voice-prefs-hint" aria-label="语音偏好说明">
      <p class="meta-line">
        唤醒词与听写偏好可在
        <RouterLink to="/me/accessibility">无障碍设置</RouterLink>
        或
        <RouterLink to="/me/voice-check">语音自检</RouterLink>
        中调整。
      </p>
      <label class="pref-row">
        <span>唤醒词</span>
        <input
          v-model="wakePhraseDraft"
          type="text"
          maxlength="8"
          aria-label="自定义唤醒词"
          @change="saveWakePhrase"
        />
      </label>
      <div class="wake-presets">
        <button
          v-for="preset in WAKE_PHRASE_PRESETS"
          :key="preset.id"
          type="button"
          class="chip"
          @click="applyWakePreset(preset.phrase)"
        >
          {{ preset.label }}
        </button>
      </div>
      <label class="pref-row">
        <span>说完后自动发送</span>
        <select :value="autoSendPresetId" @change="applyAutoSendPreset(($event.target as HTMLSelectElement).value)">
          <option v-for="preset in AUTO_SEND_PRESETS" :key="preset.id" :value="preset.id">
            {{ preset.label }}
          </option>
        </select>
      </label>
      <p class="meta-line">
        听写结束后无新输入会倒计时自动发送；可说取消/继续说，或说「发送吧」立即发送。开放域语句不会当作指令执行。
      </p>
    </section>
  </main>
</template>

<style scoped>
.assistant-page {
  display: grid;
  gap: 14px;
  padding-bottom: 28px;
}
.page-header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
  flex-wrap: wrap;
}
.page-header .ghost-link { margin-left: auto; }
.eyebrow {
  margin: 0;
  font-size: 0.78rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--muted);
}
.lede {
  margin: 6px 0 0;
  color: var(--muted);
  line-height: 1.45;
}
.ghost-link {
  flex-shrink: 0;
  color: var(--accent);
  font-weight: 600;
  text-decoration: none;
  min-height: var(--tap);
  display: inline-flex;
  align-items: center;
}
.status-card p { margin: 0 0 6px; }
.meta-line { color: var(--muted); font-size: 0.9rem; margin: 0; }
.chat-card {
  display: grid;
  gap: 12px;
  min-height: 220px;
  max-height: min(52vh, 480px);
  overflow: auto;
}
.empty-hint { color: var(--muted); margin: 0; line-height: 1.5; }
.bubble {
  display: grid;
  gap: 6px;
  padding: 12px 14px;
  border-radius: 16px;
  background: color-mix(in srgb, var(--surface) 88%, var(--accent) 12%);
}
.bubble[data-role='user'] {
  background: color-mix(in srgb, var(--accent) 18%, var(--surface));
  justify-self: end;
  max-width: 92%;
}
.bubble-role { margin: 0; font-size: 0.8rem; font-weight: 700; color: var(--muted); }
.bubble-text { margin: 0; white-space: pre-wrap; line-height: 1.5; }
.bubble-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.speech-segment-chips { display: flex; flex-wrap: wrap; gap: 8px; width: 100%; }
.speech-segment-chips .chip.active {
  outline: 2px solid color-mix(in srgb, var(--accent) 55%, transparent);
}
.ready-actions {
  display: grid;
  grid-template-columns: 1.2fr 1fr 1fr;
  gap: 8px;
}
.ready-actions .btn-large { min-height: 52px; font-size: 1.05rem; }
.suggestions { display: flex; flex-wrap: wrap; gap: 8px; }
.chip {
  border: 1px solid color-mix(in srgb, var(--accent) 35%, transparent);
  background: transparent;
  color: inherit;
  border-radius: 999px;
  padding: 8px 12px;
  min-height: var(--tap);
}
.composer { display: grid; gap: 10px; }
.composer textarea {
  width: 100%;
  resize: vertical;
  min-height: 84px;
  border-radius: 14px;
  border: 1px solid color-mix(in srgb, var(--text) 14%, transparent);
  background: var(--surface);
  color: inherit;
  padding: 12px;
  font: inherit;
}
.composer-actions {
  display: grid;
  grid-template-columns: 1.4fr 0.8fr 1fr;
  gap: 8px;
}
.mic-btn.listening {
  outline: 2px solid color-mix(in srgb, var(--accent) 55%, transparent);
}
.mic-btn.active {
  background: color-mix(in srgb, var(--accent) 22%, var(--surface));
}
.mic-btn.ready {
  outline: 2px solid color-mix(in srgb, var(--accent) 35%, transparent);
}
.error-line { color: var(--danger, #b42318); margin: 0; }
.voice-preview, .voice-status, .voice-send-hint { margin: 0; color: var(--muted); }
.voice-send-hint { color: var(--accent); font-weight: 600; }
.voice-prefs-hint { display: grid; gap: 8px; }
.voice-prefs-hint .pref-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  font-size: 0.92rem;
}
.voice-prefs-hint .pref-row input {
  flex: 1;
  min-height: var(--tap);
  border-radius: 10px;
  padding: 8px 10px;
  border: 1px solid color-mix(in srgb, var(--text) 14%, transparent);
  background: var(--surface);
  color: inherit;
  font: inherit;
}
.wake-presets { display: flex; flex-wrap: wrap; gap: 8px; }
.voice-prefs-hint a { color: var(--accent); font-weight: 600; }
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  border: 0;
}
@media (max-width: 380px) {
  .composer-actions { grid-template-columns: 1fr; }
  .ready-actions { grid-template-columns: 1fr; }
}

.network-toggle {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-top: 8px;
  min-height: var(--tap);
  color: var(--muted);
  font-size: 0.92rem;
}
.thinking-line {
  margin: 0;
  color: var(--accent);
  font-weight: 600;
}
.evidence-preview-line {
  border: 1px solid color-mix(in srgb, var(--accent) 32%, transparent);
  border-radius: 12px;
  color: var(--muted);
  line-height: 1.5;
  margin: 0;
  padding: 10px 12px;
}
</style>
