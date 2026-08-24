<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

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
  if (session.authMode !== 'session') return '当前是开发演示身份，请返回欢迎页切换到“正式账号登录”。'
  if (!session.isOwnerView) return '只有家庭管理员可以注册人脸凭证。'
  if (!session.selectedHouseholdId) return '请先选择一个家庭。'
  if (!selectedActorId.value) return '请先选择要绑定人脸的家庭账号。'
  if (selectedFrames.value.length < 2) return '请先点击“开始动态采集”，完成至少两帧画面。'
  if (!confirmationCodeValid.value) {
    return confirmationMethod.value === 'pin' ? '请输入已设置的六位家庭 PIN。' : '请输入当前正式账号密码（至少八位）。'
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

function bindCurrentHouseholdToDevice(): void {
  const householdId = session.selectedHouseholdId
  if (!householdId) return
  const household = session.households.find(item => item.id === householdId)
  bindFaceHousehold(householdId, household?.name ?? '')
  boundFaceHouseholdId.value = householdId
  pushToast('success', '本机人脸登录家庭已绑定，只会在这个家庭内自动识别成员。')
}

function clearDeviceFaceHousehold(): void {
  clearBoundFaceHousehold()
  boundFaceHouseholdId.value = ''
  pushToast('info', '已解除本机人脸登录家庭绑定。')
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
}

async function bindMemberAccount(): Promise<void> {
  const householdId = session.selectedHouseholdId
  const memberId = accountMemberId.value
  const actorId = accountActorId.value.trim()
  accountBindingError.value = ''
  if (!householdId || !memberId || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$/.test(actorId)) {
    accountBindingError.value = '请选择成员，并填写字母、数字、点、下划线或短横线组成的账号 ID。'
    return
  }
  accountBindingSaving.value = true
  try {
    await apiClient.bindMemberAccount(householdId, memberId, { actor_id: actorId }, requestOptions.value)
    await refreshMembers()
    accountActorId.value = ''
    accountMemberId.value = ''
    pushToast('success', '成员登录账号已绑定，现在可以为他采集动态人脸凭证。')
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
    return
  }
  saving.value = true
  error.value = ''
  try {
    await apiClient.registerFaceCredential(
      householdId,
      selectedFrames.value,
      {
        consent: true,
        targetActorId: selectedActorId.value,
        replaceExisting: replaceExisting.value,
        confirmationMethod: confirmationMethod.value,
        confirmationCode: confirmationCode.value,
      },
      requestOptions.value,
    )
    pushToast('success', replaceExisting.value ? '人脸凭证已重新绑定。' : '人脸凭证已注册。')
    resetForm()
    await loadCredentials()
  } catch (cause) {
    error.value = formatError(cause)
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
  <div class="view-container">
    <div class="page-heading">
      <div>
        <p class="eyebrow">家庭账号安全</p>
        <h1>人脸凭证注册</h1>
        <p class="page-subtitle">为家庭成员采集三帧动态画面；后端完成活体检查，只保存加密特征，不保存视频原片。</p>
      </div>
      <button type="button" class="btn btn-ghost" :disabled="loading" @click="loadCredentials"><AppIcon name="refresh" :size="15" /> 刷新</button>
    </div>

    <p v-if="!session.isOwnerView" class="notice warn" role="alert"><AppIcon name="shield" :size="16" /> 只有家庭管理员可以管理人脸凭证。</p>
    <p v-if="error" class="notice error" role="alert"><AppIcon name="alert" :size="16" /> {{ error }}</p>

    <div v-if="session.isOwnerView" class="grid-main-side">
      <section class="card">
        <div class="card-heading"><div><p class="eyebrow">本机登录范围</p><h3 class="card-title">绑定一个家庭</h3></div><AppIcon name="home" :size="20" style="color: var(--sky)" /></div>
        <p class="card-note">人脸自动识别只在绑定家庭的成员中进行，不会跨家庭搜索。绑定后，欢迎页可以直接识别爷爷、奶奶等成员并进入对应小账号。</p>
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
        <div class="card-heading"><div><p class="eyebrow">先绑定家庭账号</p><h3 class="card-title">给成员分配登录账号</h3></div><AppIcon name="members" :size="20" style="color: var(--sky)" /></div>
        <p class="card-note">当前家庭有成员还没有登录账号。先绑定一个账号 ID，成员才能用人脸或 PIN 快速进入自己的家庭账号。</p>
        <form class="section-stack" @submit.prevent="bindMemberAccount">
          <label class="field">成员<select v-model="accountMemberId" required><option value="" disabled>请选择成员</option><option v-for="member in unboundMembers" :key="member.id" :value="member.id">{{ member.display_name }}</option></select></label>
          <label class="field">登录账号 ID<input v-model="accountActorId" autocomplete="username" required placeholder="例如 grandpa-1" /><small>只用于本地家庭登录，不是姓名，也不要填密码。</small></label>
          <p v-if="accountBindingError" class="notice error" role="alert"><AppIcon name="alert" :size="16" /> {{ accountBindingError }}</p>
          <button type="submit" class="btn btn-primary" :disabled="accountBindingSaving || !accountMemberId || !accountActorId.trim()"><AppIcon name="key" :size="15" /> {{ accountBindingSaving ? '正在绑定' : '绑定登录账号' }}</button>
        </form>
      </section>
      <section class="card">
        <div class="card-heading"><div><p class="eyebrow">明确同意与二次确认</p><h3 class="card-title">注册或重新绑定</h3></div></div>
        <p v-if="session.authMode !== 'session'" class="notice warn" role="status"><AppIcon name="lock" :size="16" /> 开发演示身份只能读取家庭数据；注册人脸凭证需要正式账号会话。</p>
        <form class="section-stack" @submit.prevent="registerCredential">
          <label class="field">家庭账号<select v-model="selectedActorId" required><option v-for="option in actorOptions" :key="option.id" :value="option.id">{{ option.label }} · {{ option.id }}</option></select></label>
          <FaceVideoCapture
            mode="registration"
            :disabled="saving || !selectedActorId"
            :show-fallback="false"
            @captured="onFramesCaptured"
          />
          <p v-if="selectedFrames.length > 0" class="notice ok" role="status"><AppIcon name="check" :size="16" /> 已准备 {{ selectedFrames.length }} 帧动态画面，点击注册后才会提交到本地 API。</p>
          <fieldset><legend>二次确认方式</legend><label class="check-row"><input v-model="confirmationMethod" type="radio" value="pin" /> 家庭 PIN</label><label class="check-row"><input v-model="confirmationMethod" type="radio" value="password" /> 账号密码</label></fieldset>
          <label class="field">{{ confirmationMethod === 'pin' ? '六位 PIN' : '账号密码' }}<input v-model="confirmationCode" type="password" :inputmode="confirmationMethod === 'pin' ? 'numeric' : 'text'" autocomplete="off" required /></label>
          <label class="check-row"><input v-model="replaceExisting" type="checkbox" /> 已有凭证时重新绑定</label>
          <label class="check-row"><input v-model="consent" type="checkbox" required /> 我已获得本人明确同意，允许为所选家庭账号注册人脸凭证。</label>
          <p v-if="registrationBlockReason" class="notice warn" role="status"><AppIcon name="info" :size="16" /> {{ registrationBlockReason }}</p>
          <button type="submit" class="btn btn-primary" :disabled="!canRegisterCredential"><AppIcon name="shield" :size="15" /> {{ saving ? '正在校验动态画面…' : '注册动态人脸凭证' }}</button>
        </form>
      </section>

      <section class="card">
        <div class="card-heading"><div><p class="eyebrow">家庭账号安全</p><h3 class="card-title">设置家庭 PIN</h3></div></div>
        <p class="form-sub">PIN 绑定当前登录身份 <strong>{{ session.actorId }}</strong> 和当前家庭 <strong>{{ session.selectedHouseholdId }}</strong>；每个家庭身份可以分别设置自己的六位 PIN。</p>
        <form class="section-stack" @submit.prevent="savePin">
          <label class="field">六位数字 PIN<input v-model="pinDraft" type="password" inputmode="numeric" autocomplete="new-password" pattern="[0-9]{6}" maxlength="6" required placeholder="例如 123456" /></label>
          <label class="field">再次输入 PIN<input v-model="pinConfirmation" type="password" inputmode="numeric" autocomplete="new-password" pattern="[0-9]{6}" maxlength="6" required placeholder="再次输入六位 PIN" /></label>
          <p v-if="pinError" class="notice error" role="alert"><AppIcon name="alert" :size="16" /> {{ pinError }}</p>
          <p v-if="pinSuccess" class="notice ok" role="status"><AppIcon name="check" :size="16" /> {{ pinSuccess }}</p>
          <button type="submit" class="btn btn-primary" :disabled="pinSaving || !/^\d{6}$/.test(pinDraft) || pinDraft !== pinConfirmation"><AppIcon name="key" :size="15" /> {{ pinSaving ? '正在保存' : '保存家庭 PIN' }}</button>
        </form>
      </section>

      <section class="card">
        <div class="card-heading"><div><p class="eyebrow">凭证清单</p><h3 class="card-title">当前家庭的注册记录</h3></div></div>
        <div v-if="loading" class="inline-loading">正在读取凭证状态</div>
        <div v-else-if="visibleCredentials.length === 0" class="empty-state"><AppIcon class="empty-art" name="shield" :size="38" /><strong>暂无人脸凭证</strong><p>注册成功后这里只显示版本和状态，不显示模板或原始图片。</p></div>
        <ul v-else class="list-plain">
          <li v-for="credential in visibleCredentials" :key="credential.id" class="row-card">
            <div><span class="row-title">{{ actorOptions.find(option => option.id === credential.actor_id)?.label ?? credential.actor_id }}</span><p class="row-meta">版本 {{ credential.credential_version }} · {{ credential.algorithm_version }} · {{ formatDateTime(credential.created_at) }}</p></div>
            <div class="heading-actions"><span class="pill" :class="credential.status === 'ACTIVE' ? 'pine' : 'plain'">{{ credential.status }}</span><button v-if="credential.status === 'ACTIVE'" type="button" class="btn btn-danger btn-small" :disabled="saving" @click="deleteCredential(credential)"><AppIcon name="trash" :size="14" /> 删除</button></div>
          </li>
        </ul>
      </section>
    </div>
  </div>
</template>
