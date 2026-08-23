<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import AppIcon from '@/components/AppIcon.vue'
import SwitchRow from '@/components/SwitchRow.vue'
import ErrorNotice from '@/components/ErrorNotice.vue'
import { createSpeaker } from '@/composables/useSpeech'
import { ApiClient, ApiClientError } from '@/api/client'
import { buildInfoLine } from '@/buildInfo'
import { presentApiError, type ErrorPresentation } from '@/api/errors'
import { requestOutcomeLabel, requestTraces, type RequestTraceEntry } from '@/api/requestLog'
import { resetDemoData } from '@/data/demoProvider'
import { activeProvider, clearHouseholdSelection, selectHousehold } from '@/data'
import type { HouseholdOption } from '@/data/types'
import { currentAuthAdapter, familyAuthAdapter } from '@/data/authAdapter'
import { useA11y } from '@/stores/accessibility'
import {
  capabilityDescription,
  capabilityLabel,
  useCapabilities,
} from '@/stores/capabilities'
import { getAuthSession, useAuth } from '@/stores/auth'
import { isDevActorEnabled, useAuthorizationBoundary, useSession, type AuthMode } from '@/stores/session'
import { tapFeedback } from '@/utils/haptics'
import { normalizePhoneNumber } from '@/utils/phone'
import { DEFAULT_SERVER_URL_POLICY, validateServerBaseUrl } from '@/utils/serverUrl'

const { settings, setElderMode } = useA11y()
const { session, updateSession } = useSession()
const { auth, signOut, beginStepUp, confirmStepUp, cancelStepUp } = useAuth()
const { authorizationBoundary, resumeAuthorizationBoundary } = useAuthorizationBoundary()
const {
  capabilities: capabilityState,
  setCapabilities,
  clearCapabilities,
} = useCapabilities()
const feedbackSpeaker = createSpeaker(() => true)

const devActorAllowed = isDevActorEnabled()
const connectionState = ref<'idle' | 'testing' | 'ok' | 'failed'>('idle')
const connectionMessage = ref('')
const connectionError = ref<ErrorPresentation | null>(null)
const capabilityProbeError = ref<ErrorPresentation | null>(null)
/** MOB-144：最近请求与回执（本机诊断，只读内存，不落盘）。 */
const traceView = ref<RequestTraceEntry[]>([])
function refreshTraceView(): void {
  traceView.value = [...requestTraces()].slice(0, 10)
}

function formatTraceTime(iso: string): string {
  const time = new Date(iso)
  return Number.isNaN(time.getTime()) ? iso : time.toLocaleTimeString('zh-CN', { hour12: false })
}

const demoResetMessage = ref('')
const caregiverNameDraft = ref(session.caregiverName)
const caregiverPhoneDraft = ref(session.caregiverPhone)
const contactError = ref('')
const contactCallMessage = ref('')
const serverBaseUrlDraft = ref(session.serverBaseUrl)
const serverAddressError = ref('')
const actorIdDraft = ref(session.actorId)
const accessPurposeDraft = ref(session.accessPurpose)
const authBusy = ref(false)
const authMessage = ref('')
const authError = ref('')
const stepUpCode = ref('')
const pinDraft = ref('')
const households = ref<HouseholdOption[]>([])
const householdsLoading = ref(false)
const householdError = ref<ErrorPresentation | null>(null)
const householdMessage = ref('')

const currentHousehold = computed(
  () => households.value.find(item => item.id === session.currentHouseholdId) ?? null,
)
const needsHouseholdChoice = computed(
  () => households.value.length > 1 && !session.currentHouseholdId,
)

/** 读取服务端授权范围内的家庭列表；错误不暴露隐藏家庭是否存在。 */
async function loadHouseholds(): Promise<HouseholdOption[]> {
  householdsLoading.value = true
  householdError.value = null
  try {
    const options = await activeProvider().listHouseholds()
    households.value = options
    // 已选家庭不在列表里（被撤权、删除或授权变化）：回到安全选择态，不自动换一个。
    if (session.currentHouseholdId && !options.some(item => item.id === session.currentHouseholdId)) {
      clearHouseholdSelection()
      householdMessage.value = '之前选择的家庭已不可用，请重新选择；页面不会自动切到另一个家庭。'
    }
    return options
  } catch (cause) {
    households.value = []
    householdError.value = presentApiError(cause)
    throw cause
  } finally {
    householdsLoading.value = false
  }
}

