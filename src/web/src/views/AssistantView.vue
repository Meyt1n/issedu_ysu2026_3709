<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { ApiClientError, apiClient } from '../api/client'
import type {
  AssistantAgentTrace,
  AssistantCitation,
  AssistantExternalSource,
} from '../api/types'
import {
  clearChatSession,
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
  consumeAssistantSeedPrompt,
  formatError,
  requestOptions,
  selectMember,
  selectedMember,
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
  { id: 'synthesis', title: '回答生成', description: '在本机汇总证据并生成回答', icon: 'assistant', network: false },
]

const history = ref<ChatEntry[]>([])
const draft = ref('')
const sending = ref(false)
const sendError = ref('')
const voiceError = ref('')
const allowNetworkSearch = ref(false)
const webSearchAvailable = ref<boolean | null>(null)
const webSearchReason = ref<string | null>(null)
const webSearchHint = ref<string | null>(null)
const webSearchFixture = ref(false)
const webSearchProvider = ref<string | null>(null)
const showWebSearchHelp = ref(false)
const workflowTrace = ref<AssistantAgentTrace[]>([])
const selectedAgentId = ref<string | null>(null)
const workflowExpanded = ref(false)
const orchestrationPhase = ref<string | null>(null)
const workflowRouteExplanation = ref<string | null>(null)
const stopStatus = ref('')
const assistantSessionId = ref('')
const threads = ref<ChatThreadMeta[]>([])
const activeThreadId = ref('')
const settingsOpen = ref(false)
type VoiceMode = DictationMode

const voiceMode = ref<VoiceMode>('off')
const listening = computed(() =>
  voiceMode.value === 'wake' || voiceMode.value === 'active' || voiceMode.value === 'command',
)
const voicePreview = ref('')
const speakingIndex = ref<number | null>(null)
const speakingProgress = ref('')
const needMicGesture = ref(false)
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
// The generic label is replaced by the model name the API reports with each
// reply, so the UI never hardcodes a runtime model.
const modelLabel = ref('本地模型')

const wakePhrase = computed(() => voicePrefs.value.wakePhrase)

const memberHotwordExtras = computed(() =>
  memberNameHotwordPairs(session.members.map(member => member.display_name)),
)

const activeSpeakingSegments = computed(() =>
  speakingIndex.value !== null ? [...getSpeakingSegments()] : [],
)

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
  // 更换唤醒词后重新进入唤醒聆听，避免旧词残留提示。
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

async function refreshVoiceOptions(): Promise<void> {
  if (!isSpeechOutputSupported()) return
  voiceOptions.value = await listChineseVoices()
}

function applyPreferredVoice(name: string): void {
  voicePrefs.value = saveVoicePreferences({ preferredVoiceName: name })
}

