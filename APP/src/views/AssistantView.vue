<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref } from 'vue'
import { RouterLink } from 'vue-router'

import AppIcon from '@/components/AppIcon.vue'
import { ApiClientError } from '@/api/client'
import type { AssistantResponse } from '@/api/types'
import { createLiveApiClient } from '@/data'
import { createSpeaker, useSpeech } from '@/composables/useSpeech'
import {
  containsWakePhrase,
  createSpeechRecognition,
  DEFAULT_WAKE_PHRASE,
  isSpeechInputSupported,
  latestTranscriptFromEvent,
  transcriptAfterWakePhrase,
  transcriptFromEvent,
  VOICE_RESTART_DELAY_MS,
  type SpeechRecognitionLike,
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
}

type VoiceMode = 'off' | 'wake' | 'active'

const { session } = useSession()
const { settings } = useA11y()
const speech = useSpeech()
const manualSpeaker = createSpeaker(() => true)

const history = ref<ChatEntry[]>([])
const draft = ref('')
const sending = ref(false)
const sendError = ref('')
const voiceError = ref('')
const voicePreview = ref('')
const voiceMode = ref<VoiceMode>('off')
const speakingIndex = ref<number | null>(null)
const chatEnd = ref<HTMLElement | null>(null)

const speechInputSupported = isSpeechInputSupported()
const listening = computed(() => voiceMode.value !== 'off')
const liveMode = computed(() => session.dataMode === 'live')
const serverLabel = computed(() => session.serverBaseUrl.trim() || '（未填写服务器地址）')
const assistantReady = computed(() => liveMode.value && Boolean(session.serverBaseUrl.trim()))

const voiceStatusLabel = computed(() => {
  if (voiceMode.value === 'wake') return '等待唤醒：请说「小燕小燕」'
  if (voiceMode.value === 'active') return '已唤醒，正在听写到输入框'
  return ''
})

let recognition: SpeechRecognitionLike | null = null
let voiceSessionId = 0
let voiceStopRequested = false
let voiceFatalError = false
let voiceDraftPrefix = ''
let voiceRestartTimer: ReturnType<typeof setTimeout> | null = null

function scrollToEnd(): void {
  void nextTick(() => chatEnd.value?.scrollIntoView({ block: 'end', behavior: 'smooth' }))
}

function requestOptions() {
  return {
    actorId: session.actorId || undefined,
    accessPurpose: session.accessPurpose || undefined,
  }
}

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
  const current = recognition
  recognition = null
  current?.abort()
}

function scheduleVoiceRecognition(sessionId: number): void {
  if (voiceRestartTimer) clearTimeout(voiceRestartTimer)
  voiceRestartTimer = setTimeout(() => {
    voiceRestartTimer = null
    if (sessionId !== voiceSessionId || voiceStopRequested || voiceFatalError || !listening.value) return
    startVoiceRecognition(sessionId)
  }, VOICE_RESTART_DELAY_MS)
}

