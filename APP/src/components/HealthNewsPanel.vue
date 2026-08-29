<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import AppIcon from '@/components/AppIcon.vue'
import ErrorNotice from '@/components/ErrorNotice.vue'
import ListLoadingState from '@/components/ListLoadingState.vue'
import { presentListApiError, type ErrorPresentation } from '@/api/errors'
import type { HealthNewsItem, HealthNewsResponse } from '@/api/types'
import { activeProvider } from '@/data'
import {
  assistantPromptForItem,
  itemSourceLine,
  presentHealthNews,
  presentHealthNewsFreshness,
  refreshOutcomeMessage,
} from '@/utils/healthNews'

const router = useRouter()
const news = ref<HealthNewsResponse | null>(null)
const loading = ref(false)
const loadError = ref<ErrorPresentation | null>(null)
/** 刷新结果反馈；成功与「仍是缓存」都在这里说清楚，不谎报成功。 */
const refreshMessage = ref('')
let loadInFlight = false

const view = computed(() => presentHealthNews(news.value))
const freshness = computed(() => presentHealthNewsFreshness(news.value))
const refreshLabel = computed(() => (loading.value ? '刷新中…' : '刷新'))

/**
 * MOB-165：刷新只调家庭服务器，不直连外部资讯源。
 * `loadInFlight` 保证连续点击不会发出重复请求；失败时保留旧内容，不清空列表。
 */
async function loadNews(options?: { refresh?: boolean }): Promise<void> {
  if (loadInFlight) return
  loadInFlight = true
  loading.value = true
  loadError.value = null
  if (options?.refresh) refreshMessage.value = ''
  try {
    // 整份替换而不是合并：服务端换了缓存配置指纹后，旧指纹下的内容不会残留。
    news.value = await activeProvider().getHealthNews()
    if (options?.refresh) refreshMessage.value = refreshOutcomeMessage(news.value)
  } catch (cause) {
    loadError.value = presentListApiError(cause)
    refreshMessage.value = ''
  } finally {
    loading.value = false
    loadInFlight = false
  }
}

function refreshNews(): void {
  void loadNews({ refresh: true })
}

function openItem(item: HealthNewsItem): void {
  void router.push({ name: 'assistant', query: { prompt: assistantPromptForItem(item) } })
}

onMounted(() => {
  void loadNews()
})
</script>

<template>
  <section class="card health-news-panel" aria-labelledby="health-news-title">
    <div class="health-news-heading">
      <div>
        <p class="eyebrow">健康资讯</p>
        <h2 id="health-news-title">{{ view.title }}</h2>
      </div>
      <span class="health-news-status" :data-tone="view.statusTone">{{ view.statusLabel }}</span>
    </div>

    <p class="health-news-intro">{{ view.intro }}</p>

    <p
      v-if="freshness.expired"
      class="notice warn health-news-expired"
      role="alert"
    >
      {{ freshness.notice }}
    </p>
    <p v-else-if="freshness.notice" class="health-news-meta" role="status">
      {{ freshness.notice }}
    </p>

    <div class="health-news-actions">
      <button
        type="button"
        class="btn health-news-refresh"
        :class="freshness.emphasizeRefresh ? 'btn-secondary' : 'btn-quiet'"
        :disabled="loading"
        :aria-busy="loading"
        @click="refreshNews"
      >
        <AppIcon name="refresh" :size="16" />
        {{ refreshLabel }}
      </button>
    </div>
    <p v-if="refreshMessage" class="health-news-meta" role="status">{{ refreshMessage }}</p>

    <p v-if="view.degradedLabel" class="health-news-degraded" role="status">
      {{ view.degradedLabel }}
    </p>

    <ListLoadingState v-if="loading && !news" label="正在读取健康资讯…" :count="2" :disc="false" />
    <ErrorNotice v-else-if="loadError && !news" :error="loadError" :busy="loading" @retry="refreshNews" />
    <p v-else-if="loadError" class="notice warn health-news-inline-error" role="status">
      资讯刷新未完成（{{ loadError.message }}），当前仍保留上一次读取到的内容。
      <button type="button" class="btn btn-quiet" :disabled="loading" @click="refreshNews">
        {{ loading ? '重试中…' : '重试' }}
      </button>
    </p>
    <ul v-else-if="news && news.items.length > 0" class="health-news-list">
      <li v-for="item in news.items" :key="item.id">
        <button type="button" class="health-news-item" @click="openItem(item)">
          <span class="health-news-tag-row">
            <span class="health-news-tag">{{ item.tag }}</span>
            <span v-if="item.kind === 'remote' || item.source === 'remote_whitelist'" class="health-news-kind">白名单来源</span>
          </span>
          <strong>{{ item.title }}</strong>
          <span class="health-news-summary">{{ item.summary }}</span>
          <span class="health-news-source">{{ itemSourceLine(item) }}</span>
          <span class="health-news-cta">
            带着问题问助手
            <AppIcon name="chevron-right" :size="16" />
          </span>
        </button>
      </li>
    </ul>
    <p v-else class="meta-line health-news-empty" role="status">
      当前没有可展示的健康资讯，首页其他功能仍可正常使用。
    </p>

    <p v-if="news?.disclaimer" class="health-news-disclaimer">{{ news.disclaimer }}</p>
  </section>
