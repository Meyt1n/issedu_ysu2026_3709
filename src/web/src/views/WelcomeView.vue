<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'

import welcomeHero from '../assets/welcome-hero.jpg'
import { apiClient } from '../api/client'
import type { Household } from '../api/types'
import AppIcon from '../components/AppIcon.vue'
import FaceVideoCapture from '../components/FaceVideoCapture.vue'
import {
  connectWithFamilyFace,
  connectWithPin,
  connectWithPassword,
  createHouseholdAndEnter,
  formatError,
  getBoundFaceHouseholdId,
  getBoundFaceHouseholdName,
  portalWelcomeMessage,
  pushToast,
  recoverPasswordWithPin,
  refreshCapabilities,
  session,
} from '../store'
import {
  activePortalEntryMode,
  crossPortalPortsHint,
  crossPortalUrl,
  MEMBER_PORTAL_ENTRY_STEPS,
  portalEntryBranding,
  portalEntryConflictNotice,
} from '../ui/portalEntry'
import { THEMES, applyTheme, currentTheme } from '../ui/themes'
import { faceBindingSummary } from '../ui/welcomeFaceBinding'

const artRx = ref('0deg')
const artRy = ref('0deg')

function onStageMove(event: PointerEvent): void {
  const target = event.currentTarget as HTMLElement
  const rect = target.getBoundingClientRect()
  artRy.value = `${(((event.clientX - rect.left) / rect.width - 0.5) * 5).toFixed(2)}deg`
  artRx.value = `${((0.5 - (event.clientY - rect.top) / rect.height) * 5).toFixed(2)}deg`
}

function onStageLeave(): void {
  artRx.value = '0deg'
  artRy.value = '0deg'
}

const actorId = ref(session.actorId)
const accessPurpose = ref(session.accessPurpose || 'family-care')
const password = ref('')
const initialBoundFaceHouseholdId = getBoundFaceHouseholdId()
const householdId = ref(initialBoundFaceHouseholdId)
const boundFaceHouseholdName = ref(getBoundFaceHouseholdName())
const pin = ref('')
const faceFrames = ref<File[]>([])
// HCT-453：成员前台 / 管理后台分端口入口。auto 表示裸开发入口，
// 保持原欢迎页；member/admin 使用各自品牌文案与凭据默认值。
const entryMode = activePortalEntryMode()
const entryBranding = portalEntryBranding(entryMode)

const credentialMode = ref<'password' | 'pin' | 'face'>(
  entryBranding
    ? initialBoundFaceHouseholdId && entryBranding.credentialOrder[0] === 'face'
      ? 'face'
      : entryBranding.defaultCredential
    : initialBoundFaceHouseholdId
      ? 'face'
      : 'password',
)

const CREDENTIAL_LABELS: Record<'face' | 'password' | 'pin', string> = {
  face: '刷脸进入',
  password: '账号密码',
  pin: '数字密码',
}
// 正式账号密码、人脸和数字密码都走同一套正式会话；成员前台默认展示全部可用方式。
const credentialTabs = computed(() =>
  (entryBranding?.credentialOrder ?? (['face', 'password', 'pin'] as const))
    .filter(mode => !(entryBranding?.passwordBehindOtherWays && mode === 'password'))
    .map(mode => ({
      mode,
      label: CREDENTIAL_LABELS[mode],
    })),
)

const passwordBehindOtherWays = computed(() => entryBranding?.passwordBehindOtherWays ?? false)

function useOtherWaysPassword(): void {
  faceFrames.value = []
  localError.value = ''
  registerMode.value = false
  credentialMode.value = 'password'
}

function backToPrimaryCredentials(): void {
  faceFrames.value = []
  localError.value = ''
  registerMode.value = false
  credentialMode.value = entryBranding?.defaultCredential ?? 'pin'
}

const submitLabel = computed(() => {
  if (connecting.value) return '正在进入…'
  if (credentialMode.value === 'password' && registerMode.value) return '注册并登录'
  if (entryBranding) return entryBranding.ctaLabel
  return credentialMode.value === 'pin' ? '用数字密码进入' : '登录'
})

