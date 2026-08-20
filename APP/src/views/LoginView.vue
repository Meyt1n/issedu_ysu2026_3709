<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import AppIcon from '@/components/AppIcon.vue'
import { presentApiError } from '@/api/errors'
import { familyAuthAdapter } from '@/data/authAdapter'
import { useAuth } from '@/stores/auth'
import { useSession } from '@/stores/session'

const route = useRoute()
const router = useRouter()
const { session, updateSession } = useSession()
const { auth, signIn } = useAuth()

const account = ref('')
const password = ref('')
const submitting = ref(false)
const errorMessage = ref('')

const REASON_NOTICE: Record<string, string> = {
  expired: '登录会话已过期。为保护隐私，本机没有保留上一次会话的数据，请重新登录。',
  revoked: '登录会话已被撤销或授权已变更。请重新登录，页面不会显示旧会话的数据。',
  unauthenticated: '家庭服务器要求重新认证，请重新登录后继续。',
  'signed-out': '已退出登录。重新登录后才会再次加载家庭数据。',
}

const reasonNotice = computed(() => REASON_NOTICE[auth.reason] ?? '')
const serverLabel = computed(() => session.serverBaseUrl || '同源（与页面相同的地址）')
/** 与 HCT-107 `AuthCredentials` 的 `password: min_length=8` 对齐，避免把长度问题报成契约不一致。 */
const PASSWORD_MIN_LENGTH = 8
const canSubmit = computed(
  () => Boolean(account.value.trim())
    && password.value.length >= PASSWORD_MIN_LENGTH
    && !submitting.value,
)

async function submit(): Promise<void> {
  if (!canSubmit.value) return
  submitting.value = true
  errorMessage.value = ''
  try {
    // 密码只作为参数传给适配器（POST JSON body），不写入 store、存储或日志。
    await signIn(familyAuthAdapter(), { account: account.value.trim(), password: password.value })
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/'
    await router.replace(redirect.startsWith('/') ? redirect : '/')
  } catch (cause) {
    errorMessage.value = presentApiError(cause).message
  } finally {
    // 无论成功失败都立即丢弃输入框里的密码。
    password.value = ''
    submitting.value = false
  }
}

function useDemoMode(): void {
  updateSession({ dataMode: 'demo', currentMemberId: '' })
  void router.replace('/')
}
</script>

<template>
  <main id="main" class="screen">
    <header class="screen-header">
      <p class="eyebrow">家庭服务器</p>
      <h1>登录</h1>
    </header>

    <section class="card" aria-labelledby="login-title">
      <div class="h-icon-row">
        <span class="row-icon" data-tone="calm" aria-hidden="true"><AppIcon name="shield" :size="16" /></span>
        <h2 id="login-title">正式登录</h2>
      </div>

      <p v-if="reasonNotice" class="notice" data-tone="warn" role="alert">{{ reasonNotice }}</p>

      <p class="meta-line">服务器：{{ serverLabel }}</p>

      <form class="login-form" @submit.prevent="submit">
        <label class="field">
          账号
          <input
            v-model="account"
            type="text"
            name="username"
            autocomplete="username"
            autocapitalize="none"
            spellcheck="false"
            :disabled="submitting"
            placeholder="家庭服务器账号"
          />
        </label>
        <label class="field">
          密码
          <input
            v-model="password"
            type="password"
            name="password"
            autocomplete="current-password"
            :disabled="submitting"
            :aria-invalid="Boolean(errorMessage)"
            :aria-describedby="errorMessage ? 'login-help login-error' : 'login-help'"
            placeholder="家庭服务器密码"
          />
        </label>
        <p id="login-help" class="meta-line">
          密码至少 {{ PASSWORD_MIN_LENGTH }} 位，只用于本次登录请求，不会保存在本机、不会写入日志，也不会出现在地址栏。
        </p>
        <p v-if="errorMessage" id="login-error" class="notice" data-tone="error" role="alert">
          {{ errorMessage }}
        </p>
        <button type="submit" class="btn btn-block" :disabled="!canSubmit">
          {{ submitting ? '正在登录…' : '登录' }}
        </button>
      </form>
    </section>

    <section class="card" aria-labelledby="login-alt-title">
      <h2 id="login-alt-title">其他方式</h2>
      <RouterLink class="btn btn-quiet btn-block" to="/me">检查服务器与联机设置</RouterLink>
      <button type="button" class="btn btn-quiet btn-block" @click="useDemoMode">改用演示模式</button>
      <p class="meta-line">
        演示模式使用内置虚构数据，不连接任何服务器，也不需要登录。
      </p>
    </section>

    <section class="card" aria-labelledby="login-privacy-title">
      <h2 id="login-privacy-title">这一步做了什么</h2>
      <ul class="divided-list">
        <li>登录成功后建立短生命周期服务端会话，凭据只保存在内存中。</li>
        <li>会话过期、被撤销或返回 401 时立即清理本地会话，并停止所有写操作。</li>
        <li>退出登录会清除查询结果、上传草稿和能力探测快照，不保留旧会话数据。</li>
        <li>高风险动作仍需 PIN 或二维码一次性二次确认。</li>
      </ul>
    </section>
  </main>
</template>

<style scoped>
.login-form { display: grid; gap: 12px; }
</style>
