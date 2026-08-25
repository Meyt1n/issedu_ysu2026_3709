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
  openAssistantWithPrompt(item.chat_prompt)
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
        <button type="button" class="health-news-item" @click="openItem(item)">
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
  gap: 0.5rem;
}

.health-news-item {
  width: 100%;
  text-align: left;
  border: 1px solid var(--line-soft, #ece4d2);
  border-radius: 9px;
  background: var(--card-soft, #fbf7ee);
  padding: 0.6rem 0.75rem;
  display: grid;
  gap: 0.25rem;
  cursor: pointer;
  transition: border-color 160ms ease;
}

.health-news-item:hover {
  border-color: color-mix(in srgb, var(--sky, #5aa7ff) 55%, var(--line, #d7dde5));
}

.health-news-tag-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  align-items: center;
}

.health-news-tag,
.health-news-kind {
  display: inline-flex;
  width: fit-content;
  border-radius: 999px;
  padding: 0.15rem 0.55rem;
  font-size: 0.75rem;
}

.health-news-tag {
  background: color-mix(in srgb, var(--sky, #8ec5ff) 22%, transparent);
  color: var(--ink, #1d2a36);
}

.health-news-kind {
  background: color-mix(in srgb, var(--gold, #e7c27a) 28%, transparent);
  color: var(--ink, #1d2a36);
}

.health-news-item strong {
  font-size: 0.92rem;
  color: var(--ink, #1d2a36);
}

.health-news-item small,
.health-news-source {
  color: var(--muted, #5b6570);
  line-height: 1.5;
}

.health-news-source {
  font-size: 0.8rem;
}

.health-news-cta {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  margin-top: 0.2rem;
  color: var(--sky-ink, #215d9b);
  font-size: 0.88rem;
  font-weight: 600;
}

.pill.ok {
  background: color-mix(in srgb, #6fbf73 28%, transparent);
}

.pill.warn {
  background: color-mix(in srgb, var(--gold, #e7c27a) 36%, transparent);
}

.pill.muted {
  background: color-mix(in srgb, var(--line, #d7dde5) 70%, transparent);
}
</style>
