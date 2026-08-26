<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'

import { apiClient } from '../api/client'
import type { FaceCredential } from '../api/types'
import AppIcon from '../components/AppIcon.vue'
import FaceVideoCapture from '../components/FaceVideoCapture.vue'
import {
  bindFaceHousehold,
  clearBoundFaceHousehold,
  formatError,
  getBoundFaceHouseholdId,
  pushToast,
  refreshMembers,
  requestOptions,
  session,
} from '../store'
import { askConfirm } from '../ui/confirm'
import { formatDateTime } from '../ui/labels'

const credentials = ref<FaceCredential[]>([])
const visibleCredentials = computed(() => credentials.value.filter(credential => credential.status !== 'DELETED'))
const selectedActorId = ref('')
const confirmationMethod = ref<'pin' | 'password'>('pin')
const confirmationCode = ref('')
const selectedFrames = ref<File[]>([])
const consent = ref(false)
const replaceExisting = ref(false)
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const registrationSuccess = ref('')
const highlightCredentialId = ref('')
const credentialListEl = ref<HTMLElement | null>(null)
const successBannerEl = ref<HTMLElement | null>(null)
const pinDraft = ref('')
const pinConfirmation = ref('')
const pinSaving = ref(false)
const pinError = ref('')
const pinSuccess = ref('')
const accountMemberId = ref('')
const accountActorId = ref('')
const accountBindingSaving = ref(false)
const accountBindingError = ref('')
const boundFaceHouseholdId = ref(getBoundFaceHouseholdId())
const confirmationCodeValid = computed(() => {
  const code = confirmationCode.value.trim()
  return confirmationMethod.value === 'pin' ? /^\d{6}$/.test(code) : code.length >= 8 && code.length <= 256
})
const registrationBlockReason = computed(() => {
  if (session.authMode !== 'session') return '当前是调试身份，请返回欢迎页切换到“家庭账号登录”。'
  if (!session.isOwnerView) return '只有家庭管理员可以注册人脸凭证。'
  if (!session.selectedHouseholdId) return '请先选择一个家庭。'
  if (!selectedActorId.value) return '请先选择要绑定人脸的家庭登录名。'
  if (selectedFrames.value.length < 2) return '请先点大按钮开始录入，听语音把脸放进圆圈并拍满三张。'
  if (!confirmationCodeValid.value) {
    return confirmationMethod.value === 'pin' ? '请输入已设置的六位数字密码。' : '请输入当前家庭账号密码（至少八位）。'
  }
  if (!consent.value) return '请先勾选本人明确同意，才能注册人脸凭证。'
  return ''
})
const canRegisterCredential = computed(() => !saving.value && !registrationBlockReason.value)
const boundFaceHouseholdLabel = computed(() => {
  const household = session.households.find(item => item.id === boundFaceHouseholdId.value)
  return household?.name ?? boundFaceHouseholdId.value
})

const unboundMembers = computed(() => session.members.filter(member => !member.actor_id))
const legacyCredentials = computed(() =>
  visibleCredentials.value.filter(credential => credential.status === 'ACTIVE' && credential.upgrade_recommended),
)

function beginRebind(credential: FaceCredential): void {
  selectedActorId.value = credential.actor_id
  replaceExisting.value = true
  selectedFrames.value = []
  error.value = ''
  registrationSuccess.value = ''
  pushToast('info', '已选中该登录名并勾选重新绑定：请完成三帧采集后提交。')
}

function bindCurrentHouseholdToDevice(): void {
  const householdId = session.selectedHouseholdId
  if (!householdId) return
  const household = session.households.find(item => item.id === householdId)
  bindFaceHousehold(householdId, household?.name ?? '')
  boundFaceHouseholdId.value = householdId
    pushToast('success', '本机人脸登录家庭已绑定。成员前台可直接刷脸进入；请确认家人已录入人脸。')
}

function clearDeviceFaceHousehold(): void {
  clearBoundFaceHousehold()
  boundFaceHouseholdId.value = ''
  pushToast('info', '已解除本机人脸登录家庭绑定。')
}

function credentialStatusLabel(status: string): string {
  if (status === 'ACTIVE') return '有效'
  if (status === 'REVOKED') return '已撤销'
  if (status === 'DELETED') return '已删除'
  return '未知'
}

