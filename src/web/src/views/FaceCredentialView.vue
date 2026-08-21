<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import { apiClient } from '../api/client'
import type { FaceCredential } from '../api/types'
import AppIcon from '../components/AppIcon.vue'
import { formatError, pushToast, requestOptions, session } from '../store'
import { askConfirm } from '../ui/confirm'
import { formatDateTime } from '../ui/labels'

const credentials = ref<FaceCredential[]>([])
const selectedActorId = ref('')
const confirmationMethod = ref<'pin' | 'password'>('pin')
const confirmationCode = ref('')
const selectedFile = ref<File | null>(null)
const consent = ref(false)
const replaceExisting = ref(false)
const loading = ref(false)
const saving = ref(false)
const error = ref('')

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

async function loadCredentials(): Promise<void> {
  const householdId = session.selectedHouseholdId
  if (!householdId || !session.isOwnerView) return
  loading.value = true
  error.value = ''
  try {
    credentials.value = await apiClient.listFaceCredentials(householdId, requestOptions.value)
    if (!selectedActorId.value) resetForm()
  } catch (cause) {
    credentials.value = []
    error.value = formatError(cause)
  } finally {
    loading.value = false
  }
}

function chooseFile(event: Event): void {
  selectedFile.value = (event.target as HTMLInputElement).files?.[0] ?? null
}

async function registerCredential(): Promise<void> {
  const householdId = session.selectedHouseholdId
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
  const accepted = await askConfirm({
    title: '删除人脸凭证',
    message: '删除后该凭证立即失效，服务器会清空加密模板。此操作不会删除家庭账号。',
    confirmText: '删除凭证',
  })
  if (!accepted || !session.selectedHouseholdId) return
  saving.value = true
  try {
    await apiClient.deleteFaceCredential(session.selectedHouseholdId, credential.id, requestOptions.value)
    pushToast('success', '人脸凭证已删除并立即失效。')
    await loadCredentials()
  } catch (cause) {
    error.value = formatError(cause)
  } finally {
    saving.value = false
  }
}

watch(() => session.selectedHouseholdId, () => {
  resetForm()
  void loadCredentials()
})
watch(actorOptions, options => {
  if (!options.some(option => option.id === selectedActorId.value)) resetForm()
})
onMounted(() => {
  resetForm()
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
        <form class="section-stack" @submit.prevent="registerCredential">
          <label class="field">家庭账号<select v-model="selectedActorId" required><option v-for="option in actorOptions" :key="option.id" :value="option.id">{{ option.label }} · {{ option.id }}</option></select></label>
          <label class="field">注册图片<input type="file" accept="image/jpeg,image/png" required @change="chooseFile" /><small>只上传一张清晰、仅包含目标人员的 JPG 或 PNG；处理完成后不保存原图。</small></label>
          <fieldset><legend>二次确认方式</legend><label class="check-row"><input v-model="confirmationMethod" type="radio" value="pin" /> 家庭 PIN</label><label class="check-row"><input v-model="confirmationMethod" type="radio" value="password" /> 账号密码</label></fieldset>
          <label class="field">{{ confirmationMethod === 'pin' ? '六位 PIN' : '账号密码' }}<input v-model="confirmationCode" type="password" :inputmode="confirmationMethod === 'pin' ? 'numeric' : 'text'" autocomplete="off" required /></label>
          <label class="check-row"><input v-model="replaceExisting" type="checkbox" /> 已有凭证时重新绑定</label>
          <label class="check-row"><input v-model="consent" type="checkbox" required /> 我已获得本人明确同意，允许为所选家庭账号注册人脸凭证。</label>
          <button type="submit" class="btn btn-primary" :disabled="saving || !selectedFile || !consent"><AppIcon name="shield" :size="15" /> {{ saving ? '处理中…' : '注册凭证' }}</button>
        </form>
      </section>

      <section class="card">
        <div class="card-heading"><div><p class="eyebrow">凭证清单</p><h3 class="card-title">当前家庭的注册记录</h3></div></div>
        <div v-if="loading" class="inline-loading">正在读取凭证状态</div>
        <div v-else-if="credentials.length === 0" class="empty-state"><AppIcon class="empty-art" name="shield" :size="38" /><strong>暂无人脸凭证</strong><p>注册成功后这里只显示版本和状态，不显示模板或原始图片。</p></div>
        <ul v-else class="list-plain">
          <li v-for="credential in credentials" :key="credential.id" class="row-card">
            <div><span class="row-title">{{ actorOptions.find(option => option.id === credential.actor_id)?.label ?? credential.actor_id }}</span><p class="row-meta">版本 {{ credential.credential_version }} · {{ credential.algorithm_version }} · {{ formatDateTime(credential.created_at) }}</p></div>
            <div class="heading-actions"><span class="pill" :class="credential.status === 'ACTIVE' ? 'pine' : 'plain'">{{ credential.status }}</span><button v-if="credential.status === 'ACTIVE'" type="button" class="btn btn-danger btn-small" :disabled="saving" @click="deleteCredential(credential)"><AppIcon name="trash" :size="14" /> 删除</button></div>
          </li>
        </ul>
      </section>
    </div>
  </div>
</template>
