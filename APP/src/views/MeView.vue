<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { Capacitor } from '@capacitor/core'
import AppIcon from '@/components/AppIcon.vue'
import SwitchRow from '@/components/SwitchRow.vue'
import ErrorNotice from '@/components/ErrorNotice.vue'
import ListLoadingState from '@/components/ListLoadingState.vue'
import { ApiClient, ApiClientError } from '@/api/client'
import { presentApiError, presentListApiError, type ErrorPresentation } from '@/api/errors'
import { clearLocalData, localDataInventory } from '@/stores/localData'
import { resetDemoData } from '@/data/demoProvider'
import { activeProvider, clearHouseholdSelection, selectHousehold } from '@/data'
import type { HouseholdOption } from '@/data/types'
import { currentAuthAdapter, familyAuthAdapter } from '@/data/authAdapter'
import { useA11y } from '@/stores/accessibility'
import {
  canPromptInstall,
  dismissInstallEntry,
  installDismissed,
  recoverShellCaches,
  serviceWorkerSupported,
  triggerInstallPrompt,
} from '@/stores/pwa'
import { useCapabilities } from '@/stores/capabilities'
import { getAuthSession, useAuth } from '@/stores/auth'
import { resetSession, useAuthorizationBoundary, useSession, type MobileRole } from '@/stores/session'
import { tapFeedback } from '@/utils/haptics'
import { normalizePhoneNumber } from '@/utils/phone'
import { DEFAULT_SERVER_URL_POLICY, validateServerBaseUrl } from '@/utils/serverUrl'

const { settings, setElderMode } = useA11y()
const { session, updateSession } = useSession()
const { auth, signOut, beginStepUp, confirmStepUp, cancelStepUp } = useAuth()
const { authorizationBoundary, resumeAuthorizationBoundary } = useAuthorizationBoundary()
const { setCapabilities, clearCapabilities } = useCapabilities()

const isNativeApp = Capacitor.isNativePlatform()
const connectionState = ref<'idle' | 'testing' | 'ok' | 'failed'>('idle')
const connectionMessage = ref('')
const connectionError = ref<ErrorPresentation | null>(null)

/** MOB-146：本地数据管理。 */
const localDataItems = localDataInventory()
const savedLocalDataItems = localDataItems.filter(item => item.saved)
const clearArmed = ref(false)
const clearResult = ref<{ ok: boolean; failures: string[]; cleared: string[] } | null>(null)
let clearArmTimer: ReturnType<typeof setTimeout> | null = null

function armClearLocalData(): void {
  if (!clearArmed.value) {
    clearArmed.value = true
    clearResult.value = null
    if (clearArmTimer) clearTimeout(clearArmTimer)
    clearArmTimer = setTimeout(() => { clearArmed.value = false }, 4000)
    return
  }
  if (clearArmTimer) clearTimeout(clearArmTimer)
  clearArmed.value = false
  // 先重置内存态（resetSession 会把默认值持久化），再清理存储键，
  // 保证清理后两个设置键确实消失、可验证。
  resetSession()
  clearCapabilities()
  void signOut(null)
  const result = clearLocalData()
  clearResult.value = result
}

const demoResetMessage = ref('')
/** MOB-151：安装入口与外壳缓存恢复（只清 shell 前缀缓存，不碰任何健康数据）。 */
const installPromptAvailable = ref(false)
const installMessage = ref('')
const recoveryArmed = ref(false)
const recoveryMessage = ref('')
let recoveryArmTimer: ReturnType<typeof setTimeout> | null = null

function refreshInstallAvailability(): void {
  installPromptAvailable.value = canPromptInstall()
}

async function onInstallClick(): Promise<void> {
  const outcome = await triggerInstallPrompt()
  installMessage.value = outcome === 'prompted'
    ? '安装已开始'
    : '请使用浏览器菜单安装应用'
  refreshInstallAvailability()
}

function onDismissInstall(): void {
  dismissInstallEntry()
  installMessage.value = ''
}