function credentialMetaLine(credential: FaceCredential): string {
  const angles = credential.template_count ?? 1
  return `版本 ${credential.credential_version} · ${angles} 个角度 · ${formatDateTime(credential.created_at)}`
}

const actorOptions = computed(() => {
  const household = session.households.find(item => item.id === session.selectedHouseholdId)
  const options = household ? [{ id: household.created_by, label: '家庭管理员' }] : []
  for (const member of session.members) {
    if (member.actor_id && !options.some(option => option.id === member.actor_id)) {
      options.push({ id: member.actor_id, label: member.display_name })
    }
  }
  return options
})

function resetForm(): void {
  selectedActorId.value = actorOptions.value[0]?.id ?? session.actorId
  confirmationCode.value = ''
  selectedFrames.value = []
  consent.value = false
  replaceExisting.value = false
  error.value = ''
}

function clearRegistrationOutcome(): void {
  registrationSuccess.value = ''
  highlightCredentialId.value = ''
}

function resetPinForm(): void {
  pinDraft.value = ''
  pinConfirmation.value = ''
  pinError.value = ''
  pinSuccess.value = ''
}

async function savePin(): Promise<void> {
  const householdId = session.selectedHouseholdId
  const pin = pinDraft.value.trim()
  pinError.value = ''
  pinSuccess.value = ''
  if (!householdId) {
    pinError.value = '请先选择家庭。'
    return
  }
  if (!/^\d{6}$/.test(pin)) {
    pinError.value = 'PIN 必须是六位数字。'
    return
  }
  if (pin !== pinConfirmation.value.trim()) {
    pinError.value = '两次输入的 PIN 不一致。'
    return
  }

  pinSaving.value = true
  try {
    await apiClient.setPin(householdId, pin, requestOptions.value)
    pinSuccess.value = `已为当前身份 ${session.actorId} 设置家庭 ${householdId} 的 PIN。`
    pinDraft.value = ''
    pinConfirmation.value = ''
  } catch (cause) {
    pinError.value = formatError(cause)
  } finally {
    pinSaving.value = false
  }
}

async function loadCredentials(): Promise<boolean> {
  const householdId = session.selectedHouseholdId
  if (!householdId || !session.isOwnerView) return false
  loading.value = true
  error.value = ''
  try {
    credentials.value = await apiClient.listFaceCredentials(householdId, requestOptions.value)
    if (!selectedActorId.value) resetForm()
    return true
  } catch (cause) {
    error.value = formatError(cause)
    return false
  } finally {
    loading.value = false
  }
}

function onFramesCaptured(frames: File[]): void {
  selectedFrames.value = frames
  error.value = ''
  registrationSuccess.value = ''
  pushToast('success', '三张照片已拍好。请填写 PIN（或密码），勾选同意后点下方“完成注册”。')
}

async function bindMemberAccount(): Promise<void> {
  const householdId = session.selectedHouseholdId
  const memberId = accountMemberId.value
  const actorId = accountActorId.value.trim()
  accountBindingError.value = ''
  if (!householdId || !memberId || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$/.test(actorId)) {
    accountBindingError.value = '请选择成员，并填写字母、数字、点、下划线或短横线组成的登录名。'
    return
  }
  accountBindingSaving.value = true
  try {
    await apiClient.bindMemberAccount(householdId, memberId, { actor_id: actorId }, requestOptions.value)
    await refreshMembers()
    accountActorId.value = ''
    accountMemberId.value = ''
    pushToast('success', '成员登录名已绑定，现在可以为他采集人脸。')
  } catch (cause) {
    accountBindingError.value = formatError(cause)
  } finally {
    accountBindingSaving.value = false
  }
}

