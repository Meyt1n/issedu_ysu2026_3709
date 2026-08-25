<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'

import { apiClient } from '../api/client'
import type { PlanWorkbenchResponse } from '../api/types'
import AppIcon from '../components/AppIcon.vue'
import { formatError, requestOptions, selectedMember, session } from '../store'
import { formatDateTime } from '../ui/labels'

const workbench = ref<PlanWorkbenchResponse | null>(null)
const loading = ref(false)
const error = ref('')

async function loadPlans(): Promise<void> {
  if (!session.selectedHouseholdId || !session.selectedMemberId) return
  loading.value = true
  error.value = ''
  try {
    workbench.value = await apiClient.getPlanWorkbench(session.selectedHouseholdId, session.selectedMemberId, requestOptions.value)
  } catch (cause) {
    workbench.value = null
    error.value = formatError(cause)
  } finally {
    loading.value = false
  }
}

watch(() => [session.selectedHouseholdId, session.selectedMemberId], () => void loadPlans())
onMounted(() => void loadPlans())
</script>

<template>
  <section class="page-hero member-portal-hero">
    <p class="eyebrow">服药提醒</p>
    <h2 class="hero-greeting">{{ selectedMember?.display_name ?? '我的' }}的提醒</h2>
    <p class="hero-sub">这里显示家人已经确认的服药安排。需要调整时，请告诉家人。</p>
  </section>
  <p v-if="error" class="notice warn" role="status"><AppIcon name="info" :size="16" />暂时没有读取到提醒，请稍后再试。</p>
  <section class="card">
    <div v-if="loading" class="inline-loading">正在读取提醒</div>
    <div v-else-if="!workbench?.plans.length" class="empty-state member-empty"><AppIcon name="plan" :size="38" /><strong>暂时没有服药提醒</strong><p>家人创建安排后，会显示在这里。</p></div>
    <ul v-else class="list-plain member-plan-list">
      <li v-for="plan in workbench.plans" :key="plan.plan_event_id" class="member-plan-row">
        <div><strong><AppIcon name="pill" :size="18" />{{ plan.drug }}</strong><p>{{ plan.schedule }}<span v-if="plan.dose"> · 每次 {{ plan.dose }}</span></p></div>
        <span class="pill" :class="plan.status === 'ESCALATED' ? 'rose' : plan.status === 'REMINDER' ? 'gold' : 'pine'">{{ plan.status === 'ESCALATED' ? '需要家人关注' : plan.status === 'REMINDER' ? '到点提醒' : '按计划' }}</span>
        <small>下次：{{ formatDateTime(plan.next_action_at) }}</small>
      </li>
    </ul>
  </section>
</template>
