<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'

import { apiClient } from '../api/client'
import type { HealthEvent } from '../api/types'
import AppIcon from '../components/AppIcon.vue'
import { formatError, requestOptions, selectedMember, session } from '../store'
import { eventTypeLabel, formatDateTime, summarizeEventPayload } from '../ui/labels'

const events = ref<HealthEvent[]>([])
const loading = ref(false)
const error = ref('')

async function loadRecords(): Promise<void> {
  if (!session.selectedHouseholdId || !session.selectedMemberId) return
  loading.value = true
  error.value = ''
  try {
    const timeline = await apiClient.listMemberTimeline(session.selectedHouseholdId, session.selectedMemberId, requestOptions.value)
    events.value = timeline.filter(event => event.confirmation_status === 'CONFIRMED').reverse()
  } catch (cause) {
    events.value = []
    error.value = formatError(cause)
  } finally {
    loading.value = false
  }
}

watch(() => [session.selectedHouseholdId, session.selectedMemberId], () => void loadRecords())
onMounted(() => void loadRecords())
</script>

<template>
  <section class="page-hero member-portal-hero">
    <p class="eyebrow">我的记录</p>
    <h2 class="hero-greeting">{{ selectedMember?.display_name ?? '我的' }}的健康记录</h2>
    <p class="hero-sub">这里只展示家庭管理员确认过的内容，正在核对的照片不会出现在这里。</p>
  </section>
  <p v-if="error" class="notice warn" role="status"><AppIcon name="info" :size="16" />暂时无法读取记录，请稍后再试。</p>
  <section class="card">
    <div v-if="loading" class="inline-loading">正在读取记录</div>
    <div v-else-if="events.length === 0" class="empty-state member-empty"><AppIcon name="compass" :size="38" /><strong>还没有确认过的记录</strong><p>药品照片经过家庭管理员确认后，会显示在这里。</p></div>
    <ul v-else class="list-plain member-record-list">
      <li v-for="event in events" :key="event.id" class="member-record-row">
        <span class="member-record-icon"><AppIcon name="check" :size="17" /></span>
        <div><strong>{{ eventTypeLabel(event.event_type) }}</strong><p>{{ summarizeEventPayload(event) || '家庭健康记录' }}</p></div>
        <time>{{ formatDateTime(event.occurred_at) }}</time>
      </li>
    </ul>
  </section>
</template>
