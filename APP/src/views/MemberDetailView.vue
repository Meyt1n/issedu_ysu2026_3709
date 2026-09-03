<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import AppIcon from '@/components/AppIcon.vue'
import ErrorNotice from '@/components/ErrorNotice.vue'
import EmptyState from '@/components/EmptyState.vue'
import ListLoadingState from '@/components/ListLoadingState.vue'
import ListStatusAnnouncer from '@/components/ListStatusAnnouncer.vue'
import { activeProvider } from '@/data'
import { eventStatusLabel, memberRoleLabel } from '@/data/labels'
import type { MemberDetail } from '@/data/types'
import { avatarHue, formatDateTime, formatDay } from '@/utils/format'
import { presentListApiError, type ErrorPresentation } from '@/api/errors'
import { sessionContextKey, useSession } from '@/stores/session'

const route = useRoute()
const router = useRouter()
const { session } = useSession()

/** MOB-136：授权状态文字与色调（只读展示，不扩大服务端已授予范围）。 */
const AUTH_STATUS_LABELS: Record<string, { label: string; tone: 'calm' | 'warn' | 'danger' | 'neutral' }> = {
  ACTIVE: { label: '有效', tone: 'calm' },
  EXPIRING: { label: '即将到期', tone: 'warn' },
  EXPIRED: { label: '已到期', tone: 'danger' },
  REVOKED: { label: '已撤回', tone: 'neutral' },
  PENDING: { label: '待生效', tone: 'warn' },
}

function authStatusLabel(status: string) {
  return AUTH_STATUS_LABELS[status] ?? { label: `未知状态（${status}）`, tone: 'neutral' as const }
}

const detail = ref<MemberDetail | null>(null)
const loading = ref(true)
const error = ref<ErrorPresentation | null>(null)
let loadGeneration = 0
let loadInFlight = false

const listStatusMessage = computed(() => {
  if (loading.value || error.value) return ''
  return detail.value ? '已加载成员档案及其可见列表。' : ''
})

async function load(): Promise<void> {
  if (loadInFlight) return
  loadInFlight = true
  const generation = ++loadGeneration
  const expectedKey = sessionContextKey(session)
  loading.value = true
  error.value = null
  detail.value = null
  const memberId = String(route.params.memberId ?? '')
  try {
    const nextDetail = await activeProvider().getMemberDetail(memberId)
    if (generation !== loadGeneration || expectedKey !== sessionContextKey(session)) return
    detail.value = nextDetail
  } catch (cause) {
    if (generation !== loadGeneration || expectedKey !== sessionContextKey(session)) return
    error.value = presentListApiError(cause)
  } finally {
    if (generation === loadGeneration) loading.value = false
    loadInFlight = false
  }
}

onMounted(load)
watch(() => sessionContextKey(session), () => void load())
</script>

<template>
  <main id="main" class="screen">
    <button type="button" class="btn btn-quiet back-btn" @click="router.back()">
      <AppIcon name="arrow-left" :size="18" />
      返回
    </button>

    <ErrorNotice v-if="error" :error="error" :busy="loading" @retry="load" />
    <ListLoadingState v-if="loading" label="正在加载成员档案…" :count="3" />

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
          <template v-if="detail.authorizations === 'UNAUTHORIZED'">
            <p class="notice" data-tone="warn" role="status">
              当前身份无权查看这个家庭的授权管理（服务端隐藏式拒绝）；这不代表没有授权。授权的新增、修改与撤回由家庭 Owner 在网页端完成。
            </p>
          </template>
          <template v-else>
            <EmptyState v-if="detail.authorizations.length === 0" icon="shield" title="暂无对外授权" hint="家庭 Owner 可在网页端授权中心新增" />
            <ul v-else class="divided-list">
              <li v-for="auth in detail.authorizations" :key="auth.id">
                <div class="card-title-row">
                  <strong>{{ auth.granteeName }}</strong>
                  <span class="tag" :data-tone="authStatusLabel(auth.status).tone">{{ authStatusLabel(auth.status).label }}</span>
                </div>
                <span class="meta-line">身份标识：{{ auth.granteeActorId }}</span>
                <span class="meta-line">可见字段：{{ auth.fields.length > 0 ? auth.fields.join('、') : '（无）' }}</span>
                <span class="meta-line">允许动作：{{ auth.actions.length > 0 ? auth.actions.join('、') : '（无）' }}</span>
                <span class="meta-line">用途：{{ auth.purpose }}</span>
                <span class="meta-line">
                  有效期：{{ formatDay(auth.validFrom) }} 至 {{ formatDay(auth.validUntil) }}
                  <template v-if="auth.status === 'EXPIRING'">（即将到期，请到网页端确认续期）</template>
                  <template v-else-if="auth.status === 'EXPIRED'">（已到期，不再据此展示数据）</template>
                  <template v-else-if="auth.status === 'REVOKED'">（已撤回，服务端不再接受此授权）</template>
                </span>
                <span class="meta-line">服务端版本：v{{ auth.version }}</span>
              </li>
            </ul>
          </template>
          <p class="meta-line">授权的新增、修改与撤回在网页端完成；移动端只读展示服务端返回的授权状态。</p>
        </div>
      </section>
    </template>

    <ListStatusAnnouncer :message="listStatusMessage" />

    <footer class="disclaimer">仅作健康记录与提醒。</footer>
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
