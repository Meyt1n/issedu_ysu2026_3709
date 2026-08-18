<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref } from 'vue'

import { apiClient } from '../api/client'
import { normalizeSuggestedQuestions } from '../assistant/followUp'
import {
  createSpeechRecognition,
  isSpeechInputSupported,
  isSpeechOutputSupported,
  speakText,
  stopSpeaking,
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
  confidence?: string
  degraded?: boolean
  degradeReason?: string | null
  escalate?: boolean
  suggestedQuestions?: string[]
}

const history = ref<ChatEntry[]>([])
const draft = ref('')
const sending = ref(false)
const sendError = ref('')
const voiceError = ref('')
const listening = ref(false)
const speakingIndex = ref<number | null>(null)
const thinkingPhase = ref(0)
const chatWindow = ref<HTMLElement | null>(null)
// Demo-facing product label stays stable while the local runtime model can be
// switched independently through OLLAMA_MODEL.
const modelLabel = 'hct402-qlora-v5'

let streamTimer: ReturnType<typeof setInterval> | null = null
let phaseTimer: ReturnType<typeof setInterval> | null = null
let recognition: SpeechRecognitionLike | null = null
let voiceDraftPrefix = ''

const speechInputSupported = isSpeechInputSupported()
const speechOutputSupported = isSpeechOutputSupported()

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

function toggleVoiceInput(): void {
  if (listening.value) {
    recognition?.stop()
    return
  }
  voiceError.value = ''
  const nextRecognition = createSpeechRecognition()
  if (!nextRecognition) {
    voiceError.value = '当前浏览器不支持语音输入，请改用文字输入。'
    return
  }

  voiceDraftPrefix = draft.value.trim() ? `${draft.value.trim()} ` : ''
  nextRecognition.onstart = () => {
    listening.value = true
    voiceError.value = ''
  }
  nextRecognition.onresult = event => {
    const transcript = transcriptFromEvent(event)
    if (transcript) draft.value = `${voiceDraftPrefix}${transcript}`.trimStart()
  }
  nextRecognition.onerror = event => {
    listening.value = false
    const reason = event.error === 'not-allowed' || event.error === 'service-not-allowed'
      ? '麦克风权限未开启，请允许浏览器使用麦克风，或改用文字输入。'
      : '语音识别暂时失败，请重试或改用文字输入。'
    voiceError.value = reason
  }
  nextRecognition.onend = () => {
    listening.value = false
    recognition = null
  }
  recognition = nextRecognition
  try {
    nextRecognition.start()
  } catch {
    listening.value = false
    recognition = null
    voiceError.value = '语音输入未能启动，请稍后重试或改用文字输入。'
  }
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

  if (listening.value) recognition?.stop()
  if (speakingIndex.value !== null) {
    stopSpeaking()
    speakingIndex.value = null
  }
  history.value.push({ role: 'user', content, revealed: content.length })
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
      confidence: reply.confidence,
      degraded: reply.degraded,
      degradeReason: reply.degrade_reason,
      escalate: reply.escalate,
      suggestedQuestions: normalizeSuggestedQuestions(reply.suggested_questions),
    }
    history.value.push(entry)
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
  recognition?.abort()
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
            @click="send(suggestion)"
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
            v-if="entry.role === 'assistant' && !isStreaming(entry) && (entry.degraded || entry.escalate || (entry.sources?.length ?? 0) > 0 || entry.confidence)"
            class="chat-sources"
          >
            <span v-if="entry.degraded" style="color: var(--gold)">
              ⚠ 本地模型已降级{{ entry.degradeReason ? `（${entry.degradeReason}）` : '' }}，以上为受控回复，不含模型生成的医疗判断。
            </span>
            <span v-if="entry.escalate" style="color: var(--rose)">
              此问题超出系统边界，请联系医生或药师进一步确认。
            </span>
            <span v-if="entry.confidence && !entry.degraded">回答把握程度：{{ entry.confidence }}（仍需人工确认）</span>
            <template v-if="(entry.sources?.length ?? 0) > 0">
              <span v-for="source in entry.sources" :key="source">
                <AppIcon name="compass" :size="12" style="vertical-align: -1px" />
                依据：{{ source }}
              </span>
            </template>
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
              @click="send(question)"
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

    <form class="chat-compose" style="margin-top: 16px" @submit.prevent="send()">
      <textarea
        v-model="draft"
        rows="2"
        placeholder="例如：最近的用药提醒是依据什么？（回答仅供参考，不构成医疗建议）"
        @keydown.enter.exact.prevent="send()"
      />
      <button
        type="button"
        class="btn btn-ghost btn-small voice-input-button"
        :class="{ listening }"
        :disabled="sending || !speechInputSupported"
        :aria-label="listening ? '停止语音输入' : '开始语音输入'"
        :aria-pressed="listening"
        :title="speechInputSupported ? '语音只会填入输入框，点击发送后才提交' : '当前浏览器不支持语音输入'"
        @click="toggleVoiceInput"
      >
        <AppIcon name="microphone" :size="15" />
        {{ listening ? '停止录音' : '语音输入' }}
      </button>
      <button type="submit" class="btn btn-primary" :disabled="!canSend" style="align-self: flex-end">
        {{ sending ? '发送中' : '发送' }}
      </button>
    </form>
    <p v-if="voiceError" class="notice error" role="alert" style="margin-top: 10px">
      <AppIcon name="alert" :size="16" />
      {{ voiceError }}
    </p>
    <p class="text-faint" style="font-size: 12px; line-height: 1.6; margin: 10px 0 0">
      语音输入只写入草稿，发送前可修改；语音回复由浏览器本地朗读。当前资料不足时，系统不会替你做用药判断。
    </p>
  </section>
</template>