const crossEntryLink = computed(() => {
  if (!entryBranding?.crossLinkTarget) return null
  return {
    label: entryBranding.crossLinkLabel,
    target: entryBranding.crossLinkTarget,
    url: crossPortalUrl(entryBranding.crossLinkTarget),
  }
})

const entryConflictNotice = computed(() =>
  session.entryConflict ? portalEntryConflictNotice(session.entryConflict) : null,
)
const entryConflictUrl = computed(() =>
  entryConflictNotice.value ? crossPortalUrl(entryConflictNotice.value.crossLinkTarget) : '',
)
const registerMode = ref(false)
const recoveryMode = ref(false)
const recoveryHouseholdId = ref('')
const recoveryPin = ref('')
const recoveryNewPassword = ref('')
const recoveryConfirmPassword = ref('')
const recovering = ref(false)
const connecting = ref(false)
const creating = ref(false)
const createError = ref('')
const localError = ref('')
const loginHouseholds = ref<Household[]>([])
const householdsLoading = ref(false)
const householdsError = ref('')
const pinIdentityPreview = ref('')
let householdsRequest: AbortController | null = null
let householdsTimer: ReturnType<typeof setTimeout> | null = null
let pinPreviewRequest: AbortController | null = null

const householdDraft = reactive({
  name: '',
  members: [
    { displayName: '', actorId: session.actorId, role: 'SELF' as const },
    { displayName: '', actorId: '', role: 'DEPENDENT' as const },
  ],
})

const showCreateForm = computed(() => session.status === 'empty')
const accessPurposeValid = computed(() => /^[a-z][a-z0-9-]{1,63}$/.test(accessPurpose.value.trim()))
const faceBindingReady = computed(() => householdId.value.trim().length > 0)
const faceBinding = computed(() =>
  faceBindingSummary(credentialMode.value, householdId.value, boundFaceHouseholdName.value),
)
const faceCapabilityChecking = ref(false)
const faceCapabilityProbeFailed = ref(false)
const faceModelsReady = computed(
  () => session.capabilities?.available?.includes('face-recognition-local') ?? false,
)
const canConnect = computed(
  () => actorId.value.trim().length > 0 && accessPurposeValid.value && !connecting.value,
)
const canCreate = computed(
  () =>
    householdDraft.name.trim().length > 0 &&
    householdDraft.members.some(member => member.displayName.trim().length > 0) &&
    householdDraft.members
      .filter(member => member.displayName.trim().length > 0)
      .every(member => /^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$/.test(member.actorId.trim())) &&
    new Set(
      householdDraft.members
        .filter(member => member.displayName.trim().length > 0)
        .map(member => member.actorId.trim()),
    ).size === householdDraft.members.filter(member => member.displayName.trim().length > 0).length &&
    !creating.value,
)

watch(
  [actorId, accessPurpose, credentialMode],
  ([nextActorId, nextAccessPurpose, nextCredentialMode]) => {
    if (householdsTimer) clearTimeout(householdsTimer)
    householdsRequest?.abort()
    householdsRequest = null
    loginHouseholds.value = []
    householdId.value = nextCredentialMode === 'face' ? getBoundFaceHouseholdId() : ''
    boundFaceHouseholdName.value = nextCredentialMode === 'face' ? getBoundFaceHouseholdName() : ''
    householdsLoading.value = false
    householdsError.value = ''
    localError.value = ''
    pinIdentityPreview.value = ''

    // 人脸 tab 的绑定状态由 faceBinding 卡片展示；这里只为 PIN 登录加载家庭列表。
    if (nextCredentialMode !== 'pin') return
    const actor = nextActorId.trim()
    const purpose = nextAccessPurpose.trim()
    if (!actor || !purpose || !accessPurposeValid.value) return

    householdsTimer = setTimeout(async () => {
      householdsTimer = null
      const controller = new AbortController()
      householdsRequest = controller
      householdsLoading.value = true
      try {
        const households = await apiClient.listHouseholds({
          actorId: actor,
          accessPurpose: purpose,
          signal: controller.signal,
        })
        if (controller.signal.aborted) return
        loginHouseholds.value = households
        if (households.length > 0 && !households.some(item => item.id === householdId.value)) {
          householdId.value = households[0]!.id
        }
      } catch (cause) {
        if (!controller.signal.aborted) householdsError.value = formatError(cause)
      } finally {
        if (!controller.signal.aborted) householdsLoading.value = false
      }
    }, 300)
  },
)

