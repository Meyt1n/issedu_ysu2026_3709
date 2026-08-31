<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'

import { activeProvider } from '@/data'
import type { MemberSummary } from '@/data/types'
import AppIcon from '@/components/AppIcon.vue'
import AssistantEvidencePanel from '@/components/AssistantEvidencePanel.vue'
import { ApiClientError } from '@/api/client'
import type {
  AssistantCitation,
  AssistantResponse,
  EvidencePreview,
} from '@/api/types'
import { createLiveApiClient } from '@/data'
import {
  AUTO_SEND_PRESETS,
  clearChatSession,
  clearChatDraft,
  clearChatSessionsForActor,
  createChatThread,
  createAutoSendScheduler,
  createDictationController,
  deleteChatThread,
  getActiveChatThreadId,
  getAssistantSessionId,
  getSpeakingIndex,
  getSpeakingSegments,
  isSpeechInputSupported,
  jumpSpeakingSegment,
  listChatThreads,
  loadChatDraft,
  loadVoicePreferences,
  memberNameHotwordPairs,
  loadChatSession,
  regenerateAssistantSessionId,
  renameChatThread,
  saveChatSession,
  saveChatDraft,
  saveVoicePreferences,
  setActiveChatThread,
  sessionEntryToStored,
  skipSpeakingSegment,
  speakText,
  stopSpeaking,
  touchChatThread,
  validateWakePhrase,
  WAKE_PHRASE_PRESETS,
  type DictationController,
  type DictationMode,
  type ChatThreadMeta,
  type StoredChatEntry,
  type VoiceCommandId,
  type VoicePreferences,
} from '@/composables/useVoiceInput'
import { useA11y } from '@/stores/accessibility'
import { CAPABILITY_IDS, useCapabilities } from '@/stores/capabilities'
import { useSession } from '@/stores/session'
import {
  assistantReplyStatusLabel,
  isInterruptedAssistantReply,
  restoreAssistantReplyStatus,
  type AssistantReplyStatus,
} from '@/utils/assistantReply'
import {
  collectExternalDomains,
  networkSearchFailureMessage,
  networkSearchDisabledReason as resolveNetworkSearchDisabledReason,
  resolveNetworkSearchForTurn,
} from '@/utils/networkSearch'
import {
  chatEntryAriaLabel,
  chatTimestampIso,
  formatChatTimestamp,
  isChatGroupEnd,
  isChatGroupStart,
} from '@/utils/chatPresentation'

interface ChatEntry {
  role: 'user' | 'assistant'
  content: string
  /** 新消息保留创建时间；旧会话没有时间戳时不伪造当前时间。 */
  createdAt?: number
  replyStatus?: AssistantReplyStatus
  degraded?: boolean
  degradeReason?: string | null
  sources?: string[]
  /** 只保留本次回答返回的引用；会话恢复不持久化，避免与服务端索引版本产生二义。 */
  citations?: AssistantCitation[]
  suggestedQuestions?: string[]
  queryType?: string | null
  networkUsed?: boolean
  /** 联网参考命中的来源域名；只保留服务端返回的域名，不展示完整 URL。 */
  externalDomains?: string[]
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
const { capabilities, hasCapability } = useCapabilities()
const route = useRoute()

const history = ref<ChatEntry[]>([])
const threads = ref<ChatThreadMeta[]>([])
const activeThreadId = ref('')
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
/** 联网链路失败后待重试的问题；只在提供「仅用本地知识重试」入口时使用。 */
const networkFallbackQuestion = ref('')
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

/**
 * MOB-161：只有服务端显式声明 external-web 能力时才允许打开联网搜索。
 * 能力探测未完成、未声明或声明为不可用时一律 fail-closed，绝不静默降级成本地检索却声称联网。
 */
const networkSearchAvailable = computed(
  () => liveMode.value && hasCapability(CAPABILITY_IDS.externalWeb),
)
const networkSearchDisabledReason = computed(() =>
  resolveNetworkSearchDisabledReason({
    liveMode: liveMode.value,
    capabilityProbed: Boolean(capabilities.snapshot),
    externalWebAvailable: hasCapability(CAPABILITY_IDS.externalWeb),
  }),
)

// 能力从可用变为不可用时立刻关闭开关，避免把上一次的开启状态当成隐式授权继续出网。
watch(networkSearchAvailable, (available) => {
  if (!available) allowNetworkSearch.value = false
}, { immediate: true })
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
    assistantSessionId.value = getAssistantSessionId(
      session.actorId,
      session.currentHouseholdId,
      session.currentMemberId,
      activeThreadId.value,
    ) || createAssistantSessionId()
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
    activeThreadId.value,
  )
  const firstQuestion = history.value.find((entry) => entry.role === 'user')?.content
  touchChatThread(
    session.actorId,
    session.currentHouseholdId,
    session.currentMemberId,
    activeThreadId.value,
    firstQuestion,
  )
  threads.value = listChatThreads(session.actorId, session.currentHouseholdId, session.currentMemberId)
}

