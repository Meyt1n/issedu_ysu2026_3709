<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { ApiClientError, apiClient } from '../api/client'
import type {
  AssistantAgentTrace,
  AssistantCitation,
  AssistantExternalSource,
  AssistantMemoryCapture,
} from '../api/types'
import {
  createChatThread,
  deleteChatThread,
  getActiveChatThreadId,
  getAssistantSessionId,
  listChatThreads,
  loadChatSession,
  regenerateAssistantSessionId,
  saveChatSession,
  sessionEntryToStored,
  setActiveChatThread,
  touchChatThread,
  type ChatThreadMeta,
  type StoredChatEntry,
} from '../assistant/chatSession'
import { buildAssistantChatInput } from '../assistant/chatPayload'
import { normalizeSuggestedQuestions } from '../assistant/followUp'
import {
  canRecheckMedicationSafety,
  confidenceLabel,
  extraFactSources,
  routeSummary,
  visibleRiskNotice,
} from '../assistant/replyMeta'
import {
  unavailableWebSearchAvailability,
  webSearchAvailabilityFromCatalog,
  webSearchDisabledLabel,
  webSearchModeBadge,
  webSearchSkipDetail,
} from '../assistant/webSearchAvailability'
import {
  AUTO_SEND_PRESETS,
  createAutoSendScheduler,
  createDictationController,
  getSpeakingIndex,
  getSpeakingSegments,
  inspectChineseVoicePacks,
  isSpeechInputSupported,
  isSpeechOutputSupported,
  jumpSpeakingSegment,
  listChineseVoices,
  loadVoicePreferences,
  memberNameHotwordPairs,
  runVoicePreflight,
  saveVoicePreferences,
  SILENCE_PRESETS,
  skipSpeakingSegment,
  speakText,
  stopSpeaking,
  validateWakePhrase,
  WAKE_PHRASE_PRESETS,
  type DictationController,
  type DictationMode,
  type SpeechVoiceLike,
  type VoiceCommandId,
  type VoicePackReport,
  type VoicePreflightReport,
  type VoicePreferences,
} from '../assistant/voice'
import AppIcon from '../components/AppIcon.vue'
import {
  consumeAssistantSeed,
  formatError,
  pushToast,
  requestOptions,
  selectMember,
  session,
} from '../store'
import { relativeTime } from '../ui/labels'

interface ChatEntry {
  role: 'user' | 'assistant'
  content: string
  revealed: number
  openChat?: boolean
  sources?: string[]
  citations?: AssistantCitation[]
  confidence?: string
  degraded?: boolean
  degradeReason?: string | null
  escalate?: boolean
  suggestedQuestions?: string[]
  route?: string | null
  routeExplanation?: string | null
  queryType?: string | null
  riskNotice?: string | null
  orchestrationMode?: 'single' | 'multi_agent' | null
  allAgentsLocal?: boolean
  networkUsed?: boolean
  networkQuery?: string | null
  agentTrace?: AssistantAgentTrace[]
  externalSources?: AssistantExternalSource[]
  memoryCapture?: AssistantMemoryCapture | null
}

type AgentVisualStatus = 'idle' | 'pending' | 'running' | 'completed' | 'skipped' | 'blocked' | 'degraded'

interface AgentStage {
  id: string
  title: string
  description: string
  icon: string
  network: boolean
}

const AGENT_STAGES: AgentStage[] = [
  { id: 'router', title: '问题识别', description: '判断问题类型与所需资料', icon: 'compass', network: false },
  { id: 'database', title: '档案核对', description: '读取授权范围内的健康记录', icon: 'timeline', network: false },
  { id: 'rules', title: '规则核对', description: '核对确定性规则与风险依据', icon: 'alert', network: false },
  { id: 'knowledge', title: '资料检索', description: '匹配已审核的本地资料', icon: 'pill', network: false },
  { id: 'web_search', title: '联网参考', description: '获取脱敏后的公开参考', icon: 'cloud', network: true },
  { id: 'synthesis', title: '回答生成', description: '汇总证据并生成回答', icon: 'assistant', network: false },
]

const history = ref<ChatEntry[]>([])
const draft = ref('')
const selectedFile = ref<File | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const sending = ref(false)
const sendError = ref('')
const voiceError = ref('')
const allowNetworkSearch = ref(false)
const webSearchAvailable = ref<boolean | null>(null)
const webSearchReason = ref<string | null>(null)
const webSearchHint = ref<string | null>(null)
const webSearchFixture = ref(false)
const webSearchProvider = ref<string | null>(null)
const settingsOpen = ref(false)
const workflowTrace = ref<AssistantAgentTrace[]>([])
const selectedAgentId = ref<string | null>(null)
const workflowExpanded = ref(false)
const orchestrationPhase = ref<string | null>(null)
const workflowRouteExplanation = ref<string | null>(null)
const stopStatus = ref('')
const assistantSessionId = ref('')
const threads = ref<ChatThreadMeta[]>([])
const activeThreadId = ref('')
type VoiceMode = DictationMode

const voiceMode = ref<VoiceMode>('off')
const listening = computed(() => ['wake', 'active', 'command'].includes(voiceMode.value))
const voicePreview = ref('')
const needMicGesture = ref(false)
const speakingIndex = ref<number | null>(null)
const speakingProgress = ref('')
const chatWindow = ref<HTMLElement | null>(null)
const draftInput = ref<HTMLTextAreaElement | null>(null)
const sendButton = ref<HTMLButtonElement | null>(null)
const voicePrefs = ref<VoicePreferences>(loadVoicePreferences())
const wakePhraseDraft = ref(voicePrefs.value.wakePhrase)
const voiceSendHint = ref('')
const voicePackReport = ref<VoicePackReport | null>(null)
const voicePackChecking = ref(false)
const voiceOptions = ref<SpeechVoiceLike[]>([])
const preflightReport = ref<VoicePreflightReport | null>(null)
const preflightRunning = ref(false)
const speakingSegmentIndex = ref(0)
const modelLabel = ref('本地模型')

const wakePhrase = computed(() => voicePrefs.value.wakePhrase)
const memberHotwordExtras = computed(() =>
  memberNameHotwordPairs(session.members.map(member => member.display_name)),
)

const activeSpeakingSegments = computed(() =>
  speakingIndex.value !== null ? [...getSpeakingSegments()] : [],
)

function applySilencePreset(presetId: string): void {
  const preset = SILENCE_PRESETS.find(item => item.id === presetId)
  if (!preset) return
  voicePrefs.value = saveVoicePreferences({
    silenceMs: preset.silenceMs,
    continuationSilenceMs: preset.continuationSilenceMs,
  })
}

function applyAutoSendPreset(presetId: string): void {
  const preset = AUTO_SEND_PRESETS.find(item => item.id === presetId)
  if (!preset) return
  voicePrefs.value = saveVoicePreferences({ autoSendDelayMs: preset.delayMs })
  sendConfirmGate.reset()
  voiceSendHint.value = ''
}

function toggleVoicePref<K extends keyof VoicePreferences>(key: K, value: VoicePreferences[K]): void {
  voicePrefs.value = saveVoicePreferences({ [key]: value })
}

function applyWakePreset(phrase: string): void {
  wakePhraseDraft.value = phrase
  saveWakePhrase()
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
  if (listening.value || voiceMode.value === 'ready') void beginWakeListening()
}

