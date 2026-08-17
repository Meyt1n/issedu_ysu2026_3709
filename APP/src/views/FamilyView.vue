<script setup lang="ts">
import { onMounted, ref } from 'vue'

import AppIcon from '@/components/AppIcon.vue'
import EmptyState from '@/components/EmptyState.vue'
import PrivacyBadge from '@/components/PrivacyBadge.vue'
import SkeletonCard from '@/components/SkeletonCard.vue'
import { activeProvider } from '@/data'
import { memberRoleLabel } from '@/data/labels'
import type { MemberSummary } from '@/data/types'
import { avatarHue, formatDay } from '@/utils/format'

const members = ref<MemberSummary[]>([])
const loading = ref(true)
const error = ref('')

onMounted(async () => {
  try {
    members.value = await activeProvider().listMembers()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '加载失败，请稍后重试'
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <main id="main" class="screen">
    <header class="screen-header">
      <p class="eyebrow">家庭成员</p>
      <h1>家人</h1>
      <p class="screen-subtitle">只显示你被授权查看的成员与字段；“家庭成员”不等于“可以看全部”。</p>
      <PrivacyBadge />
    </header>

    <p v-if="error" class="notice" data-tone="error" role="alert">{{ error }}</p>
    <div v-if="loading" class="plain-list" aria-label="正在加载" aria-live="polite">
      <SkeletonCard />
      <SkeletonCard />
      <SkeletonCard />
    </div>

    <div v-else class="plain-list">
      <EmptyState
        v-if="members.length === 0 && !error"
        icon="family"
        title="当前身份看不到任何成员"
        hint="请在网页端检查家庭与授权设置"
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

    <p class="notice">
      授权范围由家庭服务器在接口层过滤；本页不会推断或显示未授权的内容。调整授权请使用网页端“授权设置”。
    </p>

    <footer class="disclaimer">教学演示，不用于诊断或治疗。</footer>
  </main>
</template>

<style scoped>
.member-card { text-decoration: none; color: inherit; }
.member-row { display: flex; align-items: center; gap: 12px; }
.member-info { flex: 1; display: grid; gap: 4px; min-width: 0; }
</style>
