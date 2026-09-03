<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import AppIcon from '@/components/AppIcon.vue'
import ErrorNotice from '@/components/ErrorNotice.vue'
import EmptyState from '@/components/EmptyState.vue'
import ListLoadingState from '@/components/ListLoadingState.vue'
import ListStatusAnnouncer from '@/components/ListStatusAnnouncer.vue'
import PrivacyBadge from '@/components/PrivacyBadge.vue'
import { activeProvider } from '@/data'
import { memberRoleLabel } from '@/data/labels'
import type { MemberSummary } from '@/data/types'
import { avatarHue, formatDay } from '@/utils/format'
import { presentListApiError, type ErrorPresentation } from '@/api/errors'
import { sessionContextKey, useSession } from '@/stores/session'

const members = ref<MemberSummary[]>([])
const loading = ref(true)
const error = ref<ErrorPresentation | null>(null)
const { session } = useSession()
let reloadGeneration = 0
let reloadInFlight = false

const listStatusMessage = computed(() => {
  if (loading.value || error.value) return ''
  return members.value.length > 0
    ? `已加载 ${members.value.length} 位家庭成员。`
    : '当前没有可用的家庭成员。'
})

async function reload(): Promise<void> {
  if (reloadInFlight) return
  reloadInFlight = true
  const generation = ++reloadGeneration
  const expectedKey = sessionContextKey(session)
  loading.value = true
  error.value = null
  members.value = []
  try {
    const nextMembers = await activeProvider().listMembers()
    if (generation !== reloadGeneration || expectedKey !== sessionContextKey(session)) return
    members.value = nextMembers
  } catch (cause) {
    if (generation !== reloadGeneration || expectedKey !== sessionContextKey(session)) return
    error.value = presentListApiError(cause)
  } finally {
    if (generation === reloadGeneration) loading.value = false
    reloadInFlight = false
  }
}

onMounted(reload)
watch(() => sessionContextKey(session), () => void reload())
</script>

<template>
  <main id="main" class="screen">
    <header class="screen-header">
      <p class="eyebrow">家庭成员</p>
      <h1>家人</h1>
      <p class="screen-subtitle">只显示你被授权查看的成员与字段；“家庭成员”不等于“可以看全部”。</p>
      <PrivacyBadge />
    </header>

    <ErrorNotice v-if="error" :error="error" :busy="loading" @retry="reload" />
    <ListLoadingState v-if="loading" label="正在加载家庭成员…" :count="3" />

    <div v-else class="plain-list">
      <EmptyState
        v-if="members.length === 0 && !error"
        icon="family"
        title="确实没有可用的家庭成员"
        hint="请到“我的”检查联机身份、家庭和授权设置。"
      />
      <RouterLink
        v-for="member in members"
        :key="member.id"
        class="card member-card"
        :to="`/family/${member.id}`"
      >
        <div class="member-row">
          <span class="avatar" :data-hue="avatarHue(member.name)" aria-hidden="true">{{ member.avatarText }}</span>
          <div class="member-info">
            <div class="card-title-row">
              <strong>{{ member.name }}</strong>
              <span class="tag" data-tone="neutral">{{ member.relation }} · {{ memberRoleLabel(member.role) }}</span>
            </div>
            <p v-if="member.visibleScope === 'FULL'" class="meta-line">完整视角（本人或家庭管理员）</p>
            <template v-else>
              <p class="meta-line">可见：{{ member.visibleScope.fields.join('、') }}</p>
              <p class="meta-line">
                用途：{{ member.visibleScope.purpose }}
                <template v-if="member.visibleScope.validUntil">
                  · 授权至 {{ formatDay(member.visibleScope.validUntil) }}
                </template>
              </p>
            </template>
            <p class="meta-line">
              待处理任务 {{ member.pendingTaskCount }} 项
              <template v-if="member.severeRiskCount > 0"> · 严重风险 {{ member.severeRiskCount }} 条</template>
              <template v-if="member.warningRiskCount > 0"> · 较高风险 {{ member.warningRiskCount }} 条</template>
            </p>
          </div>
          <AppIcon name="chevron-right" :size="18" />
        </div>
      </RouterLink>
    </div>

    <ListStatusAnnouncer :message="listStatusMessage" />

    <footer class="disclaimer">仅作健康记录与提醒。</footer>
  </main>
</template>

<style scoped>
.member-card { text-decoration: none; color: inherit; }
.member-row { display: flex; align-items: center; gap: 12px; }
.member-info { flex: 1; display: grid; gap: 4px; min-width: 0; }
</style>
