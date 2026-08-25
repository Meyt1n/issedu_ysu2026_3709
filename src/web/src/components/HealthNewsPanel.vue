<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { apiClient } from '../api/client'
import type { HealthNewsItem, HealthNewsResponse } from '../api/types'
import { formatError, openAssistantWithPrompt, requestOptions } from '../store'
import AppIcon from './AppIcon.vue'

const news = ref<HealthNewsResponse | null>(null)
const loading = ref(false)
const loadError = ref('')

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
        <h3 class="card-title">换季与季节照护提醒</h3>
      </div>
      <span class="pill soft">常驻首页</span>
    </div>
    <p class="health-news-intro">
      根据当前季节主动展示的教学提醒。点一条即可带着问题进入本地助手聊天。
    </p>
    <div v-if="loading" class="inline-loading">正在读取健康新闻</div>
    <p v-else-if="loadError" class="notice warn" role="status">
      <AppIcon name="info" :size="16" />
      {{ loadError }}
    </p>
    <ul v-else class="list-plain health-news-list">
      <li v-for="item in news?.items ?? []" :key="item.id">
        <button type="button" class="health-news-item" @click="openItem(item)">
          <span class="health-news-tag">{{ item.tag }}</span>
          <strong>{{ item.title }}</strong>
          <small>{{ item.summary }}</small>
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

.health-news-intro,
.health-news-disclaimer {
  color: var(--muted, #5b6570);
  font-size: 0.92rem;
  line-height: 1.55;
  margin: 0.35rem 0 0.85rem;
}

.health-news-disclaimer {
  margin-top: 0.75rem;
  margin-bottom: 0;
  font-size: 0.82rem;
}

.health-news-list {
  display: grid;
  gap: 0.75rem;
}

.health-news-item {
  width: 100%;
  text-align: left;
  border: 1px solid color-mix(in srgb, var(--line, #d7dde5) 88%, transparent);
  border-radius: 16px;
  background: color-mix(in srgb, var(--panel, #fff) 92%, var(--sky, #8ec5ff) 8%);
  padding: 0.95rem 1rem;
  display: grid;
  gap: 0.35rem;
  cursor: pointer;
  transition: transform 160ms ease, border-color 160ms ease;
}

.health-news-item:hover {
  transform: translateY(-1px);
  border-color: color-mix(in srgb, var(--sky, #5aa7ff) 55%, var(--line, #d7dde5));
}

.health-news-tag {
  display: inline-flex;
  width: fit-content;
  border-radius: 999px;
  padding: 0.15rem 0.55rem;
  background: color-mix(in srgb, var(--sky, #8ec5ff) 22%, transparent);
  color: var(--ink, #1d2a36);
  font-size: 0.75rem;
}

.health-news-item strong {
  font-size: 1rem;
  color: var(--ink, #1d2a36);
}

.health-news-item small {
  color: var(--muted, #5b6570);
  line-height: 1.5;
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

.pill.soft {
  background: color-mix(in srgb, var(--gold, #e7c27a) 24%, transparent);
}
</style>