</template>

<style scoped>
.health-news-panel {
  display: grid;
  gap: 12px;
  margin-top: 10px;
}

.health-news-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.health-news-heading h2 {
  margin: 0;
  font-size: 1.08rem;
}

.health-news-status,
.health-news-tag,
.health-news-kind {
  display: inline-flex;
  align-items: center;
  min-height: 30px;
  border-radius: var(--r-pill);
  padding: 0 10px;
  font-size: 0.78rem;
  font-weight: 800;
  white-space: nowrap;
}

.health-news-status[data-tone='ok'] {
  color: var(--c-calm-deep);
  background: var(--c-calm-soft);
}

.health-news-status[data-tone='warn'] {
  color: var(--c-warn-deep);
  background: var(--c-warn-soft);
}

.health-news-status[data-tone='muted'] {
  color: var(--c-ink-soft);
  background: var(--c-brand-softer);
}

.health-news-intro,
.health-news-meta,
.health-news-degraded,
.health-news-disclaimer,
.health-news-empty {
  margin: 0;
  color: var(--c-ink-soft);
  font-size: 0.88rem;
  line-height: 1.55;
}

.health-news-meta,
.health-news-degraded,
.health-news-disclaimer {
  font-size: 0.8rem;
}

.health-news-degraded { color: var(--c-warn-deep); }
.health-news-disclaimer { color: var(--c-ink-faint); }

.health-news-expired {
  margin: 0;
  font-size: 0.84rem;
  line-height: 1.5;
}

.health-news-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.health-news-refresh {
  align-items: center;
  display: inline-flex;
  gap: 6px;
  min-height: var(--tap);
}

.health-news-refresh:focus-visible { outline: 3px solid var(--focus-ring); outline-offset: 3px; }
.health-news-refresh[disabled] { cursor: progress; }

.health-news-inline-error {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  line-height: 1.45;
}

.health-news-inline-error .btn {
  flex: 0 0 auto;
  min-height: var(--tap);
}

.health-news-list {
  display: grid;
  gap: 10px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.health-news-item {
  width: 100%;
  min-height: var(--tap);
  display: grid;
  gap: 7px;
  padding: 14px;
  text-align: left;
  color: inherit;
  border: 1px solid var(--c-line-strong);
  border-radius: 18px;
  background: var(--c-surface-solid);
  box-shadow: var(--shadow-press);
  cursor: pointer;
  transition: transform var(--speed) var(--ease), border-color var(--speed) var(--ease);
}

.health-news-item:hover { transform: translateY(-1px); border-color: var(--c-brand); }
.health-news-item:focus-visible { outline: 3px solid var(--focus-ring); outline-offset: 3px; }

.health-news-tag-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.health-news-tag { min-height: 26px; padding-inline: 9px; color: var(--c-brand-deep); background: var(--c-brand-soft); }
.health-news-kind { min-height: 26px; padding-inline: 9px; color: var(--c-warn-deep); background: var(--c-warn-soft); }
.health-news-item strong { font-size: 0.98rem; line-height: 1.4; }
.health-news-summary,
.health-news-source { color: var(--c-ink-soft); line-height: 1.5; }
.health-news-source { color: var(--c-ink-faint); font-size: 0.78rem; }
.health-news-cta { display: inline-flex; align-items: center; gap: 4px; color: var(--c-brand-strong); font-size: 0.84rem; font-weight: 800; }

@media (max-width: 360px) {
  .health-news-heading { gap: 8px; }
  .health-news-status { padding-inline: 8px; font-size: 0.72rem; }
  .health-news-item { padding: 12px; }
}
</style>
