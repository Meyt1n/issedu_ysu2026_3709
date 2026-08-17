<script setup lang="ts">
import { ref } from 'vue'

import AppIcon from '@/components/AppIcon.vue'
import SwitchRow from '@/components/SwitchRow.vue'
import { createSpeaker } from '@/composables/useSpeech'
import { ApiClient } from '@/api/client'
import { resetDemoData } from '@/data/demoProvider'
import { useA11y } from '@/stores/accessibility'
import { useSession } from '@/stores/session'
import { tapFeedback } from '@/utils/haptics'

const { settings, setElderMode } = useA11y()
const { session, updateSession } = useSession()
const feedbackSpeaker = createSpeaker(() => true)

const connectionState = ref<'idle' | 'testing' | 'ok' | 'failed'>('idle')
const connectionMessage = ref('')
const demoResetMessage = ref('')

function onElderModeChange(enabled: boolean): void {
  setElderMode(enabled)
  tapFeedback([12, 60, 18])
  feedbackSpeaker.speak(
    enabled ? '长辈模式已开启，字号已调大，语音播报已打开。' : '长辈模式已关闭。',
  )
}

function persistSession(): void {
  updateSession({})
}

function onModeChange(mode: 'demo' | 'live'): void {
  updateSession({ dataMode: mode })
  connectionState.value = 'idle'
  connectionMessage.value = ''
}

async function testConnection(): Promise<void> {
  connectionState.value = 'testing'
  connectionMessage.value = ''
  const client = new ApiClient({ baseUrl: session.serverBaseUrl })
  try {
    const health = await client.getHealth({
      actorId: session.actorId || undefined,
      accessPurpose: session.accessPurpose || undefined,
    })
    const capabilities = await client
      .getCapabilities({ actorId: session.actorId || undefined })
      .catch(() => null)
    connectionState.value = 'ok'
    connectionMessage.value = `已连接：${health.service} ${health.version}${
      capabilities ? `，本地能力 ${capabilities.available.length} 项` : ''
    }`
  } catch (cause) {
    connectionState.value = 'failed'
    connectionMessage.value = cause instanceof Error ? cause.message : '连接失败'
  }
}

function restoreDemoData(): void {
  resetDemoData()
  demoResetMessage.value = '演示数据已恢复到初始状态。'
}
</script>

