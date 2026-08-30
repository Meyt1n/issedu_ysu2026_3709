<script setup lang="ts">
import { computed, reactive, ref } from 'vue'

import welcomeHero from '../assets/welcome-hero.jpg'
import AppIcon from '../components/AppIcon.vue'
import {
  connectWithPassword,
  createHouseholdAndEnter,
  formatError,
  portalWelcomeMessage,
  pushToast,
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
const connecting = ref(false)
const creating = ref(false)
const createError = ref('')
const localError = ref('')

// HCT-498：成员前台、管理后台和 auto 调试入口都只暴露正式账号密码登录。
// 入口模式仍只负责 HCT-453 的角色分流，不参与服务端授权判断。
const entryMode = activePortalEntryMode()
const entryBranding = portalEntryBranding(entryMode)

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
const showCreateForm = computed(() => session.status === 'empty')
const accessPurposeValid = computed(() => /^[a-z][a-z0-9-]{1,63}$/.test(accessPurpose.value.trim()))
const canConnect = computed(
  () =>
    actorId.value.trim().length > 0
    && password.value.length >= 8
    && accessPurposeValid.value
    && !connecting.value,
)

const householdDraft = reactive({
  name: '',
  members: [
    { displayName: '', actorId: session.actorId, role: 'SELF' as const },
    { displayName: '', actorId: '', role: 'DEPENDENT' as const },
  ],
})

const canCreate = computed(
  () =>
    householdDraft.name.trim().length > 0
    && householdDraft.members.some(member => member.displayName.trim().length > 0)
    && householdDraft.members
      .filter(member => member.displayName.trim().length > 0)
      .every(member => /^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$/.test(member.actorId.trim()))
    && new Set(
      householdDraft.members
        .filter(member => member.displayName.trim().length > 0)
        .map(member => member.actorId.trim()),
    ).size === householdDraft.members.filter(member => member.displayName.trim().length > 0).length
    && !creating.value,
)

async function submitLogin(): Promise<void> {
  localError.value = ''
  if (!accessPurposeValid.value) {
    localError.value = '访问用途代码需使用小写字母开头，并只包含小写字母、数字和连字符。'
    return
  }

  connecting.value = true
  try {
    await connectWithPassword(actorId.value, password.value, accessPurpose.value)
    if (session.status === 'ready') {
      password.value = ''
      pushToast('success', portalWelcomeMessage())
    }
  } finally {
    connecting.value = false
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
            : '使用正式家庭账号登录，查看经过授权的健康记录、任务与照护信息。' }}
        </p>
        <div class="welcome-art" :style="{ '--par-rx': artRx, '--par-ry': artRy }">
          <img :src="welcomeHero" alt="温馨的家庭照护插画：家人围坐在洒满阳光的窗边" />
          <span class="art-caption">本地家庭插画 · 不上传原图</span>
          <span class="art-float f1"><AppIcon name="lock" :size="13" />数据不出网</span>
          <span class="art-float f2"><AppIcon name="heart" :size="13" />{{ entryMode === 'member' ? '只看自己的日常' : '复核后才入档' }}</span>
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

      <section v-if="!showCreateForm" class="welcome-form-card">
        <span v-if="entryMode === 'member'" class="portal-mark member">
          <AppIcon name="members" :size="14" />
          成员前台 · 个人身份
        </span>
        <span v-else-if="entryMode === 'admin'" class="portal-mark admin">
          <AppIcon name="key" :size="14" />
          管理后台 · 全家管理
        </span>
        <h2>{{ entryBranding ? entryBranding.formTitle : '正式账号登录' }}</h2>
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
          v-else-if="entryMode === 'member'"
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

        <div class="notice" data-testid="formal-login-method" role="note">
          <AppIcon name="lock" :size="16" />
          <span><strong>正式账号密码登录</strong> · 登录后按家庭授权进入对应工作区</span>
        </div>
        <p class="form-sub">会话由本地 API 验证；业务请求只使用短期 Bearer 会话，不在页面持久化密码。</p>
        <form class="section-stack" data-testid="formal-login-form" @submit.prevent="submitLogin">
          <label class="field">
            正式账号
            <input v-model="actorId" autocomplete="username" placeholder="请输入管理员分配的账号" required />
          </label>
          <label class="field">
            密码
            <input v-model="password" type="password" autocomplete="current-password" minlength="8" required />
          </label>
          <label class="field">
            访问用途代码
            <input
              v-model="accessPurpose"
              autocomplete="off"
              placeholder="family-care"
              aria-label="访问用途代码"
              aria-describedby="purpose-format-hint"
              :aria-invalid="accessPurpose.trim().length > 0 && !accessPurposeValid"
              required
            />
            <small id="purpose-format-hint">照护者访问被授权数据时，需要与授权中登记的用途一致；格式为小写字母、数字和连字符。</small>
          </label>
          <p v-if="(localError || session.error) && !session.entryConflict" class="notice error" role="alert">
            <AppIcon name="alert" :size="16" />
            {{ localError || session.error }}
          </p>
          <button type="submit" class="btn btn-primary" :disabled="!canConnect">
            {{ connecting ? '正在登录…' : entryBranding?.ctaLabel ?? '登录家庭空间' }}
            <AppIcon v-if="!connecting" name="arrow-right" :size="17" />
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
          正式账号 <strong>{{ session.actorId }}</strong> 名下还没有可见的家庭。创建一个家庭并添加成员，即可开始记录。
        </p>
        <p v-if="entryMode === 'member'" class="notice warn" role="status">
          <AppIcon name="info" :size="16" />
          创建者会成为家庭管理员。建家成功后请改用管理后台完成配置；家人日常请用各自正式账号回到本前台登录。
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
            成员一正式账号
            <input v-model="householdDraft.members[0]!.actorId" autocomplete="username" placeholder="例如 parent-1" />
          </label>
          <label class="field">
            成员二（可选）
            <input v-model="householdDraft.members[1]!.displayName" autocomplete="off" placeholder="成员称呼，例如 奶奶" />
          </label>
          <label class="field">
            成员二正式账号（填写成员二时必填）
            <input v-model="householdDraft.members[1]!.actorId" autocomplete="username" placeholder="例如 grandma-1" />
          </label>
          <p class="form-sub">成员账号需先通过受控开户流程创建；这里仅把现有正式账号绑定到对应家庭成员。</p>
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