function repeatLastAnswer(): void {
  const last = [...history.value].reverse().find(entry => entry.role === 'assistant' && entry.content.trim())
  if (!last) {
    voiceError.value = '还没有可朗读的回答。'
    return
  }
  toggleSpeech(history.value.lastIndexOf(last), last.content)
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

async function refreshVoiceOptions(): Promise<void> {
  if (!speechOutputSupported) return
  voiceOptions.value = await listChineseVoices()
}

function applyPreferredVoice(name: string): void {
  voicePrefs.value = saveVoicePreferences({ preferredVoiceName: name })
}

function previewPreferredVoice(): void {
  if (!speechOutputSupported) return
  stopSpeaking()
  speakingIndex.value = null
  speakingProgress.value = ''
  speakText('您好，我会用这个声音朗读回答。')
}

async function checkVoicePacks(): Promise<void> {
  voicePackChecking.value = true
  try {
    voicePackReport.value = await inspectChineseVoicePacks()
  } finally {
    voicePackChecking.value = false
  }
}

async function runPreflight(): Promise<void> {
  preflightRunning.value = true
  try {
    preflightReport.value = await runVoicePreflight()
  } finally {
    preflightRunning.value = false
  }
}

function onDraftFocus(): void {
  if (voiceMode.value === 'active' || voiceMode.value === 'wake') ensureDictation().pause()
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

let streamTimer: ReturnType<typeof setInterval> | null = null
let stopStatusTimer: ReturnType<typeof setTimeout> | null = null

const speechInputSupported = isSpeechInputSupported()
const speechOutputSupported = isSpeechOutputSupported()
let activeSendController: AbortController | null = null
let userRequestedStop = false
let keepPartialReply = false
let dictation: DictationController | null = null

const silencePresetId = computed(() => {
  const match = SILENCE_PRESETS.find(
    preset => preset.silenceMs === voicePrefs.value.silenceMs
      && preset.continuationSilenceMs === voicePrefs.value.continuationSilenceMs,
  )
  return match?.id ?? 'custom'
})

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

function cancelActiveSend(showStatus = false): void {
  if (activeSendController) {
    userRequestedStop = showStatus
    activeSendController.abort()
    activeSendController = null
  }
}

function clearRemoteAssistantSession(sessionId: string): void {
  if (!sessionId) return
  void apiClient.clearAssistantSessionCache(sessionId, requestOptions.value).catch(() => {
    // Rotating the opaque id still isolates future requests if cleanup is unavailable.
  })
}

function isAssistantCancellation(cause: unknown): boolean {
  return cause instanceof ApiClientError
    && (cause.code === 'CANCELLED' || cause.message.includes('CANCELLED'))
}

function showStoppedStatus(text = '已停止'): void {
  stopStatus.value = text
  if (stopStatusTimer) clearTimeout(stopStatusTimer)
  stopStatusTimer = setTimeout(() => {
    stopStatusTimer = null
    stopStatus.value = ''
  }, 2400)
}

function ensureDictation(): DictationController {
  if (dictation) return dictation
  dictation = createDictationController({
    onModeChange: (mode) => {
      voiceMode.value = mode
      if (mode === 'active') {
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

function stopVoiceInput(): void {
  dictation?.stop()
  voicePreview.value = ''
  needMicGesture.value = false
  sendConfirmGate.reset()
  voiceSendHint.value = ''
}

async function beginWakeListening(): Promise<void> {
  if (!speechInputSupported) {
    voiceError.value = '当前浏览器不支持语音输入，请改用文字输入。'
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

const voiceStatusText = computed(() => {
  if (voiceMode.value === 'wake') return `正在聆听唤醒词：“${wakePhrase.value}”`
  if (voiceMode.value === 'active') return '已唤醒，识别中的文字会实时填入草稿'
  if (voiceMode.value === 'ready' || voiceMode.value === 'command') {
    return voiceSendHint.value || '说完后会倒计时自动发送；可说取消、继续说，或发送吧立即发送'
  }
  return needMicGesture.value ? '点按下方按钮一次以开启麦克风聆听' : ''
})

const autoSendPresetId = computed(() => {
  const match = AUTO_SEND_PRESETS.find(preset => preset.delayMs === voicePrefs.value.autoSendDelayMs)
  return match?.id ?? 'custom'
})

const voiceButtonLabel = computed(() => {
  if (voiceMode.value === 'wake') return '等待唤醒'
  if (voiceMode.value === 'active') return '停止语音'
  if (voiceMode.value === 'ready' || voiceMode.value === 'command') return '重新聆听'
  return needMicGesture.value ? '允许麦克风并聆听' : '开启唤醒'
})

function toggleVoiceInput(): void {
  if (listening.value || voiceMode.value === 'ready') {
    stopVoiceInput()
    return
  }
  void beginWakeListening()
}

function onVisibilityChange(): void {
  if (document.visibilityState === 'hidden') stopVoiceInput()
}

function formatModelLabel(model?: string | null): string {
  if (!model || model === 'unavailable') return '本地模型未配置'
  return model
}

const canSend = computed(() => (draft.value.trim().length > 0 || selectedFile.value !== null) && !sending.value)

const SUGGESTIONS = [
  '最近有哪些健康变化需要我确认？',
  '当前的风险提醒都是依据什么规则？',
  '这位成员正在使用哪些药品？',
]

const AGENT_DETAILS: Record<string, { boundary: string; action: string }> = {
  router: {
    boundary: '仅分析当前问题文本，不读取家庭健康数据。',
    action: '识别问题类型，按需规划后续的检索步骤。',
  },
  database: {
    boundary: '仅访问当前授权成员的只读记录，无法扩大查询范围。',
    action: '核对已确认的健康事件、成员状态和今日照护计划。',
  },
  rules: {
    boundary: '只读取确定性规则结果；不会由模型生成或改变风险等级。',
    action: '核对当前成员命中的规则、风险等级与版本化依据。',
  },
  knowledge: {
    boundary: '仅检索本地已审核资料，不访问外部网站。',
    action: '检索药品说明与护理资料，并附带可核验的出处。',
  },
  web_search: {
    boundary: '仅发送脱敏后的问题；不发送成员身份、健康记录、图片或档案数据。',
    action: '在部署与本次请求都允许时，补充公开的外部参考。',
  },
  synthesis: {
    boundary: '仅使用运维已配置的模型服务，不能绕过授权、工具白名单和输出校验。',
    action: '汇总检索到的证据，生成带出处的回答并通过安全校验。',
  },
}

function traceForAgent(agentId: string): AssistantAgentTrace | undefined {
  return workflowTrace.value.find(trace => trace.agent_id === agentId)
}

// Prefer finished traces; while in flight highlight only the active phase stage.
function agentStatus(stage: AgentStage): AgentVisualStatus {
  const trace = traceForAgent(stage.id)
  if (trace) {
    if (['completed', 'skipped', 'blocked', 'degraded'].includes(trace.status)) {
      return trace.status as AgentVisualStatus
    }
  }
  if (!sending.value) return 'idle'
  if (stage.network && (!allowNetworkSearch.value || webSearchAvailable.value === false)) {
    return 'skipped'
  }

  const phase = orchestrationPhase.value
  if (phase === 'routing' && stage.id === 'router') return 'running'
  if (phase === 'retrieving' && ['database', 'rules', 'knowledge'].includes(stage.id)) return 'running'
  if (phase === 'searching' && stage.id === 'web_search') return 'running'
  if ((phase === 'generating' || phase === 'validating') && stage.id === 'synthesis') return 'running'
  return 'pending'
}

function agentStatusLabel(status: AgentVisualStatus): string {
  const labels: Record<AgentVisualStatus, string> = {
    idle: '待执行',
    pending: '等待中',
    running: '处理中',
    completed: '已完成',
    skipped: '已跳过',
    blocked: '已拦截',
    degraded: '已降级',
  }
  return labels[status]
}

function agentStatusDetail(stage: AgentStage): string {
  const trace = traceForAgent(stage.id)
  if (trace?.summary) return trace.summary
  if (agentStatus(stage) === 'skipped' && stage.network) {
    return webSearchSkipDetail(webSearchState.value)
  }
  return stage.description
}

const PHASE_LABELS: Record<string, string> = {
  routing: '正在识别问题类型…',
  retrieving: '正在核对档案与本地资料…',
  searching: '正在获取脱敏联网参考…',
  generating: '正在生成回答…',
  validating: '正在校验引用与安全边界…',
  remembering: '正在提取可长期保存的聊天线索…',
}

const thinkingText = computed(() => {
  if (orchestrationPhase.value && PHASE_LABELS[orchestrationPhase.value]) {
    return PHASE_LABELS[orchestrationPhase.value]
  }
  return '正在核对证据并生成回答…'
})

const workflowSummary = computed(() => {
  if (sending.value) {
    return orchestrationPhase.value && PHASE_LABELS[orchestrationPhase.value]
      ? PHASE_LABELS[orchestrationPhase.value]
      : '正在分析中…'
  }
  const traces = workflowTrace.value
  if (traces.length > 0) {
    const completed = traces.filter(trace => trace.status === 'completed').length
    const usedNetwork = traces.some(trace => trace.network_used)
    return `已完成 ${completed} 个步骤${usedNetwork ? '，含脱敏联网参考' : '，未使用外部网页搜索'}`
  }
  return '发送问题后，可在此查看处理进度'
})

// 图五/图六：多智能体流程默认收成一枚小状态胶囊，详情按需展开。
const workflowChipLabel = computed(() => {
  if (sending.value) {
    return orchestrationPhase.value && PHASE_LABELS[orchestrationPhase.value]
      ? PHASE_LABELS[orchestrationPhase.value]
      : '正在分析…'
  }
  const done = workflowTrace.value.filter(trace =>
    ['completed', 'skipped', 'blocked', 'degraded'].includes(trace.status),
  ).length
  return done > 0 ? `证据分析 · ${done} 步完成` : '证据分析'
})

const selectedAgent = computed(() => AGENT_STAGES.find(stage => stage.id === selectedAgentId.value) ?? null)
const selectedAgentTrace = computed(() => (
  selectedAgentId.value ? traceForAgent(selectedAgentId.value) : undefined
))
const workflowProgressWidth = computed(() => {
  if (workflowTrace.value.length === 0) return sending.value ? '12%' : '0%'
  const completed = workflowTrace.value.filter(trace =>
    ['completed', 'skipped', 'blocked', 'degraded'].includes(trace.status),
  ).length
  const progress = (completed / AGENT_STAGES.length) * 100
  return `${Math.min(100, Math.max(sending.value ? 12 : 0, progress))}%`
})

function upsertWorkflowTrace(trace: AssistantAgentTrace): void {
  const traces = [...workflowTrace.value]
  const index = traces.findIndex(item => item.agent_id === trace.agent_id)
  if (index >= 0) traces[index] = trace
  else traces.push(trace)
  workflowTrace.value = traces
}

function toggleAgentDetails(agentId: string): void {
  selectedAgentId.value = selectedAgentId.value === agentId ? null : agentId
}

function toggleWorkflowPanel(): void {
  workflowExpanded.value = !workflowExpanded.value
  if (!workflowExpanded.value) selectedAgentId.value = null
}

function selectedAgentBoundary(): string {
  return selectedAgent.value ? AGENT_DETAILS[selectedAgent.value.id]?.boundary ?? '' : ''
}

function selectedAgentAction(): string {
  return selectedAgent.value ? AGENT_DETAILS[selectedAgent.value.id]?.action ?? '' : ''
}

const reduceMotion = () =>
  globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false

/* 滚动智能跟随：仅当用户本来就在底部附近时才自动下滚，
   回看历史时不再被流式输出强行拽到底部（HCT-535）。 */
const stickToBottom = ref(true)

function onChatScroll(): void {
  const el = chatWindow.value
  if (!el) return
  stickToBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < 96
}

function scrollToEnd(force = false): void {
  if (!force && !stickToBottom.value) return
  void nextTick(() => {
    const el = chatWindow.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

function isStreaming(entry: ChatEntry): boolean {
  return entry.role === 'assistant' && entry.revealed < entry.content.length
}

function restoreChatSession(entries: StoredChatEntry[]): void {
  history.value = entries.map(entry => ({ ...entry, revealed: entry.content.length }))
  workflowRouteExplanation.value = [...history.value]
    .reverse()
    .find(entry => entry.role === 'assistant' && entry.routeExplanation)
    ?.routeExplanation ?? null
  scrollToEnd()
}

function persistChatSession(): void {
  saveChatSession(
    session.actorId,
    session.selectedHouseholdId,
    session.selectedMemberId,
    history.value.map(entry => sessionEntryToStored(entry)),
    activeThreadId.value,
  )
  const firstQuestion = history.value.find(entry => entry.role === 'user')?.content
  touchChatThread(
    session.actorId,
    session.selectedHouseholdId,
    session.selectedMemberId,
    activeThreadId.value,
    firstQuestion,
  )
  refreshThreads()
}

function refreshThreads(): void {
  threads.value = listChatThreads(session.actorId, session.selectedHouseholdId, session.selectedMemberId)
}

/** 切换/新建线索前的公共收尾：停掉请求、朗读与打字机。 */
function suspendActiveConversation(): void {
  cancelActiveSend()
  stopVoiceInput()
  if (speakingIndex.value !== null) {
    stopSpeaking()
    speakingIndex.value = null
    speakingProgress.value = ''
  }
  if (streamTimer) {
    clearInterval(streamTimer)
    streamTimer = null
  }
  workflowTrace.value = []
  orchestrationPhase.value = null
  workflowRouteExplanation.value = null
  sendError.value = ''
  stopStatus.value = ''
  sending.value = false
}

function switchThread(threadId: string): void {
  if (!threadId || threadId === activeThreadId.value) return
  suspendActiveConversation()
  activeThreadId.value = threadId
  setActiveChatThread(session.actorId, session.selectedHouseholdId, session.selectedMemberId, threadId)
  assistantSessionId.value = getAssistantSessionId(
    session.actorId,
    session.selectedHouseholdId,
    session.selectedMemberId,
    threadId,
  )
  restoreChatSession(loadChatSession(
    session.actorId,
    session.selectedHouseholdId,
    session.selectedMemberId,
    threadId,
  ))
}

function startNewThread(): void {
  suspendActiveConversation()
  const meta = createChatThread(session.actorId, session.selectedHouseholdId, session.selectedMemberId)
  activeThreadId.value = meta.id
  assistantSessionId.value = getAssistantSessionId(
    session.actorId,
    session.selectedHouseholdId,
    session.selectedMemberId,
    meta.id,
  )
  history.value = []
  draft.value = ''
  refreshThreads()
}

function removeThread(threadId: string): void {
  if (!threadId) return
  const remoteId = getAssistantSessionId(
    session.actorId,
    session.selectedHouseholdId,
    session.selectedMemberId,
    threadId,
  )
  clearRemoteAssistantSession(remoteId)
  const remaining = deleteChatThread(
    session.actorId,
    session.selectedHouseholdId,
    session.selectedMemberId,
    threadId,
  )
  threads.value = remaining
  if (threadId === activeThreadId.value) {
    suspendActiveConversation()
    const nextId = getActiveChatThreadId(session.actorId, session.selectedHouseholdId, session.selectedMemberId)
    activeThreadId.value = nextId
    assistantSessionId.value = getAssistantSessionId(
      session.actorId,
      session.selectedHouseholdId,
      session.selectedMemberId,
      nextId,
    )
    restoreChatSession(loadChatSession(
      session.actorId,
      session.selectedHouseholdId,
      session.selectedMemberId,
      nextId,
    ))
  }
}

function threadTimeLabel(thread: ChatThreadMeta): string {
  return relativeTime(new Date(thread.updatedAt).toISOString())
}

function useSuggestedQuestion(question: string): void {
  draft.value = question
  sendError.value = ''
  void nextTick(() => draftInput.value?.focus())
}

function chooseAttachment(): void {
  if (!sending.value) fileInput.value?.click()
}

function onAttachmentChange(event: Event): void {
  const input = event.target as HTMLInputElement
  selectedFile.value = input.files?.[0] ?? null
  sendError.value = ''
}

function clearAttachment(): void {
  selectedFile.value = null
  if (fileInput.value) fileInput.value.value = ''
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

function degradeReasonLabel(reason?: string | null): string {
  const labels: Record<string, string> = {
    REQUEST_FAILED: '本地 API 请求失败',
    MODEL_UNAVAILABLE: '本地模型不可用',
    OLLAMA_UNAVAILABLE: '本地模型服务不可用',
    KNOWLEDGE_UNAVAILABLE: '本机暂无已审核的相关知识卡',
    NO_AUTHORISED_DOCUMENTS: '当前范围没有可用知识文档',
    EVIDENCE_REQUIRED: '没有足够的本地证据',
    CITATION_NOT_FOUND: '引用未通过服务端校验',
    TOOL_SCOPE_DENIED: '工具调用超出当前授权范围',
    EXTERNAL_LINK_DETECTED: '回答包含被禁止的外部链接',
    LOCAL_MODEL_ENDPOINT_REQUIRED: '本地模型地址不是回环地址',
    SCHEMA_VALIDATION_FAILED: '本地模型输出未通过格式校验',
    MEDICAL_BOUNDARY_VIOLATION: '回答触及医疗边界，已被安全拦截',
  }
  return labels[reason ?? ''] ?? reason ?? '受控降级'
}

// Knowledge-gap degrades are a friendly teaching fallback, not a safety
// interception; they get a soft note instead of the warning banner.
function isKnowledgeGapDegrade(entry: ChatEntry): boolean {
  return entry.degraded === true && entry.degradeReason === 'KNOWLEDGE_UNAVAILABLE'
}

function evidenceSummary(entry: ChatEntry): string {
  const citationCount = entry.citations?.length ?? 0
  const sourceCount = entry.sources?.length ?? 0
  if (citationCount > 0) return `已返回 ${citationCount} 条可核验知识引用`
  if (sourceCount > 0) return `已返回 ${sourceCount} 个依据标识，未提供可展开的知识片段`
  if (entry.degraded) return '本次未使用模型生成内容'
  return '本次响应没有返回可展开的知识文档引用，仍需人工确认'
}

function hasEvidenceDetails(entry: ChatEntry): boolean {
  return Boolean(
    entry.degraded
      || entry.escalate
      || entry.riskNotice
      || entry.queryType
      || entry.routeExplanation
      || (entry.sources?.length ?? 0) > 0
      || entry.confidence
      || (entry.memoryCapture?.saved_count ?? 0) + (entry.memoryCapture?.updated_count ?? 0) > 0
      || (entry.agentTrace?.length ?? 0) > 0
      || (entry.externalSources?.length ?? 0) > 0,
  )
}

function evidenceDisclosureSummary(entry: ChatEntry): string {
  const parts: string[] = []
  const citations = entry.citations?.length ?? 0
  const steps = entry.agentTrace?.length ?? 0
  const external = entry.externalSources?.length ?? 0
  const memories = (entry.memoryCapture?.saved_count ?? 0) + (entry.memoryCapture?.updated_count ?? 0)
  if (citations > 0) parts.push(`${citations} 条本地引用`)
  if (steps > 0) parts.push(`${steps} 个处理步骤`)
  if (external > 0) parts.push(`${external} 条外部参考`)
  if (memories > 0) parts.push(`${memories} 条自动记忆`)
  if (entry.degraded) parts.push('受控降级说明')
  return parts.join(' · ') || '分析说明与依据状态'
}

function citationTitle(citation: AssistantCitation): string {
  return citation.document_title?.trim() || citation.document_id
}

let regenerateOnNextValidContext = false

watch(
  () => [session.actorId, session.selectedHouseholdId, session.selectedMemberId] as const,
  ([actorId, householdId, memberId], previous) => {
    const [previousActorId, , previousMemberId] = previous ?? ['', '', '']
    const memberChanged = Boolean(previousMemberId && previousMemberId !== memberId)
    if (memberChanged && previousActorId === actorId) {
      clearRemoteAssistantSession(assistantSessionId.value)
      regenerateOnNextValidContext = !memberId
    }
    cancelActiveSend()
    if (streamTimer) {
      clearInterval(streamTimer)
      streamTimer = null
    }
    threads.value = listChatThreads(actorId, householdId, memberId)
    activeThreadId.value = getActiveChatThreadId(actorId, householdId, memberId)
    const shouldRegenerate = Boolean(memberId && (memberChanged || regenerateOnNextValidContext))
    assistantSessionId.value = shouldRegenerate
      ? regenerateAssistantSessionId(actorId, householdId, memberId, activeThreadId.value)
      : getAssistantSessionId(actorId, householdId, memberId, activeThreadId.value)
    if (memberId) regenerateOnNextValidContext = false
    workflowRouteExplanation.value = null
    stopStatus.value = ''
    restoreChatSession(loadChatSession(actorId, householdId, memberId, activeThreadId.value))
  },
  { immediate: true },
)

async function loadAgentCatalog(): Promise<void> {
  let state = unavailableWebSearchAvailability()
  try {
    const catalog = await apiClient.listAssistantAgents(requestOptions.value)
    state = webSearchAvailabilityFromCatalog(catalog)
  } catch {
    state = unavailableWebSearchAvailability()
  }
  webSearchAvailable.value = state.available
  webSearchReason.value = state.reason
  webSearchHint.value = state.hint
  webSearchFixture.value = state.fixture
  webSearchProvider.value = state.provider
}

const webSearchState = computed(() => ({
  available: webSearchAvailable.value,
  fixture: webSearchFixture.value,
  provider: webSearchProvider.value,
  reason: webSearchReason.value,
  hint: webSearchHint.value,
}))

// Reason-specific copy so users understand why the toggle is disabled and how
// a deployment operator can enable it (docs/本地部署与Demo操作指南.md §5).
const webSearchDisabledText = computed(() => webSearchDisabledLabel(webSearchState.value))
// 「教学夹具 · 不出网」vs「真实联网 · 白名单出口」badge beside the checkbox.
const webSearchBadge = computed(() => webSearchModeBadge(webSearchState.value))

onMounted(() => {
  void loadAgentCatalog()
  autoResizeDraft()
  void bootstrapVoice()
  void refreshVoiceOptions()
  document.addEventListener('visibilitychange', onVisibilityChange)
})

watch(settingsOpen, open => {
  if (open) void refreshVoiceOptions()
})

watch(
  () => session.assistantSeedPrompt,
  prompt => {
    if (prompt) void applyAssistantSeed()
  },
  { immediate: true },
)

async function applyAssistantSeed(): Promise<void> {
  const seeded = consumeAssistantSeed()
  if (!seeded.prompt) return
  if (webSearchAvailable.value === null) await loadAgentCatalog()
  if (seeded.newThread) startNewThread()
  if (seeded.allowNetworkSearch) {
    allowNetworkSearch.value = true
  }
  draft.value = seeded.prompt
  await send(seeded.prompt)
}

function startReplySpeech(index: number, content: string, resumeListeningAfter = false): boolean {
  speakingProgress.value = ''
  speakingSegmentIndex.value = 0
  const started = speakText(content, {
    onFinished: () => {
      if (speakingIndex.value === index) {
        speakingIndex.value = null
        speakingProgress.value = ''
        speakingSegmentIndex.value = 0
        if (resumeListeningAfter && !needMicGesture.value) void beginWakeListening()
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
  voiceError.value = ''
  if (listening.value) stopVoiceInput()
  if (!startReplySpeech(index, content)) {
    voiceError.value = '当前浏览器不支持语音回复，请阅读文字回答。'
  }
}

function skipCurrentSpeechSegment(): void {
  skipSpeakingSegment()
}

/** 打字机式逐字呈现：对已完整返回的回答做流式展示。 */
function streamReveal(entry: ChatEntry): void {
  if (reduceMotion()) {
    entry.revealed = entry.content.length
    scrollToEnd()
    return
  }
  if (streamTimer) clearInterval(streamTimer)
  streamTimer = setInterval(() => {
    entry.revealed = Math.min(entry.revealed + 2, entry.content.length)
    scrollToEnd()
    if (entry.revealed >= entry.content.length && streamTimer) {
      clearInterval(streamTimer)
      streamTimer = null
    }
  }, 26)
}

async function copyReply(content: string): Promise<void> {
  try {
    await globalThis.navigator?.clipboard?.writeText(content)
    pushToast('success', '回答已复制到剪贴板。')
  } catch {
    pushToast('error', '复制失败，请手动选择文本复制。')
  }
}

function autoSpeakReply(index: number, content: string): void {
  if (!voicePrefs.value.autoSpeakReplies || !speechOutputSupported || !content.trim()) return
  if (listening.value) stopVoiceInput()
  startReplySpeech(index, content, true)
}

/* 输入框随内容自动增高，上限约 7 行，避免长问题被压在小框里。 */
function autoResizeDraft(): void {
  const el = draftInput.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 168)}px`
}

watch(draft, () => autoResizeDraft())

async function send(text?: string, queryTypeOverride?: string): Promise<void> {
  const requestedContent = (text ?? draft.value).trim()
  const file = !text ? selectedFile.value : null
  if ((!requestedContent && !file) || sending.value) return

  cancelActiveSend()
  stopVoiceInput()
  if (speakingIndex.value !== null) {
    stopSpeaking()
    speakingIndex.value = null
  }
  keepPartialReply = false
  sending.value = true
  sendError.value = ''
  let attachmentText: string | undefined
  let attachmentName: string | undefined
  if (file) {
    try {
      const extracted = await apiClient.extractAssistantFile(file, requestOptions.value)
      attachmentText = extracted.text
      attachmentName = extracted.file_name
      selectedFile.value = null
      if (fileInput.value) fileInput.value.value = ''
    } catch (cause) {
      sendError.value = formatError(cause)
      sending.value = false
      return
    }
  }
  const content = requestedContent || '请读取并总结这个文件中的文字。'
  const visibleContent = attachmentName ? `${content}\n📎 ${attachmentName}` : content
  history.value.push({ role: 'user', content: visibleContent, revealed: visibleContent.length })
  persistChatSession()
  draft.value = ''
  stopStatus.value = ''
  if (stopStatusTimer) {
    clearTimeout(stopStatusTimer)
    stopStatusTimer = null
  }
  workflowTrace.value = []
  orchestrationPhase.value = 'routing'
  workflowRouteExplanation.value = null
  stickToBottom.value = true
  scrollToEnd(true)

  const streamingEntry: ChatEntry = {
    role: 'assistant',
    content: '',
    revealed: 0,
  }
  history.value.push(streamingEntry)
  const entryIndex = history.value.length - 1
  const controller = new AbortController()
  activeSendController = controller

  const applyReply = (reply: Awaited<ReturnType<typeof apiClient.assistantChat>>) => {
    const entry = history.value[entryIndex]!
    const alreadyStreamed = entry.content.length > 0 && entry.content === reply.answer
    entry.content = reply.answer
    entry.revealed = alreadyStreamed ? reply.answer.length : 0
    entry.openChat = reply.open_chat
    entry.sources = reply.sources
    entry.citations = reply.citations
    entry.confidence = reply.confidence
    entry.degraded = reply.degraded
    entry.degradeReason = reply.degrade_reason
    entry.escalate = reply.escalate
    entry.suggestedQuestions = normalizeSuggestedQuestions(reply.suggested_questions)
    entry.route = reply.route
    entry.routeExplanation = reply.route_explanation
    entry.queryType = reply.query_type
    entry.riskNotice = reply.risk_notice
    entry.orchestrationMode = reply.orchestration_mode
    entry.allAgentsLocal = reply.all_agents_local
    entry.networkUsed = reply.network_used
    entry.networkQuery = reply.network_query
    entry.agentTrace = reply.agent_trace
    entry.externalSources = reply.external_sources
    entry.memoryCapture = reply.memory_capture
    modelLabel.value = formatModelLabel(reply.model)
    workflowTrace.value = reply.agent_trace ?? []
    workflowRouteExplanation.value = reply.route_explanation ?? null
    persistChatSession()
    autoSpeakReply(entryIndex, reply.answer)
    if (!alreadyStreamed) streamReveal(entry)
  }

  const chatInput = buildAssistantChatInput({
    history: history.value.slice(0, -1),
    allowNetworkSearch: allowNetworkSearch.value,
    queryTypeOverride,
    assistantSessionId: assistantSessionId.value,
    attachmentText,
    attachmentName,
  })

  let streamCancelled = false
  try {
    const reply = await apiClient.assistantChatStream(
      chatInput,
      {
        onTrace: upsertWorkflowTrace,
        onStatus: phase => {
          orchestrationPhase.value = phase
        },
        onToken: token => {
          const entry = history.value[entryIndex]
          if (!entry || !token) return
          // Tokens are already the validated final answer text.
          entry.content += token
          entry.revealed = entry.content.length
          scrollToEnd()
        },
        onCancelled: () => {
          streamCancelled = true
        },
        onExternalSources: sources => {
          const entry = history.value[entryIndex]
          if (entry) entry.externalSources = sources
        },
      },
      session.selectedHouseholdId || undefined,
      session.selectedMemberId || undefined,
      { ...requestOptions.value, signal: controller.signal },
    )
    applyReply(reply)
  } catch (cause) {
    if (controller.signal.aborted || streamCancelled || isAssistantCancellation(cause)) {
      const entry = history.value[entryIndex]
      if (keepPartialReply && entry === streamingEntry && entry.content.trim()) {
        // 决策 4B：结束回复停在已显示内容，不删气泡、不再有新输出。
        entry.revealed = entry.content.length
        persistChatSession()
        showStoppedStatus('已结束回复，保留已生成的内容')
      } else {
        if (entry === streamingEntry) history.value.splice(entryIndex, 1)
        persistChatSession()
        if (userRequestedStop) showStoppedStatus()
      }
      keepPartialReply = false
      userRequestedStop = false
      return
    }
    // Fall back to the non-streaming endpoint when SSE is unavailable.
    try {
      const reply = await apiClient.assistantChat(
        chatInput,
        session.selectedHouseholdId || undefined,
        session.selectedMemberId || undefined,
        { ...requestOptions.value, signal: controller.signal },
      )
      applyReply(reply)
    } catch (fallbackCause) {
      if (controller.signal.aborted || isAssistantCancellation(fallbackCause)) {
        const entry = history.value[entryIndex]
        if (keepPartialReply && entry === streamingEntry && entry.content.trim()) {
          entry.revealed = entry.content.length
          persistChatSession()
          showStoppedStatus('已结束回复，保留已生成的内容')
        } else {
          if (entry === streamingEntry) history.value.splice(entryIndex, 1)
          persistChatSession()
          if (userRequestedStop) showStoppedStatus()
        }
        keepPartialReply = false
        userRequestedStop = false
        return
      }
      sendError.value = formatError(fallbackCause)
      workflowTrace.value = []
      if (history.value[entryIndex]?.role === 'assistant') history.value.pop()
      const entry: ChatEntry = {
        role: 'assistant',
        content: '本地模型或其依赖当前不可用，无法生成回答。家庭事实、规则与任务不受影响，可直接在对应页面查看。',
        revealed: 0,
        degraded: true,
        degradeReason: 'REQUEST_FAILED',
      }
      history.value.push(entry)
      persistChatSession()
      streamReveal(history.value[history.value.length - 1]!)
    }
  } finally {
    if (activeSendController === controller) activeSendController = null
    orchestrationPhase.value = null
    sending.value = false
    void loadAgentCatalog()
    if (!needMicGesture.value && speakingIndex.value === null) void beginWakeListening()
  }
}

function onMemberChange(event: Event): void {
  cancelActiveSend()
  selectMember((event.target as HTMLSelectElement).value)
}

onBeforeUnmount(() => {
  cancelActiveSend()
  stopVoiceInput()
  dictation?.dispose()
  dictation = null
  if (streamTimer) clearInterval(streamTimer)
  if (stopStatusTimer) clearTimeout(stopStatusTimer)
  document.removeEventListener('visibilitychange', onVisibilityChange)
  stopSpeaking()
})
</script>

<template>
  <div class="assistant-shell">
    <aside class="assistant-rail" aria-label="对话记录">
      <button type="button" class="btn btn-primary assistant-new-thread" :disabled="sending" @click="startNewThread">
        <AppIcon name="plus" :size="15" />
        开始新对话
      </button>
      <ul class="assistant-thread-list">
        <li
          v-for="thread in threads"
          :key="thread.id"
          class="assistant-thread"
          :class="{ active: thread.id === activeThreadId }"
        >
          <button
            type="button"
            class="assistant-thread-open"
            :aria-current="thread.id === activeThreadId ? 'true' : undefined"
            :disabled="sending"
            @click="switchThread(thread.id)"
          >
            <strong>{{ thread.title }}</strong>
            <span>{{ threadTimeLabel(thread) }}</span>
          </button>
          <button
            v-if="threads.length > 1"
            type="button"
            class="assistant-thread-delete"
            :aria-label="`删除对话：${thread.title}`"
            :disabled="sending"
            @click="removeThread(thread.id)"
          >
            <AppIcon name="close" :size="12" />
          </button>
        </li>
      </ul>
      <p class="assistant-rail-note">
        <AppIcon name="lock" :size="12" />
        完整对话正文只在浏览器本机持久化；用户明确陈述的健康信息会自动提取为服务器端“未确认”线索，长期保存在家庭数字孪生中。
      </p>
    </aside>

    <section class="assistant-main" aria-label="对话区域">
      <!-- 氛围背景层：纸感米白 + 水彩植物 + 中央柔光，纯装饰不承载内容（HCT-519 视觉） -->
      <div class="assistant-ambient" aria-hidden="true">
        <span class="ambient-mist" />
        <span class="ambient-pattern" />
        <span class="ambient-paper" />
        <span class="ambient-well" />
        <span class="ambient-arc ambient-arc-a" />
        <span class="ambient-arc ambient-arc-b" />
        <span class="ambient-halo" />

        <!-- 左侧：会话轨与主区分隔带旁的极淡植物剪影（左中 + 左下延展） -->
        <svg class="ambient-plant ambient-plant-left-mid" viewBox="0 0 220 560" fill="none">
          <path
            d="M112 556C120 448 96 336 118 224C132 158 124 92 108 26"
            stroke="#7a8c6e"
            stroke-opacity="0.22"
            stroke-width="3"
            stroke-linecap="round"
          />
          <g fill="#6e8a74" fill-opacity="0.15">
            <path d="M116 470C96 466 82 452 80 432C100 434 114 450 116 470Z" />
            <path d="M112 392C132 390 146 376 148 356C128 358 114 372 112 392Z" />
            <path d="M118 300C98 296 84 282 82 262C102 264 116 280 118 300Z" />
          </g>
          <g fill="#8ba283" fill-opacity="0.13">
            <path d="M110 336C90 330 78 316 76 296C96 300 108 316 110 336Z" />
            <path d="M114 254C134 252 148 238 150 218C130 220 116 234 114 254Z" />
            <path d="M112 176C94 170 82 156 80 138C98 142 110 158 112 176Z" />
          </g>
          <g fill="#d6c49e" fill-opacity="0.16">
            <path d="M110 96C94 88 86 74 86 58C102 62 110 78 110 96Z" />
            <circle cx="108" cy="22" r="5" />
          </g>
        </svg>
        <svg class="ambient-plant ambient-plant-left-low" viewBox="0 0 240 200" fill="none">
          <g stroke="#7a8c6e" stroke-opacity="0.18" stroke-width="2.6" stroke-linecap="round">
            <path d="M22 198C30 152 52 112 92 86" />
            <path d="M24 198C46 162 86 140 130 132" />
            <path d="M20 198C24 158 22 122 40 88" />
          </g>
          <g fill="#6e8a74" fill-opacity="0.13">
            <path d="M92 86C74 82 62 70 60 52C80 56 92 68 92 86Z" />
            <path d="M130 132C112 128 100 116 98 98C118 102 130 114 130 132Z" />
            <path d="M40 88C24 82 14 70 12 54C30 58 40 72 40 88Z" />
          </g>
          <g fill="#8ba283" fill-opacity="0.11">
            <path d="M66 118C50 112 40 100 38 84C56 88 66 102 66 118Z" />
            <path d="M104 160C88 156 78 144 76 128C94 132 104 146 104 160Z" />
          </g>
        </svg>

        <!-- 右侧：竖向水彩花枝，沿右边缘向上延展 -->
        <svg class="ambient-plant ambient-plant-right" viewBox="0 0 340 820" fill="none">
          <defs>
            <filter id="hctAmbSoft" x="-20%" y="-20%" width="140%" height="140%">
              <feGaussianBlur stdDeviation="1.2" />
            </filter>
            <path id="hctAmbLeafA" d="M0 0C14 -22 40 -32 64 -26C54 -4 24 8 0 0Z" />
            <path id="hctAmbLeafB" d="M0 0C-14 -22 -40 -32 -64 -26C-54 -4 -24 8 0 0Z" />
            <g id="hctAmbBlossom">
              <g fill="#f4ddba" fill-opacity="0.58">
                <ellipse cx="0" cy="-12.5" rx="6.2" ry="11.5" />
                <ellipse cx="0" cy="-12.5" rx="6.2" ry="11.5" transform="rotate(72)" />
                <ellipse cx="0" cy="-12.5" rx="6.2" ry="11.5" transform="rotate(144)" />
                <ellipse cx="0" cy="-12.5" rx="6.2" ry="11.5" transform="rotate(216)" />
                <ellipse cx="0" cy="-12.5" rx="6.2" ry="11.5" transform="rotate(288)" />
              </g>
              <circle r="4.2" fill="#d9a273" fill-opacity="0.4" />
            </g>
          </defs>
          <g stroke="#7a8c6e" stroke-opacity="0.2" stroke-linecap="round" fill="none">
            <path d="M296 816C266 664 300 522 268 382C246 284 270 162 240 34" stroke-width="3.2" />
            <path d="M280 520C316 500 334 470 340 436" stroke-width="2.2" />
            <path d="M268 382C236 366 218 338 214 302" stroke-width="2.2" />
            <path d="M272 210C238 196 220 170 216 136" stroke-width="2" />
          </g>
          <g filter="url(#hctAmbSoft)">
            <use href="#hctAmbLeafA" fill="#9aac86" fill-opacity="0.17" transform="translate(292 700) rotate(-18) scale(1.15)" />
            <use href="#hctAmbLeafB" fill="#6e8a74" fill-opacity="0.15" transform="translate(284 640) rotate(14)" />
            <use href="#hctAmbLeafA" fill="#b8c29a" fill-opacity="0.16" transform="translate(276 548) rotate(-10) scale(1.05)" />
            <use href="#hctAmbLeafB" fill="#9aac86" fill-opacity="0.14" transform="translate(282 470) rotate(20) scale(0.95)" />
            <use href="#hctAmbLeafA" fill="#e3c8a0" fill-opacity="0.2" transform="translate(268 366) rotate(-24) scale(0.9)" />
            <use href="#hctAmbLeafB" fill="#b8c29a" fill-opacity="0.15" transform="translate(262 300) rotate(10) scale(0.85)" />
            <use href="#hctAmbLeafA" fill="#9aac86" fill-opacity="0.16" transform="translate(268 214) rotate(-14) scale(0.9)" />
            <use href="#hctAmbLeafB" fill="#6e8a74" fill-opacity="0.13" transform="translate(246 120) rotate(18) scale(0.75)" />
            <use href="#hctAmbLeafA" fill="#cfd8b8" fill-opacity="0.18" transform="translate(322 470) rotate(-30) scale(0.8)" />
          </g>
          <circle cx="340" cy="432" r="3.4" fill="#d9a273" fill-opacity="0.32" />
          <circle cx="212" cy="298" r="3" fill="#d6c49e" fill-opacity="0.36" />
          <circle cx="240" cy="28" r="3.6" fill="#d9a273" fill-opacity="0.3" />
          <use href="#hctAmbBlossom" transform="translate(214 292) scale(0.8)" />
          <use href="#hctAmbBlossom" transform="translate(214 128) scale(0.95)" />
          <use href="#hctAmbBlossom" transform="translate(268 560) scale(1.05)" />
        </svg>
        <svg class="ambient-plant ambient-plant-right-top" viewBox="0 0 260 150" fill="none">
          <path
            d="M8 12C86 30 172 66 248 126"
            stroke="#8ba283"
            stroke-opacity="0.2"
            stroke-width="2.4"
            stroke-linecap="round"
          />
          <g fill="#9aac86" fill-opacity="0.15">
            <path d="M84 30C68 26 58 16 56 2C74 6 84 16 84 30Z" />
            <path d="M150 62C134 58 124 48 122 34C140 38 150 48 150 62Z" />
            <path d="M196 92C212 90 224 80 228 66C210 68 200 78 196 92Z" />
          </g>
          <circle cx="236" cy="112" r="4" fill="#d9a273" fill-opacity="0.3" />
          <circle cx="118" cy="34" r="2.6" fill="#d6c49e" fill-opacity="0.4" />
        </svg>

        <!-- 右下：小宠物的陪伴柔光底 + 叶芽点缀 -->
        <span class="ambient-pet-glow" />
        <svg class="ambient-plant ambient-pet-sprig" viewBox="0 0 130 80" fill="none">
          <path
            d="M6 70C34 58 62 44 92 22"
            stroke="#8ba283"
            stroke-opacity="0.22"
            stroke-width="2.2"
            stroke-linecap="round"
          />
          <g fill="#9aac86" fill-opacity="0.18">
            <path d="M38 56C24 52 16 42 15 28C31 33 39 44 38 56Z" />
            <path d="M66 40C54 34 48 24 48 12C62 18 68 30 66 40Z" />
          </g>
          <circle cx="96" cy="16" r="3.4" fill="#d9a273" fill-opacity="0.34" />
          <circle cx="112" cy="30" r="2.2" fill="#d6c49e" fill-opacity="0.42" />
        </svg>

        <!-- 底部：轻微落地渐变，提升空间稳定感 -->
        <span class="ambient-ground" />

        <!-- 漂浮微尘颗粒 -->
        <span class="ambient-dust"><i /><i /><i /><i /><i /><i /><i /></span>
      </div>

      <header class="assistant-topbar">
        <div class="assistant-topbar-title">
          <h2 class="hero-greeting">本地证据助手</h2>
        </div>
        <div class="assistant-topbar-actions">
          <label class="context-select">
            当前成员
            <select :value="session.selectedMemberId" @change="onMemberChange">
              <option v-for="member in session.members" :key="member.id" :value="member.id">
                {{ member.display_name }}
              </option>
            </select>
          </label>
          <button
            type="button"
            class="assistant-settings-trigger"
            aria-label="打开语音设置"
            title="语音设置"
            :aria-expanded="settingsOpen"
            @click="settingsOpen = true"
          >
            <AppIcon name="settings" :size="16" />
          </button>
        </div>
      </header>

      <div ref="chatWindow" class="chat-window" @scroll.passive="onChatScroll">
      <div class="chat-thread" :class="{ empty: history.length === 0 }">
      <div v-if="history.length === 0" class="assistant-empty">
        <span class="assistant-empty-art" aria-hidden="true">
          <svg class="assistant-empty-orb" viewBox="0 0 96 96" fill="none">
            <circle cx="48" cy="48" r="34" fill="var(--pine, #38665a)" opacity="0.92" />
            <circle cx="48" cy="48" r="34" stroke="var(--pine-deep, #2a4d42)" stroke-width="1.6" />
            <path
              d="M48 60c-6.4-4.2-10.4-8.4-10.4-13 0-3.3 2.5-5.8 5.5-5.8 1.9 0 3.6 1 4.9 2.8 1.3-1.8 3-2.8 4.9-2.8 3 0 5.5 2.5 5.5 5.8 0 4.6-4 8.8-10.4 13z"
              fill="#fff"
              opacity="0.94"
            />
            <circle cx="37" cy="34" r="7" fill="#fff" opacity="0.28" />
          </svg>
          <svg class="assistant-empty-sprig left" viewBox="0 0 56 44" fill="none" aria-hidden="true">
            <path d="M4 40C15 32 28 22 50 8" stroke="#6e8a74" stroke-opacity="0.4" stroke-width="1.8" stroke-linecap="round" />
            <g fill="#6e8a74" fill-opacity="0.34">
              <path d="M17 31C10 27 6 20 7 12C15 16 19 24 17 31Z" />
              <path d="M30 21C24 16 22 9 24 2C31 7 33 15 30 21Z" />
            </g>
            <path d="M41 14C37 9 36 4 38 0C43 3 44 10 41 14Z" fill="#8ba283" fill-opacity="0.3" />
            <circle cx="50" cy="7" r="2" fill="#d9a273" fill-opacity="0.4" />
          </svg>
          <svg class="assistant-empty-sprig right" viewBox="0 0 56 44" fill="none" aria-hidden="true">
            <path d="M4 40C15 32 28 22 50 8" stroke="#6e8a74" stroke-opacity="0.4" stroke-width="1.8" stroke-linecap="round" />
            <g fill="#6e8a74" fill-opacity="0.34">
              <path d="M17 31C10 27 6 20 7 12C15 16 19 24 17 31Z" />
              <path d="M30 21C24 16 22 9 24 2C31 7 33 15 30 21Z" />
            </g>
            <path d="M41 14C37 9 36 4 38 0C43 3 44 10 41 14Z" fill="#8ba283" fill-opacity="0.3" />
            <circle cx="50" cy="7" r="2" fill="#d9a273" fill-opacity="0.4" />
          </svg>
        </span>
        <strong class="assistant-empty-title">向家庭助手提问</strong>
        <div class="assistant-empty-suggestions">
          <button
            v-for="suggestion in SUGGESTIONS"
            :key="suggestion"
            type="button"
            class="assistant-suggestion"
            @click="useSuggestedQuestion(suggestion)"
          >
            <AppIcon name="sparkle" :size="13" aria-hidden="true" />
            {{ suggestion }}
          </button>
        </div>
      </div>

      <div
        v-for="(entry, index) in history"
        v-show="entry.role === 'user' || entry.content.length > 0"
        :key="index"
        class="chat-bubble-row"
        :class="entry.role"
      >
        <span v-if="entry.role === 'assistant'" class="chat-avatar" aria-hidden="true">
          <AppIcon name="assistant" :size="16" />
        </span>
        <div class="chat-bubble">
          <div class="chat-message-text" :aria-live="isStreaming(entry) ? 'polite' : undefined"><span class="chat-message-content">{{ entry.role === 'assistant' ? entry.content.slice(0, entry.revealed) : entry.content }}</span><span v-if="isStreaming(entry)" class="stream-caret" aria-hidden="true" /></div>
          <details
            v-if="entry.role === 'assistant' && !isStreaming(entry) && hasEvidenceDetails(entry)"
            class="chat-evidence"
          >
            <summary>
              <span class="chat-evidence-title">
                <AppIcon name="review" :size="14" />
                查看依据
              </span>
              <small>{{ evidenceDisclosureSummary(entry) }}</small>
            </summary>
            <div class="chat-sources">
            <span v-if="isKnowledgeGapDegrade(entry)" class="chat-evidence-summary">
              <AppIcon name="compass" :size="12" style="vertical-align: -1px" />
              本机暂无已审核的相关知识卡，以上是一般照护提示；具体用药请咨询医生或药师。
            </span>
            <span v-else-if="entry.degraded" style="color: var(--gold)">
              ⚠ {{ degradeReasonLabel(entry.degradeReason) }}，以上为受控回复，不含模型生成的医疗判断。
            </span>
            <span v-if="entry.escalate" style="color: var(--rose)">
              此问题超出助手边界，请联系医生或药师进一步确认。
            </span>
            <span v-else-if="visibleRiskNotice(entry.escalate, entry.riskNotice)" style="color: var(--rose)">
              ⚠ {{ visibleRiskNotice(entry.escalate, entry.riskNotice) }}
            </span>
            <span v-if="routeSummary(entry.queryType, entry.routeExplanation)" class="chat-route-explanation">
              <AppIcon name="compass" :size="12" style="vertical-align: -1px" />
              {{ routeSummary(entry.queryType, entry.routeExplanation) }}
              <template v-if="entry.confidence && !entry.degraded"> · 把握程度：{{ confidenceLabel(entry.confidence) }}</template>
            </span>
            <span v-if="!entry.degraded && (entry.citations?.length ?? 0) === 0" class="chat-evidence-summary">
              <AppIcon name="compass" :size="12" style="vertical-align: -1px" />
              依据状态：{{ evidenceSummary(entry) }}
            </span>
            <span v-if="entry.orchestrationMode === 'multi_agent'" class="chat-agent-locality">
              <AppIcon name="assistant" :size="12" style="vertical-align: -1px" />
              已完成本次证据编排
              <span v-if="entry.networkUsed" class="chat-agent-network">已补充脱敏联网参考</span>
            </span>
            <span
              v-if="(entry.memoryCapture?.saved_count ?? 0) + (entry.memoryCapture?.updated_count ?? 0) > 0"
              class="chat-memory-capture"
            >
              <AppIcon name="sparkle" :size="12" style="vertical-align: -1px" />
              已自动提取或更新 {{ (entry.memoryCapture?.saved_count ?? 0) + (entry.memoryCapture?.updated_count ?? 0) }} 条聊天线索；新线索为“未确认”状态，可在数字孪生页面核对。
            </span>
            <div v-if="(entry.agentTrace?.length ?? 0) > 0" class="chat-agent-trace" aria-label="处理步骤">
              <span v-for="trace in entry.agentTrace" :key="trace.agent_id" class="chat-agent-chip">
                {{ trace.role }} · {{ trace.status === 'completed' ? '完成' : trace.status === 'skipped' ? '跳过' : trace.status === 'blocked' ? '拦截' : '降级' }}
                <small>{{ trace.network_used ? '联网' : '本地编排' }}</small>
              </span>
            </div>
            <template v-if="extraFactSources(entry.sources, entry.citations).length > 0">
              <span v-for="source in extraFactSources(entry.sources, entry.citations)" :key="source">
                <AppIcon name="compass" :size="12" style="vertical-align: -1px" />
                依据标识：{{ source }}
              </span>
            </template>
            <span v-if="(entry.citations?.length ?? 0) > 0" class="chat-meta-label">
              依据 · {{ entry.citations?.length }} 条
            </span>
            <details
              v-for="citation in entry.citations ?? []"
              :key="`${citation.document_id}:${citation.chunk_id}`"
              class="chat-citation"
            >
              <summary>
                <span>{{ citationTitle(citation) }}</span>
                <span class="text-faint">版本 {{ citation.version || '未提供' }} · 片段 {{ citation.chunk_id }}</span>
              </summary>
              <p v-if="citation.text" class="chat-citation-text">{{ citation.text }}</p>
              <p v-else class="text-faint">本次响应未返回片段正文，仅保留服务端核验过的引用标识。</p>
              <p v-if="citation.locator" class="text-faint">定位：{{ citation.locator }}</p>
            </details>
              <details v-if="(entry.externalSources?.length ?? 0) > 0" class="chat-citation chat-external-sources">
              <summary>外部参考（非本地审核证据）· {{ entry.externalSources?.length }} 条</summary>
              <a
                v-for="source in entry.externalSources"
                :key="source.url"
                class="chat-external-source"
                :href="source.url"
                target="_blank"
                rel="noreferrer noopener"
              >
                <strong>{{ source.title }}</strong>
                <span>{{ source.domain || source.url }}</span>
                <small v-if="source.snippet">{{ source.snippet }}</small>
              </a>
              </details>
            </div>
          </details>
          <!-- 相关追问：服务端 suggested_questions 已在 entry 上归一化，
               但 HCT-516 精简时把渲染块一并删掉，导致这批建议永远不显示。
               只挂在最后一条已完成的助手回复下，点击放入输入框由用户确认后再发。 -->
          <div
            v-if="entry.role === 'assistant' && !isStreaming(entry) && index === history.length - 1 && (entry.suggestedQuestions?.length ?? 0) > 0"
            class="chat-follow-ups"
            aria-label="相关追问"
          >
            <div class="chat-follow-ups-heading">
              <span class="chat-follow-ups-label"><AppIcon name="sparkle" :size="13" />接下来可以问</span>
              <small>点击后会放入输入框，可修改后再发送</small>
            </div>
            <button
              v-for="question in entry.suggestedQuestions"
              :key="question"
              type="button"
              class="btn btn-ghost btn-small chat-follow-up"
              :disabled="sending"
              @click="useSuggestedQuestion(question)"
            >
              {{ question }}
            </button>
          </div>
          <div
            v-if="entry.role === 'assistant' && !isStreaming(entry) && entry.content"
            class="chat-message-actions"
            aria-label="回答操作"
          >
            <button
              type="button"
              class="btn btn-ghost btn-small"
              aria-label="复制回答全文"
              @click="copyReply(entry.content)"
            >
              <AppIcon name="check" :size="14" />
              复制
            </button>
            <template v-if="speechOutputSupported">
              <button
                type="button"
                class="btn btn-ghost btn-small"
                :aria-label="speakingIndex === index ? '停止朗读回答' : '朗读回答'"
                :aria-pressed="speakingIndex === index"
                @click="toggleSpeech(index, entry.content)"
              >
                <AppIcon :name="speakingIndex === index ? 'close' : 'volume'" :size="14" />
                {{ speakingIndex === index ? '停止朗读' : '朗读回答' }}
              </button>
              <button
                v-if="speakingIndex === index && speakingProgress"
                type="button"
                class="btn btn-ghost btn-small"
                @click="skipCurrentSpeechSegment"
              >
                {{ speakingProgress }} · 跳过本句
              </button>
            </template>
            <button
              v-if="canRecheckMedicationSafety(entry.queryType)"
              type="button"
              class="btn btn-ghost btn-small"
              :disabled="sending"
              @click="resendAsMedicationSafety(index)"
            >
              <AppIcon name="shield" :size="14" />
              按用药安全再查一次
            </button>
            <div
              v-if="speechOutputSupported && speakingIndex === index && activeSpeakingSegments.length > 1"
              class="speech-segment-chips"
              aria-label="朗读分段跳转"
            >
              <button
                v-for="(segment, segmentIndex) in activeSpeakingSegments"
                :key="`${segmentIndex}-${segment.slice(0, 12)}`"
                type="button"
                class="btn btn-ghost btn-small"
                :class="{ active: speakingSegmentIndex === segmentIndex }"
                :aria-current="speakingSegmentIndex === segmentIndex ? 'true' : undefined"
                @click="jumpSpeechSegment(segmentIndex)"
              >
                第 {{ segmentIndex + 1 }} 句
              </button>
            </div>
          </div>
        </div>
      </div>

      <div v-if="sending && !(history[history.length - 1]?.role === 'assistant' && (history[history.length - 1]?.content.length ?? 0) > 0)" class="chat-bubble-row assistant">
        <span class="chat-avatar thinking" aria-hidden="true">
          <AppIcon name="assistant" :size="16" />
        </span>
        <div class="chat-bubble thinking-bubble" role="status">
          <span class="thinking-wave" aria-hidden="true"><i /><i /><i /><i /></span>
          <span class="thinking-text">{{ thinkingText }}</span>
        </div>
      </div>
      </div>
    </div>

      <p v-if="sendError" class="notice error" role="alert">
        <AppIcon name="alert" :size="16" />
        {{ sendError }}
      </p>
      <p v-if="stopStatus" class="notice info" role="status" aria-live="polite">
        {{ stopStatus }}
      </p>
      <p v-if="voiceError" class="notice error" role="alert">
        <AppIcon name="alert" :size="16" />
        {{ voiceError }}
      </p>
      <div v-if="needMicGesture && !listening" class="voice-session-panel wake" role="status">
        <span class="voice-session-visual" aria-hidden="true"><AppIcon name="microphone" :size="24" /></span>
        <span class="voice-session-copy">
          <strong>语音唤醒已准备好</strong>
          <span>浏览器需要一次点按来允许麦克风，之后会持续等待唤醒词。</span>
        </span>
        <button type="button" class="btn btn-primary btn-small" @click="toggleVoiceInput">允许并开启</button>
      </div>
      <div v-if="listening || voiceMode === 'ready'" class="voice-session-panel" :class="voiceMode" role="status" aria-live="polite">
        <span class="voice-session-visual" aria-hidden="true">
          <span class="voice-session-ring" />
          <span class="voice-session-ring second" />
          <AppIcon name="microphone" :size="22" />
        </span>
        <span class="voice-session-copy">
          <strong>{{ voiceMode === 'wake' ? '常开唤醒' : voiceMode === 'ready' ? '口述已完成' : voiceMode === 'command' ? '等待语音指令' : '正在听写' }}</strong>
          <span>{{ voiceStatusText }}</span>
          <span v-if="voicePreview" class="voice-live-transcript">{{ voicePreview }}</span>
        </span>
      </div>
      <form class="chat-compose assistant-composer" @submit.prevent="send()">
        <input
          ref="fileInput"
          class="assistant-file-input"
          type="file"
          title="上传文件"
          @change="onAttachmentChange"
        />
        <div v-if="selectedFile" class="assistant-attachment-chip" role="status">
          <AppIcon name="upload" :size="14" />
          <span>{{ selectedFile.name }}</span>
          <small>发送前提取文字</small>
          <button type="button" class="btn btn-ghost btn-small" :disabled="sending" @click="clearAttachment">移除</button>
        </div>
        <textarea
          ref="draftInput"
          v-model="draft"
          rows="2"
          placeholder="例如：最近的用药提醒是依据什么？（回答仅供参考，不构成医疗建议）"
          @focus="onDraftFocus"
          @keydown.enter.exact.prevent="send()"
        />
        <div v-if="voiceMode === 'ready' || voiceMode === 'command'" class="voice-ready-actions" role="group" aria-label="口述确认">
          <button type="button" class="btn btn-primary btn-large" :disabled="!canSend" @click="send()">
            <AppIcon name="arrow-up" :size="16" />发送这段话
          </button>
          <button type="button" class="btn btn-ghost" @click="editDraftLine">改一句</button>
          <button type="button" class="btn btn-ghost btn-small" @click="redoVoiceDraft">重说</button>
          <button type="button" class="btn btn-ghost btn-small" @click="toggleVoiceInput">{{ voiceButtonLabel }}</button>
        </div>
        <p v-if="voiceSendHint" class="assistant-voice-send-hint" role="status">{{ voiceSendHint }}</p>
        <div v-if="voiceMode !== 'ready' && voiceMode !== 'command'" class="chat-compose-actions assistant-composer-actions">
          <label
            class="assistant-net-toggle"
            :title="webSearchAvailable === false
              ? webSearchDisabledText
              : '联网搜索只发送脱敏问题，不额外发送成员档案、图片或健康记录'"
          >
            <input v-model="allowNetworkSearch" type="checkbox" :disabled="webSearchAvailable === false" />
            <AppIcon name="cloud" :size="14" />
            联网搜索
            <span v-if="webSearchBadge" class="pill sage">{{ webSearchBadge }}</span>
          </label>
          <span class="assistant-composer-spacer" aria-hidden="true" />
          <button
            type="button"
            class="btn btn-ghost btn-small assistant-attach-button"
            :disabled="sending"
            title="上传文件并提取其中的文字"
            @click="chooseAttachment"
          >
            <AppIcon name="upload" :size="14" />
            上传文件
          </button>
          <button
            v-if="speechInputSupported"
            type="button"
            class="btn btn-ghost btn-small voice-input-button"
            :class="{ listening, active: voiceMode === 'active', need: needMicGesture }"
            :aria-pressed="listening"
            :aria-label="listening ? '停止语音唤醒' : voiceButtonLabel"
            :title="`进入助手页后会自动尝试聆听；首次需点按允许麦克风，再说「${wakePhrase}」`"
            @click="toggleVoiceInput"
          >
            <AppIcon :name="listening ? 'close' : 'microphone'" :size="14" />
            {{ voiceButtonLabel }}
          </button>
          <button
            ref="sendButton"
            type="button"
            class="assistant-send"
            :disabled="!sending && !canSend"
            :aria-label="sending ? '停止生成本次回答' : '发送'"
            :title="sending ? '停止生成本次回答' : '发送'"
            @click="sending ? cancelActiveSend(true) : send()"
          >
            <AppIcon :name="sending ? 'stop' : 'arrow-up'" :size="18" />
          </button>
        </div>
      </form>
      <p class="assistant-footnote">
        回答基于本地证据，仅供参考，不构成医疗建议；紧急情况请直接联系医生或药师。
      </p>
    </section>

    <div v-if="settingsOpen" class="assistant-settings-backdrop" @click.self="settingsOpen = false">
      <aside class="assistant-settings-drawer" role="dialog" aria-modal="true" aria-labelledby="assistant-settings-title">
        <header class="assistant-settings-header">
          <div>
            <p class="eyebrow">助手偏好</p>
            <h3 id="assistant-settings-title">语音唤醒与播报</h3>
          </div>
          <button type="button" class="assistant-settings-close" aria-label="关闭语音设置" @click="settingsOpen = false">
            <AppIcon name="close" :size="16" />
          </button>
        </header>
        <p class="assistant-settings-note">进入助手后会自动尝试保持唤醒聆听；你可以随时在输入区关闭。语音识别和播报均由浏览器本地完成。</p>
        <section class="assistant-settings-section voice-prefs-panel" aria-label="语音偏好与自检">
          <h4>语音偏好</h4>
          <label class="voice-pref-row">
            <span>唤醒词</span>
            <div class="voice-pref-control voice-wake-control">
              <input v-model="wakePhraseDraft" maxlength="8" aria-label="唤醒词" @keydown.enter.prevent="saveWakePhrase" />
              <button type="button" class="btn btn-ghost btn-small" @click="saveWakePhrase">保存</button>
            </div>
          </label>
          <div class="voice-preset-row" aria-label="唤醒词预设">
            <button
              v-for="preset in WAKE_PHRASE_PRESETS"
              :key="preset.id"
              type="button"
              class="btn btn-ghost btn-small"
              :class="{ active: wakePhrase === preset.phrase }"
              @click="applyWakePreset(preset.phrase)"
            >{{ preset.phrase }}</button>
          </div>
          <label class="voice-pref-row">
            <span>句末判定</span>
            <select :value="silencePresetId" aria-label="句末判定" @change="applySilencePreset(($event.target as HTMLSelectElement).value)">
              <option v-for="preset in SILENCE_PRESETS" :key="preset.id" :value="preset.id">{{ preset.label }}</option>
            </select>
          </label>
          <label class="voice-pref-row">
            <span>自动发送</span>
            <select :value="autoSendPresetId" aria-label="自动发送" @change="applyAutoSendPreset(($event.target as HTMLSelectElement).value)">
              <option v-for="preset in AUTO_SEND_PRESETS" :key="preset.id" :value="preset.id">{{ preset.label }}</option>
            </select>
          </label>
          <label class="voice-pref-row voice-check-row"><input type="checkbox" :checked="voicePrefs.autoSpeakReplies" @change="toggleVoicePref('autoSpeakReplies', ($event.target as HTMLInputElement).checked)" /><span>回答完成后自动朗读</span></label>
          <label class="voice-pref-row voice-check-row"><input type="checkbox" :checked="voicePrefs.confirmSound" @change="toggleVoicePref('confirmSound', ($event.target as HTMLInputElement).checked)" /><span>自动发送倒计时播放确认音</span></label>
          <label class="voice-pref-row voice-check-row"><input type="checkbox" :checked="voicePrefs.doubleWake" @change="toggleVoicePref('doubleWake', ($event.target as HTMLInputElement).checked)" /><span>需要连续两次唤醒词，减少误触</span></label>
          <label class="voice-pref-row voice-check-row"><input type="checkbox" :checked="voicePrefs.voiceCommands" @change="toggleVoicePref('voiceCommands', ($event.target as HTMLInputElement).checked)" /><span>听写后接收白名单语音指令</span></label>
          <label v-if="speechOutputSupported" class="voice-pref-row">
            <span>播报音色</span>
            <select :value="voicePrefs.preferredVoiceName" aria-label="播报音色" @change="applyPreferredVoice(($event.target as HTMLSelectElement).value)">
              <option value="">自动选择中文音色</option>
              <option v-for="voiceOption in voiceOptions" :key="voiceOption.name" :value="voiceOption.name">{{ voiceOption.name }}（{{ voiceOption.lang }}{{ voiceOption.localService ? ' · 本地' : '' }}）</option>
            </select>
            <button type="button" class="btn btn-ghost btn-small" @click="previewPreferredVoice">试听</button>
          </label>
          <div class="voice-check-actions">
            <button type="button" class="btn btn-ghost btn-small" :disabled="voicePackChecking" @click="checkVoicePacks">{{ voicePackChecking ? '检测中…' : '检查中文语音包' }}</button>
            <button type="button" class="btn btn-ghost btn-small" :disabled="preflightRunning" @click="runPreflight">{{ preflightRunning ? '自检中…' : '运行语音预检' }}</button>
          </div>
          <p v-if="voicePackReport" class="text-faint voice-check-result">{{ voicePackReport.guidance }}</p>
          <ul v-if="preflightReport" class="voice-preflight-list">
            <li v-for="(line, index) in preflightReport.guidance" :key="index">{{ line }}</li>
          </ul>
        </section>
        <p class="assistant-settings-model">当前回答模型：{{ modelLabel }} · SSE 流式输出已开启</p>
      </aside>
    </div>

  </div>
</template>

<style scoped>
/* ---------- 全幅对话画布 + 会话轨 ---------- */

.assistant-file-input {
  display: none;
}

.assistant-attachment-chip {
  align-items: center;
  background: color-mix(in srgb, var(--sky, #55809c) 10%, transparent);
  border: 1px solid color-mix(in srgb, var(--sky, #55809c) 28%, transparent);
  border-radius: 10px;
  color: var(--ink, #2f3834);
  display: flex;
  gap: 8px;
  margin: 0 0 8px;
  max-width: 100%;
  padding: 7px 9px;
}

.chat-memory-capture {
  color: var(--clay, #9a6b34);
  display: block;
  line-height: 1.5;
  margin-top: 4px;
}

.assistant-attachment-chip span {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.assistant-attachment-chip small {
  color: var(--ink-soft, #69746c);
  white-space: nowrap;
}

.assistant-attach-button {
  white-space: nowrap;
}

.assistant-shell {
  display: flex;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
  position: relative;
  width: 100%;
}

.assistant-rail {
  background: color-mix(in srgb, var(--paper-deep, #f1e9d8) 62%, transparent);
  border-right: 1px solid var(--line-soft, rgba(190, 167, 125, 0.3));
  display: flex;
  flex: 0 0 232px;
  flex-direction: column;
  gap: 12px;
  min-height: 0;
  padding: 16px 12px 12px;
  width: 232px;
}

.assistant-new-thread {
  justify-content: center;
  width: 100%;
}

.assistant-thread-list {
  align-content: start;
  display: grid;
  flex: 1 1 auto;
  gap: 6px;
  list-style: none;
  margin: 0;
  min-height: 0;
  overflow-y: auto;
  padding: 0 2px 0 0;
}

.assistant-thread {
  display: flex;
  position: relative;
}

.assistant-thread-open {
  background: transparent;
  border: 1px solid transparent;
  border-radius: 12px;
  cursor: pointer;
  display: grid;
  flex: 1 1 auto;
  gap: 2px;
  min-width: 0;
  padding: 9px 28px 9px 11px;
  text-align: left;
  transition: background 0.16s ease, border-color 0.16s ease;
}

.assistant-thread-open strong {
  color: var(--ink, #3f3a31);
  font-size: 13px;
  font-weight: 650;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.assistant-thread-open > span {
  color: var(--ink-faint, #a2937c);
  font-size: 11px;
}

.assistant-thread-open:hover,
.assistant-thread-open:focus-visible {
  background: color-mix(in srgb, var(--card, #fffcf3) 80%, transparent);
  border-color: var(--line-soft, rgba(190, 167, 125, 0.3));
  outline: none;
}

.assistant-thread.active .assistant-thread-open {
  background: var(--card, #fffcf3);
  border-color: color-mix(in srgb, var(--pine, #38665a) 34%, transparent);
  box-shadow: inset 3px 0 0 var(--pine, #38665a), 0 6px 16px rgba(94, 71, 42, 0.08);
}

.assistant-thread.active .assistant-thread-open strong { color: var(--pine-deep, #2a5045); }

.assistant-thread-delete {
  align-items: center;
  background: transparent;
  border: 0;
  border-radius: 999px;
  color: var(--ink-faint, #a2937c);
  cursor: pointer;
  display: inline-flex;
  height: 22px;
  justify-content: center;
  opacity: 0;
  position: absolute;
  right: 6px;
  top: 50%;
  transform: translateY(-50%);
  transition: opacity 0.15s ease, color 0.15s ease;
  width: 22px;
}

.assistant-thread:hover .assistant-thread-delete,
.assistant-thread-delete:focus-visible {
  opacity: 1;
}

.assistant-thread-delete:hover { color: var(--rose, #b04a5a); }

.assistant-rail-note {
  align-items: center;
  color: var(--ink-faint, #a2937c);
  display: flex;
  font-size: 11.5px;
  gap: 5px;
  line-height: 1.5;
  margin: 0;
}

.assistant-main {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  gap: 10px;
  min-height: 0;
  min-width: 0;
  padding: 14px clamp(16px, 2.4vw, 30px) 12px;
  position: relative;
}

/* ---------- 氛围背景层：纸感米白 + 水彩植物 + 中央柔光（HCT-519 视觉） ----------
   只做背景氛围：内容层全部抬到 z-index:1，装饰层 pointer-events:none，
   不参与布局，也不遮挡输入框、按钮与文字。 */
.assistant-main > *:not(.assistant-ambient) {
  position: relative;
  z-index: 1;
}

.assistant-ambient {
  inset: 0;
  overflow: hidden;
  pointer-events: none;
  position: absolute;
  z-index: 0;
}

.assistant-ambient > * {
  position: absolute;
}

/* 四周极淡的渐变晕染，中央内容区保持明亮 */
.ambient-mist {
  background:
    radial-gradient(42% 34% at 6% 10%, rgba(110, 138, 116, 0.1), transparent 70%),
    radial-gradient(36% 28% at 98% 4%, rgba(226, 178, 116, 0.1), transparent 72%),
    radial-gradient(44% 34% at 102% 74%, rgba(148, 168, 132, 0.12), transparent 72%),
    radial-gradient(38% 30% at -2% 88%, rgba(224, 196, 148, 0.1), transparent 70%);
  inset: 0;
}

/* 极淡的重复小纹样：叶片线稿 + 种子芽点，只作背景肌理 */
.ambient-pattern {
  background-image: var(--motif-leaf, none);
  background-size: 168px 168px;
  inset: 0;
  opacity: 0.34;
}

/* 纸张纤维般的低频水彩斑点 */
.ambient-paper {
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='460' height='460'%3E%3Cfilter id='p'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.011 0.013' numOctaves='3' seed='11' stitchTiles='stitch'/%3E%3CfeColorMatrix type='matrix' values='0 0 0 0 0.44 0 0 0 0 0.40 0 0 0 0 0.31 0 0 0 0.055 0'/%3E%3C/filter%3E%3Crect width='460' height='460' filter='url(%23p)'/%3E%3C/svg%3E");
  background-size: 460px 460px;
  inset: 0;
  opacity: 0.5;
}

/* 中央柔光聚焦区：像温暖晨光照在主标题后方，不是舞台灯 */
.ambient-well {
  background: radial-gradient(
    52% 46% at 50% 46%,
    rgba(255, 253, 244, 0.72),
    rgba(255, 251, 238, 0.3) 55%,
    transparent 76%
  );
  height: 520px;
  left: 50%;
  top: 34%;
  transform: translateX(-50%);
  width: min(880px, 92%);
}

.ambient-halo {
  background: radial-gradient(
    46% 44% at 50% 46%,
    rgba(240, 220, 170, 0.26),
    rgba(230, 224, 192, 0.13) 52%,
    transparent 74%
  );
  height: 440px;
  left: 50%;
  top: 30%;
  transform: translateX(-50%);
  transition: opacity 0.3s ease;
  width: min(760px, 84%);
}

/* 有对话内容时柔光收淡，不干扰正文阅读 */
.assistant-main:has(.chat-thread:not(.empty)) .ambient-halo {
  opacity: 0.55;
}

/* 弧形细线：极浅的圆环切线，只为空间层次 */
.ambient-arc {
  border: 1px solid rgba(110, 138, 116, 0.17);
  border-radius: 50%;
}

.ambient-arc-a {
  height: 640px;
  left: 50%;
  top: -470px;
  transform: translateX(-58%);
  width: 640px;
}

.ambient-arc-b {
  border-color: rgba(169, 126, 31, 0.14);
  height: 420px;
  right: -190px;
  top: 16%;
  width: 420px;
}

.ambient-plant {
  opacity: 0.92;
}

.ambient-plant-left-mid {
  height: 440px;
  left: -30px;
  top: 14%;
  width: 180px;
}

.ambient-plant-left-low {
  bottom: -6px;
  height: 196px;
  left: -44px;
  opacity: 0.85;
  width: 230px;
}

.ambient-plant-right {
  height: calc(100% + 24px);
  right: -24px;
  top: -12px;
  width: clamp(220px, 21vw, 330px);
}

.ambient-plant-right-top {
  height: 122px;
  right: 30px;
  top: -8px;
  width: 210px;
}

/* 右下宠物位：米白/淡绿圆形柔光底 + 细环，让宠物像陪伴入口 */
.ambient-pet-glow {
  background: radial-gradient(
    closest-side,
    rgba(255, 250, 236, 0.85),
    rgba(226, 236, 220, 0.42) 56%,
    transparent 78%
  );
  bottom: -34px;
  height: 252px;
  right: -14px;
  width: 252px;
}

.ambient-pet-glow::after {
  border: 1px solid rgba(110, 138, 116, 0.12);
  border-radius: 50%;
  content: "";
  inset: 16%;
  position: absolute;
}

.ambient-pet-sprig {
  bottom: 22px;
  height: 74px;
  opacity: 0.9;
  right: 206px;
  width: 118px;
}

/* 底部轻微地面感 */
.ambient-ground {
  background:
    linear-gradient(to top, rgba(211, 192, 152, 0.16), rgba(211, 192, 152, 0.05) 46%, transparent),
    radial-gradient(56% 100% at 50% 118%, rgba(186, 178, 140, 0.12), transparent 72%);
  bottom: 0;
  height: 132px;
  left: 0;
  right: 0;
}

/* 柔和浮尘颗粒：极轻、缓慢， prefers-reduced-motion 时静止 */
.ambient-dust {
  inset: 0;
}

.ambient-dust i {
  animation: ambient-float 16s ease-in-out infinite alternate;
  border-radius: 50%;
  filter: blur(1px);
  position: absolute;
}

.ambient-dust i:nth-child(1) { animation-duration: 17s; background: rgba(233, 186, 110, 0.5); height: 5px; left: 12%; top: 20%; width: 5px; }
.ambient-dust i:nth-child(2) { animation-delay: -6s; animation-duration: 19s; background: rgba(142, 166, 138, 0.42); height: 4px; left: 24%; top: 58%; width: 4px; }
.ambient-dust i:nth-child(3) { animation-delay: -3s; background: rgba(226, 205, 160, 0.55); height: 3px; left: 37%; top: 12%; width: 3px; }
.ambient-dust i:nth-child(4) { animation-delay: -9s; animation-duration: 21s; background: rgba(226, 205, 160, 0.45); height: 5px; left: 64%; top: 24%; width: 5px; }
.ambient-dust i:nth-child(5) { animation-delay: -12s; background: rgba(233, 186, 110, 0.4); height: 4px; left: 78%; top: 44%; width: 4px; }
.ambient-dust i:nth-child(6) { animation-delay: -4s; animation-duration: 23s; background: rgba(142, 166, 138, 0.3); height: 6px; left: 88%; top: 12%; width: 6px; }
.ambient-dust i:nth-child(7) { animation-delay: -15s; animation-duration: 18s; background: rgba(233, 186, 110, 0.35); height: 3px; left: 52%; top: 40%; width: 3px; }

@keyframes ambient-float {
  from { transform: translate3d(0, 0, 0); }
  to { transform: translate3d(6px, -14px, 0); }
}

.assistant-topbar {
  align-items: center;
  display: flex;
  flex: 0 0 auto;
  flex-wrap: wrap;
  gap: 10px 14px;
  justify-content: space-between;
}

.assistant-topbar-title { display: grid; gap: 2px; min-width: 0; }

.assistant-topbar-title h2 {
  font-family: var(--font-display);
  font-size: clamp(19px, 1.8vw, 23px);
  letter-spacing: 0.4px;
  margin: 0;
}

.assistant-topbar-title p {
  color: var(--ink-soft, #6d6659);
  font-size: 12.5px;
  line-height: 1.5;
  margin: 0;
}

.assistant-topbar-actions {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.assistant-settings-trigger,
.assistant-settings-close {
  align-items: center;
  background: color-mix(in srgb, var(--card, #fffcf3) 84%, transparent);
  border: 1px solid var(--line, rgba(190, 167, 125, 0.4));
  border-radius: 50%;
  color: var(--pine-deep, #2a5045);
  cursor: pointer;
  display: inline-flex;
  height: 34px;
  justify-content: center;
  padding: 0;
  transition: background 0.16s ease, border-color 0.16s ease, transform 0.16s ease;
  width: 34px;
}

.assistant-settings-trigger:hover,
.assistant-settings-trigger:focus-visible,
.assistant-settings-close:hover,
.assistant-settings-close:focus-visible {
  background: var(--pine-tint, #e3ece7);
  border-color: color-mix(in srgb, var(--pine, #38665a) 42%, var(--line));
  outline: none;
  transform: translateY(-1px);
}

.assistant-status-chip {
  align-items: center;
  background: color-mix(in srgb, var(--pine, #38665a) 9%, transparent);
  border: 1px solid color-mix(in srgb, var(--pine, #38665a) 26%, transparent);
  border-radius: 999px;
  color: var(--pine-deep, #2a5045);
  cursor: pointer;
  display: inline-flex;
  font-size: 12px;
  font-weight: 700;
  gap: 6px;
  max-width: 260px;
  overflow: hidden;
  padding: 7px 12px;
  text-overflow: ellipsis;
  transition: background 0.16s ease, border-color 0.16s ease;
  white-space: nowrap;
}

.assistant-status-chip:hover,
.assistant-status-chip.open {
  background: color-mix(in srgb, var(--pine, #38665a) 16%, transparent);
  border-color: color-mix(in srgb, var(--pine, #38665a) 42%, transparent);
}

.assistant-status-chip.busy .app-icon { animation: assistant-chip-spin 1.6s linear infinite; }

@keyframes assistant-chip-spin {
  to { transform: rotate(360deg); }
}

.assistant-workflow-pop {
  flex: 0 0 auto;
  max-height: 44vh;
  overflow-y: auto;
}

/* 输入区：与阅读列同宽居中的大圆角输入卡（类主流 AI 前端 composer）。 */
.assistant-composer {
  background: color-mix(in srgb, var(--card, #fffcf3) 94%, transparent);
  border: 1px solid var(--line, rgba(190, 167, 125, 0.4));
  border-radius: 22px;
  box-shadow: 0 12px 30px rgba(94, 71, 42, 0.08);
  flex-direction: column;
  gap: 8px;
  margin-inline: auto;
  margin-top: 4px;
  padding: 13px 15px 11px;
  width: min(100%, 820px);
}

.assistant-composer textarea {
  background: transparent;
  border: 0;
  box-shadow: none;
  font-size: 15px;
  line-height: 1.6;
  min-height: 48px;
  outline: none;
  padding: 2px 2px 0;
  width: 100%;
}

/* 输入焦点转移到整个输入卡上，保持可见的键盘焦点提示。 */
.assistant-composer:focus-within {
  border-color: color-mix(in srgb, var(--pine, #38665a) 46%, transparent);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--pine, #38665a) 16%, transparent);
}

.assistant-composer .assistant-composer-actions {
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  width: 100%;
}

.assistant-composer .assistant-composer-actions > .btn {
  border-radius: 999px;
  flex: 0 0 auto;
  width: auto;
}

.assistant-composer-spacer { flex: 1 1 auto; }

/* 圆形主操作按钮：空闲发送（↑），生成中停止（方块）。 */
.assistant-send {
  align-items: center;
  background: linear-gradient(160deg, var(--btn-primary-from, #38665a), var(--btn-primary-to, #2a5045));
  border: 0;
  border-radius: 50%;
  box-shadow: 0 6px 14px rgba(42, 80, 69, 0.28);
  color: #f6f1e4;
  cursor: pointer;
  display: inline-flex;
  flex: 0 0 auto;
  height: 40px;
  justify-content: center;
  transition: box-shadow 0.16s ease, opacity 0.16s ease, transform 0.16s ease;
  width: 40px;
}

.assistant-send:hover:not(:disabled) {
  box-shadow: 0 8px 18px rgba(42, 80, 69, 0.34);
  transform: translateY(-1px);
}

.assistant-send:focus-visible {
  outline: 3px solid color-mix(in srgb, var(--pine, #38665a) 45%, transparent);
  outline-offset: 2px;
}

.assistant-send:disabled {
  box-shadow: none;
  cursor: not-allowed;
  opacity: 0.4;
}

/* 主区内的提示条与语音状态条同宽居中。 */
.assistant-main > .notice,
.assistant-main > .voice-session-panel {
  margin-inline: auto;
  width: min(100%, 820px);
}

.voice-session-panel {
  align-items: center;
  background: color-mix(in srgb, var(--pine-tint, #e3ece7) 70%, var(--card, #fffcf3));
  border: 1px solid color-mix(in srgb, var(--pine, #38665a) 28%, var(--line));
  border-radius: 16px;
  box-shadow: 0 8px 20px rgba(56, 102, 90, 0.08);
  display: flex;
  gap: 12px;
  min-height: 62px;
  padding: 10px 13px;
}

.voice-session-panel.wake {
  background: color-mix(in srgb, var(--gold-tint, #f4ead0) 68%, var(--card, #fffcf3));
  border-color: color-mix(in srgb, var(--gold, #a97e1f) 28%, var(--line));
}

.voice-session-visual {
  align-items: center;
  background: color-mix(in srgb, var(--pine, #38665a) 13%, var(--card, #fffcf3));
  border: 1px solid color-mix(in srgb, var(--pine, #38665a) 26%, transparent);
  border-radius: 50%;
  color: var(--pine-deep, #2a5045);
  display: inline-flex;
  flex: 0 0 42px;
  height: 42px;
  justify-content: center;
  position: relative;
  width: 42px;
}

.voice-session-panel.wake .voice-session-visual {
  background: color-mix(in srgb, var(--gold, #a97e1f) 16%, var(--card, #fffcf3));
  border-color: color-mix(in srgb, var(--gold, #a97e1f) 34%, transparent);
  color: var(--gold-deep, #8f6b1f);
}

.voice-session-ring {
  border: 1px solid color-mix(in srgb, var(--pine, #38665a) 36%, transparent);
  border-radius: 50%;
  inset: -5px;
  position: absolute;
}

.voice-session-ring.second {
  animation: assistant-voice-ring 1.8s ease-out infinite;
  inset: -10px;
  opacity: 0.45;
}

@keyframes assistant-voice-ring {
  0%, 100% { opacity: 0.15; transform: scale(0.86); }
  55% { opacity: 0.72; transform: scale(1.08); }
}

.voice-session-copy {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.voice-session-copy strong { color: var(--pine-deep, #2a5045); font-size: 13.5px; }
.voice-session-copy > span { color: var(--ink-soft, #6d6659); font-size: 12px; line-height: 1.45; }
.voice-live-transcript { color: var(--ink, #3f3a31) !important; font-weight: 600; overflow-wrap: anywhere; }

.voice-ready-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 0 auto;
  width: min(100%, 820px);
}

.voice-ready-actions .btn-large {
  flex: 1 1 150px;
  min-height: 44px;
}

.assistant-voice-send-hint {
  color: var(--pine-deep, #2a5045);
  font-size: 12px;
  margin: -2px auto 0;
  width: min(100%, 820px);
}

.voice-input-button {
  min-width: 76px;
}

.voice-input-button.listening,
.voice-input-button.active {
  background: color-mix(in srgb, var(--pine, #38665a) 15%, transparent);
  border-color: color-mix(in srgb, var(--pine, #38665a) 38%, var(--line));
  color: var(--pine-deep, #2a5045);
}

.voice-input-button.need {
  border-color: color-mix(in srgb, var(--gold, #a97e1f) 48%, var(--line));
  color: var(--gold-deep, #8f6b1f);
}

.assistant-settings-backdrop {
  background: rgba(63, 58, 49, 0.22);
  inset: 0;
  position: absolute;
  z-index: 30;
}

.assistant-settings-drawer {
  animation: assistant-drawer-in 0.22s ease both;
  background: var(--card, #fffcf3);
  border-left: 1px solid var(--line, rgba(190, 167, 125, 0.4));
  bottom: 0;
  box-shadow: -18px 0 40px rgba(94, 71, 42, 0.14);
  display: flex;
  flex-direction: column;
  gap: 14px;
  max-width: 100%;
  overflow-y: auto;
  padding: 18px 18px 24px;
  position: absolute;
  right: 0;
  top: 0;
  width: min(420px, 94vw);
  z-index: 31;
}

@keyframes assistant-drawer-in {
  from { opacity: 0; transform: translateX(24px); }
  to { opacity: 1; transform: translateX(0); }
}

.assistant-settings-header {
  align-items: flex-start;
  display: flex;
  justify-content: space-between;
}

.assistant-settings-header h3 {
  font-family: var(--font-display);
  font-size: 18px;
  margin: 2px 0 0;
}

.assistant-settings-note {
  color: var(--ink-soft, #6d6659);
  font-size: 12.5px;
  line-height: 1.6;
  margin: 0;
}

.assistant-settings-section {
  border-top: 1px dashed var(--line, rgba(190, 167, 125, 0.4));
  padding-top: 12px;
}

.assistant-settings-section h4 {
  font-family: var(--font-display);
  font-size: 14px;
  margin: 0 0 10px;
}

.voice-pref-row {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: space-between;
  margin: 9px 0;
}

.voice-pref-row > span { color: var(--ink-soft, #6d6659); font-size: 13px; }
.voice-pref-row select,
.voice-pref-row input:not([type="checkbox"]) { max-width: 230px; min-width: 0; }
.voice-pref-control { align-items: center; display: flex; gap: 6px; max-width: 100%; }
.voice-wake-control input { width: 132px; }

.voice-preset-row,
.voice-check-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.voice-preset-row { margin: 0 0 12px; }
.voice-preset-row .btn.active { background: var(--pine-tint, #e3ece7); border-color: color-mix(in srgb, var(--pine) 38%, var(--line)); color: var(--pine-deep); }
.voice-check-row { justify-content: flex-start; }
.voice-check-row input { accent-color: var(--pine, #38665a); }
.voice-check-result { font-size: 12px; line-height: 1.55; margin: 7px 0 0; }
.voice-preflight-list { color: var(--ink-soft, #6d6659); font-size: 12px; line-height: 1.55; margin: 8px 0 0; padding-left: 18px; }
.assistant-settings-model { color: var(--ink-faint, #a2937c); font-size: 11.5px; line-height: 1.5; margin: auto 0 0; }

/* 空状态：吉祥物 + 一句短提示 + 建议胶囊，压缩纵向留白。 */
.assistant-empty {
  align-items: center;
  display: grid;
  gap: 8px;
  justify-items: center;
  margin: auto 0;
  padding: clamp(20px, 7vh, 64px) 12px 16px;
  text-align: center;
}

.assistant-empty-art {
  align-items: center;
  background: linear-gradient(150deg, var(--pine-tint, #e3ece7), var(--sage-tint, #e6ede4));
  border: 1px solid color-mix(in srgb, var(--pine, #38665a) 20%, transparent);
  border-radius: 50%;
  box-shadow: 0 10px 24px rgba(56, 102, 90, 0.14);
  color: var(--pine-deep, #2a5045);
  display: flex;
  height: 58px;
  justify-content: center;
  margin-bottom: 2px;
  position: relative;
  width: 58px;
}

/* 品牌氛围：图标外的浅圆环 + 极淡光晕 + 环绕叶枝，安静不抢眼 */
.assistant-empty-art::before {
  border: 1px solid color-mix(in srgb, var(--pine, #38665a) 22%, transparent);
  border-radius: 50%;
  content: "";
  inset: -11px;
  opacity: 0.7;
  position: absolute;
}

.assistant-empty-art::after {
  border: 1px solid color-mix(in srgb, var(--gold, #a97e1f) 20%, transparent);
  border-radius: 50%;
  box-shadow: 0 0 34px 12px rgba(244, 228, 186, 0.35);
  content: "";
  inset: -24px;
  opacity: 0.5;
  position: absolute;
}

.assistant-empty-sprig {
  height: 40px;
  position: absolute;
  top: 50%;
  width: 52px;
}

.assistant-empty-sprig.left {
  left: -48px;
  transform: translateY(-58%) rotate(6deg);
}

.assistant-empty-sprig.right {
  right: -48px;
  transform: translateY(-58%) scaleX(-1) rotate(6deg);
}

.assistant-empty-title {
  color: var(--ink, #37332b);
  font-family: var(--font-display);
  font-size: clamp(19px, 2vw, 23px);
  letter-spacing: 0.5px;
}

.assistant-empty-sub {
  color: var(--ink-soft, #6d6659);
  font-size: 13.5px;
  line-height: 1.6;
  margin: 0;
  max-width: 46ch;
}

.assistant-empty-suggestions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
  margin-top: 8px;
}

.assistant-suggestion {
  align-items: center;
  background: color-mix(in srgb, var(--card, #fffcf3) 82%, transparent);
  border: 1px solid var(--line, rgba(190, 167, 125, 0.4));
  border-radius: 999px;
  color: var(--ink-soft, #6d6659);
  cursor: pointer;
  display: inline-flex;
  font-size: 13px;
  font-weight: 600;
  gap: 6px;
  line-height: 1.4;
  padding: 8px 14px;
  transition: background 0.16s ease, border-color 0.16s ease, color 0.16s ease, transform 0.16s ease;
}

.assistant-suggestion .app-icon { color: var(--clay, #c26744); flex: 0 0 auto; }

.assistant-suggestion:hover,
.assistant-suggestion:focus-visible {
  background: var(--card, #fffcf3);
  border-color: color-mix(in srgb, var(--pine, #38665a) 36%, transparent);
  color: var(--pine-deep, #2a5045);
  outline: none;
  transform: translateY(-1px);
}

.assistant-net-toggle {
  align-items: center;
  color: var(--ink-soft, #6d6659);
  cursor: pointer;
  display: inline-flex;
  font-size: 12.5px;
  font-weight: 650;
  gap: 6px;
}

.assistant-net-toggle input { accent-color: var(--pine, #38665a); }

.assistant-net-toggle .pill { font-size: 10.5px; padding: 2px 7px; }

.assistant-footnote {
  color: var(--ink-faint, #a2937c);
  flex: 0 0 auto;
  font-size: 11.5px;
  line-height: 1.5;
  margin: 0;
  text-align: center;
}

@media (prefers-reduced-motion: reduce) {
  .assistant-status-chip.busy .app-icon { animation: none; }
  .voice-session-ring.second,
  .assistant-settings-drawer { animation: none; }
  .ambient-dust i { animation: none; }
  .assistant-send,
  .assistant-suggestion { transition: none; }
  .assistant-send:hover:not(:disabled),
  .assistant-suggestion:hover,
  .assistant-suggestion:focus-visible { transform: none; }
}

@media (max-width: 860px) {
  .assistant-shell { flex-direction: column; }

  .assistant-rail {
    align-items: center;
    border-bottom: 1px solid var(--line-soft, rgba(190, 167, 125, 0.3));
    border-right: 0;
    flex: 0 0 auto;
    flex-direction: row;
    gap: 8px;
    padding: 10px 14px;
    width: 100%;
  }

  .assistant-new-thread { flex: 0 0 auto; width: auto; }

  .assistant-thread-list {
    display: flex;
    gap: 6px;
    overflow-x: auto;
    overflow-y: hidden;
    padding: 0;
  }

  .assistant-thread-open { padding: 7px 26px 7px 10px; }

  .assistant-thread-open strong { max-width: 130px; }

  .assistant-thread-open > span { display: none; }

  .assistant-thread-delete { opacity: 1; }

  .assistant-rail-note { display: none; }

  .assistant-main { padding: 12px 14px 10px; }

  /* 窄屏下收掉大部分装饰，只留右侧花枝的淡影 */
  .ambient-plant-left-mid,
  .ambient-plant-left-low,
  .ambient-plant-right-top,
  .ambient-pet-sprig,
  .ambient-arc { display: none; }

  .ambient-plant-right { opacity: 0.7; width: 150px; }

  .ambient-pet-glow { height: 190px; right: -20px; width: 190px; }
}

.speech-segment-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 6px;
}
.speech-segment-chips .btn.active {
  outline: 2px solid color-mix(in srgb, var(--accent) 45%, transparent);
}
</style>
