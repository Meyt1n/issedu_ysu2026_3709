<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

import { apiClient } from '../api/client'
import type { AssistantCitation } from '../api/types'
import {
  clearChatSession,
  loadChatSession,
  saveChatSession,
  sessionEntryToStored,
  type StoredChatEntry,
} from '../assistant/chatSession'
import { normalizeSuggestedQuestions } from '../assistant/followUp'
import {
  containsWakePhrase,
  createSpeechRecognition,
  isSpeechInputSupported,
  isSpeechOutputSupported,
  speakText,
  stopSpeaking,
  transcriptAfterWakePhrase,
  transcriptFromEvent,
  type SpeechRecognitionLike,
} from '../assistant/voice'
import AppIcon from '../components/AppIcon.vue'
import {
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
  queryType?: string | null
  riskNotice?: string | null
}

const history = ref<ChatEntry[]>([])
const draft = ref('')
const sending = ref(false)
const sendError = ref('')
const voiceError = ref('')
type VoiceMode = 'off' | 'wake' | 'active'

const voiceMode = ref<VoiceMode>('off')
const listening = computed(() => voiceMode.value !== 'off')
const voicePreview = ref('')
const speakingIndex = ref<number | null>(null)
const thinkingPhase = ref(0)
const chatWindow = ref<HTMLElement | null>(null)
const draftInput = ref<HTMLTextAreaElement | null>(null)
// Demo-facing product label stays stable while the local runtime model can be
// switched independently through OLLAMA_MODEL.
const modelLabel = 'hct402-qlora-v5'

let streamTimer: ReturnType<typeof setInterval> | null = null
let phaseTimer: ReturnType<typeof setInterval> | null = null
let voiceRestartTimer: ReturnType<typeof setTimeout> | null = null
let recognition: SpeechRecognitionLike | null = null
let voiceDraftPrefix = ''
let voiceSessionId = 0
let voiceStopRequested = false
let voiceFatalError = false

const speechInputSupported = isSpeechInputSupported()
const speechOutputSupported = isSpeechOutputSupported()

const voiceStatusText = computed(() => {
  if (voiceMode.value === 'wake') return '正在聆听唤醒词：“小燕打开”'
  if (voiceMode.value === 'active') return '已唤醒，识别中的文字会实时填入草稿'
  return ''
})

const voiceButtonLabel = computed(() => {
  if (voiceMode.value === 'wake') return '等待唤醒'
  if (voiceMode.value === 'active') return '停止语音'
  return '开启唤醒'
})

const canSend = computed(() => draft.value.trim().length > 0 && !sending.value)

const SUGGESTIONS = [
  '最近有哪些健康变化需要我确认？',
  '当前的风险提醒都是依据什么规则？',
  '这位成员正在使用哪些药品？',
]

const THINKING_PHASES = [
  '连接本地模型',
  '检索家庭事实',
  '匹配规则与知识',
  '本地推理生成中（约需一分钟）',
  '组织回答与引用',
]

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
  stopVoiceInput()
  if (speakingIndex.value !== null) {
    stopSpeaking()
    speakingIndex.value = null
  }
  if (streamTimer) {
    clearInterval(streamTimer)
    streamTimer = null
  }
  if (phaseTimer) {
    clearInterval(phaseTimer)
    phaseTimer = null
  }
  clearChatSession(session.actorId, session.selectedHouseholdId, session.selectedMemberId)
  history.value = []
  draft.value = ''
  sendError.value = ''
  voiceError.value = ''
}