async function registerCredential(): Promise<void> {
  const householdId = session.selectedHouseholdId
  if (registrationBlockReason.value) {
    error.value = registrationBlockReason.value
    registrationSuccess.value = ''
    pushToast('error', registrationBlockReason.value)
    return
  }
  saving.value = true
  error.value = ''
  registrationSuccess.value = ''
  const targetActorId = selectedActorId.value
  const wasRebind = replaceExisting.value
  try {
    await apiClient.registerFaceCredential(
      householdId,
      selectedFrames.value,
      {
        consent: true,
        targetActorId,
        replaceExisting: wasRebind,
        confirmationMethod: confirmationMethod.value,
        confirmationCode: confirmationCode.value,
      },
      requestOptions.value,
    )
    const actorLabel = actorOptions.value.find(option => option.id === targetActorId)?.label ?? targetActorId
    registrationSuccess.value = wasRebind
      ? `重新绑定成功：${actorLabel} 的人脸已更新。请确认本机已绑定家庭，家人可在成员前台直接刷脸进入。`
      : `录入成功：${actorLabel} 的人脸已保存。请确认本机已绑定家庭，家人可在成员前台直接刷脸进入。`
    pushToast('success', registrationSuccess.value)
    resetForm()
    selectedActorId.value = targetActorId
    await loadCredentials()
    const latest = visibleCredentials.value.find(
      credential => credential.actor_id === targetActorId && credential.status === 'ACTIVE',
    )
    highlightCredentialId.value = latest?.id ?? ''
    await nextTick()
    successBannerEl.value?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    window.setTimeout(() => {
      credentialListEl.value?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    }, 450)
  } catch (cause) {
    error.value = formatError(cause)
    registrationSuccess.value = ''
    pushToast('error', error.value)
  } finally {
    saving.value = false
  }
}

async function deleteCredential(credential: FaceCredential): Promise<void> {
  const householdId = session.selectedHouseholdId
  if (!householdId || credential.status !== 'ACTIVE') return
  const accepted = await askConfirm({
    title: '删除人脸凭证',
    message: '删除后该凭证立即失效，服务器会清空加密模板。此操作不会删除家庭账号。',
    confirmText: '删除凭证',
  })
  if (!accepted) return
  saving.value = true
  try {
    await apiClient.deleteFaceCredential(householdId, credential.id, requestOptions.value)
    credentials.value = credentials.value.filter(item => item.id !== credential.id)
    pushToast('success', '人脸凭证已删除并立即失效。')
    const refreshed = await loadCredentials()
    if (!refreshed) {
      error.value = ''
      pushToast('info', '凭证已删除，但列表刷新失败；点击“刷新”即可重新读取状态。')
    }
  } catch (cause) {
    error.value = formatError(cause)
  } finally {
    saving.value = false
  }
}

watch(() => session.selectedHouseholdId, () => {
  clearRegistrationOutcome()
  resetForm()
  resetPinForm()
  void loadCredentials()
})
watch(actorOptions, options => {
  if (!options.some(option => option.id === selectedActorId.value)) resetForm()
})
onMounted(() => {
  resetForm()
  resetPinForm()
  void loadCredentials()
})
</script>

