<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'

import EmptyState from '@/components/EmptyState.vue'
import ErrorNotice from '@/components/ErrorNotice.vue'
import ListLoadingState from '@/components/ListLoadingState.vue'
import ListStatusAnnouncer from '@/components/ListStatusAnnouncer.vue'
import AppIcon from '@/components/AppIcon.vue'
import { presentListApiError, type ErrorPresentation } from '@/api/errors'
import { activeProvider } from '@/data'
import type { KnowledgeDocumentSummaryView, KnowledgeSearchResult } from '@/data/types'
import { sessionContextKey, useSession } from '@/stores/session'
import { formatDateTime } from '@/utils/format'

const { session } = useSession()

const documents = ref<KnowledgeDocumentSummaryView[]>([])
const loading = ref(true)
const error = ref<ErrorPresentation | null>(null)
let loadGeneration = 0
let loadInFlight = false

/* ── 条目检索（POST /knowledge/retrieve） ──
 * 检索词只随请求体发出：不进 URL、不写 localStorage、不进请求日志。
 * 权限预过滤与排序都在服务端；界面不缓存结果，切换身份/家庭即清空。 */
const query = ref('')
const searchResult = ref<KnowledgeSearchResult | null>(null)
const searching = ref(false)
const searchError = ref<ErrorPresentation | null>(null)
let searchGeneration = 0

const canSearch = computed(() => Boolean(query.value.trim()) && !searching.value)

const searchStatusMessage = computed(() => {
  if (searching.value || searchError.value) return ''
  const result = searchResult.value
  if (!result) return ''
  if (result.degraded) return result.reason
  return `检索到 ${result.total} 条相关片段。`
})

async function search(): Promise<void> {
  const keyword = query.value.trim()
  if (!keyword || searching.value) return
  const generation = ++searchGeneration
  const expectedKey = sessionContextKey(session)
  searching.value = true
  searchError.value = null
  try {
    const next = await activeProvider().searchKnowledge(keyword)
    if (generation !== searchGeneration || expectedKey !== sessionContextKey(session)) return
    searchResult.value = next
  } catch (cause) {
    if (generation !== searchGeneration || expectedKey !== sessionContextKey(session)) return
    searchError.value = presentListApiError(cause)
    searchResult.value = null
  } finally {
    if (generation === searchGeneration) searching.value = false
  }
}

function clearSearch(): void {
  searchGeneration += 1
  query.value = ''
  searchResult.value = null
  searchError.value = null
  searching.value = false
}

const listStatusMessage = computed(() => {
  if (loading.value || error.value) return ''
  return documents.value.length
    ? `已加载 ${documents.value.length} 条知识条目。`
    : '当前没有可查看的知识条目。'
})

async function load(): Promise<void> {
  if (loadInFlight) return
  loadInFlight = true
  const generation = ++loadGeneration
  const expectedKey = sessionContextKey(session)
  loading.value = true
  error.value = null
  try {
    const next = await activeProvider().listKnowledgeDocuments()
    if (generation !== loadGeneration || expectedKey !== sessionContextKey(session)) return
    documents.value = next
  } catch (cause) {
    if (generation !== loadGeneration || expectedKey !== sessionContextKey(session)) return
    error.value = presentListApiError(cause)
    documents.value = []
  } finally {
    if (generation === loadGeneration) loading.value = false
    loadInFlight = false
  }
}

onMounted(load)
watch(() => sessionContextKey(session), () => {
  clearSearch()
  void load()
})
</script>

