<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import AppIcon from '@/components/AppIcon.vue'
import ErrorNotice from '@/components/ErrorNotice.vue'
import ListLoadingState from '@/components/ListLoadingState.vue'
import ListStatusAnnouncer from '@/components/ListStatusAnnouncer.vue'
import { presentListApiError, type ErrorPresentation } from '@/api/errors'
import { activeProvider } from '@/data'
import type { KnowledgeDocumentView as KnowledgeDocument } from '@/data/types'
import { sessionContextKey, useSession } from '@/stores/session'
import { formatDateTime } from '@/utils/format'

const route = useRoute()
const router = useRouter()
const { session } = useSession()

const doc = ref<KnowledgeDocument | null>(null)
const loading = ref(true)
const error = ref<ErrorPresentation | null>(null)
let loadGeneration = 0
let loadInFlight = false

/** 助手引用带来的分块与索引版本：只用于定位和版本比对，不参与权限判定。 */
const citedChunkId = computed(() => String(route.query.chunk ?? '').trim())
const citedVersion = computed(() => String(route.query.version ?? '').trim())

/** 服务端当前版本与助手回答所用版本不一致时必须显式告知，避免版本二义。 */
const versionMismatch = computed(() => {
  const current = doc.value?.version.trim()
  if (!current || !citedVersion.value) return false
  return current !== citedVersion.value
})

const citedChunkMissing = computed(() => {
  if (!doc.value?.approved || !citedChunkId.value) return false
  return !doc.value.chunks.some((chunk) => chunk.id === citedChunkId.value)
})

const listStatusMessage = computed(() => {
  if (loading.value || error.value || !doc.value) return ''
  if (!doc.value.approved) return '该知识条目当前不可查看。'
  return `已加载知识条目，共 ${doc.value.chunks.length} 个分块。`
})

function isCited(chunkId: string): boolean {
  return citedChunkId.value !== '' && chunkId === citedChunkId.value
}

/** 定位到被引用分块；只滚动，不改变焦点顺序以外的朗读行为。 */
async function focusCitedChunk(): Promise<void> {
  if (!citedChunkId.value) return
  await nextTick()
  const target = document.getElementById(`knowledge-chunk-${citedChunkId.value}`)
  target?.scrollIntoView({ block: 'center' })
}

async function load(): Promise<void> {
  if (loadInFlight) return
  loadInFlight = true
  const generation = ++loadGeneration
  const expectedKey = sessionContextKey(session)
  loading.value = true
  error.value = null
  doc.value = null
  const docId = decodeURIComponent(String(route.params.docId ?? ''))
  try {
    const next = await activeProvider().getKnowledgeDocument(docId)
    if (generation !== loadGeneration || expectedKey !== sessionContextKey(session)) return
    doc.value = next
    void focusCitedChunk()
  } catch (cause) {
    if (generation !== loadGeneration || expectedKey !== sessionContextKey(session)) return
    error.value = presentListApiError(cause)
  } finally {
    if (generation === loadGeneration) loading.value = false
    loadInFlight = false
  }
}

onMounted(load)
watch(() => [route.params.docId, sessionContextKey(session)], load)
</script>

<template>
  <main id="main" class="screen">
    <button type="button" class="btn btn-quiet back-btn" @click="router.back()">
      <AppIcon name="arrow-left" :size="18" />
      返回
    </button>

    <ErrorNotice v-if="error" :error="error" :busy="loading" @retry="load" />
    <ListLoadingState v-if="loading" label="正在加载知识条目…" :count="3" />

    <template v-else-if="doc">
      <header class="card">
        <div class="card-title-row">
          <h1 class="doc-title">{{ doc.title }}</h1>
          <span class="tag" :data-tone="doc.approved ? 'calm' : 'warn'">
            {{ doc.approved ? '已批准' : '不可查看' }}
          </span>
        </div>
        <p class="meta-line">来源：{{ doc.source }} · 许可：{{ doc.license }}</p>
        <p class="meta-line">索引版本 {{ doc.version }} · 共 {{ doc.chunkCount }} 个分块</p>
        <p class="meta-line">
          生效自 {{ doc.effectiveFrom ? formatDateTime(doc.effectiveFrom) : '服务端未标注' }}
          <template v-if="doc.effectiveUntil"> · 截至 {{ formatDateTime(doc.effectiveUntil) }}</template>
        </p>
      </header>

      <p v-if="versionMismatch" class="error-line" role="alert">
        助手回答引用的索引版本是 {{ citedVersion }}，服务端当前为 {{ doc.version }}；两者不一致，
        请以服务端当前版本为准，必要时重新提问核对。
      </p>

      <section v-if="!doc.approved" class="card" aria-labelledby="unavailable-title">
        <h2 id="unavailable-title">该条目当前不可查看</h2>
        <p>
          服务端把这条知识标记为「{{ doc.status }}」，尚未批准发布。
          移动端不展示未批准正文，也不在本机保存。
        </p>
      </section>

      <section v-else class="card" aria-labelledby="chunks-title">
        <h2 id="chunks-title">正文分块（{{ doc.chunks.length }}）</h2>
        <p v-if="citedChunkMissing" class="meta-line" role="status">
          助手引用的分块不在当前版本里，可能已随索引更新调整；下面是该条目当前的全部分块。
        </p>
        <ul v-if="doc.chunks.length" class="divided-list">
          <li
            v-for="chunk in doc.chunks"
            :id="`knowledge-chunk-${chunk.id}`"
            :key="chunk.id"
            class="chunk-item"
            :class="{ cited: isCited(chunk.id) }"
          >
            <p class="meta-line">
              第 {{ chunk.index + 1 }} 段
              <template v-if="chunk.locator"> · {{ chunk.locator }}</template>
              <template v-if="isCited(chunk.id)"> · 助手引用的就是这一段</template>
            </p>
            <p class="chunk-text">{{ chunk.text }}</p>
          </li>
        </ul>
        <p v-else class="meta-line">服务端没有返回可展示的分块。</p>
      </section>

      <p class="meta-line">本页只读：移动端不提供知识条目的新增、修改或删除入口。</p>
    </template>

    <ListStatusAnnouncer :message="listStatusMessage" />
  </main>
</template>

<style scoped>
.back-btn {
  align-items: center;
  display: inline-flex;
  gap: 6px;
  min-height: var(--tap);
}
.doc-title {
  margin: 0;
  overflow-wrap: anywhere;
}
.chunk-item {
  display: grid;
  gap: 4px;
}
.chunk-item.cited {
  background: color-mix(in srgb, var(--surface) 88%, var(--accent) 12%);
  border-radius: 10px;
  padding: 8px;
}
.chunk-text {
  line-height: 1.65;
  margin: 0;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