watch(
  () => [credentialMode.value, householdId.value, actorId.value, accessPurpose.value] as const,
  ([mode, nextHouseholdId, nextActorId, nextPurpose]) => {
    pinPreviewRequest?.abort()
    pinPreviewRequest = null
    pinIdentityPreview.value = ''
    if (mode !== 'pin' || !nextHouseholdId.trim() || !nextActorId.trim()) return
    if (!/^[a-z][a-z0-9-]{1,63}$/.test(nextPurpose.trim())) return
    const previewController = new AbortController()
    pinPreviewRequest = previewController
    void apiClient.listMembers(nextHouseholdId.trim(), {
      actorId: nextActorId.trim(),
      accessPurpose: nextPurpose.trim(),
      signal: previewController.signal,
    }).then(members => {
      if (previewController.signal.aborted) return
      const self = members.find(member => member.actor_id === nextActorId.trim())
      pinIdentityPreview.value = self?.display_name ?? ''
    }).catch(() => {
      if (!previewController.signal.aborted) pinIdentityPreview.value = ''
    })
  },
)

async function probeFaceCapability(): Promise<void> {
  if (faceCapabilityChecking.value) return
  faceCapabilityChecking.value = true
  faceCapabilityProbeFailed.value = false
  try {
    // 人脸 tab 依赖 /meta/capabilities 判断模型是否就绪；登录前也需要预取。
    // 探测失败和“家庭没有录入人脸”是两件事，页面必须分开表达。
    await refreshCapabilities()
    faceCapabilityProbeFailed.value = !session.capabilities
  } finally {
    faceCapabilityChecking.value = false
  }
}

onMounted(() => {
  if (!session.capabilities) void probeFaceCapability()
})

watch(credentialMode, mode => {
  // 页面刚打开时能力请求可能还没返回；切到人脸 tab 时补一次探测，
  // 避免短暂的 null 被当成“人脸不可用”并把采集组件藏掉。
  if (mode === 'face' && !session.capabilities) void probeFaceCapability()
})

onBeforeUnmount(() => {
  householdsRequest?.abort()
  pinPreviewRequest?.abort()
  if (householdsTimer) clearTimeout(householdsTimer)
})

function announcePortalEntry(): void {
  if (session.status !== 'ready') return
  pushToast('success', portalWelcomeMessage())
}

async function submitSession(): Promise<void> {
  localError.value = ''
  if (!accessPurposeValid.value) {
    localError.value = '访问用途代码需使用小写字母开头，并只包含小写字母、数字和连字符。'
    return
  }
  if (credentialMode.value === 'face') {
    if (!faceBindingReady.value) {
      localError.value = '本机还没有绑定人脸登录家庭，请先绑定家庭或改用账号密码登录。'
      return
    }
    if (faceFrames.value.length < 2) {
      localError.value = '请点「刷脸进入」完成短采集，或稍等摄像头自动打开。'
      return
    }
  }
  connecting.value = true
  try {
    if (credentialMode.value === 'face') {
      if (!faceBindingReady.value) {
        localError.value = '本机还没有绑定人脸登录家庭，请改用账号密码登录。'
        return
      }
      await connectWithFamilyFace(householdId.value, faceFrames.value, accessPurpose.value)
    } else if (credentialMode.value === 'pin') {
      await connectWithPin(actorId.value, householdId.value, pin.value, accessPurpose.value)
    } else {
      await connectWithPassword(
        actorId.value,
        password.value,
        accessPurpose.value,
        registerMode.value,
      )
    }
    if (session.status === 'ready') {
      password.value = ''
      pin.value = ''
      faceFrames.value = []
      pinIdentityPreview.value = ''
      announcePortalEntry()
    }
  } finally {
    connecting.value = false
  }
}