async function onRecoverShellClick(): Promise<void> {
  if (!recoveryArmed.value) {
    recoveryArmed.value = true
    recoveryMessage.value = '再次点击确认清理缓存。'
    if (recoveryArmTimer) clearTimeout(recoveryArmTimer)
    recoveryArmTimer = setTimeout(() => {
      recoveryArmed.value = false
    }, 6000)
    return
  }
  if (recoveryArmTimer) clearTimeout(recoveryArmTimer)
  recoveryArmed.value = false
  recoveryMessage.value = ''
  try {
    const removed = await recoverShellCaches(caches)
    recoveryMessage.value = `已清理 ${removed.length} 个外壳缓存，正在刷新以加载受控版本…`
  } catch {
    recoveryMessage.value = '清理外壳缓存失败；请检查浏览器存储权限后重试。'
    return
  }
  setTimeout(() => window.location.reload(), 400)
}

onMounted(() => {
  refreshInstallAvailability()
  window.addEventListener('beforeinstallprompt', refreshInstallAvailability)
})
const caregiverNameDraft = ref(session.caregiverName)
const caregiverPhoneDraft = ref(session.caregiverPhone)
const contactError = ref('')
const contactCallMessage = ref('')
const serverBaseUrlDraft = ref(session.serverBaseUrl)
const serverAddressError = ref('')
const authBusy = ref(false)
const authMessage = ref('')
const authError = ref('')
const stepUpCode = ref('')
const pinDraft = ref('')
const households = ref<HouseholdOption[]>([])
const householdsLoading = ref(false)
const householdError = ref<ErrorPresentation | null>(null)
const householdMessage = ref('')
let householdsLoadInFlight = false

const currentHousehold = computed(
  () => households.value.find(item => item.id === session.currentHouseholdId) ?? null,
)

