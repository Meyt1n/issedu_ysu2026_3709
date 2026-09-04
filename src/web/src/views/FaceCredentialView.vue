<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'

import { apiClient } from '../api/client'
import type { FaceCredential } from '../api/types'
import AppIcon from '../components/AppIcon.vue'
import FaceVideoCapture from '../components/FaceVideoCapture.vue'
import {
  createIdempotencyKey,
  formatError,
  pushToast,
  refreshMembers,
  requestOptions,
  session,
} from '../store'
import { askConfirm } from '../ui/confirm'
import { formatDateTime } from '../ui/labels'
import { canSubmitMemberSetup, memberSetupValidationMessage } from '../ui/memberSetup'
import {
  beginPinEdit,
  cancelPinEdit,
  emptyPinRow,
  markConfiguredPinRows,
  markPinSaved,
  pinRowCanSubmit,
  pinRowIsLocked,
  pinRowSubmitLabel,
  type PinRowState,
} from '../ui/pinSetup'

const credentials = ref<FaceCredential[]>([])
const visibleCredentials = computed(() => credentials.value.filter(credential => credential.status !== 'DELETED'))
const selectedActorId = ref('')
const confirmationMethod = ref<'password'>('password')
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
const pinRows = reactive<Record<string, PinRowState>>({})
const pinSavingId = ref('')
const accountMemberId = ref('')
const accountActorId = ref('')
const accountBindingSaving = ref(false)
const accountBindingError = ref('')
const newMemberName = ref('')
const newMemberActorId = ref('')
const newMemberSaving = ref(false)
const newMemberError = ref('')
const confirmationCodeValid = computed(() => {
  const code = confirmationCode.value.trim()
  return code.length >= 8 && code.length <= 256
})
const registrationBlockReason = computed(() => {
  if (session.authMode !== 'session') return '请先用家庭账号登录。'
  if (!session.isOwnerView) return '只有家庭管理员可以在本页设置 PIN 和录入人脸。'
  if (!session.selectedHouseholdId) return '请先选择一个家庭。'
  if (!selectedActorId.value) return '请先选择要绑定人脸的登录名。'
  if (selectedFrames.value.length < 2) return '请先完成三张采集。'
  if (!confirmationCodeValid.value) return '请输入当前账号密码。'
  if (!consent.value) return '请先勾选本人明确同意。'
  return ''
})
const canRegisterCredential = computed(() => !saving.value && !registrationBlockReason.value)

const newMemberValidation = computed(() => {
  if (!newMemberName.value.trim() && !newMemberActorId.value.trim()) return ''
  return memberSetupValidationMessage(newMemberName.value, newMemberActorId.value)
})
const canCreateMember = computed(() =>
  canSubmitMemberSetup(newMemberName.value, newMemberActorId.value, newMemberSaving.value),
)

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

const pinSavedCount = computed(
  () => actorOptions.value.filter(option => pinRows[option.id]?.saved).length,
)

const faceReadyActorIds = computed(() =>
  new Set(
    visibleCredentials.value
      .filter(credential => credential.status === 'ACTIVE')
      .map(credential => credential.actor_id),
  ),
)

function ensurePinRow(actorId: string): PinRowState {
  if (!pinRows[actorId]) {
    pinRows[actorId] = emptyPinRow()
  }
  return pinRows[actorId]
}

function resetNewMemberForm(): void {
  newMemberName.value = ''
  newMemberActorId.value = ''
  newMemberError.value = ''
}

function startPinEdit(actorId: string): void {
  beginPinEdit(ensurePinRow(actorId))
}

function abortPinEdit(actorId: string): void {
  cancelPinEdit(ensurePinRow(actorId))
}

function clearPinRows(): void {
  for (const actorId of Object.keys(pinRows)) delete pinRows[actorId]
}

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

async function savePinFor(actorId: string): Promise<void> {
  const householdId = session.selectedHouseholdId
  const row = ensurePinRow(actorId)
  row.error = ''
  if (!householdId) {
    row.error = '请先选择家庭。'
    return
  }
  if (!/^\d{6}$/.test(row.pin)) {
    row.error = '请输入六位数字。'
    return
  }
  if (row.pin !== row.confirm) {
    row.error = '两次输入的数字不一致。'
    return
  }
  if (pinRowIsLocked(row)) {
    return
  }

  pinSavingId.value = actorId
  try {
    await apiClient.setPin(householdId, row.pin, requestOptions.value, actorId)
    const wasChange = row.saved
    markPinSaved(row)
    const label = actorOptions.value.find(option => option.id === actorId)?.label ?? '这位家人'
    pushToast('success', wasChange ? `已修改${label}的六位数字密码。` : `已保存${label}的六位数字密码。`)
  } catch (cause) {
    row.error = formatError(cause)
  } finally {
    pinSavingId.value = ''
  }
}

