<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { apiClient } from '../api/client'
import AppIcon from '../components/AppIcon.vue'
import {
  formatError,
  pushToast,
  requestOptions,
  selectHousehold,
  selectMember,
  session,
  setView,
} from '../store'
import {
  getShowDemoHouseholds,
  setShowDemoHouseholds,
} from '../ui/demoData'

interface Scenario {
  id: string
  title: string
  member_key: string
  summary: string
  focus?: string[]
}

const seeding = ref(false)
const seedReport = ref<Record<string, unknown> | null>(null)
const seedError = ref('')
const scenarios = ref<Scenario[]>([])
const showDemo = ref(getShowDemoHouseholds())

async function loadScenarios(): Promise<void> {
  try {
    const data = await apiClient.listClassroomScenarios(requestOptions.value)
    scenarios.value = (data.scenarios ?? []) as Scenario[]
  } catch (cause) {
    scenarios.value = []
    seedError.value = formatError(cause)
  }
}

async function runSeed(): Promise<void> {
  seeding.value = true
  seedError.value = ''
  try {
    seedReport.value = await apiClient.seedFormalDemoHealth(requestOptions.value)
    pushToast('已补种虚构演示数据（幂等）', 'success')
    if (typeof seedReport.value.household_id === 'string') {
      await selectHousehold(seedReport.value.household_id)
    }
  } catch (cause) {
    seedError.value = formatError(cause)
    pushToast(seedError.value, 'error')
  } finally {
    seeding.value = false
  }
}

function onToggleDemo(event: Event): void {
  const checked = (event.target as HTMLInputElement).checked
  showDemo.value = checked
  setShowDemoHouseholds(checked)
  pushToast(checked ? '成员前台将显示演示家庭' : '成员前台默认隐藏演示家庭（仅剩演示时仍保留）', 'info')
}

async function openScenario(scenario: Scenario): Promise<void> {
  const members = seedReport.value?.members as
    | Record<string, { id?: string }>
    | undefined
  const memberId = members?.[scenario.member_key]?.id
  if (memberId) {
    selectMember(memberId)
  }
  if (scenario.focus?.includes('allergy_conflict') || scenario.focus?.includes('expiry_check')) {
    setView('risks')
  } else if (scenario.focus?.includes('relationship-graph')) {
    setView('graph')
  } else if (scenario.focus?.includes('authorization')) {
    setView('authorizations')
  } else {
    setView('members')
  }
}

onMounted(() => {
  void loadScenarios()
})
</script>

<template>
  <section class="page-hero">
    <p class="eyebrow">家庭与研发</p>
    <h2>演示造数与课堂剧本</h2>
    <p class="hero-sub">
      一键补种正式测试账号的虚构病史、过敏、药品、指标、计划与提醒闭环；全部标注「演示」，不含真实健康数据。
    </p>
  </section>

  <section class="card">
    <div class="card-heading">
      <div>
        <p class="eyebrow">造数</p>
        <h3 class="card-title">正式演示家庭</h3>
      </div>
      <button type="button" class="btn btn-primary" :disabled="seeding || !session.actorId" @click="runSeed">
        <AppIcon name="refresh" :size="15" />
        {{ seeding ? '正在补种…' : '补种 / 重置演示健康数据' }}
      </button>
    </div>
    <p class="muted">
      需要以 <code>demo-parent</code> 或其它 <code>demo-</code> / <code>test-</code> 身份登录。会写入奶奶/爷爷关联事实，并授予
      <code>demo-child</code> 仅读奶奶 <code>health_events</code>。
    </p>
    <p v-if="seedError" class="notice error" role="alert">{{ seedError }}</p>
    <pre v-if="seedReport" class="code-block">{{ JSON.stringify(seedReport, null, 2) }}</pre>
  </section>

  <section class="card">
    <div class="card-heading">
      <div>
        <p class="eyebrow">隔离</p>
        <h3 class="card-title">演示家庭可见性</h3>
      </div>
    </div>
    <label class="check-row">
      <input type="checkbox" :checked="showDemo" @change="onToggleDemo" />
      成员前台强制显示演示家庭（管理员始终可见）
    </label>
  </section>

  <section class="card">
    <div class="card-heading">
      <div>
        <p class="eyebrow">课堂</p>
        <h3 class="card-title">三条固定剧本</h3>
      </div>
    </div>
    <div class="section-stack" style="gap: 12px">
      <article v-for="scenario in scenarios" :key="scenario.id" class="row-card">
        <strong>{{ scenario.title }}</strong>
        <p>{{ scenario.summary }}</p>
        <button type="button" class="btn btn-ghost btn-small" @click="openScenario(scenario)">
          打开对应页面
        </button>
      </article>
      <p v-if="!scenarios.length" class="muted">加载剧本失败时，可先补种数据再刷新本页。</p>
    </div>
  </section>
</template>
