<script setup lang="ts">
import { computed, reactive, ref } from 'vue'

import welcomeHero from '../assets/welcome-hero.jpg'
import AppIcon from '../components/AppIcon.vue'
import {
  connect,
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
        <p class="form-sub">当前为开发演示环境，使用开发身份标识进入。生产环境将使用本地账号认证。</p>
        <form class="section-stack" @submit.prevent="submitConnect">
          <label class="field">
            开发身份标识
            <input v-model="actorId" autocomplete="off" placeholder="例如 parent-1" required />
          </label>
          <label class="field">
            访问用途代码
            <input v-model="accessPurpose" autocomplete="off" placeholder="family-care" />
            <small>照护者访问被授权数据时，需要与授权中登记的用途一致。</small>
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