function startVoiceRecognition(sessionId: number): void {
  const nextRecognition = createSpeechRecognition('zh-CN', {
    continuous: true,
    interimResults: true,
    maxAlternatives: 3,
  })
  if (!nextRecognition) {
    voiceFatalError = true
    voiceMode.value = 'off'
    voiceError.value = '当前设备不支持连续语音输入，请改用文字输入。'
    return
  }

  nextRecognition.onstart = () => {
    if (sessionId !== voiceSessionId) return
    voiceError.value = ''
  }
  nextRecognition.onresult = (event) => {
    if (sessionId !== voiceSessionId) return
    const latest = latestTranscriptFromEvent(event)
    const transcript = transcriptFromEvent(event)
    if (!latest && !transcript) return

    if (voiceMode.value === 'wake') {
      const wakeProbe = latest || transcript
      if (!containsWakePhrase(wakeProbe) && !containsWakePhrase(transcript)) {
        voicePreview.value = `正在聆听：${wakeProbe || transcript}`
        return
      }
      voiceMode.value = 'active'
      voiceDraftPrefix = draft.value.trim() ? `${draft.value.trim()} ` : ''
    }

    const spokenSource = containsWakePhrase(transcript)
      ? transcript
      : containsWakePhrase(latest)
        ? latest
        : transcript
    const spoken = containsWakePhrase(spokenSource)
      ? transcriptAfterWakePhrase(spokenSource)
      : spokenSource.trim()
    if (spoken) {
      draft.value = `${voiceDraftPrefix}${spoken}`.trimStart()
      voicePreview.value = `正在输入：${spoken}`
    } else {
      voicePreview.value = '已唤醒，请说出问题'
    }
  }
  nextRecognition.onerror = (event) => {
    if (sessionId !== voiceSessionId) return
    const error = event.error ?? ''
    if (error === 'no-speech' || error === 'aborted') return
    if (error === 'not-allowed' || error === 'service-not-allowed') {
      voiceFatalError = true
      voiceStopRequested = true
      voiceMode.value = 'off'
      voiceError.value = '麦克风权限未开启，请允许后重试，或改用文字输入。'
      return
    }
    if (error === 'audio-capture') {
      voiceFatalError = true
      voiceStopRequested = true
      voiceMode.value = 'off'
      voiceError.value = '没有检测到可用麦克风，请检查设备或改用文字输入。'
      return
    }
    voiceError.value = '语音识别暂时中断，正在重试；也可改用文字输入。'
  }
  nextRecognition.onend = () => {
    if (sessionId !== voiceSessionId) return
    if (recognition === nextRecognition) recognition = null
    if (!voiceStopRequested && !voiceFatalError && listening.value) {
      if (voiceMode.value === 'active') {
        voiceDraftPrefix = draft.value.trim() ? `${draft.value.trim()} ` : ''
      }
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
    voiceError.value = '当前浏览器/WebView 不支持语音输入，请改用文字。'
    return
  }
  // 听说互斥：开始听之前先停朗读，避免麦克风把合成语音写进草稿。
  speech.stop()
  manualSpeaker.stop()
  speakingIndex.value = null
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
    manualSpeaker.stop()
    speech.stop()
    speakingIndex.value = null
    return
  }
  if (listening.value) stopVoiceInput()
  speakingIndex.value = index
  const started = manualSpeaker.speak(content)
  if (!started) {
    speakingIndex.value = null
    voiceError.value = '当前无法语音播报，请阅读文字回答。可先安装 Natural 类中文语音包。'
  }
}

function applySuggested(question: string): void {
  draft.value = question
  stopVoiceInput()
}

async function send(text?: string): Promise<void> {
  const content = (text ?? draft.value).trim()
  if (!content || sending.value) return

  stopVoiceInput()
  manualSpeaker.stop()
  speech.stop()
  speakingIndex.value = null

  history.value.push({ role: 'user', content })
  draft.value = ''
  sending.value = true
  sendError.value = ''
  scrollToEnd()

  if (!liveMode.value) {
    history.value.push({
      role: 'assistant',
      content:
        '当前是演示模式，助手不会连接家庭服务器。请到「我的」切换为「家庭服务器（联机）」，填写电脑后端地址（例如 http://192.168.x.x:8000）后再提问。',
      degraded: true,
      degradeReason: 'demo_mode',
    })
    sending.value = false
    scrollToEnd()
    return
  }

  if (!session.serverBaseUrl.trim()) {
    history.value.push({
      role: 'assistant',
      content: '尚未填写家庭服务器地址。请到「我的」填写电脑上 FastAPI 的局域网地址后再试。',
      degraded: true,
      degradeReason: 'missing_server',
    })
    sending.value = false
    scrollToEnd()
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
    sending.value = false
    scrollToEnd()
    return
  }

  try {
    const messages = history.value.map((entry) => ({ role: entry.role, content: entry.content }))
    const reply: AssistantResponse = await client.assistantChat(
      {
        messages,
        max_tokens: 1024,
        agent_mode: 'multi_agent',
        allow_network_search: false,
      },
      session.currentHouseholdId || undefined,
      session.currentMemberId || undefined,
      requestOptions(),
    )
    history.value.push({
      role: 'assistant',
      content: reply.answer,
      degraded: reply.degraded,
      degradeReason: reply.degrade_reason,
      sources: reply.sources,
      suggestedQuestions: (reply.suggested_questions ?? []).filter((item) => typeof item === 'string' && item.trim()),
    })
    scrollToEnd()
    // 长辈「语音播报」开启时，在用户主动发送后自动朗读最新回答。
    if (settings.voiceBroadcast) {
      const lastIndex = history.value.length - 1
      speakingIndex.value = lastIndex
      if (!manualSpeaker.speak(reply.answer)) speakingIndex.value = null
    }
  } catch (cause) {
    const message =
      cause instanceof ApiClientError
        ? cause.message
        : '家庭服务器暂时无法回答。请确认电脑后端已启动，且手机与电脑在同一局域网。'
    sendError.value = message
    history.value.push({
      role: 'assistant',
      content:
        '本地模型或其依赖当前不可用，无法生成回答。家庭事实、任务与提醒不受影响，可直接在对应页面查看。',
      degraded: true,
      degradeReason: 'request_failed',
    })
    scrollToEnd()
  } finally {
    sending.value = false
  }
}