<template>
  <div class="face-credential-page">
    <div class="page-heading">
      <div>
        <p class="eyebrow">家庭账号安全</p>
        <h1>人脸凭证注册</h1>
        <p class="page-subtitle">为家人采集三张动态画面；系统只保存加密特征，不保存照片原片。</p>
      </div>
      <button type="button" class="btn btn-ghost" :disabled="loading" @click="loadCredentials"><AppIcon name="refresh" :size="15" /> 刷新</button>
    </div>

    <p v-if="!session.isOwnerView" class="notice warn" role="alert"><AppIcon name="shield" :size="16" /> 只有家庭管理员可以管理人脸凭证。</p>
    <p
      v-if="registrationSuccess"
      ref="successBannerEl"
      class="notice ok face-register-success"
      role="status"
      aria-live="polite"
    >
      <AppIcon name="check" :size="16" /> {{ registrationSuccess }}
      <button type="button" class="btn btn-ghost btn-small" @click="clearRegistrationOutcome">知道了</button>
    </p>
    <p v-if="error" class="notice error" role="alert"><AppIcon name="alert" :size="16" /> {{ error }}</p>

    <div v-if="session.isOwnerView" class="grid-main-side">
      <div class="section-stack">
      <section class="card">
        <div class="card-heading"><div><p class="eyebrow">明确同意与二次确认</p><h3 class="card-title">注册或重新绑定</h3></div></div>
        <p class="card-note">打开语音后按屏幕提示一步步拍摄，家人可在旁协助；画面只在本机处理，不上传照片。</p>
        <p v-if="session.authMode !== 'session'" class="notice warn" role="status"><AppIcon name="lock" :size="16" /> 调试身份只能读取家庭数据；注册人脸凭证需要家庭账号登录。</p>
        <form class="section-stack" @submit.prevent="registerCredential">
          <label class="field">家庭登录名<select v-model="selectedActorId" required><option v-for="option in actorOptions" :key="option.id" :value="option.id">{{ option.label }}</option></select></label>
          <FaceVideoCapture
            mode="registration"
            :disabled="saving || !selectedActorId"
            :show-fallback="false"
            @captured="onFramesCaptured"
          />
          <p v-if="selectedFrames.length > 0" class="notice ok" role="status">
            <AppIcon name="check" :size="16" />
            三张照片已拍好。请确认下方数字密码（或登录密码）与同意项，再点「完成注册」。
          </p>
          <fieldset><legend>二次确认方式</legend><label class="check-row"><input v-model="confirmationMethod" type="radio" value="pin" /> 数字密码</label><label class="check-row"><input v-model="confirmationMethod" type="radio" value="password" /> 账号密码</label></fieldset>
          <label class="field">{{ confirmationMethod === 'pin' ? '六位数字密码' : '账号密码' }}<input v-model="confirmationCode" type="password" :inputmode="confirmationMethod === 'pin' ? 'numeric' : 'text'" autocomplete="off" required /></label>
          <label class="check-row"><input v-model="replaceExisting" type="checkbox" /> 已有凭证时重新绑定</label>
          <label class="check-row"><input v-model="consent" type="checkbox" required /> 我已获得本人明确同意，允许为所选家庭账号注册人脸凭证。</label>
          <p v-if="registrationBlockReason" class="notice warn" role="status"><AppIcon name="info" :size="16" /> {{ registrationBlockReason }}</p>
          <button type="submit" class="btn btn-primary" :disabled="!canRegisterCredential">
            <AppIcon name="shield" :size="15" />
            {{ saving ? '正在保存…' : '完成注册' }}
          </button>
        </form>
      </section>

      <section ref="credentialListEl" class="card face-credential-list-anchor">
        <div class="card-heading"><div><p class="eyebrow">凭证清单</p><h3 class="card-title">当前家庭的注册记录</h3></div></div>
        <p v-if="legacyCredentials.length > 0" class="notice warn" role="status">
          <AppIcon name="info" :size="16" />
          有 {{ legacyCredentials.length }} 条旧版凭证仍可登录，但成员区分较弱；建议重新绑定以提升识别效果。
        </p>
        <div v-if="loading" class="inline-loading">正在读取凭证状态</div>
        <div v-else-if="visibleCredentials.length === 0" class="empty-state"><AppIcon class="empty-art" name="shield" :size="38" /><strong>暂无人脸凭证</strong><p>注册成功后这里只显示版本和状态，不显示模板或原始图片。</p></div>
        <ul v-else class="list-plain">
          <li
            v-for="credential in visibleCredentials"
            :key="credential.id"
            class="row-card"
            :class="{ 'is-just-registered': credential.id === highlightCredentialId }"
          >
            <div>
              <span class="row-title">{{ actorOptions.find(option => option.id === credential.actor_id)?.label ?? '家庭成员' }}</span>
              <p class="row-meta">{{ credentialMetaLine(credential) }}</p>
              <p v-if="credential.upgrade_recommended && credential.status === 'ACTIVE'" class="row-meta">建议重新绑定以提升家庭内识别效果。</p>
            </div>
            <div class="heading-actions">
              <span class="pill" :class="credential.status === 'ACTIVE' ? 'pine' : 'plain'">{{ credentialStatusLabel(credential.status) }}</span>
              <button
                v-if="credential.status === 'ACTIVE' && credential.upgrade_recommended"
                type="button"
                class="btn btn-ghost btn-small"
                :disabled="saving"
                @click="beginRebind(credential)"
              >
                重新绑定
              </button>
              <button v-if="credential.status === 'ACTIVE'" type="button" class="btn btn-danger btn-small" :disabled="saving" @click="deleteCredential(credential)"><AppIcon name="trash" :size="14" /> 删除</button>
            </div>
          </li>
        </ul>
      </section>
      </div>

      <div class="section-stack">
        <section class="card">
          <div class="card-heading"><div><p class="eyebrow">本机登录范围</p><h3 class="card-title">绑定一个家庭</h3></div><AppIcon name="home" :size="20" style="color: var(--sky)" /></div>
          <p class="card-note">人脸识别只在绑定家庭的成员中进行，不跨家庭搜索；绑定后欢迎页可直接识别成员进入对应账号。</p>
          <p class="notice" :class="boundFaceHouseholdId === session.selectedHouseholdId ? 'ok' : 'warn'" role="status">
            <AppIcon :name="boundFaceHouseholdId ? 'check' : 'info'" :size="16" />
            {{ boundFaceHouseholdId ? `当前绑定家庭：${boundFaceHouseholdLabel}` : '本机尚未绑定家庭' }}
          </p>
          <div class="row-actions">
            <button type="button" class="btn btn-primary btn-small" :disabled="!session.selectedHouseholdId || boundFaceHouseholdId === session.selectedHouseholdId" @click="bindCurrentHouseholdToDevice">绑定当前家庭</button>
            <button v-if="boundFaceHouseholdId" type="button" class="btn btn-ghost btn-small" @click="clearDeviceFaceHousehold">解除绑定</button>
          </div>
        </section>

        <section v-if="unboundMembers.length > 0" class="card">
          <div class="card-heading"><div><p class="eyebrow">先绑定家庭登录名</p><h3 class="card-title">给成员分配登录名</h3></div><AppIcon name="members" :size="20" style="color: var(--sky)" /></div>
          <p class="card-note">成员有登录名后，才能用刷脸或数字密码进入自己的家庭账号。</p>
          <form class="section-stack" @submit.prevent="bindMemberAccount">
            <label class="field">成员<select v-model="accountMemberId" required><option value="" disabled>请选择成员</option><option v-for="member in unboundMembers" :key="member.id" :value="member.id">{{ member.display_name }}</option></select></label>
            <label class="field">登录名<input v-model="accountActorId" autocomplete="username" required placeholder="例如 grandpa-1" /><small>只用于本地家庭登录，不是姓名，也不要填密码。</small></label>
            <p v-if="accountBindingError" class="notice error" role="alert"><AppIcon name="alert" :size="16" /> {{ accountBindingError }}</p>
            <button type="submit" class="btn btn-primary" :disabled="accountBindingSaving || !accountMemberId || !accountActorId.trim()"><AppIcon name="key" :size="15" /> {{ accountBindingSaving ? '正在绑定' : '绑定登录名' }}</button>
          </form>
        </section>

        <section class="card">
          <div class="card-heading"><div><p class="eyebrow">家庭账号安全</p><h3 class="card-title">设置数字密码</h3></div></div>
          <p class="form-sub">数字密码绑定当前登录名与当前家庭；每个家庭登录名可分别设置六位数字密码。</p>
          <form class="section-stack" @submit.prevent="savePin">
            <label class="field">六位数字密码<input v-model="pinDraft" type="password" inputmode="numeric" autocomplete="new-password" pattern="[0-9]{6}" maxlength="6" required placeholder="例如 123456" /></label>
            <label class="field">再次输入数字密码<input v-model="pinConfirmation" type="password" inputmode="numeric" autocomplete="new-password" pattern="[0-9]{6}" maxlength="6" required placeholder="再次输入六位数字" /></label>
            <p v-if="pinError" class="notice error" role="alert"><AppIcon name="alert" :size="16" /> {{ pinError }}</p>
            <p v-if="pinSuccess" class="notice ok" role="status"><AppIcon name="check" :size="16" /> {{ pinSuccess }}</p>
            <button type="submit" class="btn btn-primary" :disabled="pinSaving || !/^\d{6}$/.test(pinDraft) || pinDraft !== pinConfirmation"><AppIcon name="key" :size="15" /> {{ pinSaving ? '正在保存' : '保存数字密码' }}</button>
          </form>
        </section>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 图八：去掉页面内嵌的第二层 view-container，改为普通纵向栈。 */
.face-credential-page {
  display: grid;
  align-content: start;
  gap: 16px;
}
</style>
