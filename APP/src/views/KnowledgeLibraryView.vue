<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'

import EmptyState from '@/components/EmptyState.vue'
import ErrorNotice from '@/components/ErrorNotice.vue'
import ListLoadingState from '@/components/ListLoadingState.vue'
import ListStatusAnnouncer from '@/components/ListStatusAnnouncer.vue'
import { presentListApiError, type ErrorPresentation } from '@/api/errors'
import { activeProvider } from '@/data'
import type { KnowledgeDocumentSummaryView } from '@/data/types'
import { sessionContextKey, useSession } from '@/stores/session'
import { formatDateTime } from '@/utils/format'

const { session } = useSession()

const documents = ref<KnowledgeDocumentSummaryView[]>([])
const loading = ref(true)
const error = ref<ErrorPresentation | null>(null)
let loadGeneration = 0
let loadInFlight = false

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
watch(() => sessionContextKey(session), load)
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