function clearChat(): void {
  stopVoiceInput()
  manualSpeaker.stop()
  speech.stop()
  speakingIndex.value = null
  history.value = []
  draft.value = ''
  sendError.value = ''
  voiceError.value = ''
}

onBeforeUnmount(() => {
  stopVoiceInput()
  manualSpeaker.stop()
})
</script>

<template>
  <main id="main" class="page assistant-page" tabindex="-1">
    <header class="page-header">
      <div>
        <p class="eyebrow">随身助手</p>
        <h1>语音提问</h1>
        <p class="lede">
          与网页端相同：先点「开启唤醒」，再说「{{ DEFAULT_WAKE_PHRASE }}」；识别文字只进草稿，点发送后才请求家庭服务器。
        </p>
      </div>
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
            ? '将请求你电脑上的 /api/v1/assistant/chat；音频不会上传。'
            : '演示模式不调用后端。切换联机并填写电脑局域网地址后即可对话。'
        }}
      </p>
      <p v-if="assistantReady && liveMode" class="meta-line">
        家庭 {{ session.currentHouseholdId || '未选' }} · 成员 {{ session.currentMemberId || '未选' }}
      </p>
    </section>

    <section class="card chat-card" aria-label="对话">
      <div v-if="history.length === 0" class="empty-hint">
        还没有对话。可以打字提问，或开启语音唤醒。助手不做诊断、处方或剂量判断。
      </div>
      <article
        v-for="(entry, index) in history"
        :key="`${entry.role}-${index}`"
        class="bubble"
        :data-role="entry.role"
      >
        <p class="bubble-role">{{ entry.role === 'user' ? '我' : '助手' }}</p>
        <p class="bubble-text">{{ entry.content }}</p>
        <p v-if="entry.degraded" class="meta-line">降级说明：{{ entry.degradeReason || '受控降级' }}</p>
        <div v-if="entry.role === 'assistant'" class="bubble-actions">
          <button
            type="button"
            class="btn btn-secondary"
            :aria-pressed="speakingIndex === index"
            @click="toggleSpeech(index, entry.content)"
          >
            {{ speakingIndex === index ? '停止朗读' : '朗读回答' }}
          </button>
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

    <p v-if="sendError" class="error-line" role="alert">{{ sendError }}</p>
    <p v-if="voiceError" class="error-line" role="status">{{ voiceError }}</p>
    <p v-if="voicePreview" class="voice-preview" role="status">{{ voicePreview }}</p>
    <p v-if="voiceStatusLabel" class="voice-status" role="status">{{ voiceStatusLabel }}</p>

    <form class="composer card" @submit.prevent="send()">
      <label class="sr-only" for="assistant-draft">问题草稿</label>
      <textarea
        id="assistant-draft"
        v-model="draft"
        rows="3"
        placeholder="输入问题，或语音唤醒后口述…"
        :disabled="sending"
      />
      <div class="composer-actions">
        <button
          type="button"
          class="btn btn-secondary mic-btn"
          :class="{ listening, active: voiceMode === 'active' }"
          :disabled="sending || !speechInputSupported"
          :aria-pressed="listening"
          :aria-label="listening ? '停止语音唤醒' : '开启语音唤醒'"
          :title="speechInputSupported ? '先点击开启，再说小燕小燕' : '当前不支持语音输入'"
          @click="toggleVoiceInput"
        >
          <AppIcon name="mic" :size="22" />
          {{ listening ? (voiceMode === 'active' ? '听写中' : '等待唤醒') : '开启唤醒' }}
        </button>
        <button type="button" class="btn btn-secondary" :disabled="sending || history.length === 0" @click="clearChat">
          清空
        </button>
        <button type="submit" class="btn btn-primary" :disabled="sending || !draft.trim()">
          {{ sending ? '发送中…' : '发送' }}
        </button>
      </div>
    </form>
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
}
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
.error-line { color: var(--danger, #b42318); margin: 0; }
.voice-preview, .voice-status { margin: 0; color: var(--muted); }
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
}
</style>