async function onFaceCaptured(frames: File[]): Promise<void> {
  if (!accessPurposeValid.value) {
    localError.value = '请先填写正确的访问用途代码，再开始人脸验证。'
    pushToast('error', localError.value)
    return
  }
  if (!faceModelsReady.value) {
    localError.value = '本地人脸识别服务还没有准备好，不代表家庭人脸凭证丢失；请先重新检查服务状态。'
    pushToast('error', localError.value)
    return
  }
  faceFrames.value = frames
  await submitSession()
  if (session.status !== 'ready' && (localError.value || session.error)) {
    pushToast('error', localError.value || session.error)
  }
}

function usePinFallback(): void {
  faceFrames.value = []
  localError.value = ''
  credentialMode.value = 'pin'
}

function usePasswordFallback(): void {
  faceFrames.value = []
  localError.value = ''
  registerMode.value = false
  credentialMode.value = 'password'
}

function openPasswordRecovery(): void {
  registerMode.value = false
  recoveryMode.value = true
  recoveryHouseholdId.value = householdId.value.trim()
  password.value = ''
  localError.value = ''
}

function closePasswordRecovery(): void {
  recoveryMode.value = false
  recoveryPin.value = ''
  recoveryNewPassword.value = ''
  recoveryConfirmPassword.value = ''
  localError.value = ''
}

async function submitPasswordRecovery(): Promise<void> {
  localError.value = ''
  if (!actorId.value.trim() || !recoveryHouseholdId.value.trim()) {
    localError.value = '请输入正式账号和家庭编号。'
    return
  }
  if (!/^\d{6}$/.test(recoveryPin.value)) {
    localError.value = '请输入本人已设置的六位数字密码。'
    return
  }
  if (recoveryNewPassword.value.length < 8) {
    localError.value = '新密码至少需要 8 个字符。'
    return
  }
  if (recoveryNewPassword.value !== recoveryConfirmPassword.value) {
    localError.value = '两次输入的新密码不一致。'
    return
  }
  if (!accessPurposeValid.value) {
    localError.value = '访问用途代码需使用小写字母开头，并只包含小写字母、数字和连字符。'
    return
  }
  recovering.value = true
  try {
    await recoverPasswordWithPin(
      actorId.value,
      recoveryHouseholdId.value,
      recoveryPin.value,
      recoveryNewPassword.value,
      accessPurpose.value,
    )
    recoveryPin.value = ''
    recoveryNewPassword.value = ''
    recoveryConfirmPassword.value = ''
    recoveryMode.value = false
    if (session.status === 'ready') {
      pushToast('success', '密码已重置，旧会话已全部退出。')
      announcePortalEntry()
    }
  } catch (cause) {
    localError.value = formatError(cause)
  } finally {
    recovering.value = false
  }
}

async function submitCreate(): Promise<void> {
  if (!canCreate.value) return
  creating.value = true
  createError.value = ''
  try {
    await createHouseholdAndEnter(
      householdDraft.name.trim(),
      householdDraft.members
        .filter(member => member.displayName.trim())
        .map(member => ({ ...member, actorId: member.actorId.trim() })),
    )
    pushToast('success', '家庭已创建，欢迎回家。')
  } catch (cause) {
    createError.value = formatError(cause)
  } finally {
    creating.value = false
  }
}
</script>

