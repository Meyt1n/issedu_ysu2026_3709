<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import AppIcon from '@/components/AppIcon.vue'
import ErrorNotice from '@/components/ErrorNotice.vue'
import LevelTag from '@/components/LevelTag.vue'
import { useSpeech } from '@/composables/useSpeech'
import { activeProvider } from '@/data'
import { eventStatusLabel, riskLevelLabel } from '@/data/labels'
import type { RiskCard } from '@/data/types'
import { CAPABILITY_IDS, useCapabilities } from '@/stores/capabilities'
import { sessionContextKey, useSession } from '@/stores/session'
import { formatDateTime } from '@/utils/format'
import { normalizePhoneNumber } from '@/utils/phone'
import { presentApiError, type ErrorPresentation } from '@/api/errors'

const route = useRoute()
const router = useRouter()
const { session } = useSession()
const { capabilities, hasCapability } = useCapabilities()
const speech = useSpeech()

const risk = ref<RiskCard | null>(null)
const loading = ref(true)
const error = ref<ErrorPresentation | null>(null)
const actionMessage = ref('')
const actionError = ref<ErrorPresentation | null>(null)
const acknowledging = ref(false)
const supportsAcknowledgement = computed(() =>
  session.dataMode === 'demo' || hasCapability(CAPABILITY_IDS.riskAcknowledgement),
)
const acknowledgementStatusMessage = computed(() => {
  if (session.dataMode === 'demo') return ''
  if (!capabilities.snapshot) return '能力探测尚未完成；请先到“我的”测试连接，本按钮会按不可用处理。'
  return '家庭服务器暂不支持回写“已知晓”状态；本页不会将其标记为已记录。'
})
let loadGeneration = 0

const phoneHref = computed(() => {
  const phone = normalizePhoneNumber(session.caregiverPhone)
  return phone ? `tel:${phone}` : ''
})

async function load(): Promise<void> {
  const generation = ++loadGeneration
  const expectedKey = sessionContextKey(session)
  loading.value = true
  error.value = null
  risk.value = null
  const memberId = String(route.params.memberId ?? '')
  const ruleId = decodeURIComponent(String(route.params.ruleId ?? ''))
  try {
    const nextRisk = await activeProvider().getRiskDetail(memberId, ruleId)
    if (generation !== loadGeneration || expectedKey !== sessionContextKey(session)) return
    risk.value = nextRisk
    speech.speak(`${riskLevelLabel(risk.value.level)}风险：${risk.value.message}。${risk.value.suggestion}`)
  } catch (cause) {
    if (generation !== loadGeneration || expectedKey !== sessionContextKey(session)) return
    error.value = presentApiError(cause)
  } finally {
    if (generation === loadGeneration) loading.value = false
  }
}

onMounted(load)
watch(() => sessionContextKey(session), () => void load())

async function acknowledge(): Promise<void> {
  if (!risk.value || !supportsAcknowledgement.value) return
  acknowledging.value = true
  actionError.value = null
  try {
    risk.value = await activeProvider().acknowledgeRisk(risk.value.memberId, risk.value.ruleId)
    actionMessage.value = '已记录你的知晓状态，家人可以在事件中心看到。'
  } catch (cause) {
    actionError.value = presentApiError(cause)
  } finally {
    acknowledging.value = false
  }
}
</script>

