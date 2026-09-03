<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { apiClient } from '../api/client'
import type { HealthNewsItem, HealthNewsResponse } from '../api/types'
import { itemSourceLine, presentHealthNews } from '../healthNews/healthNewsView'
import { formatError, openAssistantWithPrompt, requestOptions } from '../store'
import AppIcon from './AppIcon.vue'

const news = ref<HealthNewsResponse | null>(null)
const loading = ref(false)
const loadError = ref('')

const view = computed(() => presentHealthNews(news.value))

async function loadNews(): Promise<void> {
  loading.value = true
  loadError.value = ''
  try {
    news.value = await apiClient.getHealthNews(requestOptions.value)
  } catch (error) {
    loadError.value = formatError(error)
    news.value = null
  } finally {
    loading.value = false
  }
}

function openItem(item: HealthNewsItem): void {
  const url = item.source_url?.trim() ?? ''
  const prompt = url
    ? `请阅读这篇公开网页后再回答：${url}\n${item.chat_prompt}`
    : item.chat_prompt
  openAssistantWithPrompt(prompt, { allowNetworkSearch: true, newThread: true })
}

onMounted(() => {
  void loadNews()
})
</script>

<template>
  <section class="card health-news-panel" aria-label="健康新闻">
    <div class="card-heading">
      <div>
        <p class="eyebrow">健康新闻</p>
        <h3 class="card-title">{{ view.title }}</h3>
      </div>
      <div class="health-news-heading-actions">
        <span class="pill" :class="view.statusTone">{{ view.statusLabel }}</span>
        <button
          type="button"
          class="btn btn-ghost btn-small"
          :disabled="loading"
          :aria-busy="loading"
          @click="loadNews"
        >
          <AppIcon name="refresh" :size="14" />
          {{ loading ? '刷新中' : '刷新' }}
        </button>
      </div>
    </div>
    <p class="health-news-intro">{{ view.intro }}</p>
    <p v-if="view.showRemoteMeta" class="health-news-meta">
      <AppIcon name="lock" :size="14" />
      {{ view.fetchedLabel }}
      <span v-if="news?.cache_status === 'stale'"> · 旧缓存</span>
      <span v-if="news?.cache_status === 'fresh'"> · 缓存有效</span>
    </p>
    <p v-if="view.degradedLabel" class="health-news-degraded" role="status">
      {{ view.degradedLabel }}
    </p>
    <div v-if="loading && !news" class="inline-loading">正在读取健康新闻</div>
    <p v-else-if="loadError" class="notice warn" role="status">
      <AppIcon name="info" :size="16" />
      {{ loadError }}
    </p>
    <ul v-else class="list-plain health-news-list">
      <li v-for="item in news?.items ?? []" :key="item.id">
        <button
          type="button"
          class="health-news-item"
          @click="openItem(item)"
        >
          <span class="health-news-content">
            <span class="health-news-tag-row">
              <span class="health-news-tag">{{ item.tag }}</span>
              <span v-if="item.kind === 'remote'" class="health-news-kind">白名单来源</span>
            </span>
            <strong>{{ item.title }}</strong>
            <small>{{ item.summary }}</small>
            <span class="health-news-source">{{ itemSourceLine(item) }}</span>
            <span class="health-news-cta">
              去问问助手
              <AppIcon name="arrow-right" :size="16" />
            </span>
          </span>
        </button>
      </li>
    </ul>
    <p v-if="news?.disclaimer" class="health-news-disclaimer">{{ news.disclaimer }}</p>
  </section>
</template>

<style scoped>
.health-news-panel {
  margin-bottom: 1rem;
}

