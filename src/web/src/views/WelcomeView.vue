<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'

import welcomeHero from '../assets/welcome-hero.jpg'
import AppIcon from '../components/AppIcon.vue'
import FaceVideoCapture from '../components/FaceVideoCapture.vue'
import PasswordRevealInput from '../components/PasswordRevealInput.vue'
import {
  connectWithFamilyFace,
  connectWithPassword,
  completeBoundHouseholdPin,
  createHouseholdAndEnter,
  formatError,
  getBoundFaceHouseholdId,
  getBoundFaceHouseholdName,
  getBoundPinCandidates,
  cancelMemberPortalSelection,
  completeMemberPortalPin,
  memberPortalPinCandidates,
  portalWelcomeMessage,
  pushToast,
  recoverPasswordWithPin,
  refreshCapabilities,
  session,
} from '../store'
import {
  crossPortalPortsHint,
  crossPortalUrl,
  portalEntryBranding,
  portalEntryConflictNotice,
  resolveWelcomeEntryMode,
} from '../ui/portalEntry'
import { THEMES, applyTheme, currentTheme } from '../ui/themes'
import { FORMAL_PASSWORD_HINT, formalPasswordMeetsPolicy } from '../ui/passwordPolicy'
import {
  autoEntryMayUseBoundFace,
  faceBindingSummary,
  memberUnboundGate,
  readAdminReadyCookie,
  type WelcomeCredentialMode,
} from '../ui/welcomeFaceBinding'

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
const faceFrames = ref<File[]>([])
const entryMode = resolveWelcomeEntryMode()
const entryBranding = portalEntryBranding(entryMode)
const initialAdminReady = readAdminReadyCookie()

const credentialMode = ref<WelcomeCredentialMode>(
  entryBranding
    ? initialBoundFaceHouseholdId && entryBranding.credentialOrder[0] === 'face'
      ? 'face'
      : entryBranding.defaultCredential
    : initialBoundFaceHouseholdId
      && autoEntryMayUseBoundFace(initialBoundFaceHouseholdId, {
        readyHouseholdId: initialAdminReady?.householdId ?? '',
        readyInstanceId: initialAdminReady?.instanceId ?? '',
      })
      ? 'face'
      : 'password',
)

const CREDENTIAL_LABELS: Record<WelcomeCredentialMode, string> = {
  face: '刷脸进入',
  pin: 'PIN登录',
  password: '账号密码',
}

const credentialTabs = computed(() =>
  (entryBranding?.credentialOrder ?? (['password'] as const))
    .filter(mode => !(entryBranding?.passwordBehindOtherWays && mode === 'password'))
    .map(mode => ({
      mode,
      label: CREDENTIAL_LABELS[mode],
    })),
)

const passwordBehindOtherWays = computed(() => entryBranding?.passwordBehindOtherWays ?? false)
const showCredentialTabs = computed(() => credentialTabs.value.length > 1)

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
  credentialMode.value = initialBoundFaceHouseholdId ? 'face' : (entryBranding?.defaultCredential ?? 'password')
}

