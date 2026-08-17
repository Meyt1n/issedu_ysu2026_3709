<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import AppIcon from '@/components/AppIcon.vue'
import EmptyState from '@/components/EmptyState.vue'
import LevelTag from '@/components/LevelTag.vue'
import PrivacyBadge from '@/components/PrivacyBadge.vue'
import SkeletonCard from '@/components/SkeletonCard.vue'
import { createSpeaker } from '@/composables/useSpeech'
import { activeProvider } from '@/data'
import { riskLevelLabel, riskLevelTone } from '@/data/labels'
import type { RiskCard } from '@/data/types'
import { formatDateTime } from '@/utils/format'

const LEVEL_FILTERS = [
  { value: 'ALL', label: '全部' },
  { value: 'SEVERE', label: '严重' },
  { value: 'WARNING', label: '较高' },
  { value: 'INFO', label: '一般' },
  { value: 'TIP', label: '提示' },
] as const

type LevelFilter = (typeof LEVEL_FILTERS)[number]['value']

const risks = ref<RiskCard[]>([])
const loading = ref(true)
const error = ref('')
const levelFilter = ref<LevelFilter>('ALL')
const manualSpeaker = createSpeaker(() => true)

const filtered = computed(() =>
  levelFilter.value === 'ALL' ? risks.value : risks.value.filter(r => r.level === levelFilter.value),
)

const severeCount = computed(() => risks.value.filter(r => r.level === 'SEVERE' && !r.acknowledged).length)

/** 等级分布：用于顶部彩色比例条与图例。 */
const distribution = computed(() => {
  const buckets = [
    { level: 'SEVERE', label: '严重', tone: 'danger' },
    { level: 'WARNING', label: '较高', tone: 'warn' },
    { level: 'INFO', label: '一般', tone: 'info' },
    { level: 'TIP', label: '提示', tone: 'calm' },
  ] as const
  return buckets
    .map(bucket => ({
      ...bucket,
      count: risks.value.filter(r => r.level === bucket.level).length,
    }))
    .filter(bucket => bucket.count > 0)
})

const distributionLabel = computed(() =>
  distribution.value.map(b => `${b.label} ${b.count} 条`).join('，'),
)

async function reload(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    risks.value = await activeProvider().listRisks()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '加载失败，请稍后重试'
  } finally {
    loading.value = false
  }
}

function speakImportant(): void {
  const important = risks.value.filter(r => (r.level === 'SEVERE' || r.level === 'WARNING') && !r.acknowledged)
  if (important.length === 0) {
    manualSpeaker.speak('当前没有严重或较高等级的风险提醒。')
    return
  }
  const text = important
    .map(r => `${riskLevelLabel(r.level)}：${r.memberName}，${r.message}`)
    .join('。')
  manualSpeaker.speak(`共有 ${important.length} 条重要提醒。${text}。`)
}

onMounted(reload)
</script>

