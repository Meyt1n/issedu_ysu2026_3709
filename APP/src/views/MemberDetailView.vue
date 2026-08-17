<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import AppIcon from '@/components/AppIcon.vue'
import EmptyState from '@/components/EmptyState.vue'
import { activeProvider } from '@/data'
import { eventStatusLabel, memberRoleLabel } from '@/data/labels'
import type { MemberDetail } from '@/data/types'
import { avatarHue, formatDateTime, formatDay } from '@/utils/format'

const route = useRoute()
const router = useRouter()

const detail = ref<MemberDetail | null>(null)
const loading = ref(true)
const error = ref('')

onMounted(async () => {
  const memberId = String(route.params.memberId ?? '')
  try {
    detail.value = await activeProvider().getMemberDetail(memberId)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '加载失败或未获授权'
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <main id="main" class="screen">
    <button type="button" class="btn btn-quiet back-btn" @click="router.back()">
      <AppIcon name="arrow-left" :size="18" />
      返回
    </button>

    <p v-if="error" class="notice" data-tone="error" role="alert">{{ error }}</p>
    <section v-if="loading" class="card" aria-live="polite">
      <p class="empty-state">正在加载成员档案…</p>
    </section>

    <template v-else-if="detail">
      <header class="card">
        <div class="member-row">
          <span class="avatar" :data-hue="avatarHue(detail.summary.name)" aria-hidden="true">{{ detail.summary.avatarText }}</span>
          <div class="member-info">
            <h1>{{ detail.summary.name }}</h1>
            <p class="meta-line">
              {{ detail.summary.relation }} · {{ memberRoleLabel(detail.summary.role) }}
            </p>
            <p v-if="detail.summary.visibleScope === 'FULL'" class="meta-line">完整视角（本人或家庭管理员）</p>
            <p v-else class="meta-line">
              可见范围：{{ detail.summary.visibleScope.fields.join('、') }}
              <template v-if="detail.summary.visibleScope.validUntil">
                · 授权至 {{ formatDay(detail.summary.visibleScope.validUntil) }}
              </template>
            </p>
          </div>
        </div>
      </header>

      <section aria-labelledby="med-title">
        <div class="section-heading">
          <h2 id="med-title">用药与计划</h2>
        </div>
        <div class="card" style="margin-top: 10px">
          <p v-if="detail.medications === 'UNAUTHORIZED'" class="notice" data-tone="warn">
            「用药与计划」字段未向你授权，内容不可见。如需查看请由本人在网页端调整授权。
          </p>
          <EmptyState
            v-else-if="detail.medications.length === 0"
            icon="check"
            title="暂无已确认的用药记录"
          />
          <ul v-else class="divided-list">
            <li v-for="med in detail.medications" :key="med.name" class="med-row">
              <span
                class="icon-disc med-disc"
                :data-tone="med.expired ? 'danger' : med.stockDaysLeft !== null && med.stockDaysLeft <= 5 ? 'warn' : 'calm'"
                aria-hidden="true"
              >
                <AppIcon name="pill" :size="19" />
              </span>
              <div class="med-body">
                <div class="card-title-row">
                  <strong>{{ med.name }}</strong>
                  <span v-if="med.expired" class="tag" data-tone="danger">已过期</span>
                  <span
                    v-else-if="med.stockDaysLeft !== null && med.stockDaysLeft <= 5"
                    class="tag"
                    data-tone="warn"
                  >
                    库存不足
                  </span>
                </div>
                <span class="meta-line">{{ med.spec }} · {{ med.schedule }}</span>
                <span class="meta-line">
                  <template v-if="med.stockDaysLeft !== null">剩余约 {{ med.stockDaysLeft }} 天用量 · </template>
                  <template v-if="med.expiryDate">有效期至 {{ formatDay(med.expiryDate) }} · </template>
                  {{ med.confirmed ? '已人工确认' : '待确认' }}
                </span>
              </div>
            </li>
          </ul>
        </div>
      </section>

      <section aria-labelledby="timeline-title">
        <div class="section-heading">
          <h2 id="timeline-title">事件时间线</h2>
        </div>
        <div class="card" style="margin-top: 10px">
          <p v-if="detail.timeline === 'UNAUTHORIZED'" class="notice" data-tone="warn">
            「健康事件」字段未向你授权，内容不可见。
          </p>
          <EmptyState
            v-else-if="detail.timeline.length === 0"
            icon="clock"
            title="暂无可见的健康事件"
          />
          <ul v-else class="divided-list event-timeline">
            <li
              v-for="event in detail.timeline"
              :key="event.id"
              :data-unconfirmed="event.confirmationStatus !== 'CONFIRMED'"
            >
              <strong>{{ event.title }}</strong>
              <span class="meta-line">
                {{ eventStatusLabel(event.confirmationStatus) }} · {{ formatDateTime(event.occurredAt) }} · 来源
                {{ event.source }}
              </span>
            </li>
          </ul>
        </div>
      </section>

      <section aria-labelledby="auth-title">
        <div class="section-heading">
          <h2 id="auth-title">谁可以查看</h2>
        </div>
        <div class="card" style="margin-top: 10px">
          <EmptyState v-if="detail.authorizations.length === 0" icon="shield" title="暂无对外授权" />
          <ul v-else class="divided-list">
            <li v-for="auth in detail.authorizations" :key="auth.granteeName + auth.validUntil">
              <strong>{{ auth.granteeName }}</strong>
              <span class="meta-line">可见：{{ auth.fields.join('、') }}</span>
              <span class="meta-line">用途：{{ auth.purpose }} · 有效期至 {{ formatDay(auth.validUntil) }}</span>
            </li>
          </ul>
          <p class="meta-line">授权的新增、修改与撤回在网页端完成；移动端只读展示。</p>
        </div>
      </section>
    </template>

    <footer class="disclaimer">教学演示，不用于诊断或治疗。</footer>
  </main>
</template>

<style scoped>
.back-btn { justify-self: start; }
.member-row { display: flex; align-items: center; gap: 12px; }
.member-info { flex: 1; display: grid; gap: 4px; min-width: 0; }
.med-row { display: flex; gap: 12px; align-items: flex-start; }
.med-disc { width: 40px; height: 40px; }
.med-body { flex: 1; min-width: 0; display: grid; gap: 4px; }
</style>