watch(draft, (value) => {
  saveChatDraft(
    session.actorId,
    session.currentHouseholdId,
    session.currentMemberId,
    value,
    activeThreadId.value,
  )
})

function restoreChatSession(entries: StoredChatEntry[]): void {
  history.value = entries.map((entry) => ({
    role: entry.role,
    content: entry.content,
    createdAt: entry.createdAt,
    replyStatus: restoreAssistantReplyStatus(entry.role, entry.content, entry.degraded, entry.degradeReason),
    degraded: entry.degraded,
    degradeReason: entry.degradeReason,
    sources: entry.sources,
    suggestedQuestions: entry.suggestedQuestions,
  }))
  scrollToEnd()
}

function refreshThreads(): void {
  threads.value = listChatThreads(session.actorId, session.currentHouseholdId, session.currentMemberId)
}

/** 切换/新建会话前统一停止请求、语音和流式状态，避免旧会话内容串入新会话。 */
function suspendActiveConversation(): void {
  cancelActiveSend()
  stopVoiceInput()
  if (speakingIndex.value !== null) {
    stopSpeaking()
    speakingIndex.value = null
    speakingProgress.value = ''
  }
  orchestrationPhase.value = null
  liveEvidencePreview.value = null
  sendError.value = ''
  cancelStatus.value = ''
  sending.value = false
}

function switchThread(threadId: string): void {
  if (!threadId || threadId === activeThreadId.value) return
  suspendActiveConversation()
  activeThreadId.value = threadId
  setActiveChatThread(session.actorId, session.currentHouseholdId, session.currentMemberId, threadId)
  assistantSessionId.value = getAssistantSessionId(
    session.actorId,
    session.currentHouseholdId,
    session.currentMemberId,
    threadId,
  )
  restoreChatSession(loadChatSession(
    session.actorId,
    session.currentHouseholdId,
    session.currentMemberId,
    threadId,
  ))
  draft.value = loadChatDraft(
    session.actorId,
    session.currentHouseholdId,
    session.currentMemberId,
    threadId,
  )
}

function startNewThread(): void {
  suspendActiveConversation()
  const meta = createChatThread(session.actorId, session.currentHouseholdId, session.currentMemberId)
  activeThreadId.value = meta.id
  assistantSessionId.value = getAssistantSessionId(
    session.actorId,
    session.currentHouseholdId,
    session.currentMemberId,
    meta.id,
  )
  history.value = []
  draft.value = ''
  refreshThreads()
}

function removeThread(threadId: string): void {
  if (!threadId || sending.value) return
  const title = threads.value.find(thread => thread.id === threadId)?.title ?? '该会话'
  if (globalThis.confirm && !globalThis.confirm(`确定删除“${title}”吗？消息与草稿会从本机清除。`)) return
  const remaining = deleteChatThread(
    session.actorId,
    session.currentHouseholdId,
    session.currentMemberId,
    threadId,
  )
  threads.value = remaining
  if (threadId !== activeThreadId.value) return
  suspendActiveConversation()
  const nextId = getActiveChatThreadId(session.actorId, session.currentHouseholdId, session.currentMemberId)
  activeThreadId.value = nextId
  assistantSessionId.value = getAssistantSessionId(
    session.actorId,
    session.currentHouseholdId,
    session.currentMemberId,
    nextId,
  )
  restoreChatSession(loadChatSession(
    session.actorId,
    session.currentHouseholdId,
    session.currentMemberId,
    nextId,
  ))
  draft.value = loadChatDraft(
    session.actorId,
    session.currentHouseholdId,
    session.currentMemberId,
    nextId,
  )
}

