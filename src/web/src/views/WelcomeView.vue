<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'

import welcomeHero from '../assets/welcome-hero.jpg'
import { apiClient } from '../api/client'
import type { Household } from '../api/types'
import AppIcon from '../components/AppIcon.vue'
import FaceVideoCapture from '../components/FaceVideoCapture.vue'
import {
  connect,
  connectWithFamilyFace,
  connectWithPin,
  connectWithPassword,
  createHouseholdAndEnter,
  formatError,
  getBoundFaceHouseholdId,
  getBoundFaceHouseholdName,
  pushToast,
  session,
} from '../store'
import { SHOW_DEV_LOGIN } from '../ui/featureFlags'
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
const initialBoundFaceHouseholdId = getBoundFaceHouseholdId()
const householdId = ref(initialBoundFaceHouseholdId)
const boundFaceHouseholdName = ref(getBoundFaceHouseholdName())
const pin = ref('')
const faceFrames = ref<File[]>([])
// 开发演示入口默认只在开发环境出现；本地教学 Compose 构建通过
// VITE_SHOW_DEV_LOGIN=true 显式保留（与后端 ALLOW_DEV_ACTOR_HEADER 对齐）。
const showDevelopmentEntry = SHOW_DEV_LOGIN
const authMode = ref<'development' | 'session'>(showDevelopmentEntry ? session.authMode : 'session')
const credentialMode = ref<'password' | 'pin' | 'face'>(
  initialBoundFaceHouseholdId ? 'face' : 'password',
)
const registerMode = ref(false)
const connecting = ref(false)
const creating = ref(false)
const createError = ref('')
const localError = ref('')
const loginHouseholds = ref<Household[]>([])
const householdsLoading = ref(false)
const householdsError = ref('')
let householdsRequest: AbortController | null = null
let householdsTimer: ReturnType<typeof setTimeout> | null = null

const householdDraft = reactive({
  name: '',
  members: [
    { displayName: '', actorId: session.actorId, role: 'SELF' as const },
    { displayName: '', actorId: '', role: 'DEPENDENT' as const },
  ],
})

const showCreateForm = computed(() => session.status === 'empty')
const accessPurposeValid = computed(() => /^[a-z][a-z0-9-]{1,63}$/.test(accessPurpose.value.trim()))
const faceBindingReady = computed(() => householdId.value.trim().length > 0)
const faceHouseholdLabel = computed(
  () => boundFaceHouseholdName.value || '当前绑定家庭（仅在本机使用）',
)
const canConnect = computed(
  () => actorId.value.trim().length > 0 && accessPurposeValid.value && !connecting.value,
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
  [actorId, accessPurpose, credentialMode, authMode],
  ([nextActorId, nextAccessPurpose, nextCredentialMode, nextAuthMode]) => {
    if (householdsTimer) clearTimeout(householdsTimer)
    householdsRequest?.abort()
    householdsRequest = null
    loginHouseholds.value = []
    householdId.value = nextCredentialMode === 'face' ? getBoundFaceHouseholdId() : ''
    boundFaceHouseholdName.value = nextCredentialMode === 'face' ? getBoundFaceHouseholdName() : ''
    householdsLoading.value = false
    householdsError.value = ''
    localError.value = ''

    if (nextAuthMode !== 'session' || (nextCredentialMode !== 'pin' && nextCredentialMode !== 'face')) return
    const actor = nextActorId.trim()
    const purpose = nextAccessPurpose.trim()
    if (!purpose || !accessPurposeValid.value) return
    if (nextCredentialMode === 'face') {
      householdsError.value = householdId.value
        ? ''
        : '这是第一次使用人脸登录。请先用账号密码进入，再到“人脸凭证”页面绑定当前家庭。'
      return
    }
    if (!actor) return

    householdsTimer = setTimeout(async () => {
      householdsTimer = null
      const controller = new AbortController()
      householdsRequest = controller
      householdsLoading.value = true
      try {
        const households = await apiClient.listHouseholds({
          actorId: actor,
          accessPurpose: purpose,
          signal: controller.signal,
        })
        if (controller.signal.aborted) return
        loginHouseholds.value = households
        if (households.length > 0 && !households.some(item => item.id === householdId.value)) {
          householdId.value = households[0]!.id
        }
      } catch (cause) {
        if (!controller.signal.aborted) householdsError.value = formatError(cause)
      } finally {
        if (!controller.signal.aborted) householdsLoading.value = false
      }
    }, 300)
  },
)