<template>
  <main id="main" class="screen">
    <header class="card">
      <h1 class="library-title">知识条目</h1>
      <p class="meta-line">
        这里只能阅读家庭服务器已批准的知识条目。移动端不提供新增、修改或删除入口，
        内容也不会保存在本机。
      </p>
    </header>

    <section class="card" aria-labelledby="knowledge-search-title">
      <div class="h-icon-row">
        <span class="row-icon" data-tone="calm" aria-hidden="true"><AppIcon name="eye" :size="16" /></span>
        <h2 id="knowledge-search-title">检索条目</h2>
      </div>
      <form class="search-form" role="search" @submit.prevent="search">
        <label class="field" for="knowledge-search-input">
          想查什么
          <input
            id="knowledge-search-input"
            v-model="query"
            type="search"
            name="knowledge-query"
            autocomplete="off"
            enterkeyhint="search"
            placeholder="例如：漏服怎么记录"
            :disabled="searching"
            aria-describedby="knowledge-search-help"
          />
        </label>
        <p id="knowledge-search-help" class="meta-line">
          检索词只随本次请求发给家庭服务器，不保存在本机、不出现在地址栏。
          结果由服务端在你被授权的条目范围内排序，移动端不改写正文。
        </p>
        <div class="btn-row">
          <button type="submit" class="btn" :disabled="!canSearch">
            {{ searching ? '正在检索…' : '检索' }}
          </button>
          <button
            v-if="query || searchResult || searchError"
            type="button"
            class="btn btn-quiet"
            :disabled="searching"
            @click="clearSearch"
          >
            清空
          </button>
        </div>
      </form>

      <ErrorNotice v-if="searchError" :error="searchError" :busy="searching" @retry="search" />
      <ListLoadingState v-else-if="searching" label="正在检索知识条目…" :count="2" />

      <template v-else-if="searchResult">
        <p v-if="searchResult.degraded" class="notice" data-tone="warn" role="status">
          <AppIcon name="alert" :size="16" />
          {{ searchResult.reason }}
        </p>
        <ul v-else class="divided-list">
          <li v-for="hit in searchResult.hits" :key="hit.chunkId">
            <RouterLink
              class="library-item"
              :to="{ name: 'knowledge-document', params: { docId: hit.documentId } }"
            >
              <span class="library-item-title">{{ hit.title }}</span>
              <span class="hit-text">{{ hit.text }}</span>
              <span class="meta-line">
                来源：{{ hit.source }} · 索引版本 {{ hit.version }}
                <template v-if="hit.locator"> · {{ hit.locator }}</template>
              </span>
              <span class="meta-line">命中方式：{{ hit.matchReason }} · 相关度 {{ hit.score }}</span>
            </RouterLink>
          </li>
        </ul>
      </template>

      <ListStatusAnnouncer :message="searchStatusMessage" />
    </section>

    <ErrorNotice v-if="error" :error="error" :busy="loading" @retry="load" />
    <ListLoadingState v-if="loading" label="正在加载知识条目…" :count="3" />

    <template v-else-if="!error">
      <EmptyState
        v-if="documents.length === 0"
        icon="eye"
        title="确实没有可查看的知识条目"
        hint="家庭服务器尚未批准任何条目，或当前身份没有被授权查看。"
      />
      <ul v-else class="divided-list">
        <li v-for="doc in documents" :key="doc.id">
          <RouterLink
            class="library-item"
            :to="{ name: 'knowledge-document', params: { docId: doc.id } }"
          >
            <span class="library-item-title">{{ doc.title }}</span>
            <span class="meta-line">来源：{{ doc.source }} · 索引版本 {{ doc.version }}</span>
            <span v-if="doc.effectiveFrom" class="meta-line">
              生效自 {{ formatDateTime(doc.effectiveFrom) }}
            </span>
          </RouterLink>
        </li>
      </ul>
    </template>

    <ListStatusAnnouncer :message="listStatusMessage" />
  </main>
</template>

<style scoped>
.library-title {
  margin: 0;
  overflow-wrap: anywhere;
}
.search-form { display: grid; gap: 10px; }
.hit-text {
  color: var(--c-ink-soft);
  font-size: 0.9rem;
  overflow-wrap: anywhere;
}
.library-item {
  color: inherit;
  display: grid;
  gap: 3px;
  min-height: var(--tap);
  padding: 6px 0;
  text-decoration: none;
}
.library-item:focus-visible {
  outline: 3px solid color-mix(in srgb, var(--accent) 58%, transparent);
  outline-offset: 2px;
}
.library-item-title {
  font-weight: 600;
  overflow-wrap: anywhere;
}
</style>
