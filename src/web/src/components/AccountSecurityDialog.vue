<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { changeCurrentPassword, formatError, pushToast } from '../store'
import AppIcon from './AppIcon.vue'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: [] }>()

const currentPassword = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const error = ref('')
const submitting = ref(false)

function clearSecrets(): void {
  currentPassword.value = ''
  newPassword.value = ''
  confirmPassword.value = ''
  error.value = ''
}

function close(): void {
  if (submitting.value) return
  clearSecrets()
  emit('close')
}

async function submit(): Promise<void> {
  error.value = ''
  if (newPassword.value.length < 8) {
    error.value = '新密码至少需要 8 个字符。'
    return
  }
  if (newPassword.value !== confirmPassword.value) {
    error.value = '两次输入的新密码不一致。'
    return
  }
  submitting.value = true
  try {
    await changeCurrentPassword(currentPassword.value, newPassword.value)
    clearSecrets()
    emit('close')
    pushToast('success', '密码已修改，其他设备上的旧会话已退出。')
  } catch (cause) {
    error.value = formatError(cause)
  } finally {
    submitting.value = false
  }
}

function onKeydown(event: KeyboardEvent): void {
  if (props.open && event.key === 'Escape') close()
}

watch(() => props.open, open => {
  if (!open) clearSecrets()
})
onMounted(() => window.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <Teleport to="body">
    <Transition name="modal">
      <div
        v-if="open"
        class="modal-backdrop"
        role="dialog"
        aria-modal="true"
        aria-labelledby="account-security-title"
        @click.self="close"
      >
        <div class="modal-card account-security-card">
          <span class="modal-icon primary"><AppIcon name="key" :size="22" /></span>
          <h3 id="account-security-title" class="modal-title">修改正式账号密码</h3>
          <p class="modal-message">
            修改成功后会立即撤销这个账号在其他设备上的旧会话，当前页面会自动换成新会话。
          </p>
          <form class="section-stack account-security-form" @submit.prevent="submit">
            <label class="field">
              当前密码
              <input
                v-model="currentPassword"
                type="password"
                autocomplete="current-password"
                aria-label="当前密码"
                minlength="8"
                required
                autofocus
              />
            </label>
            <label class="field">
              新密码
              <input
                v-model="newPassword"
                type="password"
                autocomplete="new-password"
                aria-label="新密码"
                minlength="8"
                required
              />
              <small>至少 8 个字符；不能与当前密码相同。</small>
            </label>
            <label class="field">
              再次输入新密码
              <input
                v-model="confirmPassword"
                type="password"
                autocomplete="new-password"
                aria-label="再次输入新密码"
                minlength="8"
                required
              />
            </label>
            <p v-if="error" class="notice error" role="alert">
              <AppIcon name="alert" :size="16" />
              {{ error }}
            </p>
            <div class="modal-actions account-security-actions">
              <button type="button" class="btn btn-ghost" :disabled="submitting" @click="close">
                取消
              </button>
              <button type="submit" class="btn btn-primary" :disabled="submitting">
                {{ submitting ? '正在修改…' : '确认修改' }}
              </button>
            </div>
          </form>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.account-security-card {
  justify-items: stretch;
  max-width: 440px;
  text-align: left;
}

.account-security-card .modal-icon,
.account-security-card .modal-title,
.account-security-card .modal-message {
  justify-self: center;
}

.account-security-form {
  margin-top: 8px;
  width: 100%;
}

.account-security-actions {
  justify-content: flex-end;
}
</style>