<template>
  <main id="main" class="screen">
    <header class="screen-header">
      <p class="eyebrow">风险与提醒</p>
      <h1>提醒</h1>
      <p class="screen-subtitle">
        风险等级由确定性规则计算；一般与信息类提醒会合并并受每日预算控制，严重提醒不被压制。
      </p>
      <PrivacyBadge />
    </header>

    <div class="btn-row">
      <button type="button" class="btn btn-quiet" @click="speakImportant">
        <AppIcon name="sound" :size="18" />
        播报重要提醒
      </button>
      <button type="button" class="btn btn-quiet" :disabled="loading" @click="reload">
        <AppIcon name="refresh" :size="18" />
        刷新
      </button>
    </div>

    <div class="filter-row" role="group" aria-label="按风险等级筛选">
      <button
        v-for="filter in LEVEL_FILTERS"
        :key="filter.value"
        type="button"
        class="filter-chip"
        :aria-pressed="levelFilter === filter.value"
        @click="levelFilter = filter.value"
      >
        {{ filter.label }}
      </button>
    </div>

    <div v-if="!loading && distribution.length > 0" class="card distribution-card">
      <div class="level-bar" role="img" :aria-label="`风险等级分布：${distributionLabel}`">
        <span
          v-for="bucket in distribution"
          :key="bucket.level"
          :data-tone="bucket.tone"
          :style="{ flexGrow: bucket.count }"
        ></span>
      </div>
      <p class="meta-line">
        <template v-for="bucket in distribution" :key="bucket.level">
          {{ bucket.label }} {{ bucket.count }} 条&nbsp;&nbsp;
        </template>
      </p>
    </div>

    <p v-if="severeCount > 0" class="notice" data-tone="error" role="alert">
      有 {{ severeCount }} 条严重风险待处理，请优先查看。
    </p>
    <p v-if="error" class="notice" data-tone="error" role="alert">{{ error }}</p>

    <div v-if="loading" class="plain-list" aria-label="正在加载" aria-live="polite">
      <SkeletonCard />
      <SkeletonCard />
    </div>

    <div v-else class="plain-list">
      <EmptyState
        v-if="filtered.length === 0"
        icon="shield"
        title="该等级下暂无提醒"
        hint="规则重新计算后结果会更新"
      />
      <RouterLink
        v-for="risk in filtered"
        :key="`${risk.memberId}-${risk.ruleId}`"
        class="card risk-card"
        :to="`/alerts/${risk.memberId}/${encodeURIComponent(risk.ruleId)}`"
      >
        <div class="risk-row">
          <span class="icon-disc" :data-tone="riskLevelTone(risk.level)" aria-hidden="true">
            <AppIcon name="alert" :size="21" />
          </span>
          <div class="risk-body">
            <p class="risk-message">{{ risk.message }}</p>
            <p class="meta-line">
              <LevelTag kind="risk" :value="risk.level" />
              <span v-if="risk.acknowledged" class="tag" data-tone="calm">已记录知晓</span>
            </p>
            <p class="meta-line">
              {{ risk.memberName }}
              <template v-if="risk.createdAt"> · {{ formatDateTime(risk.createdAt) }}</template>
              · 证据 {{ risk.sourceCount }} 条
            </p>
          </div>
          <AppIcon name="chevron-right" :size="17" />
        </div>
      </RouterLink>
    </div>

    <footer class="disclaimer">
      风险提示只说明“发现已知资料，需要进一步确认”，不构成诊断或用药调整建议。
    </footer>
  </main>
</template>

<style scoped>
.filter-row { display: flex; gap: 8px; flex-wrap: wrap; }
.filter-chip {
  min-height: calc(var(--tap) - 6px);
  padding: 4px 17px;
  border: 1px solid var(--glass-border);
  border-radius: var(--r-pill);
  background: var(--glass-chip);
  -webkit-backdrop-filter: blur(10px);
  backdrop-filter: blur(10px);
  color: var(--c-ink-soft);
  font-weight: 800;
  cursor: pointer;
  box-shadow: inset 0 1px 0 var(--hilite);
  transition: background var(--speed), color var(--speed), transform var(--speed) var(--ease-spring);
}
.filter-chip:active { transform: scale(0.94); }
.filter-chip[aria-pressed='true'] {
  background: var(--grad-btn);
  border-color: transparent;
  color: #fff;
  box-shadow: 0 8px 16px -8px rgba(0, 0, 0, 0.5);
}
html[data-contrast='high'] .filter-chip { border: 2px solid #000; background: #fff; }
html[data-contrast='high'] .filter-chip[aria-pressed='true'] { background: var(--c-brand); color: #fff; }
.risk-row { display: flex; align-items: center; gap: 12px; }
.risk-body { flex: 1; min-width: 0; display: grid; gap: 6px; }
.risk-message { font-weight: 700; line-height: 1.4; }
.distribution-card { gap: 9px; padding: 14px 16px; }
</style>