async function onHouseholdChange(nextId: string): Promise<void> {
  if (!nextId || nextId === session.currentHouseholdId) return
  const label = households.value.find(item => item.id === nextId)?.name ?? nextId
  const confirmed = typeof window.confirm !== 'function'
    || window.confirm(`切换到「${label}」？当前家庭的成员、任务、风险、事件和上传草稿会被清除后重新加载。`)
  if (!confirmed) return

  householdMessage.value = ''
  // selectHousehold 走 updateSession，会触发上下文清理（Provider 缓存、上传草稿、当前成员）。
  selectHousehold(nextId)
  cancelStepUp()
  stepUpCode.value = ''
  // 旧家庭的能力快照不再适用；立即重探而不是留一个空状态让入口全禁用。
  clearCapabilities()
  await probeCapabilities()
  householdMessage.value = `已切换到「${label}」，旧家庭的查询、上传草稿和能力快照已清除。`
}
const serverAddressPlaceholder = DEFAULT_SERVER_URL_POLICY.allowPrivateHttp
  ? '例如 http://192.168.1.10:8000（受控 Debug 联调）'
  : '例如 https://family.example.test（发布构建仅 HTTPS）'
const serverAddressHelp = DEFAULT_SERVER_URL_POLICY.allowPrivateHttp
  ? '当前为开发/Android Debug 构建：明文 HTTP 仅允许家庭局域网或本机地址，公网仍须使用 HTTPS。'
  : '当前为发布构建：服务器必须使用 HTTPS；家庭局域网 HTTP 仅在受控 Debug 联调包开放。'

const usesRealAuth = computed(() => session.authMode === 'real')
const signedIn = computed(() => auth.status === 'authenticated')
const sessionExpiryLabel = computed(() => {
  if (!auth.expiresAt) return ''
  const time = Date.parse(auth.expiresAt)
  return Number.isFinite(time) ? new Date(time).toLocaleString() : ''
})

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
  updateSession({
    actorId: actorIdDraft.value,
    accessPurpose: accessPurposeDraft.value,
    currentMemberId: '',
  })
  connectionState.value = 'idle'
  connectionMessage.value = ''
  connectionError.value = null
  capabilityProbeError.value = null
  clearCapabilities()
}

function onAuthModeChange(mode: AuthMode): void {
  if (mode === 'dev-actor' && !devActorAllowed) return
  authMessage.value = ''
  authError.value = ''
  stepUpCode.value = ''
  cancelStepUp()
  // 切换身份来源等于换一套凭据；旧查询、上传和能力探测必须一起丢弃。
  updateSession({ authMode: mode, actorId: mode === 'dev-actor' ? actorIdDraft.value : '', currentMemberId: '' })
  connectionState.value = 'idle'
  connectionMessage.value = ''
  connectionError.value = null
  capabilityProbeError.value = null
  clearCapabilities()
}

/**
 * 当前用于二次确认的家庭。
 *
 * MOB-158：只使用用户显式选择的家庭；恰好一个家庭时自动选定以保持低步骤体验，
 * 可访问多个但未选择时 fail-closed，绝不再默认取列表第一个。
 */
async function resolveHouseholdId(): Promise<string> {
  if (session.currentHouseholdId) return session.currentHouseholdId
  const options = await loadHouseholds()
  if (options.length === 1) {
    selectHousehold(options[0]!.id)
    return options[0]!.id
  }
  throw new ApiClientError('当前身份可访问多个家庭，请先选择一个家庭', {
    status: 409,
    code: 'HOUSEHOLD_NOT_SELECTED',
  })
}

async function submitHouseholdPin(): Promise<void> {
  const pin = pinDraft.value.trim()
  if (!/^[0-9]{6}$/.test(pin)) {
    authError.value = '家庭 PIN 必须是 6 位数字。'
    return
  }
  authBusy.value = true
  authError.value = ''
  authMessage.value = ''
  try {
    const client = new ApiClient({
      baseUrl: session.serverBaseUrl,
      authSessionProvider: getAuthSession,
    })
    await client.setAccountPin(await resolveHouseholdId(), pin, {
      accessPurpose: session.accessPurpose || undefined,
    })
    authMessage.value = '家庭 PIN 已保存在家庭服务器（只存哈希）；本机不保留这个 PIN。'
  } catch (cause) {
    authError.value = presentApiError(cause).message
  } finally {
    // PIN 用完即弃，不留在输入框、store 或本机存储里。
    pinDraft.value = ''
    authBusy.value = false
  }
}

async function submitSignOut(): Promise<void> {
  authBusy.value = true
  authError.value = ''
  authMessage.value = ''
  try {
    // 本地会话先失效；随后通知服务端销毁会话。
    await signOut(currentAuthAdapter())
    households.value = []
    householdMessage.value = ''
    authMessage.value = '已退出登录，本机不再保留该会话的查询、上传和能力探测结果。'
    connectionState.value = 'idle'
    connectionMessage.value = ''
  } catch (cause) {
    authError.value = presentApiError(cause).message
  } finally {
    authBusy.value = false
  }
}