<template>
  <main id="main" class="screen">
    <header class="screen-header">
      <p class="eyebrow">设置</p>
      <h1>我的</h1>
    </header>

    <section class="card" aria-labelledby="elder-title">
      <h2 id="elder-title" class="visually-hidden-title">长辈模式</h2>
      <SwitchRow
        title="长辈模式"
        description="特大字号 + 语音播报 + 简化导航（今日 / 拍药盒 / 求助 / 我的）"
        :model-value="settings.elderMode"
        @update:model-value="onElderModeChange"
      />
    </section>

    <RouterLink class="card link-card" to="/me/accessibility">
      <AppIcon name="settings" :size="22" />
      <span class="link-card-text">
        <strong>无障碍设置</strong>
        <span class="meta-line">字号、对比度、语音播报、动效</span>
      </span>
      <AppIcon name="chevron-right" :size="18" />
    </RouterLink>

    <section class="card" aria-labelledby="contact-title">
      <div class="h-icon-row">
        <span class="row-icon" data-tone="danger" aria-hidden="true"><AppIcon name="phone" :size="16" /></span>
        <h2 id="contact-title">紧急联系人</h2>
      </div>
      <label class="field">
        称呼
        <input v-model="session.caregiverName" type="text" placeholder="例如：女儿 王芳" @change="persistSession" />
      </label>
      <label class="field">
        电话
        <input v-model="session.caregiverPhone" type="tel" placeholder="用于「求助」页一键拨号" @change="persistSession" />
      </label>
      <p class="meta-line">仅保存在本机，用于求助页和风险卡的“联系家人”按钮，不会上传。</p>
    </section>

    <section class="card" aria-labelledby="source-title">
      <div class="h-icon-row">
        <span class="row-icon" data-tone="info" aria-hidden="true"><AppIcon name="refresh" :size="16" /></span>
        <h2 id="source-title">数据来源</h2>
      </div>
      <fieldset class="mode-fieldset">
        <legend class="meta-line">选择应用连接的数据</legend>
        <label class="mode-option">
          <input
            type="radio"
            name="data-mode"
            value="demo"
            :checked="session.dataMode === 'demo'"
            @change="onModeChange('demo')"
          />
          <span>
            <strong>演示模式（默认）</strong>
            <span class="meta-line">内置虚构数据，开箱即用，不连接任何服务器</span>
          </span>
        </label>
        <label class="mode-option">
          <input
            type="radio"
            name="data-mode"
            value="live"
            :checked="session.dataMode === 'live'"
            @change="onModeChange('live')"
          />
          <span>
            <strong>家庭服务器（联机）</strong>
            <span class="meta-line">连接主仓库 FastAPI；适配层为起步版本，需联调验收</span>
          </span>
        </label>
      </fieldset>

      <template v-if="session.dataMode === 'live'">
        <label class="field">
          服务器地址
          <input
            v-model="session.serverBaseUrl"
            type="url"
            placeholder="例如 http://192.168.1.10:8000（留空表示同源）"
            @change="persistSession"
          />
          <small>健康数据默认不出网：请填写家庭局域网内的地址。</small>
        </label>
        <label class="field">
          开发身份（X-Actor-Id）
          <input v-model="session.actorId" type="text" placeholder="Actor ID" @change="persistSession" />
        </label>
        <label class="field">
          访问目的代码（X-Access-Purpose）
          <input v-model="session.accessPurpose" type="text" placeholder="family-care" @change="persistSession" />
        </label>
        <button type="button" class="btn btn-block" :disabled="connectionState === 'testing'" @click="testConnection">
          {{ connectionState === 'testing' ? '正在测试…' : '测试连接' }}
        </button>
        <p
          v-if="connectionMessage"
          class="notice"
          :data-tone="connectionState === 'ok' ? 'success' : 'error'"
          role="status"
        >
          {{ connectionMessage }}
        </p>
      </template>

      <template v-else>
        <button type="button" class="btn btn-quiet btn-block" @click="restoreDemoData">恢复演示数据</button>
        <p v-if="demoResetMessage" class="notice" data-tone="success" role="status">{{ demoResetMessage }}</p>
      </template>
    </section>

    <section class="card" aria-labelledby="privacy-title">
      <div class="h-icon-row">
        <span class="row-icon" data-tone="calm" aria-hidden="true"><AppIcon name="shield" :size="16" /></span>
        <h2 id="privacy-title">隐私与边界</h2>
      </div>
      <ul class="divided-list">
        <li>家庭健康数据默认不出网；本应用仅连接家庭可信域内的服务器。</li>
        <li>照护者只能看到被精细授权的字段；授权可随时在网页端撤回。</li>
        <li>药盒识别永远需要人工确认；冲突与未知不会自动入库。</li>
        <li>风险等级由确定性规则决定；应用不做诊断、处方或剂量判断。</li>
        <li>没有购药、问诊、广告或任何健康消费导流。</li>
      </ul>
    </section>

    <section class="card" aria-labelledby="about-title">
      <div class="h-icon-row">
        <span class="row-icon" data-tone="accent" aria-hidden="true"><AppIcon name="heart" :size="16" /></span>
        <h2 id="about-title">关于</h2>
      </div>
      <p class="meta-line">家健镜随身版 v0.1.0 · 教学演示，不用于诊断或治疗</p>
      <p class="meta-line">
        配套网页端与后端：
        <a href="https://github.com/Meyt1n/issedu_ysu2026_3709" rel="noreferrer">issedu_ysu2026_3709</a>
      </p>
    </section>
  </main>
</template>

<style scoped>
.link-card {
  display: flex;
  align-items: center;
  gap: 12px;
  text-decoration: none;
  color: inherit;
}
.link-card-text { flex: 1; display: grid; gap: 2px; }
.visually-hidden-title {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
}
.mode-fieldset { border: 0; margin: 0; padding: 0; display: grid; gap: 10px; }
.mode-option {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  background: var(--well-bg);
  border: 1.5px solid transparent;
  border-radius: var(--r-btn);
  padding: 12px 14px;
  cursor: pointer;
  box-shadow: inset 0 1px 0 var(--hilite);
  transition: border-color var(--speed), background var(--speed);
}
.mode-option:has(input:checked) {
  background: var(--c-brand-softer);
  border-color: var(--c-brand);
}
html[data-contrast='high'] .mode-option { border-color: #000; background: #fff; }
.mode-option input { width: 20px; height: 20px; margin-top: 3px; flex: 0 0 auto; }
.mode-option > span { display: grid; gap: 2px; }
</style>