async function loadCredentials(): Promise<boolean> {
  const householdId = session.selectedHouseholdId
  if (!householdId || !session.isOwnerView) return false
  loading.value = true
  error.value = ''
  try {
    credentials.value = await apiClient.listFaceCredentials(householdId, requestOptions.value)
    try {
      const pinStatus = await apiClient.listPinStatus(householdId, requestOptions.value)
      for (const option of actorOptions.value) ensurePinRow(option.id)
      markConfiguredPinRows(pinRows, pinStatus.configured_actor_ids)
    } catch {
      // 旧 API 没有状态端点时，仍用本页第一次保存后的锁定态。
    }
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
  pushToast('success', '三张已拍好，请输入密码后完成注册。')
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
    pushToast('success', '成员登录名已绑定，现在可以在第一步为他设置 PIN。')
  } catch (cause) {
    accountBindingError.value = formatError(cause)
  } finally {
    accountBindingSaving.value = false
  }
}

async function createFamilyMember(): Promise<void> {
  const householdId = session.selectedHouseholdId
  const displayName = newMemberName.value.trim()
  const actorId = newMemberActorId.value.trim()
  newMemberError.value = ''
  if (!householdId) {
    newMemberError.value = '请先选择家庭。'
    return
  }
  const validation = memberSetupValidationMessage(displayName, actorId)
  if (validation) {
    newMemberError.value = validation
    return
  }

  newMemberSaving.value = true
  try {
    const member = await apiClient.createMember(
      householdId,
      { display_name: displayName, role: 'DEPENDENT', actor_id: actorId },
      { ...requestOptions.value, idempotencyKey: createIdempotencyKey() },
    )
    await refreshMembers()
    ensurePinRow(member.actor_id ?? actorId)
    resetNewMemberForm()
    pushToast('success', `已添加${member.display_name}。请继续为他设置六位数字密码，保存后即可在成员前台选人登录。`)
  } catch (cause) {
    newMemberError.value = formatError(cause)
  } finally {
    newMemberSaving.value = false
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
      ? `重新绑定成功：${actorLabel} 的人脸已更新。成员前台可刷脸进入。`
      : `录入成功：${actorLabel} 的人脸已保存。成员前台可刷脸进入。`
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
  clearPinRows()
  resetNewMemberForm()
  resetForm()
  void loadCredentials()
})
watch(actorOptions, options => {
  if (!options.some(option => option.id === selectedActorId.value)) resetForm()
  for (const option of options) ensurePinRow(option.id)
}, { immediate: true })
onMounted(() => {
  resetForm()
  void loadCredentials()
})
</script>

