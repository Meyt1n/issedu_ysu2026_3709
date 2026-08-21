<script setup lang="ts">
import { computed, reactive, ref } from 'vue'

import welcomeHero from '../assets/welcome-hero.jpg'
import AppIcon from '../components/AppIcon.vue'
import FaceLoginCapture from '../components/FaceLoginCapture.vue'
import {
  connect,
  connectWithFace,
  connectWithPin,
  connectWithPassword,
  createHouseholdAndEnter,
  formatError,
  pushToast,
  session,
} from '../store'
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
const householdId = ref('')
const pin = ref('')
const faceFrames = ref<File[]>([])
const authMode = ref<'development' | 'session'>(session.authMode)
const credentialMode = ref<'password' | 'pin' | 'face'>('password')
const registerMode = ref(false)
const connecting = ref(false)
const creating = ref(false)
const createError = ref('')

const householdDraft = reactive({
  name: '',
  members: [
    { displayName: '', role: 'SELF' as const },
    { displayName: '', role: 'DEPENDENT' as const },
  ],
})

const showCreateForm = computed(() => session.status === 'empty')
const canConnect = computed(() => actorId.value.trim().length > 0 && !connecting.value)
const accessPurposeValid = computed(() => /^[a-z][a-z0-9-]{1,63}$/.test(accessPurpose.value.trim()))
const canCreate = computed(
  () =>
    householdDraft.name.trim().length > 0 &&
    householdDraft.members.some(member => member.displayName.trim().length > 0) &&
    !creating.value,
)

async function submitConnect(): Promise<void> {
  connecting.value = true
  try {
    await connect(actorId.value, accessPurpose.value)
    if (session.status === 'ready') pushToast('success', '已进入家庭健康空间。')
  } finally {
    connecting.value = false
  }
}

async function submitSession(): Promise<void> {
  connecting.value = true
  try {
    if (credentialMode.value === 'face') {
      await connectWithFace(actorId.value, householdId.value, faceFrames.value, accessPurpose.value)
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
      pushToast('success', registerMode.value ? '本地账号已注册并登录。' : '已建立本地安全会话。')
    }
  } finally {
    connecting.value = false
  }
}

async function onFaceCaptured(frames: File[]): Promise<void> {
  faceFrames.value = frames
  await submitSession()
}

function usePinFallback(): void {
  faceFrames.value = []
  credentialMode.value = 'pin'
}