<template>
  <main id="main" class="screen">
    <button type="button" class="btn btn-quiet back-btn" @click="router.back()">
      <AppIcon name="arrow-left" :size="18" />
      返回
    </button>

    <ErrorNotice v-if="error" :error="error" @retry="load" />
    <section v-if="loading" class="card" aria-live="polite">
      <p class="empty-state">正在加载风险依据…</p>
    </section>

    <template v-else-if="risk">
      <header class="card">
        <div class="card-title-row">
          <LevelTag kind="risk" :value="risk.level" />
          <span v-if="risk.acknowledged" class="tag" data-tone="calm">已记录知晓</span>
        </div>
        <h1 class="risk-title">{{ risk.message }}</h1>
        <p class="meta-line">
          {{ risk.memberName }}
          <template v-if="risk.createdAt"> · {{ formatDateTime(risk.createdAt) }}</template>
        </p>
        <p class="meta-line">规则 {{ risk.ruleId }} · 版本 {{ risk.ruleVersion ?? '服务端未返回完整审计信息' }}</p>
      </header>

      <section class="card" aria-labelledby="audit-title">
        <div class="card-title-row">
          <h2 id="audit-title">服务端审计信息</h2>
          <span class="tag" :data-tone="risk.audit.complete ? 'calm' : 'warn'">
            {{ risk.audit.complete ? '字段完整' : '信息不完整' }}
          </span>
        </div>
        <dl class="audit-grid">
          <div><dt>风险指纹</dt><dd>{{ risk.riskFingerprint ? '已由服务端返回' : '服务端未返回完整审计信息' }}</dd></div>
          <div><dt>去重/合并</dt><dd>{{ risk.audit.mergedCount ?? '服务端未返回完整审计信息' }}</dd></div>
          <div><dt>预算结论</dt><dd>{{ risk.audit.budgetStatus ?? '服务端未返回完整审计信息' }}</dd></div>
          <div><dt>下次可见</dt><dd>{{ risk.audit.nextVisibleAt ? formatDateTime(risk.audit.nextVisibleAt) : '服务端未返回完整审计信息' }}</dd></div>
          <div><dt>有效期</dt><dd>{{ risk.audit.validUntil ? formatDateTime(risk.audit.validUntil) : '服务端未返回完整审计信息' }}</dd></div>
          <div><dt>证据摘要</dt><dd>{{ risk.audit.evidenceSummary ?? '服务端未返回完整审计信息' }}</dd></div>
        </dl>
        <p v-if="!risk.audit.complete" class="meta-line">
          服务端未返回完整审计信息；移动端不会根据本地规则推断合并、预算、有效期或医疗结论。
        </p>
        <p v-else-if="risk.audit.budgetReason" class="meta-line">{{ risk.audit.budgetReason }}</p>
      </section>

      <section class="card" aria-labelledby="why-title">
        <h2 id="why-title">为什么出现这条提醒</h2>
        <p>{{ risk.explanation }}</p>
      </section>

      <section class="card" aria-labelledby="evidence-title">
        <h2 id="evidence-title">证据事件（{{ risk.sourceEvents.length }}）</h2>
        <p v-if="risk.sourceEvents.length === 0" class="meta-line">
          证据摘要暂不可用；联机模式下以家庭服务器返回的脱敏摘要为准。
        </p>
        <ul v-else class="divided-list">
          <li v-for="event in risk.sourceEvents" :key="event.id">
            <strong>{{ event.eventType }}</strong>
            <span class="meta-line">
              {{ event.id }} · {{ eventStatusLabel(event.confirmationStatus) }}
              <template v-if="event.createdAt"> · {{ formatDateTime(event.createdAt) }}</template>
            </span>
          </li>
        </ul>
        <p class="meta-line">本页只展示脱敏摘要，不加载健康事件正文。</p>
      </section>

      <section class="card" aria-labelledby="suggestion-title">
        <h2 id="suggestion-title">建议处理</h2>
        <p>{{ risk.suggestion }}</p>
        <p v-if="!supportsAcknowledgement" class="notice" data-tone="warn" role="status">{{ acknowledgementStatusMessage }}</p>
        <ErrorNotice v-if="actionError" :error="actionError" @retry="acknowledge" />
        <p v-else-if="actionMessage" class="notice" data-tone="success" role="status">{{ actionMessage }}</p>
        <div class="btn-row">
          <button
            type="button"
            class="btn"
            :disabled="acknowledging || risk.acknowledged || !supportsAcknowledgement"
            @click="acknowledge"
          >
            <AppIcon name="check" :size="18" />
            {{ risk.acknowledged ? '已记录知晓' : '我已知晓' }}
          </button>
          <a v-if="phoneHref" class="btn btn-quiet" :href="phoneHref">
            <AppIcon name="phone" :size="18" />
            联系家人{{ session.caregiverName ? `（${session.caregiverName}）` : '' }}
          </a>
          <RouterLink v-else class="btn btn-quiet" to="/me">
            设置紧急联系人后可一键拨号
          </RouterLink>
        </div>
      </section>
    </template>

    <footer class="disclaimer">
      本提示由确定性规则给出，仅表示“发现已知资料，需要进一步确认”；不构成诊断、处方或停药建议。紧急情况请联系医生或当地急救服务。
    </footer>
  </main>
</template>

<style scoped>
.back-btn { justify-self: start; }
.risk-title { font-size: 1.25rem; }
.audit-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px 16px; margin: 0; }
.audit-grid div { display: grid; gap: 3px; }
.audit-grid dt { color: var(--c-ink-muted); font-size: .78rem; }
.audit-grid dd { margin: 0; font-weight: 800; overflow-wrap: anywhere; }
</style>