<template>
  <div class="face-credential-page">
    <div class="page-heading">
      <div>
        <p class="eyebrow">注册后请按顺序完成</p>
        <h1>家人登录设置</h1>
        <p class="page-subtitle">
          第一步必做：给每位家人（含家庭管理员）设置六位数字密码。第二步选做：给需要刷脸进入的人录入人脸。管理员登录后这台电脑会自动绑定，做完即可去成员前台刷脸或 PIN 选人。
        </p>
      </div>
      <button type="button" class="btn btn-ghost" :disabled="loading" @click="loadCredentials"><AppIcon name="refresh" :size="15" /> 刷新</button>
    </div>

    <p v-if="!session.isOwnerView" class="notice warn" role="alert"><AppIcon name="shield" :size="16" /> 只有家庭管理员可以设置 PIN 和录入人脸。</p>
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

    <div v-if="session.isOwnerView" class="section-stack">
      <section class="card" data-testid="member-pin-setup">
        <div class="card-heading">
          <div>
            <p class="eyebrow">第一步 · 必做</p>
            <h3 class="card-title">给每位家人设置六位数字密码</h3>
          </div>
          <span class="pill pine">{{ pinSavedCount }}/{{ actorOptions.length }} 已设置</span>
        </div>
        <p class="notice warn" role="status">
          <AppIcon name="info" :size="16" />
          家庭管理员和每位家人都要各设一组。成员前台登录时：管理员账号 → 选人 → 输入这里保存的数字。忘记管理员密码时也可以用同一组数字本地恢复。
        </p>

        <div class="member-add-panel">
          <div>
            <p class="eyebrow">家庭成员</p>
            <h4 class="card-title">新增家人</h4>
            <p class="form-sub">添加后会同步到成员前台和后台的成员选择器；还需在下面保存六位数字密码，家人才可以登录。</p>
          </div>
          <form class="member-add-form" data-testid="add-member-form" @submit.prevent="createFamilyMember">
            <label class="field">
              家人称呼
              <input v-model="newMemberName" required maxlength="120" autocomplete="name" placeholder="例如 奶奶" />
            </label>
            <label class="field">
              登录名
              <input
                v-model="newMemberActorId"
                required
                maxlength="120"
                autocomplete="username"
                pattern="[A-Za-z0-9][A-Za-z0-9._:-]{0,119}"
                placeholder="例如 grandma-1"
              />
              <small>用于登录和 PIN 绑定，只能使用字母、数字、点、下划线、冒号或短横线。</small>
            </label>
            <p v-if="newMemberError || newMemberValidation" class="notice error" role="alert">
              <AppIcon name="alert" :size="16" /> {{ newMemberError || newMemberValidation }}
            </p>
            <button type="submit" class="btn btn-ghost" data-testid="add-member-submit" :disabled="!canCreateMember">
              <AppIcon name="plus" :size="15" /> {{ newMemberSaving ? '正在添加' : '新增成员' }}
            </button>
          </form>
        </div>

        <form v-if="unboundMembers.length > 0" class="section-stack" @submit.prevent="bindMemberAccount">
          <p class="form-sub">还有成员没有登录名，先补上才能出现在下面名单里。</p>
          <label class="field">成员<select v-model="accountMemberId" required><option value="" disabled>请选择成员</option><option v-for="member in unboundMembers" :key="member.id" :value="member.id">{{ member.display_name }}</option></select></label>
          <label class="field">登录名<input v-model="accountActorId" autocomplete="username" required placeholder="例如 grandpa-1" /><small>只用于本地家庭登录，不是姓名。</small></label>
          <p v-if="accountBindingError" class="notice error" role="alert"><AppIcon name="alert" :size="16" /> {{ accountBindingError }}</p>
          <button type="submit" class="btn btn-ghost" :disabled="accountBindingSaving || !accountMemberId || !accountActorId.trim()"><AppIcon name="key" :size="15" /> {{ accountBindingSaving ? '正在绑定' : '绑定登录名' }}</button>
        </form>

        <div v-if="actorOptions.length === 0" class="empty-state">
          <strong>还没有可设置 PIN 的家人</strong>
          <p>请先在创建家庭时填写登录账号，或在上面为成员绑定登录名。</p>
        </div>
        <ul v-else class="list-plain pin-person-list">
          <li v-for="option in actorOptions" :key="option.id" class="row-card pin-person-row">
            <div>
              <span class="row-title">{{ option.label }}</span>
              <span v-if="pinRowIsLocked(pinRows[option.id])" class="pill pine">已设置</span>
              <span v-else-if="pinRows[option.id]?.editing" class="pill gold">正在修改</span>
              <p class="row-meta">{{ option.id === session.actorId ? '家庭管理员也需要一组数字，用于找回密码。' : '成员前台选中这位家人后输入这组数字。' }}</p>
            </div>
            <div v-if="pinRowIsLocked(pinRows[option.id])" class="pin-person-locked">
              <p class="row-meta">已设置六位数字，页面不会回显。更换时请点「修改」。</p>
              <button
                type="button"
                class="btn btn-ghost btn-small"
                data-testid="pin-edit"
                :aria-label="`修改${option.label}的六位数字密码`"
                @click="startPinEdit(option.id)"
              >
                修改
              </button>
            </div>
            <form
              v-else-if="pinRows[option.id]"
              class="pin-person-fields"
              data-testid="pin-save-form"
              @submit.prevent="savePinFor(option.id)"
            >
              <label class="field">六位数字<input v-model="pinRows[option.id].pin" type="password" inputmode="numeric" autocomplete="new-password" pattern="[0-9]{6}" maxlength="6" required placeholder="123456" :aria-label="`${option.label}的六位数字密码`" /></label>
              <label class="field">再输入一次<input v-model="pinRows[option.id].confirm" type="password" inputmode="numeric" autocomplete="new-password" pattern="[0-9]{6}" maxlength="6" required placeholder="再次输入" :aria-label="`${option.label}再次输入数字密码`" /></label>
              <button
                type="submit"
                class="btn btn-primary btn-small"
                data-testid="pin-save"
                :disabled="pinSavingId === option.id || !pinRowCanSubmit(pinRows[option.id])"
              >
                {{ pinRowSubmitLabel(pinRows[option.id], pinSavingId === option.id) }}
              </button>
              <button
                v-if="pinRows[option.id]?.editing"
                type="button"
                class="btn btn-ghost btn-small"
                data-testid="pin-edit-cancel"
                @click="abortPinEdit(option.id)"
              >
                取消
              </button>
              <p v-if="pinRows[option.id]?.error" class="notice error" role="alert">{{ pinRows[option.id].error }}</p>
            </form>
          </li>
        </ul>
      </section>

      <section class="card">
        <div class="card-heading">
          <div>
            <p class="eyebrow">第二步 · 选做</p>
            <h3 class="card-title">给需要刷脸的人录入人脸</h3>
          </div>
        </div>
        <p class="notice" role="status">
          <AppIcon name="info" :size="16" />
          整步都可以跳过。管理员登录后台后，这台电脑会自动绑定当前家庭。给家人（含管理员）录入人脸后，成员前台就可以刷脸进入。
        </p>

        <p v-if="session.authMode !== 'session'" class="notice warn" role="status"><AppIcon name="lock" :size="16" /> 录入人脸需要正式账号会话。</p>
        <form class="section-stack" @submit.prevent="registerCredential">
          <label class="field">
            给谁录入
            <select v-model="selectedActorId" required>
              <option v-for="option in actorOptions" :key="option.id" :value="option.id">
                {{ option.label }}{{ faceReadyActorIds.has(option.id) ? '（已录入）' : '' }}
              </option>
            </select>
          </label>
          <FaceVideoCapture
            mode="registration"
            :disabled="saving || !selectedActorId"
            :show-fallback="false"
            @captured="onFramesCaptured"
          />
          <p v-if="selectedFrames.length > 0" class="notice ok" role="status">
            <AppIcon name="check" :size="16" />
            三张照片已拍好。请输入账号密码并勾选同意后，再点「完成录入」。
          </p>
          <label class="field">
            账号密码
            <input
              v-model="confirmationCode"
              type="password"
              autocomplete="current-password"
              required
            />
          </label>
          <label class="check-row"><input v-model="replaceExisting" type="checkbox" /> 已有人脸时重新绑定</label>
          <label class="check-row"><input v-model="consent" type="checkbox" required /> 我已获得本人明确同意，允许为所选家人录入人脸。</label>
          <p v-if="registrationBlockReason" class="notice warn" role="status"><AppIcon name="info" :size="16" /> {{ registrationBlockReason }}</p>
          <button type="submit" class="btn btn-primary" :disabled="!canRegisterCredential">
            <AppIcon name="shield" :size="15" />
            {{ saving ? '正在保存…' : '完成录入' }}
          </button>
        </form>
      </section>

      <section ref="credentialListEl" class="card face-credential-list-anchor">
        <div class="card-heading"><div><p class="eyebrow">已录入的人脸</p><h3 class="card-title">当前家庭记录</h3></div></div>
        <p v-if="legacyCredentials.length > 0" class="notice warn" role="status">
          <AppIcon name="info" :size="16" />
          有 {{ legacyCredentials.length }} 条旧版记录仍可登录，但成员区分较弱；建议重新绑定。
        </p>
        <div v-if="loading" class="inline-loading">正在读取状态</div>
        <div v-else-if="visibleCredentials.length === 0" class="empty-state"><AppIcon class="empty-art" name="shield" :size="38" /><strong>还没有人脸记录</strong><p>第二步是选做。录入后这里只显示版本和状态，不显示照片。</p></div>
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
  </div>