<template>
  <div
    class="welcome-stage"
    :class="{
      'welcome-stage--member': entryMode === 'member',
      'welcome-stage--admin': entryMode === 'admin',
    }"
    style="align-content: center; gap: 26px"
    @pointermove="onStageMove"
    @pointerleave="onStageLeave"
  >
    <div class="welcome-inner">
      <section class="welcome-intro">
        <span class="welcome-badge">
          <AppIcon :name="entryMode === 'member' ? 'heart' : 'lock'" :size="15" />
          {{ entryBranding ? entryBranding.badge : '健康信息默认只保存在家里' }}
        </span>
        <h1 v-if="entryBranding" class="welcome-title">{{ entryBranding.heroTitle }}</h1>
        <h1 v-else class="welcome-title">
          把家人的健康变化，<br />
          <span class="accent">温柔而可靠</span>地记下来
        </h1>
        <p class="welcome-lede">
          {{ entryBranding
            ? entryBranding.heroLede
            : '家健镜帮家人记下用药和提醒，发现需要核对的情况，再用清楚明白的方式告诉每一位照护者。' }}
        </p>
        <div class="welcome-art" :style="{ '--par-rx': artRx, '--par-ry': artRy }">
          <img :src="welcomeHero" alt="温馨的家庭照护插画：家人围坐在洒满阳光的窗边" />
          <span class="art-caption">本地家庭插画 · 不上传原图</span>
          <span class="art-float f1"><AppIcon name="lock" :size="13" />数据不出网</span>
          <span class="art-float f2"><AppIcon name="heart" :size="13" />{{ entryMode === 'member' ? '刷脸就能进' : '记错了也能改' }}</span>
        </div>
        <div class="welcome-chip-row">
          <template v-if="entryBranding">
            <span v-for="chip in entryBranding.chips" :key="chip.text" class="welcome-chip">
              <AppIcon :name="chip.icon" :size="14" />{{ chip.text }}
            </span>
          </template>
          <template v-else>
            <span class="welcome-chip"><AppIcon name="timeline" :size="14" />记错了也能改</span>
            <span class="welcome-chip"><AppIcon name="scan" :size="14" />拍药盒，家人核对后才保存</span>
            <span class="welcome-chip"><AppIcon name="key" :size="14" />谁能看什么，家人说了算</span>
          </template>
        </div>
      </section>

      <section
        v-if="!showCreateForm"
        class="welcome-form-card"
        :class="{ 'welcome-form-card--face': credentialMode === 'face' }"
      >
        <span v-if="entryMode === 'member'" class="portal-mark member">
          <AppIcon name="members" :size="14" />
          成员前台 · 个人身份
        </span>
        <span v-else-if="entryMode === 'admin'" class="portal-mark admin">
          <AppIcon name="key" :size="14" />
          管理后台 · 全家管理
        </span>
        <h2>{{ entryBranding ? entryBranding.formTitle : '进入家庭空间' }}</h2>
        <p v-if="entryBranding" class="portal-identity-hint">{{ entryBranding.formIdentityHint }}</p>
        <div v-if="entryConflictNotice" class="notice warn entry-conflict" role="alert">
          <AppIcon name="info" :size="16" />
          <span>{{ entryConflictNotice.message }}</span>
          <a v-if="entryConflictUrl" class="btn btn-primary btn-small" :href="entryConflictUrl">
            {{ entryConflictNotice.crossLinkLabel }}
          </a>
          <span v-else class="entry-conflict-hint">
            {{ entryConflictNotice.crossLinkLabel }}（{{ crossPortalPortsHint(entryConflictNotice.crossLinkTarget) }}）
          </span>
        </div>
        <div
          v-else-if="entryMode === 'member' && !showCreateForm"
          class="notice entry-guide"
          role="note"
          data-testid="member-portal-entry-guide"
        >
          <AppIcon name="info" :size="16" />
          <div>
            <strong>正确进入成员前台</strong>
            <ol>
              <li v-for="step in MEMBER_PORTAL_ENTRY_STEPS" :key="step">{{ step }}</li>
            </ol>
          </div>
        </div>
        <p v-if="entryBranding" class="form-sub">登录信息只留在当前页面，关掉后需要重新登录；可按需要使用账号密码、人脸或数字密码。</p>
        <p v-else class="form-sub">使用正式家庭账号登录。登录信息只留在当前页面，关掉后需要重新登录。</p>
        <div class="notice" data-testid="formal-login-method" role="note">
          <AppIcon name="lock" :size="16" />
          <span><strong>正式账号密码登录</strong> · 也可按入口配置使用已启用的人脸或数字密码</span>
        </div>
        <form v-if="recoveryMode" class="section-stack password-recovery-form" @submit.prevent="submitPasswordRecovery">
          <div class="notice" role="note">
            <AppIcon name="key" :size="16" />
            <span>
              <strong>本地忘记密码恢复</strong> · 使用这个账号本人在该家庭已设置的六位数字密码验证
            </span>
          </div>
          <p class="form-sub">
            系统不会发送邮件或短信。恢复成功后会退出这个账号在其他设备上的旧会话；如果从未设置数字密码，请联系家庭管理员或维护人员走受控恢复流程。
          </p>
          <label class="field">
            正式账号
            <input v-model="actorId" autocomplete="username" placeholder="例如 parent-1" required />
          </label>
          <label class="field">
            家庭编号
            <input
              v-model="recoveryHouseholdId"
              autocomplete="off"
              placeholder="请输入家庭唯一编号（请问家人）"
              required
            />
          </label>
          <label class="field">
            本人六位数字密码
            <input
              v-model="recoveryPin"
              type="password"
              inputmode="numeric"
              autocomplete="one-time-code"
              pattern="[0-9]{6}"
              maxlength="6"
              required
            />
          </label>
          <label class="field">
            新密码
            <input
              v-model="recoveryNewPassword"
              type="password"
              autocomplete="new-password"
              aria-label="新密码"
              minlength="8"
              required
            />
            <small>至少 8 个字符。</small>
          </label>
          <label class="field">
            再次输入新密码
            <input
              v-model="recoveryConfirmPassword"
              type="password"
              autocomplete="new-password"
              aria-label="再次输入新密码"
              minlength="8"
              required
            />
          </label>
          <label class="field">
            访问用途代码
            <input
              v-model="accessPurpose"
              autocomplete="off"
              placeholder="family-care"
              aria-label="访问用途代码"
              :aria-invalid="accessPurpose.trim().length > 0 && !accessPurposeValid"
            />
            <small>使用小写字母开头，例如 family-care。</small>
          </label>
          <p v-if="localError" class="notice error" role="alert">
            <AppIcon name="alert" :size="16" />
            {{ localError }}
          </p>
          <button
            type="submit"
            class="btn btn-primary"
            :disabled="recovering || !actorId.trim() || !recoveryHouseholdId.trim() || !/^\d{6}$/.test(recoveryPin) || recoveryNewPassword.length < 8 || recoveryNewPassword !== recoveryConfirmPassword || !accessPurposeValid"
          >
            {{ recovering ? '正在重置…' : '重置密码并登录' }}
            <AppIcon v-if="!recovering" name="arrow-right" :size="17" />
          </button>
          <button type="button" class="btn btn-ghost btn-small" :disabled="recovering" @click="closePasswordRecovery">
            返回账号登录
          </button>
        </form>
        <form v-else class="section-stack" @submit.prevent="submitSession">
          <div class="segmented-control" role="group" aria-label="选择账号登录凭据">
            <button
              v-for="tab in credentialTabs"
              :key="tab.mode"
              type="button"
              :class="{ active: credentialMode === tab.mode }"
              @click="credentialMode = tab.mode"
            >
              {{ tab.label }}
            </button>
          </div>
          <p v-if="entryMode === 'admin'" class="form-sub">
            管理员推荐使用账号密码；数字密码和刷脸主要供家人在成员前台使用。
          </p>
          <p v-if="passwordBehindOtherWays && credentialMode === 'password'" class="form-sub">
            账号密码主要供管理员或特殊情况使用；家人日常推荐刷脸或数字密码。
          </p>
          <label v-if="credentialMode === 'password'" class="field">
            正式账号
            <input v-model="actorId" autocomplete="username" placeholder="例如 parent-1" required />
          </label>
          <label v-if="credentialMode === 'pin'" class="field">
            家庭
            <select v-if="loginHouseholds.length > 0" v-model="householdId" autocomplete="off" required>
              <option v-for="household in loginHouseholds" :key="household.id" :value="household.id">
                {{ household.name }}
              </option>
            </select>
            <input
              v-else
              v-model="householdId"
              autocomplete="off"
              placeholder="请输入家庭编号（请问家人）"
              required
            />
            <small v-if="householdsLoading">正在加载可访问的家庭...</small>
            <small v-else-if="householdsError">家庭列表加载失败，可手动填写家庭唯一编号。</small>
            <small v-else>选好家庭名称即可；提交时由系统使用内部编号。</small>
          </label>
          <!-- 本机家庭绑定只服务人脸 1:N 登录，密码 / PIN 模式不渲染该卡片。 -->
          <div v-if="faceBinding.visible" class="face-family-summary" role="status">
            <AppIcon :name="faceBinding.bound ? 'home' : 'info'" :size="18" />
            <div>
              <strong>{{ faceBinding.title }}</strong>
              <small>{{ faceBinding.detail }}</small>
              <small v-if="faceBinding.bound" class="face-login-bound-hint">
                本机已绑定这个家庭。点「刷脸进入」即可，也可以自动打开摄像头。
              </small>
              <button v-if="faceBinding.fallbackLabel" type="button" class="btn btn-ghost btn-small" @click="usePasswordFallback">
                {{ faceBinding.fallbackLabel }}
              </button>
            </div>
          </div>
          <label v-if="credentialMode === 'pin'" class="field">
            你的登录名
            <input v-model="actorId" autocomplete="username" placeholder="家人帮你设好的登录名" required />
            <small v-if="pinIdentityPreview">将以 <strong>{{ pinIdentityPreview }}</strong> 的身份进入。</small>
            <small v-else>填写家人帮你设好的登录名，不是家庭名称。</small>
          </label>
          <label v-if="credentialMode === 'password'" class="field">
            密码
            <input v-model="password" type="password" autocomplete="current-password" minlength="8" required />
          </label>
          <label v-else-if="credentialMode === 'pin'" class="field">
            六位数字密码
            <input v-model="pin" type="password" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9]{6}" maxlength="6" required />
          </label>
          <div
            v-if="credentialMode === 'face' && faceBindingReady && (faceCapabilityChecking || (!session.capabilities && !faceCapabilityProbeFailed))"
            class="welcome-face-unavailable"
          >
            <p class="notice" role="status" aria-live="polite">
              <AppIcon name="info" :size="16" />
              正在检查本地人脸识别服务，请稍等…
            </p>
          </div>
          <div
            v-else-if="credentialMode === 'face' && faceBindingReady && !faceModelsReady"
            class="welcome-face-unavailable"
          >
            <p class="notice warn" role="status">
              <AppIcon name="info" :size="16" />
              {{ faceCapabilityProbeFailed
                ? '暂时无法确认本地人脸服务状态。家庭绑定和已录入的人脸凭证不会因此丢失。'
                : '本地人脸识别模型尚未就绪。家庭绑定和已录入的人脸凭证不会因此丢失。' }}
            </p>
            <div class="row-actions">
              <button type="button" class="btn btn-primary" @click="probeFaceCapability">重新检查</button>
              <button type="button" class="btn btn-primary" @click="usePinFallback">改用数字密码</button>
              <button type="button" class="btn btn-ghost" @click="usePasswordFallback">改用账号密码</button>
            </div>
          </div>
          <FaceVideoCapture
            v-else-if="credentialMode === 'face' && faceBindingReady && faceModelsReady"
            compact
            mode="login"
            :auto-start="faceBinding.bound"
            :disabled="connecting || !accessPurposeValid"
            @captured="onFaceCaptured"
            @fallback="usePinFallback"
          />
          <p v-if="credentialMode === 'face' && connecting" class="notice ok" role="status" aria-live="polite">
            <AppIcon name="check" :size="16" />
            正在识别，请稍等…
          </p>
          <label class="field">
            访问用途代码
            <input
              v-model="accessPurpose"
              autocomplete="off"
              placeholder="family-care"
              aria-label="访问用途代码"
              :aria-invalid="accessPurpose.trim().length > 0 && !accessPurposeValid"
            />
            <small>使用小写字母开头，例如 family-care。</small>
          </label>
          <p v-if="credentialMode === 'pin'" class="form-sub">数字密码只用于当前家庭和所选登录名，连续输错会暂时锁定。</p>
          <p v-if="(localError || session.error) && !session.entryConflict" class="notice error" role="alert">
            <AppIcon name="alert" :size="16" />
            {{ localError || session.error }}
          </p>
          <button v-if="credentialMode !== 'face'" type="submit" class="btn btn-primary" :disabled="!accessPurposeValid || !actorId.trim() || (credentialMode === 'password' ? password.length < 8 : !householdId.trim() || !/^\d{6}$/.test(pin)) || connecting">
            {{ submitLabel }}
            <AppIcon v-if="!connecting" name="arrow-right" :size="17" />
          </button>
          <button v-if="credentialMode === 'password'" type="button" class="btn btn-ghost btn-small" @click="registerMode = !registerMode">
            {{ registerMode ? '已有账号？返回登录' : '首次使用？注册本地账号' }}
          </button>
          <button
            v-if="credentialMode === 'password' && !registerMode"
            type="button"
            class="btn btn-ghost btn-small"
            data-testid="forgot-password"
            @click="openPasswordRecovery"
          >
            忘记密码？用六位数字密码重置
          </button>
          <button
            v-if="passwordBehindOtherWays && credentialMode !== 'password'"
            type="button"
            class="portal-other-ways"
            @click="useOtherWaysPassword"
          >
            其他方式：用账号密码登录
          </button>
          <button
            v-else-if="passwordBehindOtherWays"
            type="button"
            class="portal-other-ways"
            @click="backToPrimaryCredentials"
          >
            回到刷脸 / 数字密码登录
          </button>
        </form>
        <p v-if="crossEntryLink" class="welcome-cross-entry">
          <a v-if="crossEntryLink.url" :href="crossEntryLink.url">{{ crossEntryLink.label }}</a>
          <span v-else>{{ crossEntryLink.label }}（{{ crossPortalPortsHint(crossEntryLink.target) }}）</span>
        </p>
        <p class="welcome-disclaimer">
          家庭健康记录仅供日常参考，不提供诊断、处方或用药决策；紧急情况请联系医生或当地急救服务。
        </p>
      </section>

      <section v-else class="welcome-form-card">
        <h2>创建你的家庭</h2>
        <p class="form-sub">
          身份 <strong>{{ session.actorId }}</strong> 名下还没有可见的家庭。创建一个家庭并添加成员，即可开始记录。
        </p>
        <p v-if="entryMode === 'member'" class="notice warn" role="status">
          <AppIcon name="info" :size="16" />
          创建者会成为家庭管理员。建家成功后请改用管理后台完成配置；家人日常请用成员账号回到本前台登录。
        </p>
        <form class="section-stack" @submit.prevent="submitCreate">
          <label class="field">
            家庭名称
            <input v-model="householdDraft.name" autocomplete="off" placeholder="例如 爷爷奶奶家" required />
          </label>
          <label class="field">
            成员一（本人）
            <input v-model="householdDraft.members[0]!.displayName" autocomplete="off" placeholder="成员称呼，例如 爷爷" />
          </label>
          <label class="field">
            成员一登录账号
            <input v-model="householdDraft.members[0]!.actorId" autocomplete="username" placeholder="例如 parent-1" />
            <small>这个账号用于密码、数字密码或刷脸快速登录，默认填当前登录名。</small>
          </label>
          <label class="field">
            成员二（可选）
            <input v-model="householdDraft.members[1]!.displayName" autocomplete="off" placeholder="成员称呼，例如 奶奶" />
          </label>
          <label class="field">
            成员二登录账号（填写成员二时必填）
            <input v-model="householdDraft.members[1]!.actorId" autocomplete="username" placeholder="例如 grandma-1" />
          </label>
          <p class="form-sub">后续到“人脸凭证”页面，为每个登录名采集三张短画面；系统只保存加密特征，不保存照片原片。录入后请绑定本机家庭，成员前台即可直接刷脸进入。</p>
          <p v-if="createError" class="notice error" role="alert">
            <AppIcon name="alert" :size="16" />
            {{ createError }}
          </p>
          <button type="submit" class="btn btn-clay" :disabled="!canCreate">
            {{ creating ? '正在创建' : '创建家庭并进入' }}
            <AppIcon v-if="!creating" name="heart" :size="17" />
          </button>
        </form>
        <p class="welcome-disclaimer">创建后只保存在家里，记错了以后还能更正。</p>
      </section>
    </div>

    <div class="welcome-theme-row" role="group" aria-label="切换界面主题">
      <span class="text-faint" style="font-size: 12.5px">换个心情：</span>
      <button
        v-for="theme in THEMES"
        :key="theme.id"
        type="button"
        class="swatch"
        :class="{ active: currentTheme === theme.id }"
        :title="`${theme.name} · ${theme.tagline}`"
        :style="{ background: `linear-gradient(135deg, ${theme.swatches[1]} 50%, ${theme.swatches[2]} 50%)` }"
        @click="applyTheme(theme.id)"
      />
    </div>
  </div>
</template>