function clearAllThreads(): void {
  if (sending.value || !session.actorId) return
  if (globalThis.confirm && !globalThis.confirm('确定清空当前账号的全部助手会话吗？消息与草稿会从本机清除。')) return
  clearChatSessionsForActor(session.actorId)
  threads.value = listChatThreads(session.actorId, session.currentHouseholdId, session.currentMemberId)
  activeThreadId.value = getActiveChatThreadId(session.actorId, session.currentHouseholdId, session.currentMemberId)
  assistantSessionId.value = getAssistantSessionId(
    session.actorId,
    session.currentHouseholdId,
    session.currentMemberId,
    activeThreadId.value,
  )
  history.value = []
  draft.value = ''
  sendError.value = ''
  cancelStatus.value = '已清空当前账号的全部助手会话与草稿'
}

function renameThread(threadId: string): void {
  if (sending.value) return
  const current = threads.value.find(thread => thread.id === threadId)
  const nextTitle = globalThis.prompt?.('为会话设置名称', current?.title ?? '')
  if (nextTitle === null || nextTitle === undefined) return
  threads.value = renameChatThread(
    session.actorId,
    session.currentHouseholdId,
    session.currentMemberId,
    threadId,
    nextTitle,
  )
}

function threadTimeLabel(thread: ChatThreadMeta): string {
  const elapsed = Math.max(0, Date.now() - thread.updatedAt)
  if (elapsed < 60_000) return '刚刚'
  if (elapsed < 3_600_000) return `${Math.floor(elapsed / 60_000)} 分钟前`
  if (elapsed < 86_400_000) return `${Math.floor(elapsed / 3_600_000)} 小时前`
  return `${Math.floor(elapsed / 86_400_000)} 天前`
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

/**
 * MOB-161：只从服务端返回的外部来源里取域名做展示，去重并限量。
 * 不展示完整 URL，也不在本地解析或补全域名，避免把未经服务端核验的地址呈现给用户。
 */
function applyAssistantReply(entryIndex: number, reply: AssistantResponse): void {
  const entry = history.value[entryIndex]
  if (!entry) return
  entry.content = reply.answer
  entry.replyStatus = 'completed'
  entry.degraded = reply.degraded
  entry.degradeReason = reply.degrade_reason
  entry.sources = reply.sources
  entry.citations = reply.citations
  entry.suggestedQuestions = (reply.suggested_questions ?? []).filter(
    (item) => typeof item === 'string' && item.trim(),
  )
  entry.queryType = reply.query_type
  entry.networkUsed = reply.network_used
  entry.externalDomains = reply.network_used ? collectExternalDomains(reply.external_sources) : []
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

/**
 * 服务端联网节点可能在 HTTP 成功后以 degraded trace 返回本地回答；
 * 这条路径也必须保留原问题并提供本地重试入口（不能只处理网络异常）。
 */
function applyNetworkSearchFailure(reply: AssistantResponse, question: string, optedIn: boolean): void {
  if (!optedIn) return
  const message = networkSearchFailureMessage(reply.agent_trace)
  if (!message) return
  sendError.value = message
  networkFallbackQuestion.value = question
}

/** 取消/结束回复的收尾：保留已显示内容并明确标记为不完整。 */
function settleCancelledReply(entryIndex: number, streamingEntry: ChatEntry): void {
  const entry = history.value[entryIndex]
  if (entry === streamingEntry && entry.content.trim()) {
    entry.replyStatus = keepPartialReply ? 'ended' : 'stopped'
    entry.degraded = true
    entry.degradeReason = keepPartialReply ? 'reply_ended' : 'user_stopped'
    entry.sources = undefined
    entry.citations = undefined
    entry.suggestedQuestions = undefined
    entry.networkUsed = false
    entry.externalDomains = []
    entry.agentTraceSummary = undefined
    cancelStatus.value = keepPartialReply
      ? '已结束回复，保留已生成的内容'
      : '已停止，已保留未完整内容；可点击“重新提问”'
  } else {
    if (entry === streamingEntry) history.value.splice(entryIndex, 1)
    cancelStatus.value = '已停止'
  }
  keepPartialReply = false
  persistChatSession()
  scrollToEnd()
}

/**
 * MOB-161 验收 4：联网被限速、超时或上游失败后，用同一个问题只走本地知识重试。
 * 这里不改开关状态，只让这一轮强制不出网，避免用户为了拿到回答而永久关掉开关。
 */
function retryWithLocalKnowledgeOnly(): void {
  const question = networkFallbackQuestion.value.trim()
  if (!question || sending.value) return
  networkFallbackQuestion.value = ''
  sendError.value = ''
  void send(question, undefined, { localOnly: true })
}

function retryInterruptedReply(replyIndex: number): void {  if (!isInterruptedAssistantReply(history.value[replyIndex]?.replyStatus)) return
  for (let index = replyIndex - 1; index >= 0; index -= 1) {
    const entry = history.value[index]
    if (entry?.role === 'user' && entry.content.trim()) {
      draft.value = entry.content
      sendError.value = ''
      cancelStatus.value = '已恢复原问题，请确认后重新提问'
      void nextTick(() => draftInput.value?.focus())
      return
    }
  }
  cancelStatus.value = '找不到原问题，请重新输入后再试'
}

async function send(
  text?: string,
  queryTypeOverride?: string,
  options?: { localOnly?: boolean },
): Promise<void> {
  const content = (text ?? draft.value).trim()
  if (!content || sending.value) return

  networkFallbackQuestion.value = ''
  cancelActiveSend()
  stopVoiceInput()
  stopSpeaking()
  speakingIndex.value = null
  speakingProgress.value = ''
  keepPartialReply = false

  history.value.push({ role: 'user', content, createdAt: Date.now() })
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
      createdAt: Date.now(),
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
      createdAt: Date.now(),
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
      createdAt: Date.now(),
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
  // 双重闸门：即使开关状态残留为开，缺少服务端 external-web 能力时也绝不请求出网。
  const networkSearchForThisTurn = resolveNetworkSearchForTurn({
    localOnly: options?.localOnly,
    available: networkSearchAvailable.value,
    userEnabled: allowNetworkSearch.value,
  })
  const chatInput = {
    messages,
    max_tokens: 1024,
    agent_mode: 'multi_agent' as const,
    allow_network_search: networkSearchForThisTurn,
    query_type_override: queryTypeOverride,
    assistant_session_id: assistantSessionId.value,
  }
  const householdId = session.currentHouseholdId || undefined
  const memberId = session.currentMemberId || undefined
  const requestOpts = { ...requestOptions(), signal: controller.signal }

  // 流式展示：token 直接写入这条气泡；结束回复/停止时按需保留或移除。
  const streamingEntry: ChatEntry = { role: 'assistant', content: '', createdAt: Date.now(), replyStatus: 'streaming' }
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
            if (!token || controller.signal.aborted) return
            streamStarted = true
            streamingEntry.content += token
            orchestrationPhase.value = 'generating'
            scrollToEnd()
          },
          onEvidencePreview: (preview) => {
            liveEvidencePreview.value = preview
            scrollToEnd()
          },
          onExternalSources: (sources) => {
            const domains = collectExternalDomains(sources)
            if (!domains.length) return
            streamingEntry.networkUsed = true
            streamingEntry.externalDomains = domains
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
      applyNetworkSearchFailure(reply, content, networkSearchForThisTurn)
    } catch (streamError) {
      if (controller.signal.aborted || streamCancelled || isAssistantCancellation(streamError)) {
        settleCancelledReply(entryIndex, streamingEntry)
        return
      }
      if (streamStarted && streamingEntry.content.trim()) {
        streamingEntry.content = streamingEntry.content.trim()
        streamingEntry.replyStatus = 'incomplete'
        streamingEntry.degraded = true
        streamingEntry.degradeReason = 'stream_incomplete'
        sendError.value = '流式连接中断，已保留已生成内容。'
        persistChatSession()
        scrollToEnd()
        return
      }
      const reply = await client.assistantChat(chatInput, householdId, memberId, requestOpts)
      applyAssistantReply(entryIndex, reply)
      applyNetworkSearchFailure(reply, content, networkSearchForThisTurn)
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
      // 本轮请求过出网：把原问题留下来，给一个只走本地知识的重试入口（验收 4）。
      if (networkSearchForThisTurn) networkFallbackQuestion.value = content
      const fallbackContent =
        '本地模型或其依赖当前不可用，无法生成回答。家庭事实、任务与提醒不受影响，可直接在对应页面查看。'
      const entry = history.value[entryIndex]
      if (entry === streamingEntry) {
        entry.content = fallbackContent
        entry.replyStatus = 'incomplete'
        entry.degraded = true
        entry.degradeReason = 'request_failed'
      } else {
        history.value.push({
          role: 'assistant',
          content: fallbackContent,
          createdAt: Date.now(),
          replyStatus: 'incomplete',
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
  assistantSessionId.value = regenerateAssistantSessionId(
    session.actorId,
    session.currentHouseholdId,
    session.currentMemberId,
    activeThreadId.value,
  ) || createAssistantSessionId()
  draft.value = ''
  sendError.value = ''
  voiceError.value = ''
  cancelStatus.value = ''
  liveEvidencePreview.value = null
  orchestrationPhase.value = null
  clearChatSession(
    session.actorId,
    session.currentHouseholdId,
    session.currentMemberId,
    activeThreadId.value,
  )
  clearChatDraft(
    session.actorId,
    session.currentHouseholdId,
    session.currentMemberId,
    activeThreadId.value,
  )
  refreshThreads()
}

/** 资讯卡只预填草稿，不自动发送；用户仍需自行编辑并确认提问。 */
function applyPromptFromRoute(): void {
  const prompt = typeof route.query.prompt === 'string' ? route.query.prompt.trim() : ''
  if (!prompt) return
  draft.value = prompt.slice(0, 240)
  sendError.value = ''
  void nextTick(() => draftInput.value?.focus())
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
    threads.value = listChatThreads(actorId, householdId, memberId)
    activeThreadId.value = getActiveChatThreadId(actorId, householdId, memberId)
    assistantSessionId.value = getAssistantSessionId(actorId, householdId, memberId, activeThreadId.value)
    restoreChatSession(loadChatSession(actorId, householdId, memberId, activeThreadId.value))
    draft.value = loadChatDraft(actorId, householdId, memberId, activeThreadId.value)
  },
  { immediate: true },
)

watch(
  () => route.query.prompt,
  () => applyPromptFromRoute(),
  { immediate: true },
)

onMounted(() => {
  void loadMemberHotwords()
  // MOB-166：即使系统之前授予过麦克风权限，也必须由用户点按后才启动识别。
  // 这样切回助手页不会在公共场合或后台意外占用麦克风。
  if (speechInputSupported) needMicGesture.value = true
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
  <main id="main" class="screen assistant-page" tabindex="-1">
    <header class="page-header">
      <div>
        <p class="eyebrow">随身助手</p>
        <h1>语音提问</h1>
        <p class="lede">
          点按下方按钮开启麦克风，再说「{{ wakePhrase }}」；离开页面或切到后台会立即停止聆听。
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
      <div class="network-search">
        <label class="network-toggle">
          <input
            v-model="allowNetworkSearch"
            type="checkbox"
            :disabled="sending || !networkSearchAvailable"
            :aria-describedby="networkSearchDisabledReason ? 'network-search-reason' : undefined"
          />
          允许本次脱敏联网参考
        </label>
        <p
          v-if="networkSearchDisabledReason"
          id="network-search-reason"
          class="meta-line"
          role="status"
        >
          {{ networkSearchDisabledReason }}联网搜索保持关闭，助手只用家庭服务器上的本地知识回答。
        </p>
        <details class="network-scope">
          <summary class="network-scope-summary">出网范围说明</summary>
          <ul class="network-scope-list">
            <li v-if="liveMode">会出网：这一轮里被服务端判定需要外部参考的检索词。</li>
            <li v-else>演示模式不会出网；切换联机且服务端开放能力后，才会按本开关决定是否请求外部参考。</li>
            <li>不会出网：成员姓名、健康事件正文、用药记录、位置与家庭标识。</li>
            <li>默认关闭。关掉后立即只用本地知识，不保留任何隐式授权。</li>
            <li>联网结果只作参考，需人工确认，不构成诊断、处方或剂量建议。</li>
          </ul>
        </details>
      </div>
    </section>

    <section class="card thread-card" aria-label="会话历史">
      <div class="thread-card-header">
        <div>
          <h2>会话历史</h2>
          <p class="meta-line">当前账号、家庭和成员分别保存；只在本标签页保留，不会上传服务器。</p>
        </div>
        <div class="thread-actions">
          <button type="button" class="btn btn-secondary" :disabled="sending" @click="startNewThread">
            新建会话
          </button>
          <button type="button" class="btn btn-secondary" :disabled="sending || threads.length === 0" @click="clearAllThreads">
            清空全部历史
          </button>
        </div>
      </div>
      <ul class="thread-list">
        <li v-for="thread in threads" :key="thread.id" class="thread-item" :class="{ active: thread.id === activeThreadId }">
          <button
            type="button"
            class="thread-open"
            :aria-current="thread.id === activeThreadId ? 'page' : undefined"
            :disabled="sending"
            @click="switchThread(thread.id)"
          >
            <strong>{{ thread.title }}</strong>
            <span>{{ threadTimeLabel(thread) }}</span>
          </button>
          <button
            type="button"
            class="thread-rename"
            :aria-label="`重命名会话：${thread.title}`"
            :disabled="sending"
            @click="renameThread(thread.id)"
          >
            重命名
          </button>
          <button
            type="button"
            class="thread-delete"
            :aria-label="`删除会话：${thread.title}`"
            :disabled="sending"
            @click="removeThread(thread.id)"
          >
            删除
          </button>
        </li>
      </ul>
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
        :class="{
          'bubble--group-start': isChatGroupStart(history, index),
          'bubble--group-end': isChatGroupEnd(history, index),
          'bubble--continuation': !isChatGroupStart(history, index),
        }"
        :aria-label="chatEntryAriaLabel(entry)"
      >
        <p
          class="bubble-role"
          :class="{ 'sr-only': !isChatGroupStart(history, index) }"
        >
          {{ entry.role === 'user' ? '我' : '助手' }}
        </p>
        <p class="bubble-text">{{ entry.content || '正在生成回答…' }}</p>
        <time
          v-if="entry.createdAt"
          class="bubble-time"
          :datetime="chatTimestampIso(entry.createdAt)"
        >
          {{ formatChatTimestamp(entry.createdAt) }}
        </time>
        <p
          v-if="entry.role === 'assistant' && entry.replyStatus"
          class="meta-line reply-status"
          role="status"
          aria-live="polite"
        >
          {{ assistantReplyStatusLabel(entry.replyStatus) }}
          <span v-if="entry.replyStatus === 'stopped' || entry.replyStatus === 'ended'">；未得出引用完整性结论。</span>
          <span v-else-if="entry.replyStatus === 'incomplete'">；请重新提问以获得完整回答。</span>
        </p>
        <p v-if="entry.degraded" class="meta-line">降级说明：{{ entry.degradeReason || '受控降级' }}</p>
        <p v-if="entry.agentTraceSummary" class="meta-line">{{ entry.agentTraceSummary }}</p>
        <p v-if="entry.networkUsed" class="meta-line">
          已启用联网参考 · 需人工确认，不作诊断
          <template v-if="entry.externalDomains?.length">
            · 来源域名：{{ entry.externalDomains.join('、') }}
          </template>
          <template v-else>· 服务端未返回来源域名</template>
        </p>
        <AssistantEvidencePanel
          v-if="entry.role === 'assistant' && entry.content"
          :citations="entry.citations"
          :sources="entry.sources"
          :degraded="entry.degraded"
          :degrade-reason="entry.degradeReason"
        />
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
            v-if="isInterruptedAssistantReply(entry.replyStatus)"
            type="button"
            class="btn btn-secondary"
            @click="retryInterruptedReply(index)"
          >
            重新提问
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
    <button
      v-if="networkFallbackQuestion && !sending"
      type="button"
      class="btn btn-secondary local-only-retry"
      @click="retryWithLocalKnowledgeOnly"
    >
      仅用本地知识重试
    </button>
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
          :title="speechInputSupported ? '点按后才会开启麦克风；离开页面会停止聆听' : '当前不支持语音输入'"
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
.thread-card { display: grid; gap: 10px; }
.thread-card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.thread-card-header h2 { margin: 0 0 4px; font-size: 1.05rem; }
.thread-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.thread-list {
  display: grid;
  gap: 6px;
  list-style: none;
  margin: 0;
  padding: 0;
}
.thread-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.thread-open {
  display: grid;
  gap: 2px;
  min-width: 0;
  border: 1px solid transparent;
  border-radius: 10px;
  background: transparent;
  color: inherit;
  cursor: pointer;
  padding: 8px 10px;
  text-align: left;
}
.thread-open strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.thread-open span { color: var(--muted); font-size: 0.8rem; }
.thread-item.active .thread-open {
  border-color: color-mix(in srgb, var(--accent) 42%, transparent);
  background: color-mix(in srgb, var(--accent) 10%, var(--surface));
}
.thread-open:focus-visible,
.thread-rename:focus-visible,
.thread-delete:focus-visible {
  outline: 3px solid color-mix(in srgb, var(--accent) 55%, transparent);
  outline-offset: 1px;
}
.thread-rename,
.thread-delete {
  min-height: var(--tap);
  border: 0;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  padding: 6px 8px;
  white-space: nowrap;
}
.thread-delete { color: var(--danger, #b42318); }
.chat-card {
  display: grid;
  gap: 8px;
  min-height: 220px;
  max-height: min(52vh, 480px);
  overflow: auto;
  /* 固定底部导航遮住 WebView 边缘时，最后一条消息仍可完整滚动到可视区域。 */
  padding: 10px 10px calc(10px + var(--hct-bottom-clearance));
  scroll-padding-bottom: calc(10px + var(--hct-bottom-clearance));
}
.empty-hint { color: var(--muted); margin: 0; line-height: 1.5; }
.bubble {
  display: grid;
  gap: 7px;
  min-width: 0;
  overflow-wrap: anywhere;
  padding: 13px 15px 11px;
  position: relative;
  transition: margin var(--speed) var(--ease), border-radius var(--speed) var(--ease);
}
.bubble[data-role='user'] {
  align-self: end;
  background:
    linear-gradient(145deg, color-mix(in srgb, var(--c-brand-soft) 86%, var(--c-surface-solid)), color-mix(in srgb, var(--c-calm-soft) 72%, var(--c-surface-solid)));
  border: 1px solid color-mix(in srgb, var(--c-brand) 18%, transparent);
  border-radius: 20px 20px 6px 20px;
  box-shadow: 0 7px 18px color-mix(in srgb, var(--c-brand) 10%, transparent), inset 0 1px 0 var(--hilite);
  color: var(--c-ink);
  justify-self: end;
  max-width: min(86%, 480px);
}
.bubble[data-role='assistant'] {
  align-self: start;
  background: linear-gradient(145deg, color-mix(in srgb, var(--c-surface-solid) 94%, transparent), color-mix(in srgb, var(--c-brand-softer) 34%, var(--c-surface-solid)));
  border: 1px solid color-mix(in srgb, var(--c-brand) 16%, var(--c-line-strong));
  border-radius: 20px 20px 20px 7px;
  box-shadow: 0 10px 28px color-mix(in srgb, var(--c-ink) 8%, transparent), inset 0 1px 0 var(--hilite);
  max-width: calc(100% - 12px);
}
.bubble[data-role='assistant']::before {
  background: linear-gradient(90deg, var(--c-brand), var(--c-calm), transparent);
  border-radius: var(--r-pill);
  content: '';
  height: 2px;
  left: 16px;
  opacity: 0.42;
  position: absolute;
  top: 0;
  width: 82px;
}
.bubble--continuation {
  margin-top: -5px;
}
.bubble--continuation[data-role='user'] { border-top-right-radius: 7px; }
.bubble--continuation[data-role='assistant'] { border-top-left-radius: 7px; }
.bubble-role { margin: 0; font-size: 0.78rem; font-weight: 800; color: var(--c-ink-faint); }
.bubble-text {
  margin: 0;
  max-width: 100%;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
  line-height: 1.7;
  word-break: break-word;
}
.bubble-time {
  color: var(--c-ink-faint);
  font-size: 0.72rem;
  line-height: 1.3;
  justify-self: end;
}
.bubble[data-role='user'] .bubble-time { color: color-mix(in srgb, var(--c-brand-deep) 72%, var(--c-ink-faint)); }
.bubble--continuation .bubble-time { margin-top: -2px; }
html[data-contrast='high'] .bubble { background: #fff; border: 2px solid #000; box-shadow: none; }
html[data-contrast='high'] .bubble[data-role='user'] { color: #000; }
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
.network-search {
  display: grid;
  gap: 4px;
}
.network-scope-summary {
  color: var(--muted);
  cursor: pointer;
  font-size: 0.92rem;
  min-height: var(--tap);
  padding: 8px 0;
}
.network-scope-summary:focus-visible,
.local-only-retry:focus-visible {
  outline: 3px solid color-mix(in srgb, var(--accent) 58%, transparent);
  outline-offset: 2px;
}
.network-scope-list {
  color: var(--muted);
  display: grid;
  font-size: 0.92rem;
  gap: 4px;
  line-height: 1.55;
  margin: 0;
  padding-left: 20px;
}
.local-only-retry {
  justify-self: start;
  min-height: var(--tap);
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
