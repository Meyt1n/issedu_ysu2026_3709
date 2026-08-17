<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import AppIcon from '@/components/AppIcon.vue'
import LevelTag from '@/components/LevelTag.vue'
import { useSpeech } from '@/composables/useSpeech'
import { activeProvider } from '@/data'
import { eventStatusLabel, riskLevelLabel } from '@/data/labels'
import type { RiskCard } from '@/data/types'
import { useSession } from '@/stores/session'
import { formatDateTime } from '@/utils/format'

const route = useRoute()
const router = useRouter()
const { session } = useSession()
const speech = useSpeech()

const risk = ref<RiskCard | null>(null)
const loading = ref(true)
const error = ref('')
const actionMessage = ref('')
const actionError = ref('')
const acknowledging = ref(false)

const phoneHref = computed(() =>
  session.caregiverPhone ? `tel:${session.caregiverPhone.replace(/\s+/g, '')}` : '',
)

onMounted(async () => {
  const memberId = String(route.params.memberId ?? '')
  const ruleId = decodeURIComponent(String(route.params.ruleId ?? ''))
  try {
    risk.value = await activeProvider().getRiskDetail(memberId, ruleId)
    speech.speak(`${riskLevelLabel(risk.value.level)}风险：${risk.value.message}。${risk.value.suggestion}`)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '加载失败或未获授权'
  } finally {
    loading.value = false
  }
})

async function acknowledge(): Promise<void> {
  if (!risk.value) return
  acknowledging.value = true
  actionError.value = ''
  try {
    risk.value = await activeProvider().acknowledgeRisk(risk.value.memberId, risk.value.ruleId)
    actionMessage.value = '已记录你的知晓状态，家人可以在事件中心看到。'
  } catch (cause) {
    actionError.value = cause instanceof Error ? cause.message : '操作失败，请稍后重试'
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

    <p v-if="error" class="notice" data-tone="error" role="alert">{{ error }}</p>
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
        <p class="meta-line">规则 {{ risk.ruleId }} · 版本 {{ risk.ruleVersion }}</p>
      </header>

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
        <p v-if="actionError" class="notice" data-tone="error" role="alert">{{ actionError }}</p>
        <p v-else-if="actionMessage" class="notice" data-tone="success" role="status">{{ actionMessage }}</p>
        <div class="btn-row">
          <button
            type="button"
            class="btn"
            :disabled="acknowledging || risk.acknowledged"
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
</style>