function previewPreferredVoice(): void {
  if (!isSpeechOutputSupported()) return
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
  if (voiceMode.value === 'active' || voiceMode.value === 'wake') {
    ensureDictation().pause()
  }
  // 手动改字时取消自动发送，避免改到一半被发出。
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

function formatModelLabel(model?: string | null): string {
  if (!model || model === 'unavailable') return '本地模型未配置'
  return model
}

let streamTimer: ReturnType<typeof setInterval> | null = null
let stopStatusTimer: ReturnType<typeof setTimeout> | null = null
let dictation: DictationController | null = null

const speechInputSupported = isSpeechInputSupported()
const speechOutputSupported = isSpeechOutputSupported()
let activeSendController: AbortController | null = null
let userRequestedStop = false
let keepPartialReply = false

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

function rotateAssistantSession(): void {
  clearRemoteAssistantSession(assistantSessionId.value)
  assistantSessionId.value = regenerateAssistantSessionId(
    session.actorId,
    session.selectedHouseholdId,
    session.selectedMemberId,
    activeThreadId.value,
  )
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
      void nextTick(() => {
        sendButton.value?.focus()
      })
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

const canSend = computed(() => draft.value.trim().length > 0 && !sending.value)

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
    boundary: '仅使用本机模型，健康数据不离开本机。',
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
  generating: '正在本机生成回答…',
  validating: '正在校验引用与安全边界…',
}

const thinkingText = computed(() => {
  if (orchestrationPhase.value && PHASE_LABELS[orchestrationPhase.value]) {
    return PHASE_LABELS[orchestrationPhase.value]
  }
  return '正在本机核对证据并生成回答…'
})

const workflowSummary = computed(() => {
  if (sending.value) {
    return orchestrationPhase.value && PHASE_LABELS[orchestrationPhase.value]
      ? PHASE_LABELS[orchestrationPhase.value]
      : '正在本机分析中…'
  }
  const traces = workflowTrace.value
  if (traces.length > 0) {
    const completed = traces.filter(trace => trace.status === 'completed').length
    const usedNetwork = traces.some(trace => trace.network_used)
    return `已完成 ${completed} 个步骤${usedNetwork ? '，含脱敏联网参考' : '，全程在本机完成'}`
  }
  return '发送问题后，可在此查看处理进度'
})

// 图五/图六：多智能体流程默认收成一枚小状态胶囊，详情按需展开。
const workflowChipLabel = computed(() => {
  if (sending.value) {
    return orchestrationPhase.value && PHASE_LABELS[orchestrationPhase.value]
      ? PHASE_LABELS[orchestrationPhase.value]
      : '正在本机分析…'
  }
  const done = workflowTrace.value.filter(trace =>
    ['completed', 'skipped', 'blocked', 'degraded'].includes(trace.status),
  ).length
  return done > 0 ? `本地分析 · ${done} 步完成` : '本地分析'
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

function scrollToEnd(): void {
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

/** 切换/新建线索前的公共收尾：停掉请求、语音与打字机。 */
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

function clearConversation(): void {
  cancelActiveSend()
  rotateAssistantSession()
  stopVoiceInput()
  if (speakingIndex.value !== null) {
    stopSpeaking()
    speakingIndex.value = null
  }
  if (streamTimer) {
    clearInterval(streamTimer)
    streamTimer = null
  }
  clearChatSession(session.actorId, session.selectedHouseholdId, session.selectedMemberId, activeThreadId.value)
  history.value = []
  workflowTrace.value = []
  orchestrationPhase.value = null
  workflowRouteExplanation.value = null
  draft.value = ''
  sendError.value = ''
  stopStatus.value = ''
  if (stopStatusTimer) {
    clearTimeout(stopStatusTimer)
    stopStatusTimer = null
  }
  voiceError.value = ''
  sending.value = false
}

function useSuggestedQuestion(question: string): void {
  draft.value = question
  sendError.value = ''
  void nextTick(() => draftInput.value?.focus())
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
      || (entry.agentTrace?.length ?? 0) > 0
      || (entry.externalSources?.length ?? 0) > 0,
  )
}

function evidenceDisclosureSummary(entry: ChatEntry): string {
  const parts: string[] = []
  const citations = entry.citations?.length ?? 0
  const steps = entry.agentTrace?.length ?? 0
  const external = entry.externalSources?.length ?? 0
  if (citations > 0) parts.push(`${citations} 条本地引用`)
  if (steps > 0) parts.push(`${steps} 个处理步骤`)
  if (external > 0) parts.push(`${external} 条外部参考`)
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

function onVisibilityChange(): void {
  if (document.visibilityState === 'hidden') stopVoiceInput()
}

watch(settingsOpen, (open) => {
  if (open) void refreshVoiceOptions()
})

onMounted(() => {
  void loadAgentCatalog()
  void bootstrapVoice()
  void refreshVoiceOptions()
  document.addEventListener('visibilitychange', onVisibilityChange)
  const seeded = consumeAssistantSeedPrompt()
  if (seeded) {
    draft.value = seeded
    void send(seeded)
  }
})

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
  voiceError.value = ''
  if (listening.value) stopVoiceInput()
  if (!startReplySpeech(index, content, false)) {
    voiceError.value = '当前浏览器不支持语音回复，请阅读文字回答。'
  }
}

/** 决策 3A：开启「语音回复」后，回答完成自动播报；播完再回听，期间可打断。 */
function autoSpeakReply(index: number, content: string): void {
  if (!speechOutputSupported) return
  if (!loadVoicePreferences().autoSpeakReplies) return
  if (!content.trim()) return
  if (listening.value) stopVoiceInput()
  startReplySpeech(index, content, true)
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

async function send(text?: string, queryTypeOverride?: string): Promise<void> {
  const content = (text ?? draft.value).trim()
  if (!content || sending.value) return

  cancelActiveSend()
  stopVoiceInput()
  if (speakingIndex.value !== null) {
    stopSpeaking()
    speakingIndex.value = null
  }
  keepPartialReply = false
  history.value.push({ role: 'user', content, revealed: content.length })
  persistChatSession()
  draft.value = ''
  sending.value = true
  sendError.value = ''
  stopStatus.value = ''
  if (stopStatusTimer) {
    clearTimeout(stopStatusTimer)
    stopStatusTimer = null
  }
  workflowTrace.value = []
  orchestrationPhase.value = 'routing'
  workflowRouteExplanation.value = null
  scrollToEnd()

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
    workflowTrace.value = reply.agent_trace ?? []
    workflowRouteExplanation.value = reply.route_explanation ?? null
    if (reply.model) modelLabel.value = formatModelLabel(reply.model)
    persistChatSession()
    if (!alreadyStreamed) streamReveal(entry)
    autoSpeakReply(entryIndex, reply.answer)
  }

  const chatInput = buildAssistantChatInput({
    history: history.value.slice(0, -1),
    allowNetworkSearch: allowNetworkSearch.value,
    queryTypeOverride,
    assistantSessionId: assistantSessionId.value,
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
    // 自动播报进行中时不开麦回听（开麦会停止朗读）；播完由 onFinished 回听。
    if (!needMicGesture.value && speakingIndex.value === null) void beginWakeListening()
  }
}

function onMemberChange(event: Event): void {
  cancelActiveSend()
  selectMember((event.target as HTMLSelectElement).value)
}

onBeforeUnmount(() => {
  cancelActiveSend()
  if (streamTimer) clearInterval(streamTimer)
  if (stopStatusTimer) clearTimeout(stopStatusTimer)
  document.removeEventListener('visibilitychange', onVisibilityChange)
  dictation?.dispose()
  dictation = null
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
        对话只保存在当前标签页，退出登录即清除。
      </p>
    </aside>

    <section class="assistant-main" aria-label="对话区域">
      <header class="assistant-topbar">
        <div class="assistant-topbar-title">
          <h2 class="hero-greeting">本地证据助手</h2>
          <p>基于本地事实与规则回答并给出引用；资料不足会明说，不替医生做决定。</p>
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
            class="assistant-status-chip"
            :class="{ busy: sending, open: workflowExpanded }"
            :aria-expanded="workflowExpanded"
            aria-label="查看本地分析过程"
            @click="toggleWorkflowPanel"
          >
            <AppIcon name="sparkle" :size="13" />
            {{ workflowChipLabel }}
          </button>
          <button
            v-if="history.length > 0"
            type="button"
            class="btn btn-ghost btn-small"
            :disabled="sending"
            @click="clearConversation"
          >
            清空会话
          </button>
          <button
            type="button"
            class="icon-button assistant-settings-button"
            aria-label="助手设置"
            :aria-expanded="settingsOpen"
            @click="settingsOpen = !settingsOpen"
          >
            <AppIcon name="settings" :size="18" />
          </button>
        </div>
      </header>

      <section v-if="workflowExpanded" class="agent-workflow-panel assistant-workflow-pop" aria-label="本地分析流程">
        <div class="agent-workflow-heading">
          <div>
            <span class="agent-workflow-kicker"><AppIcon name="sparkle" :size="13" />本地分析流程</span>
            <small>{{ workflowSummary }}</small>
          </div>
          <div class="agent-workflow-actions">
            <span class="agent-local-badge">
              <i />数据不离开本机
            </span>
            <button
              type="button"
              class="btn btn-ghost btn-small"
              :aria-expanded="workflowExpanded"
              @click="toggleWorkflowPanel"
            >
              收起
            </button>
          </div>
        </div>
        <div class="agent-workflow-grid">
          <span class="agent-flow-rail" aria-hidden="true">
            <span class="agent-flow-fill" :class="{ 'is-indeterminate': sending }" :style="{ width: workflowProgressWidth }">
              <i v-if="sending" class="agent-flow-runner" />
            </span>
          </span>
          <button
            v-for="stage in AGENT_STAGES"
            :key="stage.id"
            type="button"
            class="agent-stage"
            :class="[`is-${agentStatus(stage)}`, { 'is-selected': selectedAgentId === stage.id }]"
            :aria-expanded="selectedAgentId === stage.id"
            :aria-label="`${stage.title}，${agentStatusLabel(agentStatus(stage))}，点击查看详情`"
            @click="toggleAgentDetails(stage.id)"
          >
            <div class="agent-stage-topline">
              <span class="agent-stage-icon"><AppIcon :name="stage.icon" :size="17" /></span>
              <span class="agent-stage-status">{{ agentStatusLabel(agentStatus(stage)) }}</span>
            </div>
            <strong>{{ stage.title }}</strong>
            <small>{{ agentStatusDetail(stage) }}</small>
            <span class="agent-stage-kind">{{ stage.network ? '联网参考（可选）' : '本机步骤' }}</span>
          </button>
        </div>
        <section v-if="selectedAgent" class="agent-detail-panel" :aria-label="`${selectedAgent.title}详情`">
          <div class="agent-detail-heading">
            <div class="agent-detail-title">
              <span class="agent-stage-icon"><AppIcon :name="selectedAgent.icon" :size="18" /></span>
              <div>
                <strong>{{ selectedAgent.title }}</strong>
                <small>{{ selectedAgent.network ? '受控联网步骤' : '本机步骤' }} · {{ agentStatusLabel(agentStatus(selectedAgent)) }}</small>
              </div>
            </div>
            <button type="button" class="btn btn-ghost btn-small" @click="selectedAgentId = null">
              <AppIcon name="close" :size="13" />关闭
            </button>
          </div>
          <div class="agent-detail-grid">
            <div>
              <span>职责</span>
              <p>{{ selectedAgentAction() }}</p>
            </div>
            <div>
              <span>数据边界</span>
              <p>{{ selectedAgentBoundary() }}</p>
            </div>
            <div>
              <span>本次执行</span>
              <p v-if="selectedAgentTrace">
                {{ selectedAgentTrace.summary || '已返回执行结果' }} · {{ selectedAgentTrace.duration_ms ?? 0 }} ms · {{ selectedAgentTrace.source_count ?? 0 }} 条依据
              </p>
              <p v-else class="text-faint">尚未执行；发送问题后这里会显示实际的处理结果。</p>
            </div>
            <div v-if="selectedAgent.id === 'router' && workflowRouteExplanation">
              <span>分流说明</span>
              <p>{{ workflowRouteExplanation }}</p>
            </div>
          </div>
        </section>
        <p class="agent-workflow-note">
          <AppIcon name="lock" :size="12" />健康档案不会发送到外部；回答只引用通过服务端校验的本地资料。
        </p>
      </section>

      <div ref="chatWindow" class="chat-window">
      <div class="chat-thread" :class="{ empty: history.length === 0 }">
      <div v-if="history.length === 0" class="assistant-empty">
        <span class="assistant-empty-art" aria-hidden="true">
          <AppIcon name="assistant" :size="30" />
        </span>
        <strong class="assistant-empty-title">向家庭助手提问</strong>
        <p class="assistant-empty-sub">回答只依据这个家庭的本地事实与已审核资料；证据不足会明说。</p>
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
          <div class="chat-message-text"><span class="chat-message-content">{{ entry.role === 'assistant' ? entry.content.slice(0, entry.revealed) : entry.content }}</span><span v-if="isStreaming(entry)" class="stream-caret" aria-hidden="true" /></div>
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
              分析全程在本机完成
              <span v-if="entry.networkUsed" class="chat-agent-network">已补充脱敏联网参考</span>
            </span>
            <div v-if="(entry.agentTrace?.length ?? 0) > 0" class="chat-agent-trace" aria-label="处理步骤">
              <span v-for="trace in entry.agentTrace" :key="trace.agent_id" class="chat-agent-chip">
                {{ trace.role }} · {{ trace.status === 'completed' ? '完成' : trace.status === 'skipped' ? '跳过' : trace.status === 'blocked' ? '拦截' : '降级' }}
                <small>{{ trace.network_used ? '联网' : '本机' }}</small>
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

      <div
        v-if="needMicGesture && !listening"
        class="voice-session-panel wake"
        role="status"
        aria-live="polite"
      >
        <span class="voice-session-visual" aria-hidden="true">
          <AppIcon name="microphone" :size="17" />
        </span>
        <span class="voice-session-copy">
          <strong>需要一次点按开启麦克风</strong>
          <span>浏览器要求用户手势后才能开麦；点按后会自动等待「{{ wakePhrase }}」。</span>
        </span>
      </div>
      <div
        v-if="listening || voiceMode === 'ready'"
        class="voice-session-panel"
        :class="voiceMode"
        role="status"
        aria-live="polite"
      >
        <span class="voice-session-visual" aria-hidden="true">
          <span class="voice-session-ring" />
          <span class="voice-session-ring second" />
          <AppIcon name="microphone" :size="17" />
        </span>
        <span class="voice-session-copy">
          <strong>
            {{
              voiceMode === 'wake'
                ? '等待唤醒'
                : voiceMode === 'ready'
                  ? '已听完'
                  : voiceMode === 'command'
                    ? '指令聆听'
                    : '已唤醒，正在实时输入'
            }}
          </strong>
          <span>{{ voiceStatusText }}</span>
          <span v-if="voicePreview" class="voice-live-transcript">{{ voicePreview }}</span>
        </span>
      </div>
      <form class="chat-compose assistant-composer" @submit.prevent="send()">
        <textarea
          ref="draftInput"
          v-model="draft"
          rows="2"
          placeholder="例如：最近的用药提醒是依据什么？（回答仅供参考，不构成医疗建议）"
          @focus="onDraftFocus"
          @keydown.enter.exact.prevent="send()"
        />
        <div v-if="voiceMode === 'ready' || voiceMode === 'command'" class="voice-ready-actions" role="group" aria-label="口述确认">
          <button ref="sendButton" type="submit" class="btn btn-primary btn-large" :disabled="!canSend">
            发送
          </button>
          <button type="button" class="btn btn-ghost" @click="editDraftLine">
            改一句
          </button>
          <button type="button" class="btn btn-ghost" @click="redoVoiceDraft">
            重说
          </button>
          <button type="button" class="btn btn-ghost btn-small" @click="toggleVoiceInput">
            {{ voiceButtonLabel }}
          </button>
        </div>
        <p v-if="voiceSendHint" class="text-faint" style="font-size: 13px; margin: 6px 0 0" role="status">{{ voiceSendHint }}</p>
        <div v-if="voiceMode !== 'ready' && voiceMode !== 'command'" class="chat-compose-actions assistant-composer-actions">
          <label
            class="assistant-net-toggle"
            :title="webSearchAvailable === false
              ? webSearchDisabledText
              : '仅发送脱敏后的问题以补充公开参考；详情见右上角设置'"
          >
            <input v-model="allowNetworkSearch" type="checkbox" :disabled="webSearchAvailable === false" />
            <AppIcon name="cloud" :size="14" />
            联网搜索
            <span v-if="webSearchBadge" class="pill sage">{{ webSearchBadge }}</span>
          </label>
          <span class="assistant-composer-spacer" aria-hidden="true" />
          <button
            type="button"
            class="btn btn-ghost btn-small voice-input-button"
            :class="{ listening, active: voiceMode === 'active', ready: voiceMode === 'ready', need: needMicGesture }"
            :disabled="sending || !speechInputSupported"
            :aria-label="listening ? '停止语音唤醒' : voiceButtonLabel"
            :aria-pressed="listening"
            :title="speechInputSupported ? `进入助手页后会自动尝试聆听；首次需点按允许麦克风，再说「${wakePhrase}」` : '当前浏览器不支持语音输入'"
            @click="toggleVoiceInput"
          >
            <AppIcon name="microphone" :size="15" />
            {{ voiceButtonLabel }}
          </button>
          <button
            v-if="sending"
            type="button"
            class="btn btn-ghost btn-small"
            aria-label="停止生成本次回答"
            @click="cancelActiveSend(true)"
          >
            停止
          </button>
          <button
            ref="sendButton"
            type="submit"
            class="assistant-send"
            :disabled="!canSend"
            :aria-label="sending ? '发送中' : '发送'"
            :title="sending ? '正在生成回答' : '发送（Enter）'"
          >
            <AppIcon name="arrow-up" :size="18" />
          </button>
        </div>
      </form>
      <p class="assistant-footnote">
        回答基于本地证据，仅供参考，不构成医疗建议；紧急情况请直接联系医生或药师。
      </p>
    </section>

    <div
      v-if="settingsOpen"
      class="assistant-settings-backdrop"
      aria-hidden="true"
      @click="settingsOpen = false"
    />
    <aside v-if="settingsOpen" class="assistant-settings" role="dialog" aria-modal="false" aria-label="助手设置">
      <header class="assistant-settings-head">
        <strong><AppIcon name="settings" :size="16" />助手设置</strong>
        <button type="button" class="icon-button" aria-label="关闭设置" @click="settingsOpen = false">
          <AppIcon name="close" :size="15" />
        </button>
      </header>

      <section class="assistant-settings-section" aria-label="会话状态">
        <h4>会话状态</h4>
        <dl class="assistant-settings-facts">
          <div><dt>本地模型</dt><dd>{{ modelLabel }}</dd></div>
          <div><dt>可见范围</dt><dd>{{ selectedMember?.display_name ?? '未选择成员' }}</dd></div>
          <div><dt>证据模式</dt><dd>先依据后解释</dd></div>
          <div><dt>处理方式</dt><dd>本地多步核对</dd></div>
          <div><dt>使用边界</dt><dd>健康参考 · 需人工确认</dd></div>
        </dl>
      </section>

      <section class="assistant-settings-section" aria-label="联网搜索">
        <h4>联网搜索</h4>
        <label class="agent-network-toggle">
          <input v-model="allowNetworkSearch" type="checkbox" :disabled="webSearchAvailable === false" />
          <span>
            <strong>
              补充联网参考
              <span v-if="webSearchBadge" class="pill sage" style="margin-left: 6px">{{ webSearchBadge }}</span>
            </strong>
            <small v-if="webSearchAvailable === false">
              {{ webSearchDisabledText }}
              <button type="button" class="link-inline" @click="showWebSearchHelp = !showWebSearchHelp">
                {{ showWebSearchHelp ? '收起启用方法' : '如何启用？' }}
              </button>
            </small>
            <small v-else-if="webSearchFixture">
              开启后由本机教学夹具提供演示用外部参考样式，不会发起任何网络请求；夹具内容不构成医疗证据。
              <button type="button" class="link-inline" @click="showWebSearchHelp = !showWebSearchHelp">
                {{ showWebSearchHelp ? '收起切换方法' : '如何切到真实联网？' }}
              </button>
            </small>
            <small v-else>开启后仅将脱敏后的问题发送到可信搜索服务以补充公开参考；家庭成员、健康记录与图片始终保留在本机。</small>
          </span>
        </label>
        <div v-if="showWebSearchHelp && webSearchAvailable === false" class="notice info web-search-help" role="note">
          <p style="margin: 0 0 6px">{{ webSearchHint ?? '请部署负责人在 .env 中开启联网搜索后重启 API。' }}</p>
          <pre class="mono web-search-help-env"><code>AGENT_WEB_SEARCH_ENABLED=true
# 离线课堂演示（不出网）：
AGENT_WEB_SEARCH_PROVIDER=fixture
# 真实联网（白名单出口）：
# AGENT_WEB_SEARCH_PROVIDER=duckduckgo_html
# AGENT_WEB_SEARCH_ALLOWED_DOMAINS=html.duckduckgo.com</code></pre>
          <p style="margin: 6px 0 0">修改 .env 并重启 API 后刷新本页；每次提问仍需勾选本选项，外部结果只作为「非本地审核证据」参考。</p>
        </div>
        <div v-if="showWebSearchHelp && webSearchAvailable && webSearchFixture" class="notice info web-search-help" role="note">
          <p style="margin: 0 0 6px">
            当前为教学夹具演示（不出网）。若本机允许访问搜索站点，部署负责人可在 .env 切换到真实联网 provider 并重启 API：
          </p>
          <pre class="mono web-search-help-env"><code>AGENT_WEB_SEARCH_ENABLED=true
AGENT_WEB_SEARCH_PROVIDER=duckduckgo_html
AGENT_WEB_SEARCH_URL=https://html.duckduckgo.com/html/
AGENT_WEB_SEARCH_ALLOWED_DOMAINS=html.duckduckgo.com
# 自建 SearXNG：AGENT_WEB_SEARCH_PROVIDER=searxng 并把 URL/白名单换成你的实例</code></pre>
          <p style="margin: 6px 0 0">切换后本徽标会变为「真实联网 · 白名单出口」；只发送脱敏后的问题，外部结果仍只是「非本地审核证据」参考。</p>
        </div>
      </section>

      <section class="assistant-settings-section voice-prefs-panel" aria-label="语音偏好与自检">
        <h4>语音偏好</h4>
        <p class="text-faint" style="font-size: 12px; line-height: 1.6; margin: 0 0 10px">
          点击输入框旁的麦克风按钮开启唤醒，再说「{{ wakePhrase }}」开始实时填入草稿。
          中途停顿不超过「静音结束」时长（默认约 15 秒）会继续累加，不会打断口述；
          静音结束后会倒计时自动发送（可在下方改时长或关闭），等待时继续说话会取消倒计时并累加进草稿，
          也可说「取消」「继续说」，或说「发送吧」立即发送。
          语音回复由浏览器本地朗读，原始音频不会上传到本地助手 API。
        </p>
        <label class="voice-pref-row">
          <span>唤醒词</span>
          <input
            v-model="wakePhraseDraft"
            type="text"
            maxlength="8"
            aria-label="自定义唤醒词"
            @change="saveWakePhrase"
          />
        </label>
        <div class="row-actions" style="margin: 0 0 8px">
          <button
            v-for="preset in WAKE_PHRASE_PRESETS"
            :key="preset.id"
            type="button"
            class="btn btn-ghost btn-small"
            @click="applyWakePreset(preset.phrase)"
          >
            {{ preset.label }}
          </button>
        </div>
        <label class="voice-pref-row">
          <span>静音结束</span>
          <select :value="silencePresetId" @change="applySilencePreset(($event.target as HTMLSelectElement).value)">
            <option v-for="preset in SILENCE_PRESETS" :key="preset.id" :value="preset.id">
              {{ preset.label }}
            </option>
          </select>
        </label>
        <label class="voice-pref-row">
          <span>说完后自动发送</span>
          <select :value="autoSendPresetId" @change="applyAutoSendPreset(($event.target as HTMLSelectElement).value)">
            <option v-for="preset in AUTO_SEND_PRESETS" :key="preset.id" :value="preset.id">
              {{ preset.label }}
            </option>
          </select>
        </label>
        <label class="voice-pref-row">
          <input
            type="checkbox"
            :checked="voicePrefs.autoSpeakReplies"
            :disabled="!speechOutputSupported"
            @change="toggleVoicePref('autoSpeakReplies', ($event.target as HTMLInputElement).checked)"
          />
          <span>语音回复：回答完成后自动朗读（可随时停止）</span>
        </label>
        <label class="voice-pref-row">
          <span>播报音色</span>
          <select
            :value="voicePrefs.preferredVoiceName"
            :disabled="!speechOutputSupported"
            @change="applyPreferredVoice(($event.target as HTMLSelectElement).value)"
          >
            <option value="">自动优选（更自然的中文女声）</option>
            <option v-for="voiceOption in voiceOptions" :key="voiceOption.name" :value="voiceOption.name">
              {{ voiceOption.name }}（{{ voiceOption.lang }}{{ voiceOption.localService ? ' · 本地' : '' }}）
            </option>
          </select>
        </label>
        <div class="row-actions" style="margin: 0 0 8px">
          <button
            type="button"
            class="btn btn-ghost btn-small"
            :disabled="!speechOutputSupported"
            @click="previewPreferredVoice"
          >
            试听当前音色
          </button>
        </div>
        <label class="voice-pref-row">
          <input
            type="checkbox"
            :checked="voicePrefs.confirmSound"
            @change="toggleVoicePref('confirmSound', ($event.target as HTMLInputElement).checked)"
          />
          <span>听写结束后轻量提示音</span>
        </label>
        <label class="voice-pref-row">
          <input
            type="checkbox"
            :checked="voicePrefs.doubleWake"
            @change="toggleVoicePref('doubleWake', ($event.target as HTMLInputElement).checked)"
          />
          <span>双次唤醒确认（降低误唤醒）</span>
        </label>
        <label class="voice-pref-row">
          <input
            type="checkbox"
            :checked="voicePrefs.voiceCommands"
            @change="toggleVoicePref('voiceCommands', ($event.target as HTMLInputElement).checked)"
          />
          <span>听写后聆听白名单语音指令</span>
        </label>
        <div class="row-actions" style="margin-top: 8px">
          <button type="button" class="btn btn-ghost btn-small" :disabled="voicePackChecking" @click="checkVoicePacks">
            {{ voicePackChecking ? '检测中…' : '检查中文语音包' }}
          </button>
          <button type="button" class="btn btn-ghost btn-small" :disabled="preflightRunning" @click="runPreflight">
            {{ preflightRunning ? '自检中…' : '运行语音预检' }}
          </button>
        </div>
        <p v-if="voicePackReport" class="text-faint" style="font-size: 12px; margin: 8px 0 0">
          {{ voicePackReport.guidance }}
        </p>
        <ul v-if="preflightReport" class="voice-preflight-list">
          <li v-for="(line, idx) in preflightReport.guidance" :key="idx">{{ line }}</li>
        </ul>
      </section>
    </aside>
  </div>
</template>

<style scoped>
/* ---------- 图五/图六：全幅对话画布 + 会话轨 + 设置抽屉 ---------- */

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

/* 圆形主发送按钮（↑），与文本框同卡右下角。 */
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

/* 主区内的提示条与语音状态条与阅读列同宽居中。 */
.assistant-main > .notice,
.assistant-main > .voice-session-panel {
  margin-inline: auto;
  width: min(100%, 820px);
}

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
  width: 58px;
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

.assistant-settings-backdrop {
  background: rgba(63, 58, 49, 0.22);
  inset: 0;
  position: absolute;
  z-index: 30;
}

.assistant-settings {
  animation: assistant-drawer-in 0.22s ease both;
  background: var(--card, #fffcf3);
  border-left: 1px solid var(--line, rgba(190, 167, 125, 0.4));
  bottom: 0;
  box-shadow: -18px 0 40px rgba(94, 71, 42, 0.14);
  display: flex;
  flex-direction: column;
  gap: 14px;
  overflow-y: auto;
  padding: 18px 18px 24px;
  position: absolute;
  right: 0;
  top: 0;
  width: min(380px, 94vw);
  z-index: 31;
}

@keyframes assistant-drawer-in {
  from { opacity: 0; transform: translateX(24px); }
  to { opacity: 1; transform: translateX(0); }
}

.assistant-settings-head {
  align-items: center;
  display: flex;
  justify-content: space-between;
}

.assistant-settings-head strong {
  align-items: center;
  display: inline-flex;
  font-family: var(--font-display);
  font-size: 16px;
  gap: 7px;
}

.assistant-settings-section {
  border-top: 1px dashed var(--line, rgba(190, 167, 125, 0.4));
  padding-top: 12px;
}

.assistant-settings-section h4 {
  font-family: var(--font-display);
  font-size: 14px;
  margin: 0 0 8px;
}

.assistant-settings-facts { display: grid; gap: 7px; margin: 0; }

.assistant-settings-facts > div { display: flex; font-size: 13px; gap: 10px; }

.assistant-settings-facts dt { color: var(--ink-soft, #6d6659); flex: 0 0 76px; }

.assistant-settings-facts dd { margin: 0; overflow-wrap: anywhere; }

@media (prefers-reduced-motion: reduce) {
  .assistant-settings { animation: none; }
  .assistant-status-chip.busy .app-icon { animation: none; }
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
}

.voice-ready-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  width: 100%;
}
.voice-ready-actions .btn-large {
  flex: 1 1 140px;
  min-height: 48px;
  font-size: 16px;
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
.voice-pref-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  margin: 6px 0;
}
.voice-preflight-list {
  margin: 8px 0 0;
  padding-left: 18px;
  font-size: 12px;
  color: var(--ink-soft);
}
.link-inline {
  background: none;
  border: none;
  color: var(--pine, #2f6f5e);
  cursor: pointer;
  font-size: inherit;
  padding: 0;
  text-decoration: underline;
}
.web-search-help {
  font-size: 12.5px;
  line-height: 1.6;
  margin-top: 8px;
}
.web-search-help-env {
  background: color-mix(in srgb, var(--ink) 6%, transparent);
  border-radius: 8px;
  font-size: 12px;
  line-height: 1.55;
  margin: 0;
  overflow-x: auto;
  padding: 8px 10px;
  user-select: all;
  white-space: pre;
}
</style>