function useSuggestedQuestion(question: string): void {
  draft.value = question
  sendError.value = ''
  void nextTick(() => draftInput.value?.focus())
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

watch(
  () => [session.actorId, session.selectedHouseholdId, session.selectedMemberId] as const,
  ([actorId, householdId, memberId]) => {
    if (streamTimer) {
      clearInterval(streamTimer)
      streamTimer = null
    }
    restoreChatSession(loadChatSession(actorId, householdId, memberId))
  },
  { immediate: true },
)

function stopVoiceInput(): void {
  voiceStopRequested = true
  voiceFatalError = false
  voiceSessionId += 1
  voiceMode.value = 'off'
  voicePreview.value = ''
  if (voiceRestartTimer) {
    clearTimeout(voiceRestartTimer)
    voiceRestartTimer = null
  }
  const currentRecognition = recognition
  recognition = null
  currentRecognition?.abort()
}

function scheduleVoiceRecognition(sessionId: number): void {
  if (voiceRestartTimer) clearTimeout(voiceRestartTimer)
  voiceRestartTimer = setTimeout(() => {
    voiceRestartTimer = null
    if (sessionId !== voiceSessionId || voiceStopRequested || voiceFatalError || !listening.value) return
    startVoiceRecognition(sessionId)
  }, 80)
}

function startVoiceRecognition(sessionId: number): void {
  const nextRecognition = createSpeechRecognition('zh-CN', {
    continuous: true,
    interimResults: true,
    maxAlternatives: 1,
  })
  if (!nextRecognition) {
    voiceFatalError = true
    voiceMode.value = 'off'
    voiceError.value = '当前浏览器不支持连续语音输入，请改用文字输入。'
    return
  }

  nextRecognition.onstart = () => {
    if (sessionId !== voiceSessionId) return
    voiceError.value = ''
  }
  nextRecognition.onresult = event => {
    if (sessionId !== voiceSessionId) return
    const transcript = transcriptFromEvent(event)
    if (!transcript) return

    if (voiceMode.value === 'wake') {
      if (!containsWakePhrase(transcript)) {
        voicePreview.value = `正在聆听：${transcript}`
        return
      }
      voiceMode.value = 'active'
    }

    const spoken = containsWakePhrase(transcript)
      ? transcriptAfterWakePhrase(transcript)
      : transcript.trim()
    if (spoken) {
      // interimResults=true means this is intentionally updated before the
      // browser marks the utterance final; it never submits the message.
      draft.value = `${voiceDraftPrefix}${spoken}`.trimStart()
      voicePreview.value = `正在输入：${spoken}`
    } else {
      voicePreview.value = '已唤醒，请说出问题'
    }
  }
  nextRecognition.onerror = event => {
    if (sessionId !== voiceSessionId) return
    const error = event.error ?? ''
    if (error === 'no-speech' || error === 'aborted') return

    if (error === 'not-allowed' || error === 'service-not-allowed') {
      voiceFatalError = true
      voiceStopRequested = true
      voiceMode.value = 'off'
      voiceError.value = '麦克风权限未开启，请允许浏览器使用麦克风，或改用文字输入。'
      return
    }
    if (error === 'audio-capture') {
      voiceFatalError = true
      voiceStopRequested = true
      voiceMode.value = 'off'
      voiceError.value = '没有检测到可用麦克风，请检查系统设备或改用文字输入。'
      return
    }
    voiceError.value = '语音识别服务暂时中断，正在快速重试；也可以改用文字输入。'
  }
  nextRecognition.onend = () => {
    if (sessionId !== voiceSessionId) return
    if (recognition === nextRecognition) recognition = null
    if (!voiceStopRequested && !voiceFatalError && listening.value) {
      scheduleVoiceRecognition(sessionId)
    }
  }

  recognition = nextRecognition
  try {
    nextRecognition.start()
  } catch {
    if (sessionId !== voiceSessionId) return
    voiceFatalError = true
    voiceStopRequested = true
    voiceMode.value = 'off'
    recognition = null
    voiceError.value = '语音输入未能启动，请稍后重试或改用文字输入。'
  }
}

function toggleVoiceInput(): void {
  if (listening.value) {
    stopVoiceInput()
    return
  }
  voiceError.value = ''
  if (!speechInputSupported) {
    voiceError.value = '当前浏览器不支持语音输入，请改用文字输入。'
    return
  }

  voiceDraftPrefix = draft.value.trim() ? `${draft.value.trim()} ` : ''
  voicePreview.value = ''
  voiceStopRequested = false
  voiceFatalError = false
  const sessionId = ++voiceSessionId
  voiceMode.value = 'wake'
  startVoiceRecognition(sessionId)
}

function toggleSpeech(index: number, content: string): void {
  if (speakingIndex.value === index) {
    stopSpeaking()
    speakingIndex.value = null
    return
  }
  voiceError.value = ''
  const started = speakText(content, () => {
    if (speakingIndex.value === index) speakingIndex.value = null
  })
  if (!started) {
    voiceError.value = '当前浏览器不支持语音回复，请阅读文字回答。'
    return
  }
  speakingIndex.value = index
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

async function send(text?: string): Promise<void> {
  const content = (text ?? draft.value).trim()
  if (!content || sending.value) return

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
  thinkingPhase.value = 0
  scrollToEnd()
  phaseTimer = setInterval(() => {
    thinkingPhase.value = (thinkingPhase.value + 1) % THINKING_PHASES.length
  }, 950)

  try {
    const reply = await apiClient.assistantChat(
      {
        messages: history.value.map(entry => ({ role: entry.role, content: entry.content })),
        // Qwen3 基座模型可能先生成内部思考；提高上限，确保最终 JSON 不会被提前截断。
        max_tokens: 1024,
      },
      session.selectedHouseholdId || undefined,
      session.selectedMemberId || undefined,
      requestOptions.value,
    )
    const entry: ChatEntry = {
      role: 'assistant',
      content: reply.answer,
      revealed: 0,
      sources: reply.sources,
      citations: reply.citations,
      confidence: reply.confidence,
      degraded: reply.degraded,
      degradeReason: reply.degrade_reason,
      escalate: reply.escalate,
      suggestedQuestions: normalizeSuggestedQuestions(reply.suggested_questions),
      route: reply.route,
      queryType: reply.query_type,
      riskNotice: reply.risk_notice,
    }
    history.value.push(entry)
    persistChatSession()
    streamReveal(history.value[history.value.length - 1]!)
  } catch (cause) {
    sendError.value = formatError(cause)
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
  } finally {
    sending.value = false
    if (phaseTimer) {
      clearInterval(phaseTimer)
      phaseTimer = null
    }
  }
}

function onMemberChange(event: Event): void {
  selectMember((event.target as HTMLSelectElement).value)
}

onBeforeUnmount(() => {
  if (streamTimer) clearInterval(streamTimer)
  if (phaseTimer) clearInterval(phaseTimer)
  stopVoiceInput()
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
        <AppIcon name="leaf" :size="17" />
        <span class="session-text">
          <span class="session-label">使用边界</span>
          <span class="session-value">教学演示 · 不作医疗建议</span>
        </span>
      </span>
    </div>
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
            v-if="entry.role === 'assistant' && !isStreaming(entry) && (entry.degraded || entry.escalate || entry.riskNotice || entry.queryType || (entry.sources?.length ?? 0) > 0 || entry.confidence)"
            class="chat-sources"
          >
            <span v-if="entry.queryType" class="chat-evidence-summary">
              <AppIcon name="compass" :size="12" style="vertical-align: -1px" />
              问题类型：{{ questionTypeLabel(entry.queryType) }}
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
          </div>
        </div>
      </div>

      <div v-if="sending" class="chat-bubble-row assistant">
        <span class="chat-avatar thinking" aria-hidden="true">
          <AppIcon name="assistant" :size="16" />
        </span>
        <div class="chat-bubble thinking-bubble" role="status">
          <span class="thinking-wave" aria-hidden="true"><i /><i /><i /><i /></span>
          <Transition name="fade" mode="out-in">
            <span :key="thinkingPhase" class="thinking-text">{{ THINKING_PHASES[thinkingPhase] }}…</span>
          </Transition>
        </div>
      </div>
    </div>

    <p v-if="sendError" class="notice error" role="alert" style="margin-top: 14px">
      <AppIcon name="alert" :size="16" />
      {{ sendError }}
    </p>

    <form class="chat-compose" @submit.prevent="send()">
      <textarea
        ref="draftInput"
        v-model="draft"
        rows="2"
        placeholder="例如：最近的用药提醒是依据什么？（回答仅供参考，不构成医疗建议）"
        @keydown.enter.exact.prevent="send()"
      />
      <div class="chat-compose-actions">
        <button
          type="button"
          class="btn btn-ghost btn-small voice-input-button"
          :class="{ listening, active: voiceMode === 'active' }"
          :disabled="sending || !speechInputSupported"
          :aria-label="listening ? '停止语音唤醒' : '开启语音唤醒'"
          :aria-pressed="listening"
          :title="speechInputSupported ? '先点击开启，再说“小燕打开”；识别文字只会实时填入草稿' : '当前浏览器不支持语音输入'"
          @click="toggleVoiceInput"
        >
          <AppIcon name="microphone" :size="15" />
          {{ voiceButtonLabel }}
        </button>
        <button type="submit" class="btn btn-primary" :disabled="!canSend">
          {{ sending ? '发送中' : '发送' }}
        </button>
      </div>
    </form>
    <div
      v-if="listening"
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
        <strong>{{ voiceMode === 'wake' ? '等待唤醒' : '已唤醒，正在实时输入' }}</strong>
        <span>{{ voiceStatusText }}</span>
        <span v-if="voicePreview" class="voice-live-transcript">{{ voicePreview }}</span>
      </span>
    </div>
    <p v-if="voiceError" class="notice error" role="alert" style="margin-top: 10px">
      <AppIcon name="alert" :size="16" />
      {{ voiceError }}
    </p>
    <p class="text-faint" style="font-size: 12px; line-height: 1.6; margin: 10px 0 0">
      先点击“开启唤醒”，再说“小燕打开”开始实时填入草稿；发送前可修改。语音回复由浏览器本地朗读，原始音频不会上传到本地助手 API。
    </p>
  </section>
</template>