async function submitCreate(): Promise<void> {
  if (!canCreate.value) return
  creating.value = true
  createError.value = ''
  try {
    await createHouseholdAndEnter(
      householdDraft.name.trim(),
      householdDraft.members.filter(member => member.displayName.trim()),
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
    style="align-content: center; gap: 26px"
    @pointermove="onStageMove"
    @pointerleave="onStageLeave"
  >
    <div class="welcome-inner">
      <section class="welcome-intro">
        <span class="welcome-badge">
          <AppIcon name="lock" :size="15" />
          健康数据默认保存在本地家庭可信域
        </span>
        <h1 class="welcome-title">
          把家人的健康变化，<br />
          <span class="accent">温柔而可靠</span>地记下来
        </h1>
        <p class="welcome-lede">
          家健镜持续记录家庭健康事实的每一次变化，用确定性规则发现冲突与风险，
          再以带证据的方式解释给每一位照护者听。
        </p>
        <div class="welcome-art" :style="{ '--par-rx': artRx, '--par-ry': artRy }">
          <img :src="welcomeHero" alt="温馨的家庭照护插画：家人围坐在洒满阳光的窗边" />
          <span class="art-caption">AI 生成教学插画 · 本地资源</span>
          <span class="art-float f1"><AppIcon name="lock" :size="13" />数据不出网</span>
          <span class="art-float f2"><AppIcon name="heart" :size="13" />事实可追溯</span>
        </div>
        <div class="welcome-chip-row">
          <span class="welcome-chip"><AppIcon name="timeline" :size="14" />事件不可覆盖 · 可更正</span>
          <span class="welcome-chip"><AppIcon name="scan" :size="14" />多证据识别 · 人工确认</span>
          <span class="welcome-chip"><AppIcon name="key" :size="14" />字段级授权 · 随时撤回</span>
        </div>
      </section>

      <section v-if="!showCreateForm" class="welcome-form-card">
        <h2>进入家庭空间</h2>
        <div class="segmented-control" role="group" aria-label="选择登录方式">
          <button type="button" :class="{ active: authMode === 'development' }" @click="authMode = 'development'">开发演示</button>
          <button type="button" :class="{ active: authMode === 'session' }" @click="authMode = 'session'">正式账号登录</button>
        </div>
        <p v-if="authMode === 'development'" class="form-sub">仅用于非生产本地演示，使用开发身份标识；不会建立正式会话。</p>
        <p v-else class="form-sub">使用本地账号建立短期会话。令牌只保存在当前页面内存，不写入浏览器持久缓存。</p>
        <form v-if="authMode === 'development'" class="section-stack" @submit.prevent="submitConnect">
          <label class="field">
            开发身份标识
            <input v-model="actorId" autocomplete="off" placeholder="例如 parent-1" required />
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
            />
            <small id="purpose-format-hint">照护者访问被授权数据时，需要与授权中登记的用途一致；格式为小写字母、数字和连字符。</small>
          </label>
          <p v-if="session.error" class="notice error" role="alert">
            <AppIcon name="alert" :size="16" />
            {{ session.error }}
          </p>
          <button type="submit" class="btn btn-primary" :disabled="!canConnect">
            {{ connecting ? '正在进入' : '进入家庭空间' }}
            <AppIcon v-if="!connecting" name="arrow-right" :size="17" />
          </button>
        </form>
        <form v-else class="section-stack" @submit.prevent="submitSession">
          <div class="segmented-control" role="group" aria-label="选择账号登录凭据">
            <button type="button" :class="{ active: credentialMode === 'face' }" @click="credentialMode = 'face'">人脸识别</button>
            <button type="button" :class="{ active: credentialMode === 'password' }" @click="credentialMode = 'password'">账号密码</button>
            <button type="button" :class="{ active: credentialMode === 'pin' }" @click="credentialMode = 'pin'">家庭 PIN</button>
          </div>
          <label v-if="credentialMode === 'password'" class="field">
            本地账号
            <input v-model="actorId" autocomplete="username" placeholder="例如 parent-1" required />
          </label>
          <label v-else class="field">
            家庭 ID
            <input v-model="householdId" autocomplete="off" placeholder="例如 household-1" required />
          </label>
          <label v-if="credentialMode === 'pin' || credentialMode === 'face'" class="field">
            家庭成员身份
            <input v-model="actorId" autocomplete="username" placeholder="例如 parent-1" required />
          </label>
          <label v-if="credentialMode === 'password'" class="field">
            密码
            <input v-model="password" type="password" autocomplete="current-password" minlength="8" required />
          </label>
          <label v-else-if="credentialMode === 'pin'" class="field">
            六位数字 PIN
            <input v-model="pin" type="password" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9]{6}" maxlength="6" required />
          </label>
          <FaceLoginCapture
            v-if="credentialMode === 'face'"
            :disabled="connecting || !actorId.trim() || !householdId.trim()"
            @captured="onFaceCaptured"
            @fallback="usePinFallback"
          />
          <label class="field">
            访问用途代码
            <input v-model="accessPurpose" autocomplete="off" placeholder="family-care" aria-label="访问用途代码" />
          </label>
          <p v-if="credentialMode === 'pin'" class="form-sub">PIN 只用于当前家庭和所选身份，连续输错会暂时锁定。</p>
          <p v-if="session.error" class="notice error" role="alert">
            <AppIcon name="alert" :size="16" />
            {{ session.error }}
          </p>
          <button v-if="credentialMode !== 'face'" type="submit" class="btn btn-primary" :disabled="!actorId.trim() || (credentialMode === 'password' ? password.length < 8 : !householdId.trim() || !/^\d{6}$/.test(pin)) || connecting">
            {{ connecting ? '正在建立会话' : credentialMode === 'pin' ? '使用 PIN 登录' : registerMode ? '注册并登录' : '登录' }}
            <AppIcon v-if="!connecting" name="arrow-right" :size="17" />
          </button>
          <button v-if="credentialMode === 'password'" type="button" class="btn btn-ghost btn-small" @click="registerMode = !registerMode">
            {{ registerMode ? '已有账号？返回登录' : '首次使用？注册本地账号' }}
          </button>
        </form>
        <p class="welcome-disclaimer">
          教学演示系统，不提供诊断、处方或用药决策；不提供购药、问诊或广告导流。
        </p>
      </section>

      <section v-else class="welcome-form-card">
        <h2>创建你的家庭</h2>
        <p class="form-sub">
          身份 <strong>{{ session.actorId }}</strong> 名下还没有可见的家庭。创建一个家庭并添加成员，即可开始记录。
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
            成员二（可选）
            <input v-model="householdDraft.members[1]!.displayName" autocomplete="off" placeholder="成员称呼，例如 奶奶" />
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
        <p class="welcome-disclaimer">创建动作只写入本地数据库，随时可以通过补偿事件更正。</p>
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