/** 读取服务端授权范围内的家庭列表；错误不暴露隐藏家庭是否存在。 */
async function loadHouseholds(): Promise<HouseholdOption[]> {
  if (householdsLoadInFlight) return households.value
  householdsLoadInFlight = true
  householdsLoading.value = true
  householdError.value = null
  try {
    const options = await activeProvider().listHouseholds()
    households.value = options
    syncMobileRole(options)
    // 已选家庭不在列表里（被撤权、删除或授权变化）：清除选择回到安全态，不自动换一个，
    // 并把确切原因告诉用户 —— 守卫刻意保留了这个失效选择，就是为了能在这里解释。
    if (session.currentHouseholdId && !options.some(item => item.id === session.currentHouseholdId)) {
      clearHouseholdSelection()
      householdMessage.value = '当前家庭不可用，已清除选择。'
    }
    return options
  } catch (cause) {
    households.value = []
    householdError.value = presentListApiError(cause)
    throw cause
  } finally {
    householdsLoading.value = false
    householdsLoadInFlight = false
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
  syncMobileRole(households.value)
  cancelStepUp()
  stepUpCode.value = ''
  // 旧家庭的能力快照不再适用；立即重探而不是留一个空状态让入口全禁用。
  clearCapabilities()
  await probeCapabilities()
  householdMessage.value = `已切换到「${label}」`
}
const serverAddressPlaceholder = DEFAULT_SERVER_URL_POLICY.allowPrivateHttp
  ? '例如 http://192.168.1.10:8000'
  : '例如 https://family.example.test'
const serverAddressHelp = DEFAULT_SERVER_URL_POLICY.allowPrivateHttp
  ? '请输入家庭服务器地址。'
  : '请输入 HTTPS 家庭服务器地址。'

const usesRealAuth = computed(() => session.authMode === 'real')
const signedIn = computed(() => auth.status === 'authenticated')
const isMemberMode = computed(() => session.mobileRole === 'member')

const detectedMobileRole = computed<MobileRole | null>(() => {
  if (session.dataMode !== 'live') return null
  const actorId = (usesRealAuth.value ? auth.actorId : session.actorId).trim()
  if (!actorId) return null
  const household = households.value.find(item => item.id === session.currentHouseholdId)
    ?? (households.value.length === 1 ? households.value[0] : null)
  if (!household?.createdBy) return null
  return household.createdBy === actorId ? 'admin' : 'member'
})
const mobileRoleMessage = ref('')

function syncMobileRole(options: HouseholdOption[]): void {
  if (session.dataMode !== 'live') return
  const actorId = (usesRealAuth.value ? auth.actorId : session.actorId).trim()
  const household = options.find(item => item.id === session.currentHouseholdId)
    ?? (options.length === 1 ? options[0] : null)
  if (!actorId || !household?.createdBy) return
  const role: MobileRole = household.createdBy === actorId ? 'admin' : 'member'
  if (session.mobileRole !== role) updateSession({ mobileRole: role, currentMemberId: '' })
  mobileRoleMessage.value = `已按服务器身份识别为${role === 'admin' ? '家庭管理员' : '家庭成员'}端。`
}

function onMobileRoleChange(role: MobileRole): void {
  if (detectedMobileRole.value) return
  updateSession({ mobileRole: role, currentMemberId: '' })
  mobileRoleMessage.value = role === 'member'
    ? '已切换为家庭成员端：只显示自己的今日安排、拍药盒、求助和基础设置。'
    : '已切换为家庭管理员端：恢复完整家庭照护入口。'
}

function onElderModeChange(enabled: boolean): void {
  setElderMode(enabled)
  tapFeedback([12, 60, 18])
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

function contactCaregiver(): void {
  const phone = normalizePhoneNumber(caregiverPhoneDraft.value)
  if (!phone) {
    contactError.value = '请先保存一个有效的联系人号码。'
    return
  }
  contactError.value = ''
  contactCallMessage.value = '正在拨号'
  tapFeedback([12, 60, 18])
  window.location.href = `tel:${phone}`
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
    authMessage.value = '已退出登录'
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
  clearCapabilities()
}

function onModeChange(mode: 'demo' | 'live'): void {
  updateSession({ dataMode: mode, currentMemberId: '' })
  connectionState.value = 'idle'
  connectionMessage.value = ''
  connectionError.value = null
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
  try {
    return setCapabilities(await probeClient().getCapabilities(probeOptions()))
  } catch (cause) {
    clearCapabilities()
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
  clearCapabilities()
  try {
    await probeClient().getHealth(probeOptions())
    const probe = await probeCapabilities()
    resumeAuthorizationBoundary()
    connectionState.value = 'ok'
    connectionMessage.value = probe ? '已连接' : '部分功能暂不可用'
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
  demoResetMessage.value = '已恢复默认数据。'
}

onMounted(() => {
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
        :model-value="settings.elderMode"
        @update:model-value="onElderModeChange"
      />
    </section>

    <section class="card" aria-labelledby="mobile-role-title">
      <div class="card-title-row">
        <h2 id="mobile-role-title">手机端身份</h2>
        <span class="tag" :data-tone="isMemberMode ? 'info' : 'calm'">
          {{ isMemberMode ? '家庭成员' : '家庭管理员' }}
        </span>
      </div>
      <fieldset class="mode-fieldset">
        <legend class="visually-hidden-title">手机端身份</legend>
        <label class="mode-option">
          <input
            type="radio"
            name="mobile-role"
            value="admin"
            :checked="session.mobileRole === 'admin'"
            :disabled="Boolean(detectedMobileRole)"
            @change="onMobileRoleChange('admin')"
          />
          <span>
            <strong>家庭管理员</strong>
          </span>
        </label>
        <label class="mode-option">
          <input
            type="radio"
            name="mobile-role"
            value="member"
            :checked="session.mobileRole === 'member'"
            :disabled="Boolean(detectedMobileRole)"
            @change="onMobileRoleChange('member')"
          />
          <span>
            <strong>家庭成员</strong>
          </span>
        </label>
      </fieldset>
      <p v-if="!detectedMobileRole && mobileRoleMessage" class="notice" data-tone="success" role="status">
        {{ mobileRoleMessage }}
      </p>
    </section>

    <RouterLink class="card link-card" to="/me/accessibility">
      <AppIcon name="settings" :size="22" />
      <span class="link-card-text">
        <strong>无障碍设置</strong>
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
          placeholder="请输入联系人电话"
          :aria-invalid="Boolean(contactError)"
          :aria-describedby="contactError ? 'contact-help contact-error' : 'contact-help'"
          @change="persistContact"
        />
      </label>
      <span id="contact-help" class="visually-hidden">联系人电话</span>
      <p v-if="contactError" id="contact-error" class="notice" data-tone="error" role="alert">{{ contactError }}</p>
      <p v-if="contactCallMessage" class="notice" data-tone="info" role="status">{{ contactCallMessage }}</p>
      <button
        v-if="normalizePhoneNumber(caregiverPhoneDraft)"
        type="button"
        class="btn btn-quiet btn-block"
        @click="contactCaregiver"
      >
        拨打电话
      </button>
    </section>

    <section v-if="!isNativeApp" class="card" aria-labelledby="pwa-title">
      <div class="h-icon-row">
        <span class="row-icon" data-tone="info" aria-hidden="true"><AppIcon name="shield" :size="16" /></span>
        <h2 id="pwa-title">应用安装</h2>
      </div>
      <template v-if="serviceWorkerSupported()">
        <div v-if="!installDismissed" class="pwa-install-row">
          <button type="button" :disabled="!installPromptAvailable" @click="onInstallClick">
            {{ installPromptAvailable ? '安装到主屏幕' : '安装入口待系统就绪' }}
          </button>
          <button type="button" class="secondary" @click="onDismissInstall">不再提示</button>
        </div>
        <p v-if="!installDismissed && !installPromptAvailable" class="meta-line">
          请使用浏览器菜单中的“安装应用 / 添加到主屏幕”。
        </p>
        <p v-if="installMessage" class="notice" data-tone="info" role="status">{{ installMessage }}</p>
        <div class="pwa-recovery-row">
          <button type="button" :class="['recovery-button', { armed: recoveryArmed }]" @click="onRecoverShellClick">
            {{ recoveryArmed ? '确认清理并刷新' : '清理离线外壳缓存' }}
          </button>
        </div>
        <p class="meta-line">
          清理应用缓存
        </p>
        <p v-if="recoveryMessage" class="notice" :data-tone="recoveryMessage.includes('失败') ? 'error' : 'info'" role="status">
          {{ recoveryMessage }}
        </p>
      </template>
    </section>

    <section class="card" aria-labelledby="source-title">
      <div class="h-icon-row">
        <span class="row-icon" data-tone="info" aria-hidden="true"><AppIcon name="refresh" :size="16" /></span>
        <h2 id="source-title">数据来源</h2>
      </div>
      <fieldset class="mode-fieldset">
        <legend class="visually-hidden-title">数据来源</legend>
        <label class="mode-option">
          <input
            type="radio"
            name="data-mode"
            value="demo"
            :checked="session.dataMode === 'demo'"
            @change="onModeChange('demo')"
          />
          <span>
            <strong>本地数据</strong>
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
            <strong>家庭服务器</strong>
          </span>
        </label>
      </fieldset>

            <template v-if="session.dataMode === 'live'">
        <p v-if="authorizationBoundary.status === 'reverification-required'" class="notice" data-tone="warn" role="alert">
          请重新连接服务器。
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
            <small id="server-address-help">{{ serverAddressHelp }}</small>
        </label>
        <p v-if="serverAddressError" id="server-address-error" class="notice" data-tone="error" role="alert">{{ serverAddressError }}</p>

        <button
          type="button"
          class="btn btn-block"
          :disabled="connectionState === 'testing'"
          @click="testConnection"
        >
          {{ connectionState === 'testing' ? '连接中…' : '连接服务器' }}
        </button>
        <p
          v-if="connectionMessage"
          class="notice"
          :data-tone="connectionState === 'ok' ? 'success' : 'error'"
          role="status"
        >
          {{ connectionMessage }}
        </p>
        <ErrorNotice v-if="connectionError" :error="connectionError" :busy="connectionState === 'testing'" @retry="testConnection" />

        <section class="household-panel" aria-labelledby="household-title">
          <div class="h-icon-row">
            <span class="row-icon" data-tone="info" aria-hidden="true"><AppIcon name="user" :size="16" /></span>
            <h3 id="household-title">当前家庭</h3>
          </div>

          <ListLoadingState v-if="householdsLoading" label="正在读取可访问的家庭…" :count="2" :disc="false" />

          <template v-else-if="households.length">
            <p v-if="currentHousehold" class="meta-line">
              {{ currentHousehold.name }}
            </p>
            <label v-if="households.length > 1" class="field">
              家庭
              <select
                :value="session.currentHouseholdId"
                :disabled="householdsLoading"
                @change="onHouseholdChange(($event.target as HTMLSelectElement).value)"
              >
                <option value="" disabled>请选择家庭</option>
                <option v-for="item in households" :key="item.id" :value="item.id">{{ item.name }}</option>
              </select>
            </label>
          </template>

          <p v-else-if="!householdError" class="meta-line">暂无家庭</p>

          <p v-if="householdMessage" class="notice" data-tone="info" role="status">{{ householdMessage }}</p>
          <ErrorNotice v-if="householdError" :error="householdError" :busy="householdsLoading" @retry="loadHouseholds" />
        </section>

        <section v-if="usesRealAuth" class="auth-design-note" aria-labelledby="auth-session-title">
          <div class="h-icon-row">
            <span class="row-icon" data-tone="calm" aria-hidden="true"><AppIcon name="shield" :size="16" /></span>
            <h3 id="auth-session-title">账户</h3>
          </div>

          <template v-if="signedIn">
            <button
              type="button"
              class="btn btn-quiet btn-block"
              :disabled="authBusy"
              @click="submitSignOut"
            >
              {{ authBusy ? '处理中…' : '退出登录' }}
            </button>

            <template v-if="!isMemberMode">
            <h4 class="step-up-title">家庭 PIN</h4>
            <label class="field">
              设置 PIN
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
              保存 PIN
            </button>
            <button
              type="button"
              class="btn btn-quiet btn-block"
              :disabled="authBusy"
              @click="startStepUp"
            >
              验证 PIN
            </button>
            <template v-if="auth.pendingStepUp">
              <label class="field">
                PIN
                <input
                  v-model="stepUpCode"
                  type="password"
                  inputmode="numeric"
                  autocomplete="one-time-code"
                  maxlength="6"
                  placeholder="6 位数字"
                />
              </label>
              <button
                type="button"
                class="btn btn-block"
                :disabled="authBusy || !stepUpCode.trim()"
                @click="submitStepUp"
              >
                提交
              </button>
            </template>
            </template>
            <p v-else class="notice" data-tone="info" role="status">
              管理员功能
            </p>
          </template>

          <template v-else>
            <p class="notice" data-tone="warn" role="status">
              未登录
            </p>
            <RouterLink class="btn btn-block" to="/login">登录</RouterLink>
          </template>

          <p v-if="authMessage" class="notice" data-tone="success" role="status">{{ authMessage }}</p>
          <p v-if="authError" class="notice" data-tone="error" role="alert">{{ authError }}</p>
        </section>
      </template>

      <template v-else>
        <button type="button" class="btn btn-quiet btn-block" @click="restoreDemoData">恢复默认数据</button>
        <p v-if="demoResetMessage" class="notice" data-tone="success" role="status">{{ demoResetMessage }}</p>
      </template>
    </section>

    <section class="card" aria-labelledby="local-data-title">
      <div class="h-icon-row">
        <span class="row-icon" data-tone="calm" aria-hidden="true"><AppIcon name="shield" :size="16" /></span>
        <h2 id="local-data-title">本地数据管理</h2>
      </div>
      <ul class="divided-list">
        <li v-for="item in savedLocalDataItems" :key="item.key">
          <div class="card-title-row">
            <strong>{{ item.label }}</strong>
            <span class="tag" data-tone="info">本机保存</span>
          </div>
        </li>
      </ul>
      <button
        type="button"
        class="btn btn-quiet btn-block"
        :data-tone="clearArmed ? 'danger' : undefined"
        @click="armClearLocalData"
      >
        {{ clearArmed ? '再次点击确认' : '清除本地设置' }}
      </button>
      <p v-if="clearResult && clearResult.ok" class="notice" data-tone="success" role="status">
        已清除：{{ clearResult.cleared.join('、') }}
      </p>
      <p v-else-if="clearResult && !clearResult.ok" class="notice" data-tone="error" role="alert">
        清理未完成，不声称已删除：{{ clearResult.failures.join('；') }}。请检查浏览器存储设置（隐私模式可能禁用存储）后重试。
      </p>
    </section>

    <section class="card" aria-labelledby="privacy-title">
      <div class="h-icon-row">
        <span class="row-icon" data-tone="calm" aria-hidden="true"><AppIcon name="shield" :size="16" /></span>
        <h2 id="privacy-title">隐私与边界</h2>
      </div>
      <RouterLink class="btn btn-quiet btn-block" to="/me/privacy">
        <AppIcon name="shield" :size="18" />
        隐私设置
      </RouterLink>
    </section>

    <section class="card" aria-labelledby="about-title">
      <div class="h-icon-row">
        <span class="row-icon" data-tone="accent" aria-hidden="true"><AppIcon name="heart" :size="16" /></span>
        <h2 id="about-title">关于</h2>
      </div>
      <p class="meta-line">家健镜随身版</p>
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

.pwa-install-row,
.pwa-recovery-row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin: 10px 0 4px;
}

.pwa-install-row button,
.pwa-recovery-row .recovery-button {
  border: 1px solid #2f6d5a;
  background: #2f6d5a;
  color: #fff;
  border-radius: 10px;
  padding: 8px 14px;
  font-size: 0.9rem;
}

.pwa-install-row button.secondary {
  background: transparent;
  color: #2f6d5a;
}

.pwa-install-row button:disabled {
  opacity: 0.55;
}

.pwa-recovery-row .recovery-button.armed {
  background: #b3541e;
  border-color: #b3541e;
}

.onboarding-card {
  display: grid;
  gap: 10px;
}

.onboarding-steps {
  display: grid;
  gap: 10px;
  margin: 0;
  padding: 0;
  list-style: none;
  counter-reset: none;
}

.onboarding-step {
  display: grid;
  gap: 4px;
  padding: 10px 12px;
  border-radius: 12px;
  border-left: 4px solid var(--c-line-strong);
  background: var(--c-surface-solid);
}

.onboarding-step[data-status='current'] { border-left-color: var(--c-brand); }
.onboarding-step[data-status='blocked'] { border-left-color: var(--c-warn-deep); }
.onboarding-step[data-status='done'] { border-left-color: var(--c-calm-deep); }

.onboarding-step-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 8px;
  margin: 0;
}

.onboarding-step-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 24px;
  min-height: 24px;
  border-radius: 50%;
  background: var(--c-brand-softer);
  color: var(--c-brand-deep);
  font-size: 0.8rem;
  font-weight: 800;
}

.onboarding-step-status {
  color: var(--c-ink-soft);
  font-size: 0.8rem;
  font-weight: 700;
}

.onboarding-step-detail,
.onboarding-step-next {
  margin: 0;
  color: var(--c-ink-soft);
  font-size: 0.86rem;
  line-height: 1.55;
  overflow-wrap: anywhere;
}

.onboarding-step-next { color: var(--c-brand-strong); font-weight: 700; }

.onboarding-recheck {
  align-items: center;
  display: inline-flex;
  gap: 6px;
  justify-self: start;
  min-height: var(--tap);
}
</style>
