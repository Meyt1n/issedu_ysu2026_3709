<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import { apiClient } from '../api/client'
import type { FaceCredential } from '../api/types'
import AppIcon from '../components/AppIcon.vue'
import { formatError, pushToast, requestOptions, session } from '../store'
import { askConfirm } from '../ui/confirm'
import { formatDateTime } from '../ui/labels'

const credentials = ref<FaceCredential[]>([])
const visibleCredentials = computed(() => credentials.value.filter(credential => credential.status !== 'DELETED'))
const selectedActorId = ref('')
const confirmationMethod = ref<'pin' | 'password'>('pin')
const confirmationCode = ref('')
const selectedFile = ref<File | null>(null)
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
  selectedFile.value = null
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

function chooseFile(event: Event): void {
  selectedFile.value = (event.target as HTMLInputElement).files?.[0] ?? null
}

async function registerCredential(): Promise<void> {
  const householdId = session.selectedHouseholdId
  if (session.authMode !== 'session') {
    error.value = '人脸凭证注册需要正式账号会话，请先切换到“正式账号登录”。'
    return
  }
  if (!householdId || !selectedFile.value || !selectedActorId.value || !consent.value) {
    error.value = '请选择账号、图片并确认生物特征处理同意。'
    return
  }
  saving.value = true
  error.value = ''
  try {
    await apiClient.registerFaceCredential(
      householdId,
      selectedFile.value,
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
        <p class="page-subtitle">仅保存加密特征与版本元数据；本页面不实现人脸登录匹配或活体检测。</p>
      </div>
      <button type="button" class="btn btn-ghost" :disabled="loading" @click="loadCredentials"><AppIcon name="refresh" :size="15" /> 刷新</button>
    </div>

    <p v-if="!session.isOwnerView" class="notice warn" role="alert"><AppIcon name="shield" :size="16" /> 只有家庭管理员可以管理人脸凭证。</p>
    <p v-if="error" class="notice error" role="alert"><AppIcon name="alert" :size="16" /> {{ error }}</p>

    <div v-if="session.isOwnerView" class="grid-main-side">
      <section class="card">
        <div class="card-heading"><div><p class="eyebrow">明确同意与二次确认</p><h3 class="card-title">注册或重新绑定</h3></div></div>
        <p v-if="session.authMode !== 'session'" class="notice warn" role="status"><AppIcon name="lock" :size="16" /> 开发演示身份只能读取家庭数据；注册人脸凭证需要正式账号会话。</p>
        <form class="section-stack" @submit.prevent="registerCredential">
          <label class="field">家庭账号<select v-model="selectedActorId" required><option v-for="option in actorOptions" :key="option.id" :value="option.id">{{ option.label }} · {{ option.id }}</option></select></label>
          <label class="field">注册图片<input type="file" accept="image/jpeg,image/png" required @change="chooseFile" /><small>请上传至少 640×480 的 JPG/PNG 正面照片：只保留一张人脸，光线均匀、避免反光和模糊，不要裁切脸部；处理完成后不保存原图。</small></label>
          <fieldset><legend>二次确认方式</legend><label class="check-row"><input v-model="confirmationMethod" type="radio" value="pin" /> 家庭 PIN</label><label class="check-row"><input v-model="confirmationMethod" type="radio" value="password" /> 账号密码</label></fieldset>
          <label class="field">{{ confirmationMethod === 'pin' ? '六位 PIN' : '账号密码' }}<input v-model="confirmationCode" type="password" :inputmode="confirmationMethod === 'pin' ? 'numeric' : 'text'" autocomplete="off" required /></label>
          <label class="check-row"><input v-model="replaceExisting" type="checkbox" /> 已有凭证时重新绑定</label>
          <label class="check-row"><input v-model="consent" type="checkbox" required /> 我已获得本人明确同意，允许为所选家庭账号注册人脸凭证。</label>
          <button type="submit" class="btn btn-primary" :disabled="session.authMode !== 'session' || saving || !selectedFile || !consent"><AppIcon name="shield" :size="15" /> {{ saving ? '处理中…' : '注册凭证' }}</button>
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
