<script setup lang="ts">
import { ref } from 'vue'

import AppIcon from '@/components/AppIcon.vue'
import SwitchRow from '@/components/SwitchRow.vue'
import ErrorNotice from '@/components/ErrorNotice.vue'
import { createSpeaker } from '@/composables/useSpeech'
import { ApiClient } from '@/api/client'
import { presentApiError, type ErrorPresentation } from '@/api/errors'
import { resetDemoData } from '@/data/demoProvider'
import { useA11y } from '@/stores/accessibility'
import {
  capabilityDescription,
  capabilityLabel,
  useCapabilities,
} from '@/stores/capabilities'
import { useSession } from '@/stores/session'
import { tapFeedback } from '@/utils/haptics'
import { normalizePhoneNumber } from '@/utils/phone'
import { DEFAULT_SERVER_URL_POLICY, validateServerBaseUrl } from '@/utils/serverUrl'

const { settings, setElderMode } = useA11y()
const { session, updateSession } = useSession()
const {
  capabilities: capabilityState,
  setCapabilities,
  clearCapabilities,
} = useCapabilities()
const feedbackSpeaker = createSpeaker(() => true)

const connectionState = ref<'idle' | 'testing' | 'ok' | 'failed'>('idle')
const connectionMessage = ref('')
const connectionError = ref<ErrorPresentation | null>(null)
const capabilityProbeError = ref<ErrorPresentation | null>(null)
const demoResetMessage = ref('')
const caregiverNameDraft = ref(session.caregiverName)
const caregiverPhoneDraft = ref(session.caregiverPhone)
const contactError = ref('')
const contactCallMessage = ref('')
const serverBaseUrlDraft = ref(session.serverBaseUrl)
const serverAddressError = ref('')
const serverAddressPlaceholder = DEFAULT_SERVER_URL_POLICY.allowPrivateHttp
  ? '例如 http://192.168.1.10:8000（受控 Debug 联调）'
  : '例如 https://family.example.test（发布构建仅 HTTPS）'
const serverAddressHelp = DEFAULT_SERVER_URL_POLICY.allowPrivateHttp
  ? '当前为开发/Android Debug 构建：明文 HTTP 仅允许家庭局域网或本机地址，公网仍须使用 HTTPS。'
  : '当前为发布构建：服务器必须使用 HTTPS；家庭局域网 HTTP 仅在受控 Debug 联调包开放。'

function onElderModeChange(enabled: boolean): void {
  setElderMode(enabled)
  tapFeedback([12, 60, 18])
  feedbackSpeaker.speak(
    enabled ? '长辈模式已开启，字号已调大，语音播报已打开。' : '长辈模式已关闭。',
  )
}

function persistContact(): void {
  const name = caregiverNameDraft.value.trim()
  if (name.length > 80) {
    contactError.value = '联系人称呼不能超过 80 个字符。'
    return
  }
  if (/[\u0000-\u001f\u007f]/.test(name)) {
    contactError.value = '联系人称呼不能包含控制字符。'
    return
  }

  const phone = normalizePhoneNumber(caregiverPhoneDraft.value)
  if (phone === null) {
    contactError.value = '请输入 7–15 位数字的电话号码，可带国际区号；不会拨打未通过校验的号码。'
    return
  }

  contactError.value = ''
  contactCallMessage.value = ''
  caregiverNameDraft.value = name
  caregiverPhoneDraft.value = phone
  updateSession({ caregiverName: name, caregiverPhone: phone })
}

function testContactCall(): void {
  const phone = normalizePhoneNumber(caregiverPhoneDraft.value)
  if (!phone) {
    contactError.value = '请先保存一个有效的联系人号码。'
    return
  }
  contactError.value = ''
  const confirmed = typeof window.confirm !== 'function'
    || window.confirm(`将打开手机拨号界面：${phone}。确认继续吗？`)
  if (confirmed) {
    contactCallMessage.value = '已请求系统拨号界面；如果设备或 PWA 未打开电话应用，请复制号码后手动拨打。'
    window.location.href = `tel:${phone}`
  }
}

function persistConnectionSession(): void {
  // 身份、访问目的或服务器变化后，下一页不得继续展示旧家庭/成员状态。
  updateSession({ currentMemberId: '' })
  connectionState.value = 'idle'
  connectionMessage.value = ''
  connectionError.value = null
  capabilityProbeError.value = null
  clearCapabilities()
}

