<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { ApiClientError, apiClient } from '../api/client'
import type {
  AssistantAgentTrace,
  AssistantCitation,
  AssistantExternalSource,
  EvidencePreview,
} from '../api/types'
import {
  clearChatSession,
  getAssistantSessionId,
  loadChatSession,
  regenerateAssistantSessionId,
  saveChatSession,
  sessionEntryToStored,
  type StoredChatEntry,
} from '../assistant/chatSession'
import { normalizeSuggestedQuestions } from '../assistant/followUp'
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

interface ChatEntry {
  role: 'user' | 'assistant'
  content: string
  revealed: number
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
const workflowTrace = ref<AssistantAgentTrace[]>([])
const selectedAgentId = ref<string | null>(null)
const workflowExpanded = ref(false)
const orchestrationPhase = ref<string | null>(null)
const workflowRouteExplanation = ref<string | null>(null)
const liveEvidencePreview = ref<EvidencePreview | null>(null)
const stopStatus = ref('')
const assistantSessionId = ref('')
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
  )
}

function isAssistantCancellation(cause: unknown): boolean {
  return cause instanceof ApiClientError
    && (cause.code === 'CANCELLED' || cause.message.includes('CANCELLED'))
}

function showStoppedStatus(): void {
  stopStatus.value = '已停止'
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

const EVIDENCE_TOOL_LABELS: Record<string, string> = {
  get_member_state: '成员状态',
  get_health_events: '健康事件',
  get_care_plan_status: '今日照护计划',
  get_applied_rules: '已应用规则',
  get_risk_alerts: '风险提醒',
}

function evidenceToolLabel(tool: string): string {
  return EVIDENCE_TOOL_LABELS[tool] ?? tool
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
    return webSearchAvailable.value === false ? '当前部署未启用联网参考' : '本次请求未开启联网搜索'
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
  )
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
  clearChatSession(session.actorId, session.selectedHouseholdId, session.selectedMemberId)
  history.value = []
  workflowTrace.value = []
  orchestrationPhase.value = null
  workflowRouteExplanation.value = null
  liveEvidencePreview.value = null
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
    KNOWLEDGE_UNAVAILABLE: '本地知识库不可用',
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

function evidenceSummary(entry: ChatEntry): string {
  const citationCount = entry.citations?.length ?? 0
  const sourceCount = entry.sources?.length ?? 0
  if (citationCount > 0) return `已返回 ${citationCount} 条可核验知识引用`
  if (sourceCount > 0) return `已返回 ${sourceCount} 个依据标识，未提供可展开的知识片段`
  if (entry.degraded) return '本次未使用模型生成内容'
  return '本次响应没有返回可展开的知识文档引用，仍需人工确认'
}

function citationTitle(citation: AssistantCitation): string {
  return citation.document_title?.trim() || citation.document_id
}

function questionTypeLabel(queryType?: string | null): string {
  const labels: Record<string, string> = {
    MEDICATION_SAFETY: '用药安全核对',
    MEDICATION_RECORD: '用药记录查询',
    FAMILY_RECORD: '家庭健康档案查询',
    RULE_EVIDENCE: '规则与证据查询',
    URGENT: '紧急情况分流',
    GENERAL: '一般健康信息',
  }
  return labels[queryType ?? ''] ?? '一般健康信息'
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
    const shouldRegenerate = Boolean(memberId && (memberChanged || regenerateOnNextValidContext))
    assistantSessionId.value = shouldRegenerate
      ? regenerateAssistantSessionId(actorId, householdId, memberId)
      : getAssistantSessionId(actorId, householdId, memberId)
    if (memberId) regenerateOnNextValidContext = false
    workflowRouteExplanation.value = null
    liveEvidencePreview.value = null
    stopStatus.value = ''
    restoreChatSession(loadChatSession(actorId, householdId, memberId))
  },
  { immediate: true },
)

async function loadAgentCatalog(): Promise<void> {
  try {
    const catalog = await apiClient.listAssistantAgents(requestOptions.value)
    webSearchAvailable.value = catalog.web_search_ready ?? catalog.web_search_enabled
  } catch {
    webSearchAvailable.value = null
  }
}