async function startStepUp(): Promise<void> {
  authBusy.value = true
  authError.value = ''
  authMessage.value = ''
  stepUpCode.value = ''
  try {
    const challenge = await beginStepUp(familyAuthAdapter(), {
      action: 'confirm_high_risk',
      method: 'pin',
      householdId: await resolveHouseholdId(),
    })
    authMessage.value = `已发起二次确认（${challenge.action}），请输入该家庭的 6 位 PIN。`
  } catch (cause) {
    authError.value = presentApiError(cause).message
  } finally {
    authBusy.value = false
  }
}

async function submitStepUp(): Promise<void> {
  authBusy.value = true
  authError.value = ''
  try {
    await confirmStepUp(familyAuthAdapter(), {
      action: 'confirm_high_risk',
      method: 'pin',
      code: stepUpCode.value.trim(),
    })
    authMessage.value = '二次确认已通过；该确认只能使用一次。'
  } catch (cause) {
    authError.value = presentApiError(cause).message
  } finally {
    // PIN 用完即弃，不写入 store、存储或日志。
    stepUpCode.value = ''
    authBusy.value = false
  }
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

function probeClient(): ApiClient {
  return new ApiClient({
    baseUrl: session.serverBaseUrl,
    // 正式鉴权模式下只用内存会话，未登录时不回退开发期身份头。
    ...(usesRealAuth.value ? { authSessionProvider: getAuthSession } : {}),
  })
}

function probeOptions() {
  return usesRealAuth.value
    ? { accessPurpose: session.accessPurpose || undefined }
    : { actorId: session.actorId || undefined, accessPurpose: session.accessPurpose || undefined }
}

/** 重探服务端能力；供测试连接与家庭切换共用。 */
async function probeCapabilities(): Promise<ReturnType<typeof setCapabilities> | null> {
  capabilityProbeError.value = null
  try {
    return setCapabilities(await probeClient().getCapabilities(probeOptions()))
  } catch (cause) {
    clearCapabilities()
    capabilityProbeError.value = presentApiError(cause)
    return null
  }
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
  try {
    const health = await probeClient().getHealth(probeOptions())
    const probe = await probeCapabilities()
    resumeAuthorizationBoundary()
    connectionState.value = 'ok'
    connectionMessage.value = `已连接：${health.service} ${health.version}${
      probe ? `，已探测 ${probe.available.length} 项可用能力` : '；能力探测未完成'
    }`
    // 连接可用后再读家庭列表：多家庭时要求显式选择，单家庭自动选定。
    await loadHouseholds().catch(() => undefined)
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

onMounted(() => {
  refreshTraceView()
  // 联机且已具备取数条件时预读家庭列表，让选择器一进页面就能用。
  if (session.dataMode !== 'live') return
  if (usesRealAuth.value && !signedIn.value) return
  if (!usesRealAuth.value && !session.actorId.trim()) return
  void loadHouseholds().catch(() => undefined)
})
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
        <p v-if="authorizationBoundary.status === 'reverification-required'" class="notice" data-tone="warn" role="alert">
          授权边界已失效。为保护隐私，成员、任务、风险、事件和视觉候选不会从本地恢复；请重新测试连接后再加载数据。
        </p>
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

        <fieldset v-if="devActorAllowed" class="mode-fieldset">
          <legend class="meta-line">身份来源</legend>
          <label class="mode-option">
            <input
              type="radio"
              name="auth-mode"
              value="real"
              :checked="session.authMode === 'real'"
              @change="onAuthModeChange('real')"
            />
            <span>
              <strong>正式登录（默认）</strong>
              <span class="meta-line">账号密码登录家庭服务器，使用短生命周期会话</span>
            </span>
          </label>
          <label class="mode-option">
            <input
              type="radio"
              name="auth-mode"
              value="dev-actor"
              :checked="session.authMode === 'dev-actor'"
              @change="onAuthModeChange('dev-actor')"
            />
            <span>
              <strong>开发期身份（仅本地联调）</strong>
              <span class="meta-line">直接发送 X-Actor-Id；仅在开启开发配置的构建里可选，不能用于生产</span>
            </span>
          </label>
        </fieldset>
        <p v-else class="meta-line">
          当前为正式构建：只能使用正式登录，开发期 X-Actor-Id 路径未启用。
        </p>

        <label v-if="session.authMode === 'dev-actor'" class="field">
          开发期身份（仅本地联调）
          <input v-model="actorIdDraft" type="text" placeholder="Actor ID" @change="persistConnectionSession" />
        </label>
        <label class="field">
          访问目的代码（X-Access-Purpose）
          <input v-model="accessPurposeDraft" type="text" placeholder="family-care" @change="persistConnectionSession" />
        </label>
        <p v-if="session.authMode === 'dev-actor' && !session.actorId.trim()" class="notice" data-tone="warn" role="status">
          请先填写开发身份；未配置身份时不会加载任何家庭或健康数据。
        </p>
        <p v-else-if="!session.accessPurpose.trim()" class="notice" data-tone="warn" role="status">
          请先填写访问目的代码；访问目的为空时不会加载任何家庭或健康数据。
        </p>
        <button
          type="button"
          class="btn btn-block"
          :disabled="connectionState === 'testing'
            || (session.authMode === 'dev-actor' && !session.actorId.trim())
            || !session.accessPurpose.trim()"
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

        <section class="household-panel" aria-labelledby="household-title">
          <div class="h-icon-row">
            <span class="row-icon" data-tone="info" aria-hidden="true"><AppIcon name="user" :size="16" /></span>
            <h3 id="household-title">当前家庭</h3>
          </div>

          <p v-if="householdsLoading" class="meta-line">正在读取可访问的家庭…</p>

          <template v-else-if="households.length">
            <p v-if="currentHousehold" class="meta-line">
              数据来源：{{ currentHousehold.name }}<template v-if="households.length > 1">（共 {{ households.length }} 个可访问家庭，可切换）</template>
            </p>
            <p v-if="needsHouseholdChoice" class="notice" data-tone="warn" role="alert">
              当前身份可以访问 {{ households.length }} 个家庭。请显式选择一个后再加载数据；应用不会替你选默认家庭。
            </p>
            <label v-if="households.length > 1" class="field">
              选择家庭
              <select
                :value="session.currentHouseholdId"
                :disabled="householdsLoading"
                @change="onHouseholdChange(($event.target as HTMLSelectElement).value)"
              >
                <option value="" disabled>请选择家庭</option>
                <option v-for="item in households" :key="item.id" :value="item.id">{{ item.name }}</option>
              </select>
            </label>
            <p v-else class="meta-line">当前身份只被授权访问这一个家庭；出现多个家庭时这里会要求显式选择。</p>
          </template>

          <p v-else-if="!householdError" class="meta-line">尚未读取家庭列表；测试连接后会自动读取。</p>

          <p v-if="householdMessage" class="notice" data-tone="info" role="status">{{ householdMessage }}</p>
          <ErrorNotice v-if="householdError" :error="householdError" @retry="loadHouseholds" />
          <p class="meta-line">
            选择家庭不等于获得权限：成员、字段、动作、目的和期限仍由家庭服务器逐次校验。本机只保存家庭标识，不保存家庭健康数据。
          </p>
        </section>

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

        <section v-if="usesRealAuth" class="auth-design-note" aria-labelledby="auth-session-title">
          <div class="h-icon-row">
            <span class="row-icon" data-tone="calm" aria-hidden="true"><AppIcon name="shield" :size="16" /></span>
            <h3 id="auth-session-title">正式登录与会话</h3>
          </div>

          <template v-if="signedIn">
            <p class="meta-line">当前身份：{{ auth.actorId }}</p>
            <p v-if="sessionExpiryLabel" class="meta-line">会话有效至：{{ sessionExpiryLabel }}</p>
            <button
              type="button"
              class="btn btn-quiet btn-block"
              :disabled="authBusy"
              @click="submitSignOut"
            >
              {{ authBusy ? '处理中…' : '退出登录' }}
            </button>

            <h4 class="step-up-title">高风险动作二次确认（PIN）</h4>
            <p class="meta-line">
              授权变更、删除等高风险动作需要用本家庭的 6 位 PIN 再确认一次。PIN 只保存在家庭服务器上（仅哈希），
              本机不保留，也不会写入日志或地址栏。
            </p>
            <label class="field">
              设置或更新家庭 PIN
              <input
                v-model="pinDraft"
                type="password"
                inputmode="numeric"
                autocomplete="new-password"
                maxlength="6"
                placeholder="6 位数字"
              />
            </label>
            <button
              type="button"
              class="btn btn-quiet btn-block"
              :disabled="authBusy || pinDraft.trim().length !== 6"
              @click="submitHouseholdPin"
            >
              保存家庭 PIN
            </button>
            <button
              type="button"
              class="btn btn-quiet btn-block"
              :disabled="authBusy"
              @click="startStepUp"
            >
              发起二次确认
            </button>
            <template v-if="auth.pendingStepUp">
              <label class="field">
                家庭 PIN
                <input
                  v-model="stepUpCode"
                  type="password"
                  inputmode="numeric"
                  autocomplete="one-time-code"
                  maxlength="6"
                  placeholder="本家庭的 6 位 PIN"
                />
              </label>
              <button
                type="button"
                class="btn btn-block"
                :disabled="authBusy || !stepUpCode.trim()"
                @click="submitStepUp"
              >
                提交二次确认
              </button>
            </template>
          </template>

          <template v-else>
            <p class="notice" data-tone="warn" role="status">
              尚未登录家庭服务器。为保护隐私，未登录状态下不会加载成员、任务、风险和事件，也不允许提交写操作。
            </p>
            <RouterLink class="btn btn-block" to="/login">前往登录</RouterLink>
          </template>

          <p v-if="authMessage" class="notice" data-tone="success" role="status">{{ authMessage }}</p>
          <p v-if="authError" class="notice" data-tone="error" role="alert">{{ authError }}</p>
          <ul class="divided-list">
            <li>会话凭据只保存在内存，不写 localStorage、URL、日志或通知。</li>
            <li>会话过期、被撤销或返回 401 时立即清理本地会话并阻断写入。</li>
            <li>退出登录或切换家庭/成员会清除查询结果、上传草稿和能力探测快照。</li>
          </ul>
        </section>

        <section v-else class="auth-design-note" aria-labelledby="auth-dev-title">
          <div class="h-icon-row">
            <span class="row-icon" data-tone="warn" aria-hidden="true"><AppIcon name="shield" :size="16" /></span>
            <h3 id="auth-dev-title">开发期身份（未使用正式鉴权）</h3>
          </div>
          <p class="notice" data-tone="warn" role="status">
            当前请求使用开发期 X-Actor-Id 头，仅供本地联调，不代表正式鉴权已接入；
            服务端在 APP_ENV=production 或关闭 ALLOW_DEV_ACTOR_HEADER 时会直接拒绝。
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

    <section class="card" aria-labelledby="trace-title">
      <div class="h-icon-row">
        <span class="row-icon" data-tone="info" aria-hidden="true"><AppIcon name="refresh" :size="16" /></span>
        <h2 id="trace-title">最近请求与回执</h2>
        <button type="button" class="btn btn-quiet" style="margin-left:auto" @click="refreshTraceView">刷新</button>
      </div>
      <p class="meta-line">
        本机诊断信息：只记录请求方法、路径（不含查询串）、结局、状态、服务端请求标识与时间，不包含健康正文，也不会上传；切换身份或退出登录后自动清空。
      </p>
      <p v-if="traceView.length === 0" class="meta-line" role="status">
        暂无记录；进行任何联机操作后点击“刷新”查看。
      </p>
      <ul v-else class="divided-list">
        <li v-for="entry in traceView" :key="entry.seq">
          <div class="card-title-row">
            <strong>{{ entry.method }} {{ entry.path }}</strong>
            <span class="tag" :data-tone="entry.outcome === 'success' ? 'calm' : entry.outcome === 'client-error' ? 'warn' : 'danger'">
              {{ requestOutcomeLabel(entry.outcome) }}{{ entry.status !== null ? `（${entry.status}）` : '' }}
            </span>
          </div>
          <span class="meta-line">请求标识：{{ entry.requestId ?? '回执信息不可用（服务端未返回请求 ID）' }}</span>
          <span class="meta-line">时间：{{ formatTraceTime(entry.at) }}</span>
          <span v-if="entry.idempotencyKey" class="meta-line">幂等键：{{ entry.idempotencyKey }}（同一键多次出现表示重试，服务端只落一条）</span>
          <span v-if="entry.receiptId" class="meta-line">回执对象：{{ entry.receiptId }}</span>
        </li>
      </ul>
    </section>

    <section class="card" aria-labelledby="about-title">
      <div class="h-icon-row">
        <span class="row-icon" data-tone="accent" aria-hidden="true"><AppIcon name="heart" :size="16" /></span>
        <h2 id="about-title">关于</h2>
      </div>
      <p class="meta-line">家健镜随身版 {{ buildInfoLine() }} · 教学演示，不用于诊断或治疗</p>
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
.step-up-title { margin: 6px 0 0; font-size: 0.94rem; }
.household-panel {
  display: grid;
  gap: 10px;
  margin-top: 18px;
  padding-top: 18px;
  border-top: 1px solid var(--line);
}
.household-panel h3 { margin: 0; font-size: 1rem; }
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