onBeforeUnmount(() => {
  householdsRequest?.abort()
  if (householdsTimer) clearTimeout(householdsTimer)
})

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
  localError.value = ''
  if (!accessPurposeValid.value) {
    localError.value = '访问用途代码需使用小写字母开头，并只包含小写字母、数字和连字符。'
    return
  }
  connecting.value = true
  try {
    if (credentialMode.value === 'face') {
      if (!faceBindingReady.value) {
        localError.value = '本机还没有绑定家庭，请先用账号密码进入完成首次设置。'
        return
      }
      await connectWithFamilyFace(householdId.value, faceFrames.value, accessPurpose.value)
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
  if (!accessPurposeValid.value) {
    localError.value = '请先填写正确的访问用途代码，再开始人脸验证。'
    return
  }
  faceFrames.value = frames
  await submitSession()
}

function usePinFallback(): void {
  faceFrames.value = []
  localError.value = ''
  credentialMode.value = 'pin'
}

function usePasswordFallback(): void {
  faceFrames.value = []
  localError.value = ''
  registerMode.value = false
  credentialMode.value = 'password'
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
          <span class="art-caption">本地家庭插画 · 不上传原图</span>
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
          <button v-if="showDevelopmentEntry" type="button" :class="{ active: authMode === 'development' }" @click="authMode = 'development'">开发演示</button>
          <button type="button" :class="{ active: authMode === 'session' }" @click="authMode = 'session'">正式账号登录</button>
        </div>
        <p v-if="authMode === 'development'" class="form-sub">仅用于非生产本地演示，使用开发身份标识；不会建立正式会话。</p>
        <p v-else class="form-sub">使用本地账号建立短期会话。令牌只保存在当前页面内存，不写入浏览器持久缓存。</p>
        <form v-if="authMode === 'development'" class="section-stack" @submit.prevent="submitConnect">
          <label class="field">
            开发身份标识
            <input v-model="actorId" autocomplete="off" placeholder="例如 parent-1" required />
          </label>
          <label v-if="authMode === 'development'" class="field">
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
          <label v-if="credentialMode === 'pin'" class="field">
            家庭
            <select v-if="loginHouseholds.length > 0" v-model="householdId" autocomplete="off" required>
              <option v-for="household in loginHouseholds" :key="household.id" :value="household.id">
                {{ household.name }}
              </option>
            </select>
            <input
              v-else
              v-model="householdId"
              autocomplete="off"
              placeholder="请输入家庭唯一编号"
              required
            />
            <small v-if="householdsLoading">正在加载可访问的家庭...</small>
            <small v-else-if="householdsError">家庭列表加载失败，可手动填写家庭唯一编号。</small>
            <small v-else>家庭名称仅用于展示，提交时使用系统唯一编号。</small>
          </label>
          <div v-else class="face-family-summary" role="status">
            <AppIcon :name="faceBindingReady ? 'home' : 'lock'" :size="18" />
            <div>
              <strong>{{ faceBindingReady ? faceHouseholdLabel : '本机还没有绑定家庭' }}</strong>
              <small v-if="faceBindingReady">人脸只会在这个家庭的成员中匹配，不会跨家庭搜索。</small>
              <small v-else>首次使用请先用账号密码进入一次，在“人脸凭证”页面完成家庭绑定。</small>
              <button v-if="!faceBindingReady" type="button" class="btn btn-ghost btn-small" @click="usePasswordFallback">先用账号密码进入</button>
            </div>
          </div>
          <label v-if="credentialMode === 'pin'" class="field">
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
          <FaceVideoCapture
            v-if="credentialMode === 'face'"
            :disabled="connecting || !faceBindingReady || !accessPurposeValid"
            @captured="onFaceCaptured"
            @fallback="usePinFallback"
          />
          <label v-if="authMode === 'development'" class="field">
            访问用途代码
            <input
              v-model="accessPurpose"
              autocomplete="off"
              placeholder="family-care"
              aria-label="访问用途代码"
              :aria-invalid="accessPurpose.trim().length > 0 && !accessPurposeValid"
            />
            <small>使用小写字母开头，例如 family-care。</small>
          </label>
          <p v-if="credentialMode === 'pin'" class="form-sub">PIN 只用于当前家庭和所选身份，连续输错会暂时锁定。</p>
          <p v-if="localError || session.error" class="notice error" role="alert">
            <AppIcon name="alert" :size="16" />
            {{ localError || session.error }}
          </p>
          <button v-if="credentialMode !== 'face'" type="submit" class="btn btn-primary" :disabled="!accessPurposeValid || !actorId.trim() || (credentialMode === 'password' ? password.length < 8 : !householdId.trim() || !/^\d{6}$/.test(pin)) || connecting">
            {{ connecting ? '正在建立会话' : credentialMode === 'pin' ? '使用 PIN 登录' : registerMode ? '注册并登录' : '登录' }}
            <AppIcon v-if="!connecting" name="arrow-right" :size="17" />
          </button>
          <button v-if="credentialMode === 'password'" type="button" class="btn btn-ghost btn-small" @click="registerMode = !registerMode">
            {{ registerMode ? '已有账号？返回登录' : '首次使用？注册本地账号' }}
          </button>
        </form>
        <p class="welcome-disclaimer">
          家庭健康记录仅供日常参考，不提供诊断、处方或用药决策；紧急情况请联系医生或当地急救服务。
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
            成员一登录账号
            <input v-model="householdDraft.members[0]!.actorId" autocomplete="username" placeholder="例如 parent-1" />
            <small>这个账号用于密码、PIN 或人脸快速登录，默认填当前身份。</small>
          </label>
          <label class="field">
            成员二（可选）
            <input v-model="householdDraft.members[1]!.displayName" autocomplete="off" placeholder="成员称呼，例如 奶奶" />
          </label>
          <label class="field">
            成员二登录账号（填写成员二时必填）
            <input v-model="householdDraft.members[1]!.actorId" autocomplete="username" placeholder="例如 grandma-1" />
          </label>
          <p class="form-sub">后续到“人脸凭证”页面，为每个登录账号采集一段动态视频；系统只保存加密特征，不保存视频原片。</p>
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