</template>

<style scoped>
.face-credential-page {
  display: grid;
  align-content: start;
  gap: 16px;
}

.pin-person-list {
  display: grid;
  gap: 10px;
}

.member-add-panel {
  display: grid;
  gap: 12px;
  padding: 14px;
  border: 1px solid color-mix(in srgb, var(--line) 78%, var(--pine));
  border-radius: 14px;
  background: color-mix(in srgb, var(--card) 82%, var(--pine-tint));
}

.member-add-panel .card-title {
  margin: 2px 0 4px;
}

.member-add-panel .form-sub {
  margin: 0;
}

.member-add-form {
  display: grid;
  gap: 10px;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) auto;
  align-items: start;
}

.member-add-form .notice {
  grid-column: 1 / -1;
  margin: 0;
}

@media (max-width: 840px) {
  .member-add-form {
    grid-template-columns: 1fr;
  }
}

.pin-person-row {
  align-items: start;
  display: grid;
  gap: 12px;
  grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.4fr);
}

.pin-person-fields {
  align-items: end;
  display: grid;
  gap: 8px;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) auto auto;
}

.pin-person-fields .notice {
  grid-column: 1 / -1;
}

.pin-person-locked {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  justify-content: space-between;
}

.pin-person-locked .row-meta {
  margin: 0;
}

@media (max-width: 840px) {
  .pin-person-row,
  .pin-person-fields {
    grid-template-columns: 1fr;
  }
}
</style>