function onVisibilityChange(): void {
  if (document.visibilityState === 'hidden') stopVoiceInput()
}

onMounted(() => {
  void loadAgentCatalog()
  void bootstrapVoice()
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

function toggleSpeech(index: number, content: string): void {
  if (speakingIndex.value === index) {
    stopSpeaking()
    speakingIndex.value = null
    speakingProgress.value = ''
    return
  }
  voiceError.value = ''
  if (listening.value) stopVoiceInput()
  speakingProgress.value = ''
  speakingSegmentIndex.value = 0
  const started = speakText(content, {
    onFinished: () => {
      if (speakingIndex.value === index) {
        speakingIndex.value = null
        speakingProgress.value = ''
        speakingSegmentIndex.value = 0
      }
    },
    onProgress: (progress) => {
      speakingSegmentIndex.value = progress.index
      speakingProgress.value = `正在朗读 ${progress.index + 1}/${progress.total}`
    },
  })
  if (!started) {
    voiceError.value = '当前浏览器不支持语音回复，请阅读文字回答。'
    return
  }
  speakingIndex.value = index
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
  liveEvidencePreview.value = null
  workflowExpanded.value = true
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
  }

  const chatInput = {
    messages: history.value
      .slice(0, -1)
      .map(entry => ({ role: entry.role, content: entry.content })),
    max_tokens: 1024,
    agent_mode: 'multi_agent' as const,
    allow_network_search: allowNetworkSearch.value,
    query_type_override: queryTypeOverride,
    assistant_session_id: assistantSessionId.value || undefined,
  }

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
        onEvidencePreview: preview => {
          liveEvidencePreview.value = preview
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
      if (history.value[entryIndex] === streamingEntry) history.value.splice(entryIndex, 1)
      persistChatSession()
      if (userRequestedStop) showStoppedStatus()
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
        if (history.value[entryIndex] === streamingEntry) history.value.splice(entryIndex, 1)
        persistChatSession()
        if (userRequestedStop) showStoppedStatus()
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
    liveEvidencePreview.value = null
    sending.value = false
    if (!needMicGesture.value) void beginWakeListening()
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
  <section class="page-hero">
    <div class="card-heading" style="margin-bottom: 0">
      <div>
        <h2 class="hero-greeting">本地证据助手</h2>
        <p class="hero-sub">
          助手只基于本地事实、规则与文档回答，并给出引用；资料不足时会明确说「无法判断」，不会替医生做决定。
        </p>
      </div>
      <label class="context-select">
        当前成员
        <select :value="session.selectedMemberId" @change="onMemberChange">
          <option v-for="member in session.members" :key="member.id" :value="member.id">
            {{ member.display_name }}
          </option>
        </select>
      </label>
      <div v-if="history.length > 0" class="row-actions">
        <span class="text-faint" style="font-size: 12px">仅保存在当前标签页</span>
        <button type="button" class="btn btn-ghost btn-small" :disabled="sending" @click="clearConversation">
          清空会话
        </button>
      </div>
    </div>
  </section>

  <section class="card">
    <div class="session-bar" aria-label="会话状态">
      <span class="session-item">
        <AppIcon name="assistant" :size="17" />
        <span class="session-text">
          <span class="session-label">本地模型</span>
          <span class="session-value">{{ modelLabel }}</span>
        </span>
      </span>
      <span class="session-item">
        <AppIcon name="eye" :size="17" />
        <span class="session-text">
          <span class="session-label">可见范围</span>
          <span class="session-value">{{ selectedMember?.display_name ?? '未选择成员' }}</span>
        </span>
      </span>
      <span class="session-item">
        <AppIcon name="compass" :size="17" />
        <span class="session-text">
          <span class="session-label">证据模式</span>
          <span class="session-value">先依据后解释</span>
        </span>
      </span>
      <span class="session-item">
        <AppIcon name="assistant" :size="17" />
        <span class="session-text">
          <span class="session-label">处理方式</span>
          <span class="session-value">本地多步核对</span>
        </span>
      </span>
      <span class="session-item">
        <AppIcon name="leaf" :size="17" />
        <span class="session-text">
          <span class="session-label">使用边界</span>
          <span class="session-value">健康参考 · 需人工确认</span>
        </span>
      </span>
    </div>
    <section class="agent-workflow-panel" aria-label="本地分析流程">
      <div class="agent-workflow-heading">
        <div>
          <span class="agent-workflow-kicker"><AppIcon name="sparkle" :size="13" />本地分析流程</span>
          <strong>识别 · 检索 · 生成，全程在本机完成</strong>
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
            {{ workflowExpanded ? '收起详情' : '查看详情' }}
          </button>
        </div>
      </div>
      <template v-if="workflowExpanded">
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
      </template>
    </section>
    <div ref="chatWindow" class="chat-window">
      <div v-if="history.length === 0" class="empty-state">
        <AppIcon class="empty-art" name="assistant" :size="40" />
        <strong>向家庭助手提问</strong>
        <p>助手会调用本地事实、规则与知识文档回答；没有证据时会拒答并提示联系医生或药师。</p>
        <div class="row-actions" style="justify-content: center">
          <button
            v-for="suggestion in SUGGESTIONS"
            :key="suggestion"
            type="button"
            class="btn btn-ghost btn-small"
            @click="useSuggestedQuestion(suggestion)"
          >
            {{ suggestion }}
          </button>
        </div>
      </div>

      <div v-for="(entry, index) in history" :key="index" class="chat-bubble-row" :class="entry.role">
        <span v-if="entry.role === 'assistant'" class="chat-avatar" aria-hidden="true">
          <AppIcon name="assistant" :size="16" />
        </span>
        <div class="chat-bubble">
          {{ entry.role === 'assistant' ? entry.content.slice(0, entry.revealed) : entry.content
          }}<span v-if="isStreaming(entry)" class="stream-caret" aria-hidden="true" />
          <div
            v-if="entry.role === 'assistant' && !isStreaming(entry) && (entry.degraded || entry.escalate || entry.riskNotice || entry.queryType || entry.routeExplanation || (entry.sources?.length ?? 0) > 0 || entry.confidence || (entry.agentTrace?.length ?? 0) > 0 || (entry.externalSources?.length ?? 0) > 0)"
            class="chat-sources"
          >
            <span v-if="entry.queryType" class="chat-evidence-summary">
              <AppIcon name="compass" :size="12" style="vertical-align: -1px" />
              问题类型：{{ questionTypeLabel(entry.queryType) }}
            </span>
            <span v-if="entry.routeExplanation" class="chat-route-explanation">
              <AppIcon name="timeline" :size="12" style="vertical-align: -1px" />
              分流说明：{{ entry.routeExplanation }}
            </span>
            <span v-if="entry.degraded" style="color: var(--gold)">
              ⚠ {{ degradeReasonLabel(entry.degradeReason) }}，以上为受控回复，不含模型生成的医疗判断。
            </span>
            <span v-if="entry.escalate" style="color: var(--rose)">
              此问题超出系统边界，请联系医生或药师进一步确认。
            </span>
            <span v-if="entry.riskNotice" style="color: var(--rose)">
              ⚠ {{ entry.riskNotice }}
            </span>
            <span v-if="entry.confidence && !entry.degraded">回答把握程度：{{ entry.confidence }}（仍需人工确认）</span>
            <span v-if="!entry.degraded" class="chat-evidence-summary">
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
            <template v-if="(entry.sources?.length ?? 0) > 0">
              <span v-for="source in entry.sources" :key="source">
                <AppIcon name="compass" :size="12" style="vertical-align: -1px" />
                依据标识：{{ source }}
              </span>
            </template>
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
          <div
            v-if="entry.role === 'assistant' && !isStreaming(entry) && (entry.suggestedQuestions?.length ?? 0) > 0"
            class="chat-follow-ups"
            aria-label="相关追问"
          >
            <span class="chat-follow-ups-label">你还可以问：</span>
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
            class="chat-follow-ups"
            aria-label="用药安全复核"
          >
            <button
              type="button"
              class="btn btn-ghost btn-small chat-follow-up"
              :disabled="sending"
              @click="resendAsMedicationSafety(index)"
            >
              按用药安全再查一次
            </button>
          </div>
          <div v-if="entry.role === 'assistant' && !isStreaming(entry) && speechOutputSupported" class="chat-voice-actions">
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
            <div
              v-if="speakingIndex === index && activeSpeakingSegments.length > 1"
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

      <section
        v-if="sending && liveEvidencePreview"
        class="assistant-evidence-preview"
        role="status"
        aria-live="polite"
        aria-label="本轮证据预览"
      >
        <div class="assistant-evidence-preview-heading">
          <span><AppIcon name="review" :size="15" />已找到可核对的依据</span>
          <small>仅显示资料名称和数量，不含健康正文</small>
        </div>
        <p>问题类型：{{ questionTypeLabel(liveEvidencePreview.query_type) }}</p>
        <div class="assistant-evidence-preview-groups">
          <span v-if="liveEvidencePreview.database_tools.length">
            档案：{{ liveEvidencePreview.database_tools.map(evidenceToolLabel).join('、') }}
          </span>
          <span v-if="liveEvidencePreview.rule_tools.length">
            规则：{{ liveEvidencePreview.rule_tools.map(evidenceToolLabel).join('、') }}
          </span>
          <span>
            本地资料：{{ liveEvidencePreview.knowledge_count }} 条
            <template v-if="liveEvidencePreview.knowledge_titles.length">
              （{{ liveEvidencePreview.knowledge_titles.join('、') }}）
            </template>
          </span>
          <span v-if="liveEvidencePreview.external_count">
            外部参考：{{ liveEvidencePreview.external_count }} 条（非本地审核证据）
          </span>
        </div>
      </section>

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

    <p v-if="sendError" class="notice error" role="alert" style="margin-top: 14px">
      <AppIcon name="alert" :size="16" />
      {{ sendError }}
    </p>
    <p v-if="stopStatus" class="notice info" role="status" aria-live="polite" style="margin-top: 14px">
      {{ stopStatus }}
    </p>

    <form class="chat-compose" @submit.prevent="send()">
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
      <div v-if="voiceMode !== 'ready' && voiceMode !== 'command'" class="chat-compose-actions">
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
          class="btn btn-ghost"
          aria-label="停止生成本次回答"
          @click="cancelActiveSend(true)"
        >
          停止
        </button>
        <button ref="sendButton" type="submit" class="btn btn-primary" :disabled="!canSend">
          {{ sending ? '发送中' : '发送' }}
        </button>
      </div>
    </form>
    <label class="agent-network-toggle">
      <input v-model="allowNetworkSearch" type="checkbox" :disabled="sending || webSearchAvailable === false" />
      <span>
        <strong>补充联网参考</strong>
        <small v-if="webSearchAvailable === false">联网参考当前未启用，全部分析在本机完成。</small>
        <small v-else>开启后仅将脱敏后的问题发送到可信搜索服务以补充公开参考；家庭成员、健康记录与图片始终保留在本机。</small>
      </span>
    </label>
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
    <p v-if="voiceError" class="notice error" role="alert" style="margin-top: 10px">
      <AppIcon name="alert" :size="16" />
      {{ voiceError }}
    </p>
    <p class="text-faint" style="font-size: 12px; line-height: 1.6; margin: 10px 0 0">
      先点击开启唤醒，再说「{{ wakePhrase }}」开始实时填入草稿。
      说完并静音后会倒计时自动发送（可在下方偏好改时长或关闭）；等待时可说「取消」「继续说」，或说「发送吧」立即发送。
      语音回复由浏览器本地朗读，原始音频不会上传到本地助手 API。
    </p>

    <section class="voice-prefs-panel card-sub" aria-label="语音偏好与自检">
      <strong class="voice-prefs-title">语音偏好</strong>
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
  </section>
</template>

<style scoped>
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
.voice-prefs-panel {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid color-mix(in srgb, var(--ink) 8%, transparent);
}
.voice-prefs-title {
  display: block;
  font-size: 13px;
  margin-bottom: 8px;
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
</style>