function persistServerAddress(): void {
  const result = validateServerBaseUrl(serverBaseUrlDraft.value)
  if (!result.ok) {
    serverAddressError.value = result.message
    connectionState.value = 'idle'
    clearCapabilities()
    return
  }

  serverAddressError.value = ''
  serverBaseUrlDraft.value = result.value
  updateSession({ serverBaseUrl: result.value, currentMemberId: '' })
  connectionState.value = 'idle'
  connectionMessage.value = ''
  connectionError.value = null
  capabilityProbeError.value = null
  clearCapabilities()
}

function onModeChange(mode: 'demo' | 'live'): void {
  updateSession({ dataMode: mode, currentMemberId: '' })
  connectionState.value = 'idle'
  connectionMessage.value = ''
  connectionError.value = null
  capabilityProbeError.value = null
  clearCapabilities()
}

async function testConnection(): Promise<void> {
  const serverAddress = validateServerBaseUrl(serverBaseUrlDraft.value)
  if (!serverAddress.ok) {
    serverAddressError.value = serverAddress.message
    return
  }
  if (serverAddress.value !== session.serverBaseUrl) persistServerAddress()
  if (serverAddressError.value) return

  connectionState.value = 'testing'
  connectionMessage.value = ''
  connectionError.value = null
  capabilityProbeError.value = null
  clearCapabilities()
  const client = new ApiClient({ baseUrl: session.serverBaseUrl })
  try {
    const health = await client.getHealth({
      actorId: session.actorId || undefined,
      accessPurpose: session.accessPurpose || undefined,
    })
    let probe: ReturnType<typeof setCapabilities> | null = null
    try {
      probe = setCapabilities(await client.getCapabilities({ actorId: session.actorId || undefined }))
    } catch (cause) {
      clearCapabilities()
      capabilityProbeError.value = presentApiError(cause)
    }
    connectionState.value = 'ok'
    connectionMessage.value = `已连接：${health.service} ${health.version}${
      probe ? `，已探测 ${probe.available.length} 项可用能力` : '；能力探测未完成'
    }`
  } catch (cause) {
    clearCapabilities()
    connectionState.value = 'failed'
    connectionError.value = presentApiError(cause)
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
        <input v-model="caregiverNameDraft" type="text" placeholder="例如：女儿 王芳" @change="persistContact" />
      </label>
      <label class="field">
        电话
        <input
          v-model="caregiverPhoneDraft"
          type="tel"
          inputmode="tel"
          placeholder="用于「求助」页一键拨号"
          :aria-invalid="Boolean(contactError)"
          :aria-describedby="contactError ? 'contact-help contact-error' : 'contact-help'"
          @change="persistContact"
        />
      </label>
      <p id="contact-help" class="meta-line">仅保存在本机，用于求助页和风险卡的“联系家人”按钮，不会上传。</p>
      <p v-if="contactError" id="contact-error" class="notice" data-tone="error" role="alert">{{ contactError }}</p>
      <p v-if="contactCallMessage" class="notice" data-tone="info" role="status">{{ contactCallMessage }}</p>
      <button
        v-if="normalizePhoneNumber(caregiverPhoneDraft)"
        type="button"
        class="btn btn-quiet btn-block"
        @click="testContactCall"
      >
        测试拨号（需再次确认）
      </button>
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
            v-model="serverBaseUrlDraft"
            type="url"
            :placeholder="serverAddressPlaceholder"
            :aria-invalid="Boolean(serverAddressError)"
            :aria-describedby="serverAddressError ? 'server-address-help server-address-error' : 'server-address-help'"
            @change="persistServerAddress"
          />
          <small id="server-address-help">{{ serverAddressHelp }}留空表示同源。</small>
        </label>
        <p v-if="serverAddressError" id="server-address-error" class="notice" data-tone="error" role="alert">{{ serverAddressError }}</p>
        <label class="field">
          开发期身份（仅本地联调）
          <input v-model="session.actorId" type="text" placeholder="Actor ID" @change="persistConnectionSession" />
        </label>
        <label class="field">
          访问目的代码（X-Access-Purpose）
          <input v-model="session.accessPurpose" type="text" placeholder="family-care" @change="persistConnectionSession" />
        </label>
        <p v-if="!session.actorId.trim()" class="notice" data-tone="warn" role="status">
          请先填写开发身份；未配置身份时不会加载任何家庭或健康数据。
        </p>
        <p v-else-if="!session.accessPurpose.trim()" class="notice" data-tone="warn" role="status">
          请先填写访问目的代码；访问目的为空时不会加载任何家庭或健康数据。
        </p>
        <button
          type="button"
          class="btn btn-block"
          :disabled="connectionState === 'testing' || !session.actorId.trim() || !session.accessPurpose.trim()"
          @click="testConnection"
        >
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
        <p v-if="capabilityProbeError" class="notice" data-tone="warn" role="status">
          能力限制暂时无法读取：{{ capabilityProbeError.message }} 未声明的能力均按不可用处理，请先不要使用相关入口。
        </p>
        <ErrorNotice v-if="connectionError" :error="connectionError" @retry="testConnection" />

        <section
          v-if="capabilityState.snapshot"
          class="capability-panel"
          aria-labelledby="capability-title"
          aria-live="polite"
        >
          <div class="h-icon-row">
            <span class="row-icon" data-tone="info" aria-hidden="true"><AppIcon name="shield" :size="16" /></span>
            <h3 id="capability-title">服务能力与限制</h3>
          </div>
          <p class="meta-line">能力阶段：{{ capabilityState.snapshot.phase }}</p>
          <div class="capability-group">
            <strong>已提供（{{ capabilityState.snapshot.available.length }}）</strong>
            <ul v-if="capabilityState.snapshot.available.length" class="capability-list">
              <li v-for="id in capabilityState.snapshot.available" :key="`available-${id}`">
                <span class="tag" data-tone="calm">可用</span>
                <span>
                  <strong>{{ capabilityLabel(id) }}</strong>
                  <span class="meta-line">{{ capabilityDescription(id) }}</span>
                </span>
              </li>
            </ul>
            <p v-else class="meta-line">服务没有声明可用能力。</p>
          </div>
          <div class="capability-group">
            <strong>未提供或未启用（{{ capabilityState.snapshot.unavailable.length }}）</strong>
            <ul v-if="capabilityState.snapshot.unavailable.length" class="capability-list">
              <li v-for="id in capabilityState.snapshot.unavailable" :key="`unavailable-${id}`">
                <span class="tag" data-tone="warn">不可用</span>
                <span>
                  <strong>{{ capabilityLabel(id) }}</strong>
                  <span class="meta-line">{{ capabilityDescription(id) }} 相关入口会保持禁用。</span>
                </span>
              </li>
            </ul>
            <p v-else class="meta-line">服务没有声明未提供能力。</p>
          </div>
          <p class="notice" data-tone="warn" role="status">
            未列出的能力也按不可用处理；移动端不会把接口缺失包装成可用功能。
          </p>
        </section>

        <section class="auth-design-note" aria-labelledby="auth-design-title">
          <div class="h-icon-row">
            <span class="row-icon" data-tone="calm" aria-hidden="true"><AppIcon name="shield" :size="16" /></span>
            <h3 id="auth-design-title">正式鉴权（适配设计）</h3>
          </div>
          <p class="meta-line">当前仍使用开发期身份头，不代表正式登录已经接入。</p>
          <ul class="divided-list">
            <li>账号密码登录后使用短生命周期会话，登出或撤销后立即清理。</li>
            <li>高风险授权、删除等动作由主仓库要求 PIN/二维码一次性二次确认。</li>
            <li>正式会话只在内存传给 API Client，不写入本机存储或 URL。</li>
          </ul>
          <p class="notice" data-tone="warn" role="status">
            HCT-107 接口尚未提供联调版本；当前不会显示伪造的登录成功或二次确认结果。
          </p>
        </section>
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
.auth-design-note {
  display: grid;
  gap: 10px;
  margin-top: 18px;
  padding-top: 18px;
  border-top: 1px solid var(--line);
}
.auth-design-note h3 { margin: 0; font-size: 1rem; }
.auth-design-note .divided-list { margin: 0; }
.capability-panel {
  display: grid;
  gap: 12px;
  margin-top: 18px;
  padding-top: 18px;
  border-top: 1px solid var(--line);
}
.capability-panel h3 { margin: 0; font-size: 1rem; }
.capability-group { display: grid; gap: 8px; }
.capability-list { display: grid; gap: 8px; margin: 0; padding: 0; list-style: none; }
.capability-list li {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: start;
  gap: 8px;
  padding: 10px 12px;
  border-radius: var(--r-btn);
  background: var(--well-bg);
}
.capability-list li > span:last-child { display: grid; gap: 2px; }
.capability-list .tag { margin-top: 1px; }
</style>