.health-news-heading-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.health-news-intro,
.health-news-disclaimer,
.health-news-meta,
.health-news-degraded {
  color: var(--muted, #5b6570);
  font-size: 0.92rem;
  line-height: 1.55;
  margin: 0.35rem 0 0.85rem;
}

.health-news-meta {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  margin-top: 0;
  font-size: 0.82rem;
}

.health-news-degraded {
  margin-top: 0;
  font-size: 0.82rem;
  color: color-mix(in srgb, var(--warn, #b7791f) 85%, #000);
}

.health-news-disclaimer {
  margin-top: 0.75rem;
  margin-bottom: 0;
  font-size: 0.82rem;
}

.health-news-list {
  display: grid;
  gap: 0.85rem;
  grid-auto-rows: 320px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.health-news-list > li {
  display: flex;
  min-width: 0;
}

.health-news-item {
  align-content: stretch;
  height: 100%;
  isolation: isolate;
  min-height: 0;
  overflow: hidden;
  padding: 0;
  position: relative;
  width: 100%;
  text-align: left;
  contain: paint;
  border: 1px solid color-mix(in srgb, var(--line, #d7dde5) 88%, transparent);
  border-radius: 16px;
  display: grid;
  cursor: pointer;
  transition: transform 200ms ease, border-color 200ms ease, box-shadow 200ms ease;
  /* 纸色晕染全覆盖（HCT-533）：四角淡彩收在纸色底上，边缘不发白、饱和度减半 */
  background:
    radial-gradient(circle at 0% 0%, color-mix(in srgb, var(--sky, #47708c) 10%, transparent) 0%, transparent 62%),
    radial-gradient(circle at 100% 0%, color-mix(in srgb, var(--pine, #38665a) 9%, transparent) 0%, transparent 58%),
    radial-gradient(circle at 0% 100%, color-mix(in srgb, var(--pine, #38665a) 8%, transparent) 0%, transparent 54%),
    radial-gradient(circle at 100% 100%, color-mix(in srgb, var(--sky, #47708c) 8%, transparent) 0%, transparent 58%),
    color-mix(in srgb, var(--paper, #f6f1e6) 38%, var(--card, #fffdf8));
}

.health-news-item:hover {
  transform: translateY(-2px);
  border-color: color-mix(in srgb, var(--pine, #38665a) 45%, var(--line, #d7dde5));
  box-shadow: 0 16px 28px rgba(63, 58, 49, 0.1);
}

.health-news-content {
  align-content: stretch;
  display: grid;
  gap: 0.48rem;
  grid-template-rows: auto auto 1fr auto auto;
  width: 100%;
  min-height: 100%;
  padding: 1.15rem 1.2rem 1.1rem;
  position: relative;
  z-index: 2;
}

.health-news-tag-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
  align-items: center;
}

.health-news-tag,
.health-news-kind {
  display: inline-flex;
  width: fit-content;
  border-radius: 999px;
  padding: 0.2rem 0.6rem;
  font-size: 0.74rem;
  font-weight: 500;
}

.health-news-tag {
  background: color-mix(in srgb, var(--pine, #38665a) 18%, rgba(255, 255, 255, 0.7));
  color: var(--pine-deep, #2a4d42);
  border: 1px solid color-mix(in srgb, var(--pine, #38665a) 28%, transparent);
}

.health-news-kind {
  background: color-mix(in srgb, var(--gold, #e7c27a) 22%, rgba(255, 255, 255, 0.7));
  color: var(--gold-deep, #8f6b1f);
  border: 1px solid color-mix(in srgb, var(--gold, #e7c27a) 32%, transparent);
}

.health-news-item strong {
  font-size: 1.12rem;
  line-height: 1.38;
  color: var(--ink, #3f3a31);
  font-weight: 600;
  /* 标题最多 3 行，避免长短标题把同排卡片撑得参差。 */
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.health-news-item small,
.health-news-source {
  color: var(--ink-soft, #6d6659);
  line-height: 1.52;
}

.health-news-item small {
  font-size: 0.92rem;
  /* 摘要占剩余空间并最多 4 行，行高一致后 CTA 统一锚在卡片底部。 */
  display: -webkit-box;
  -webkit-line-clamp: 4;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.health-news-source {
  font-size: 0.82rem;
  opacity: 0.88;
}

.health-news-cta {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  margin-top: 0.25rem;
  color: var(--pine-deep, #2a4d42);
  font-size: 0.9rem;
  font-weight: 600;
  transition: gap 180ms ease;
}

.health-news-item:hover .health-news-cta {
  gap: 0.6rem;
}

.pill.ok {
  background: color-mix(in srgb, var(--pine, #38665a) 24%, transparent);
  color: var(--pine-deep, #2a4d42);
}

.pill.warn {
  background: color-mix(in srgb, var(--gold, #e7c27a) 32%, transparent);
  color: var(--gold-deep, #8f6b1f);
}

.pill.muted {
  background: color-mix(in srgb, var(--line, #d7dde5) 60%, transparent);
  color: var(--ink-soft, #6d6659);
}

@media (max-width: 720px) {
  .health-news-list {
    grid-template-columns: 1fr;
  }

  .health-news-item {
    height: auto;
    min-height: 200px;
  }
}
</style>