const submitLabel = computed(() => {
  if (connecting.value) return '正在进入…'
  if (credentialMode.value === 'password' && registerMode.value) return '注册并登录'
  if (entryBranding) return entryBranding.ctaLabel
  return '登录家庭空间'
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
const selectingMember = computed(() => session.status === 'selecting-member')
const deviceBindingRevision = ref(0)
const pinCandidates = computed(() => {
  // Cookie/localStorage are not reactive sources. The revision is bumped by
  // the cross-portal polling below when the admin signs in or changes the
  // bound family, so an already-open member page sees the new candidates.
  void deviceBindingRevision.value
  return selectingMember.value ? memberPortalPinCandidates() : getBoundPinCandidates()
})
const pickedMemberId = ref(pinCandidates.value[0]?.id ?? '')
const memberPin = ref('')
const accountFieldLabel = computed(() => (entryMode === 'member' ? '家庭管理员账号' : '正式账号'))
const boundPinReady = computed(() => {
  void deviceBindingRevision.value
  return getBoundPinCandidates().length > 0
})
const adminReady = ref(readAdminReadyCookie())
const capabilitiesReady = ref(Boolean(session.capabilities))
let adminReadyPoll: number | null = null
watch(
  () => session.capabilities?.instance_id,
  () => {
    adminReady.value = readAdminReadyCookie()
  },
)
const unboundGate = computed(() => {
  // Keep the household read in the same reactive boundary as the ready
  // cookie. This matters when the member page was opened before admin login.
  void deviceBindingRevision.value
  return memberUnboundGate(entryMode, getBoundFaceHouseholdId(), {
    instanceId: session.capabilities?.instance_id ?? '',
    readyInstanceId: adminReady.value?.instanceId ?? '',
    readyHouseholdId: adminReady.value?.householdId ?? '',
    capabilitiesPending: !capabilitiesReady.value,
  })
})
const adminRegisterUrl = computed(() => crossPortalUrl('admin'))

const householdDraft = reactive({
  name: '',
  members: [
    { displayName: '', actorId: session.actorId, role: 'SELF' as const },
    { displayName: '', actorId: '', role: 'DEPENDENT' as const },
  ],
})

const showCreateForm = computed(() => session.status === 'empty')
const faceBindingReady = computed(() => householdId.value.trim().length > 0)
const faceBinding = computed(() =>
  faceBindingSummary(credentialMode.value, householdId.value, boundFaceHouseholdName.value),
)
const faceCapabilityChecking = ref(false)
const faceCapabilityProbeFailed = ref(false)
const faceModelsReady = computed(
  () => session.capabilities?.available?.includes('face-recognition-local') ?? false,
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
  () => session.status,
  status => {
    if (status === 'selecting-member') {
      pickedMemberId.value = pinCandidates.value[0]?.id ?? ''
      memberPin.value = ''
      localError.value = ''
    }
  },
)

async function submitMemberPin(): Promise<void> {
  localError.value = ''
  if (!pickedMemberId.value) {
    localError.value = '请选择家庭成员。'
    return
  }
  if (!/^\d{6}$/.test(memberPin.value)) {
    localError.value = '请输入这位家人的六位数字密码。'
    return
  }
  connecting.value = true
  try {
    if (selectingMember.value) {
      await completeMemberPortalPin(pickedMemberId.value, memberPin.value)
    } else {
      await completeBoundHouseholdPin(pickedMemberId.value, memberPin.value)
    }
    if (session.status === 'ready') {
      memberPin.value = ''
      announcePortalEntry()
    } else if (session.error) {
      localError.value = session.error
    }
  } finally {
    connecting.value = false
  }
}

watch(credentialMode, mode => {
  householdId.value = mode === 'password' ? '' : getBoundFaceHouseholdId()
  boundFaceHouseholdName.value = mode === 'password' ? '' : getBoundFaceHouseholdName()
  localError.value = ''
  faceFrames.value = []
  if (mode === 'pin' && !pickedMemberId.value) {
    pickedMemberId.value = pinCandidates.value[0]?.id ?? ''
  }
  if (mode === 'face' && !session.capabilities) void probeFaceCapability()
})

async function probeFaceCapability(): Promise<void> {
  if (faceCapabilityChecking.value) return
  faceCapabilityChecking.value = true
  faceCapabilityProbeFailed.value = false
  try {
    await refreshCapabilities()
    faceCapabilityProbeFailed.value = !session.capabilities
  } finally {
    faceCapabilityChecking.value = false
  }
}

onMounted(() => {
  refreshDeviceBindingSnapshot()
  void refreshCapabilities().finally(() => {
    capabilitiesReady.value = true
    adminReady.value = readAdminReadyCookie()
  })
  if (!unboundGate.value.blocked && credentialMode.value === 'face' && !session.capabilities) {
    void probeFaceCapability()
  }
  adminReadyPoll = window.setInterval(refreshDeviceBindingSnapshot, 2000)
})

onBeforeUnmount(() => {
  faceFrames.value = []
  if (adminReadyPoll !== null) {
    window.clearInterval(adminReadyPoll)
    adminReadyPoll = null
  }
})

function announcePortalEntry(): void {
  if (session.status !== 'ready') return
  pushToast('success', portalWelcomeMessage())
}

async function submitSession(): Promise<void> {
  if (connecting.value) return
  localError.value = ''
  if (credentialMode.value === 'face') {
    if (!faceBindingReady.value) {
      localError.value = '本机还没有绑定家庭。请先到管理后台登录一次，或改用 PIN 登录。'
      return
    }
    if (faceFrames.value.length < 2) {
      localError.value = '请点「刷脸进入」，或稍等摄像头打开。'
      return
    }
  }
  if (credentialMode.value === 'pin') {
    await submitMemberPin()
    return
  }
  if (credentialMode.value === 'password') {
    if (!actorId.value.trim() || !password.value) {
      localError.value = `请输入${accountFieldLabel.value}和密码。`
      return
    }
    if (registerMode.value && !formalPasswordMeetsPolicy(password.value)) {
      localError.value = `${FORMAL_PASSWORD_HINT}。`
      return
    }
  }
  connecting.value = true
  try {
    if (credentialMode.value === 'face') {
      await connectWithFamilyFace(householdId.value, faceFrames.value, accessPurpose.value)
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
      faceFrames.value = []
      announcePortalEntry()
    }
  } finally {
    connecting.value = false
  }
}

async function onFaceCaptured(frames: File[]): Promise<void> {
  if (!faceModelsReady.value) {
    localError.value = '人脸识别还没准备好，请改用 PIN 登录。'
    pushToast('error', localError.value)
    return
  }
  faceFrames.value = frames
  await submitSession()
  if (session.status !== 'ready' && (localError.value || session.error)) {
    pushToast('error', localError.value || session.error)
  }
}

function usePasswordFallback(): void {
  faceFrames.value = []
  localError.value = ''
  registerMode.value = false
  credentialMode.value = entryMode === 'member' ? 'pin' : 'password'
}

function refreshDeviceBindingSnapshot(): void {
  adminReady.value = readAdminReadyCookie()
  // Keep refs that also drive the face tab in sync with the shared cookie. A
  // member page can remain mounted while the admin signs in on another tab.
  householdId.value = getBoundFaceHouseholdId()
  boundFaceHouseholdName.value = getBoundFaceHouseholdName()
  deviceBindingRevision.value += 1
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
    localError.value = '请输入账号和家庭编号。'
    return
  }
  if (!/^\d{6}$/.test(recoveryPin.value)) {
    localError.value = '请输入已设置的六位数字。'
    return
  }
  if (recoveryNewPassword.value.length < 8 || !formalPasswordMeetsPolicy(recoveryNewPassword.value)) {
    localError.value = FORMAL_PASSWORD_HINT + '。'
    return
  }
  if (recoveryNewPassword.value !== recoveryConfirmPassword.value) {
    localError.value = '两次输入的新密码不一致。'
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
      pushToast('success', '密码已重置。')
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
    pushToast('success', '家庭已创建。')
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
          {{ entryBranding ? entryBranding.badge : '家健镜' }}
        </span>
        <h1 v-if="entryBranding" class="welcome-title">{{ entryBranding.heroTitle }}</h1>
        <h1 v-else class="welcome-title">
          把家人的健康变化，<br />
          <span class="accent">温柔而可靠</span>地记下来
        </h1>
        <p class="welcome-lede">
          {{ entryBranding
            ? entryBranding.heroLede
            : '记下用药和提醒，发现需要核对的情况，再告诉每一位照护者。' }}
        </p>
        <div class="welcome-art" :style="{ '--par-rx': artRx, '--par-ry': artRy }">
          <img :src="welcomeHero" alt="温馨的家庭照护插画：家人围坐在洒满阳光的窗边" />
        </div>
        <div class="welcome-chip-row">
          <template v-if="entryBranding">
            <span v-for="chip in entryBranding.chips" :key="chip.text" class="welcome-chip">
              <AppIcon :name="chip.icon" :size="14" />{{ chip.text }}
            </span>
          </template>
          <template v-else>
            <span class="welcome-chip"><AppIcon name="timeline" :size="14" />记错了也能改</span>
            <span class="welcome-chip"><AppIcon name="scan" :size="14" />拍药盒再核对</span>
            <span class="welcome-chip"><AppIcon name="key" :size="14" />谁能看什么，家人说了算</span>
          </template>
        </div>
      </section>

      <section
        v-if="!showCreateForm"
        class="welcome-form-card"
        :class="{ 'welcome-form-card--face': credentialMode === 'face' && !unboundGate.blocked }"
      >
        <span v-if="entryMode === 'member'" class="portal-mark member">
          <AppIcon name="members" :size="14" />
          成员前台
        </span>
        <span v-else-if="entryMode === 'admin'" class="portal-mark admin">
          <AppIcon name="key" :size="14" />
          管理后台
        </span>
        <h2>{{
          recoveryMode
            ? '忘记密码'
            : selectingMember
              ? '选择家庭成员'
              : unboundGate.blocked
                ? unboundGate.title
                : entryBranding ? entryBranding.formTitle : '登录'
        }}</h2>
        <p v-if="selectingMember" class="form-sub">选择要进入的家人，再输入这位家人的六位数字密码。PIN 由管理员在后台「登录设置」页保存。</p>
        <p v-else-if="unboundGate.blocked" class="portal-identity-hint">{{ unboundGate.message }}</p>
        <p v-else-if="entryBranding?.formIdentityHint" class="portal-identity-hint">{{ entryBranding.formIdentityHint }}</p>
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
        <form v-if="selectingMember" class="section-stack" @submit.prevent="submitMemberPin">
          <div class="segmented-control member-picker" role="listbox" aria-label="选择家庭成员">
            <button
              v-for="member in pinCandidates"
              :key="member.id"
              type="button"
              role="option"
              :aria-selected="pickedMemberId === member.id"
              :class="{ active: pickedMemberId === member.id }"
              @click="pickedMemberId = member.id"
            >
              {{ member.display_name }}
            </button>
          </div>
          <label class="field">
            六位数字密码
            <PasswordRevealInput
              v-model="memberPin"
              inputmode="numeric"
              autocomplete="one-time-code"
              pattern="[0-9]{6}"
              :maxlength="6"
              required
              aria-label="六位数字密码"
            />
          </label>
          <p v-if="localError || session.error" class="notice error" role="alert">
            <AppIcon name="alert" :size="16" />
            {{ localError || session.error }}
          </p>
          <button
            type="submit"
            class="btn btn-primary"
            :disabled="connecting || !pickedMemberId || !/^\d{6}$/.test(memberPin)"
          >
            {{ connecting ? '正在进入…' : '进入前台' }}
            <AppIcon v-if="!connecting" name="arrow-right" :size="17" />
          </button>
          <button type="button" class="btn btn-ghost btn-small" :disabled="connecting" @click="cancelMemberPortalSelection">
            换管理员账号
          </button>
        </form>
        <form v-else-if="recoveryMode" class="section-stack password-recovery-form" @submit.prevent="submitPasswordRecovery">
          <label class="field">
            正式账号
            <input v-model="actorId" autocomplete="username" required />
          </label>
          <label class="field">
            家庭编号
            <input v-model="recoveryHouseholdId" autocomplete="off" required />
          </label>
          <label class="field">
            本人六位数字密码
            <PasswordRevealInput
              v-model="recoveryPin"
              inputmode="numeric"
              autocomplete="one-time-code"
              pattern="[0-9]{6}"
              :maxlength="6"
              required
              aria-label="本人六位数字密码"
            />
          </label>
          <label class="field">
            新密码
            <PasswordRevealInput
              v-model="recoveryNewPassword"
              autocomplete="new-password"
              aria-label="新密码"
              :minlength="8"
              required
            />
            <small>{{ FORMAL_PASSWORD_HINT }}。</small>
          </label>
          <label class="field">
            再次输入新密码
            <PasswordRevealInput
              v-model="recoveryConfirmPassword"
              autocomplete="new-password"
              aria-label="再次输入新密码"
              :minlength="8"
              required
            />
          </label>
          <p v-if="localError" class="notice error" role="alert">
            <AppIcon name="alert" :size="16" />
            {{ localError }}
          </p>
          <button
            type="submit"
            class="btn btn-primary"
            :disabled="recovering || !actorId.trim() || !recoveryHouseholdId.trim() || !/^\d{6}$/.test(recoveryPin) || !formalPasswordMeetsPolicy(recoveryNewPassword) || recoveryNewPassword !== recoveryConfirmPassword"
          >
            {{ recovering ? '正在重置…' : '重置密码并登录' }}
          </button>
          <button type="button" class="btn btn-ghost btn-small" :disabled="recovering" @click="closePasswordRecovery">
            返回登录
          </button>
        </form>
        <div
          v-else-if="unboundGate.blocked"
          class="section-stack member-unbound-gate"
          data-testid="member-unbound-gate"
        >
          <a
            v-if="adminRegisterUrl"
            class="btn btn-primary"
            :href="adminRegisterUrl"
          >
            {{ unboundGate.ctaLabel }}
            <AppIcon name="arrow-right" :size="17" />
          </a>
          <p v-else class="notice warn" role="status">
            <AppIcon name="info" :size="16" />
            请打开管理后台（{{ crossPortalPortsHint('admin') }}）注册或登录家庭管理员账号。
          </p>
        </div>
        <form v-else class="section-stack" novalidate @submit.prevent="submitSession">
          <div v-if="showCredentialTabs" class="segmented-control" role="group" aria-label="选择账号登录凭据">
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
          <label v-if="credentialMode === 'password'" class="field">
            {{ accountFieldLabel }}
            <input
              v-model="actorId"
              autocomplete="username"
              :aria-label="accountFieldLabel"
              :aria-invalid="Boolean((localError || session.error) && !session.entryConflict)"
            />
            <small v-if="entryMode === 'member'">请输入家庭管理员账号，不是家人姓名。每位家人的六位数字密码在管理后台「登录设置」里保存。</small>
          </label>
          <div v-if="credentialMode === 'pin' && boundPinReady" class="segmented-control member-picker" role="listbox" aria-label="选择家庭成员">
            <button
              v-for="member in pinCandidates"
              :key="member.id"
              type="button"
              role="option"
              :aria-selected="pickedMemberId === member.id"
              :class="{ active: pickedMemberId === member.id }"
              @click="pickedMemberId = member.id"
            >
              {{ member.display_name }}
            </button>
          </div>
          <label v-if="credentialMode === 'pin' && boundPinReady" class="field">
            六位数字密码
            <PasswordRevealInput
              v-model="memberPin"
              inputmode="numeric"
              autocomplete="one-time-code"
              pattern="[0-9]{6}"
              :maxlength="6"
              required
              aria-label="六位数字密码"
            />
          </label>
          <p v-else-if="credentialMode === 'pin'" class="notice warn" role="status">
            <AppIcon name="info" :size="16" />
            请先到管理后台用家庭管理员账号登录一次。登录后这台电脑会自动绑定这个家庭，这里就可以选择家人。
          </p>
          <div v-if="faceBinding.visible" class="face-family-summary" role="status">
            <AppIcon :name="faceBinding.bound ? 'home' : 'info'" :size="18" />
            <div>
              <strong>{{ faceBinding.title }}</strong>
              <small v-if="faceBinding.detail">{{ faceBinding.detail }}</small>
              <button v-if="faceBinding.fallbackLabel" type="button" class="btn btn-ghost btn-small" @click="usePasswordFallback">
                {{ faceBinding.fallbackLabel }}
              </button>
            </div>
          </div>
          <label v-if="credentialMode === 'password'" class="field">
            密码
            <PasswordRevealInput
              v-model="password"
              autocomplete="current-password"
              aria-label="密码"
              :aria-invalid="Boolean((localError || session.error) && !session.entryConflict)"
            />
            <small v-if="registerMode">{{ FORMAL_PASSWORD_HINT }}。</small>
          </label>
          <div
            v-if="credentialMode === 'face' && faceBindingReady && (faceCapabilityChecking || (!session.capabilities && !faceCapabilityProbeFailed))"
            class="welcome-face-unavailable"
          >
            <p class="notice" role="status" aria-live="polite">
              <AppIcon name="info" :size="16" />
              正在检查人脸识别…
            </p>
          </div>
          <div
            v-else-if="credentialMode === 'face' && faceBindingReady && !faceModelsReady"
            class="welcome-face-unavailable"
          >
            <p class="notice warn" role="status">
              <AppIcon name="info" :size="16" />
              {{ faceCapabilityProbeFailed
                ? '暂时无法确认人脸服务，请改用 PIN 登录。'
                : '人脸识别尚未就绪，请改用 PIN 登录。' }}
            </p>
            <div class="row-actions">
              <button type="button" class="btn btn-primary" @click="probeFaceCapability">重新检查</button>
              <button type="button" class="btn btn-ghost" @click="usePasswordFallback">改用 PIN 登录</button>
            </div>
          </div>
          <FaceVideoCapture
            v-else-if="credentialMode === 'face' && faceBindingReady && faceModelsReady"
            compact
            mode="login"
            :auto-start="faceBinding.bound"
            :disabled="connecting"
            :fallback-label="entryMode === 'member' ? '改用 PIN 登录' : '改用账号密码'"
            @captured="onFaceCaptured"
            @fallback="usePasswordFallback"
          />
          <p v-if="credentialMode === 'face' && connecting" class="notice ok" role="status" aria-live="polite">
            <AppIcon name="check" :size="16" />
            正在识别…
          </p>
          <p v-if="(localError || session.error) && !session.entryConflict" class="notice error" role="alert">
            <AppIcon name="alert" :size="16" />
            {{ localError || session.error }}
          </p>
          <p
            v-if="credentialMode === 'password' && registerMode"
            class="notice"
            role="status"
          >
            <AppIcon name="info" :size="16" />
            <span v-if="entryMode === 'member'">
              这里注册的是家庭管理员账号。建家后请到管理后台「登录设置」给每位家人设置六位数字密码，再回成员前台选人登录。
            </span>
            <span v-else>
              注册并创建家庭后，会进入「登录设置」：先给每位家人设 PIN，再按需录入人脸。
            </span>
          </p>
          <button
            v-if="credentialMode === 'password'"
            type="submit"
            class="btn btn-primary"
            :aria-busy="connecting"
          >
            {{ submitLabel }}
            <AppIcon v-if="!connecting" name="arrow-right" :size="17" />
          </button>
          <button
            v-else-if="credentialMode === 'pin' && boundPinReady"
            type="submit"
            class="btn btn-primary"
            :disabled="connecting || !pickedMemberId || !/^\d{6}$/.test(memberPin)"
          >
            {{ connecting ? '正在进入…' : '进入前台' }}
            <AppIcon v-if="!connecting" name="arrow-right" :size="17" />
          </button>
          <button v-if="credentialMode === 'password' && entryMode !== 'member'" type="button" class="btn btn-ghost btn-small" @click="registerMode = !registerMode">
            {{ registerMode ? '返回登录' : '注册本地账号' }}
          </button>
          <button
            v-if="credentialMode === 'password' && !registerMode"
            type="button"
            class="btn btn-ghost btn-small"
            data-testid="forgot-password"
            @click="openPasswordRecovery"
          >
            忘记密码
          </button>
          <button
            v-if="passwordBehindOtherWays && credentialMode !== 'password'"
            type="button"
            class="portal-other-ways"
            @click="useOtherWaysPassword"
          >
            用账号密码登录
          </button>
          <button
            v-else-if="passwordBehindOtherWays"
            type="button"
            class="portal-other-ways"
            @click="backToPrimaryCredentials"
          >
            回到刷脸登录
          </button>
        </form>
        <p v-if="crossEntryLink && !unboundGate.blocked" class="welcome-cross-entry">
          <a v-if="crossEntryLink.url" :href="crossEntryLink.url">{{ crossEntryLink.label }}</a>
          <span v-else>{{ crossEntryLink.label }}（{{ crossPortalPortsHint(crossEntryLink.target) }}）</span>
        </p>
        <!-- 安全边界文案：本地优先承诺 + 非诊断声明 + 急救指引。
             这三句是登录页的合规底线（NFR-02 / hct405 安全边界），任何入口模式都要出现，
             不能因为改版精简掉；HCT-510 精简登录页时曾漏掉，此处恢复完整版。 -->
        <p class="welcome-disclaimer">
          健康信息默认只保存在家里。家庭健康记录仅供日常参考，不提供诊断、处方或用药决策；紧急情况请联系医生或当地急救服务。
        </p>
      </section>

      <section v-else class="welcome-form-card">
        <h2>创建你的家庭</h2>
        <p class="form-sub">这里只登记家庭和 1～2 名成员。创建后会进入「登录设置」：第一步给每位家人（含管理员）设六位数字密码，第二步可录入人脸。刷脸可跳过 PIN。</p>
        <form class="section-stack" @submit.prevent="submitCreate">
          <label class="field">
            家庭名称
            <input v-model="householdDraft.name" autocomplete="off" placeholder="例如 爷爷奶奶家" required />
          </label>
          <label class="field">
            成员一（本人）
            <input v-model="householdDraft.members[0]!.displayName" autocomplete="off" placeholder="例如 爷爷" />
          </label>
          <label class="field">
            成员一登录账号
            <input v-model="householdDraft.members[0]!.actorId" autocomplete="username" placeholder="例如 parent-1" />
          </label>
          <label class="field">
            成员二（可选）
            <input v-model="householdDraft.members[1]!.displayName" autocomplete="off" placeholder="例如 奶奶" />
          </label>
          <label class="field">
            成员二登录账号
            <input v-model="householdDraft.members[1]!.actorId" autocomplete="username" placeholder="例如 grandma-1" />
          </label>
          <p v-if="createError" class="notice error" role="alert">
            <AppIcon name="alert" :size="16" />
            {{ createError }}
          </p>
          <button type="submit" class="btn btn-clay" :disabled="!canCreate">
            {{ creating ? '正在创建' : '创建家庭并进入' }}
            <AppIcon v-if="!creating" name="heart" :size="17" />
          </button>
        </form>
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
