<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'

import AppIcon from '@/components/AppIcon.vue'
import {
  inspectChineseVoicePacks,
  loadVoicePreferences,
  runVoicePreflight,
  type VoicePackReport,
  type VoicePreflightReport,
} from '@/composables/useVoiceInput'
import { useSession } from '@/stores/session'

const router = useRouter()
const { session } = useSession()
const voicePrefs = loadVoicePreferences()

const voiceReport = ref<VoicePackReport | null>(null)
const preflightReport = ref<VoicePreflightReport | null>(null)
const checking = ref(false)

async function runChecks(): Promise<void> {
  checking.value = true
  try {
    voiceReport.value = await inspectChineseVoicePacks()
    preflightReport.value = await runVoicePreflight({
      serverBaseUrl: session.dataMode === 'live' ? session.serverBaseUrl : undefined,
    })
  } finally {
    checking.value = false
  }
}
</script>

<template>
  <main id="main" class="screen">
    <button type="button" class="btn btn-quiet back-btn" @click="router.back()">
      <AppIcon name="arrow-left" :size="18" />
      返回
    </button>

    <header class="screen-header">
      <p class="eyebrow">语音自检</p>
      <h1>助手语音预检</h1>
      <p class="screen-subtitle">
        检查麦克风、中文语音包与（联机时）家庭服务器连通；不上传音频，仅本机诊断。
        当前唤醒词：「{{ voicePrefs.wakePhrase }}」（可在无障碍设置中修改）。
      </p>
    </header>

    <section class="card">
      <p class="meta-line">
        当前模式：{{ session.dataMode === 'live' ? '联机' : '演示' }}
        <template v-if="session.dataMode === 'live'">
          · 服务器 {{ session.serverBaseUrl.trim() || '（未填写）' }}
        </template>
      </p>
      <button type="button" class="btn btn-primary btn-block" :disabled="checking" @click="runChecks">
        {{ checking ? '自检中…' : '运行语音预检' }}
      </button>
    </section>

    <section v-if="preflightReport" class="card" aria-label="预检清单">
      <h2>检查清单</h2>
      <ul class="checklist">
        <li :data-ok="preflightReport.speechInput">
          语音输入（SpeechRecognition）：{{ preflightReport.speechInput ? '支持' : '不支持' }}
        </li>
        <li :data-ok="true">
          唤醒词偏好：「{{ voicePrefs.wakePhrase }}」；近音字可匹配（如家健镜/家建镜）
        </li>
        <li :data-ok="preflightReport.microphone === 'granted'">
          麦克风权限：{{ preflightReport.microphone ?? '未知' }}
        </li>
        <li :data-ok="preflightReport.speechOutput">
          语音播报（TTS）：{{ preflightReport.speechOutput ? '支持' : '不支持' }}
        </li>
        <li :data-ok="preflightReport.voices.preferredNatural">
          中文 Natural 类音色：{{ preflightReport.voices.preferredNatural ? '已检测到' : '未检测到' }}
        </li>
        <li v-if="preflightReport.serverReachable !== null" :data-ok="preflightReport.serverReachable">
          家庭服务器：{{ preflightReport.serverDetail }}
        </li>
      </ul>
      <div class="guidance">
        <p v-for="(line, index) in preflightReport.guidance" :key="index">{{ line }}</p>
      </div>
      <p v-if="voiceReport?.names.length" class="meta-line">
        本机中文音色：{{ voiceReport.names.slice(0, 8).join('；') }}
      </p>
    </section>

    <footer class="disclaimer">
      听感准备说明见主仓库 <code>docs/demo/中文语音包与听感准备说明.md</code>；真机签收见
      <code>docs/testing/MOB-150-Android真机语音助手验收记录.md</code>（须设备填写，Cloud Agent 不能代签）。
    </footer>
  </main>
</template>

<style scoped>
.back-btn { justify-self: start; }
.checklist {
  margin: 0;
  padding-left: 18px;
  display: grid;
  gap: 8px;
}
.checklist li[data-ok='false'] { color: var(--danger, #b42318); }
.guidance { margin-top: 12px; display: grid; gap: 6px; }
.guidance p { margin: 0; line-height: 1.45; }
.meta-line { color: var(--c-ink-soft); font-size: 0.9rem; margin: 0 0 12px; }
</style>
