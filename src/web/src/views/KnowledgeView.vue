<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { ApiClientError, apiClient } from '../api/client'
import type {
  AssistantTool,
  KnowledgeDocument,
  KnowledgeRetrieveResponse,
  WebSearchOpsSnapshot,
} from '../api/types'
import AppIcon from '../components/AppIcon.vue'
import {
  createIdempotencyKey,
  formatError,
  pushToast,
  requestOptions,
  session,
} from '../store'
import { askConfirm } from '../ui/confirm'
import { formatDateTime } from '../ui/labels'
import { vReveal } from '../ui/motion'

const documents = ref<KnowledgeDocument[]>([])
const tools = ref<AssistantTool[]>([])

const DOC_PREVIEW = 6
const showAllDocs = ref(false)
const visibleDocuments = computed(() =>
  showAllDocs.value ? documents.value : documents.value.slice(0, DOC_PREVIEW),
)
const loading = ref(false)
const busy = ref(false)
const retrieval = ref<KnowledgeRetrieveResponse | null>(null)
const retrieving = ref(false)
const retrieveQuery = ref('')
const snapshotVersion = ref('')
const snapshotResult = ref('')
const webSearchOps = ref<WebSearchOpsSnapshot | null>(null)
const webSearchOpsLoading = ref(false)
const webSearchOpsForbidden = ref(false)
const webSearchOpsError = ref(false)

const docDraft = reactive({
  title: '',
  source: '',
  version: '1.0',
  license: 'internal',
  content: '',
})

const canCreateDoc = computed(
  () =>
    docDraft.title.trim().length > 0 &&
    docDraft.source.trim().length > 0 &&
    docDraft.content.trim().length > 0 &&
    !busy.value,
)

async function loadKnowledge(): Promise<void> {
  loading.value = true
  try {
    const [docsResult, toolsResult] = await Promise.allSettled([
      apiClient.listKnowledgeDocuments(requestOptions.value),
      apiClient.listAssistantTools(requestOptions.value),
    ])
    documents.value = docsResult.status === 'fulfilled' ? docsResult.value : []
    tools.value = toolsResult.status === 'fulfilled' ? toolsResult.value.tools : []
  } finally {
    loading.value = false
  }
}

async function loadWebSearchOps(): Promise<void> {
  webSearchOpsLoading.value = true
  webSearchOpsForbidden.value = false
  webSearchOpsError.value = false
  try {
    webSearchOps.value = await apiClient.getAssistantWebSearchOps(requestOptions.value)
  } catch (cause) {
    webSearchOps.value = null
    if (cause instanceof ApiClientError && cause.status === 403) {
      webSearchOpsForbidden.value = true
    } else {
      webSearchOpsError.value = true
    }
  } finally {
    webSearchOpsLoading.value = false
  }
}

function formatHitRate(value: number): string {
  return `${(Math.max(0, Math.min(1, value)) * 100).toFixed(1)}%`
}

async function createDocument(): Promise<void> {
  if (!canCreateDoc.value) return
  busy.value = true
  try {
    await apiClient.createKnowledgeDocument(
      {
        title: docDraft.title.trim(),
        content: docDraft.content.trim(),
        source: docDraft.source.trim(),
        version: docDraft.version.trim() || '1.0',
        license: docDraft.license.trim() || 'internal',
      },
      { ...requestOptions.value, idempotencyKey: createIdempotencyKey() },
    )
    pushToast('success', '知识文档已登记并自动分块，可用于检索与助手引用。')
    docDraft.title = ''
    docDraft.content = ''
    await loadKnowledge()
  } catch (cause) {
    pushToast('error', formatError(cause))
  } finally {
    busy.value = false
  }
}

async function removeDocument(doc: KnowledgeDocument): Promise<void> {
  const accepted = await askConfirm({
    title: '下线这篇知识文档？',
    message: `《${doc.title}》下线后不再参与检索与助手引用；历史回答中的引用记录仍会保留。`,
    confirmText: '下线文档',
  })
  if (!accepted) return

  busy.value = true
  try {
    await apiClient.deleteKnowledgeDocument(doc.id, requestOptions.value)
    pushToast('info', `文档「${doc.title}」已下线，不再参与检索。`)
    await loadKnowledge()
  } catch (cause) {
    pushToast('error', formatError(cause))
  } finally {
    busy.value = false
  }
}

async function runRetrieve(): Promise<void> {
  const query = retrieveQuery.value.trim()
  if (!query || retrieving.value) return
  retrieving.value = true
  retrieval.value = null
  try {
    retrieval.value = await apiClient.retrieveKnowledge(
      query,
      5,
      session.selectedHouseholdId || undefined,
      session.selectedMemberId || undefined,
      requestOptions.value,
    )
  } catch (cause) {
    pushToast('error', formatError(cause))
  } finally {
    retrieving.value = false
  }
}

async function createSnapshot(): Promise<void> {
  const version = snapshotVersion.value.trim()
  if (!version || busy.value) return
  busy.value = true
  try {
    const snapshot = await apiClient.createKnowledgeSnapshot(version, requestOptions.value)
    snapshotResult.value = `快照 ${snapshot.version}：${snapshot.document_count} 篇文档 / ${snapshot.chunk_count} 个分块 · 校验和 ${snapshot.checksum.slice(0, 12)}…`
    pushToast('success', '索引快照已固定，助手回答可追溯到该知识版本。')
    snapshotVersion.value = ''
  } catch (cause) {
    pushToast('error', formatError(cause))
  } finally {
    busy.value = false
  }
}
onMounted(() => {
  void loadKnowledge()
  void loadWebSearchOps()
})
</script>

<template>
  <section class="page-hero">
    <div class="card-heading" style="margin-bottom: 0">
      <div>
        <h2 class="hero-greeting gradient-text">知识文档</h2>
        <p class="hero-sub">
          本地助手只引用这里登记的版本化知识；权限外或未登记的内容不会出现在回答里。
        </p>
      </div>
      <span class="pill sage">{{ documents.length }} 篇在用</span>
    </div>
  </section>

  <div class="grid-main-side">
    <div class="section-stack">
      <section class="card">
        <div class="card-heading">
          <div>
            <p class="eyebrow">版本化知识</p>
            <h3 class="card-title">在用文档</h3>
          </div>
          <button type="button" class="btn btn-ghost btn-small" :disabled="loading" @click="loadKnowledge">
            <AppIcon name="refresh" :size="15" />
            刷新
          </button>
        </div>
        <div v-if="loading" class="inline-loading">
          <span class="loading-dots"><span /><span /><span /></span>
          正在读取知识库
        </div>
        <div v-else-if="documents.length === 0" class="empty-state">
          <AppIcon class="empty-art" name="review" :size="38" />
          <strong>知识库还是空的</strong>
          <p>登记药品说明书摘要、照护指引等资料后，助手的回答才能带上可核对的引用。</p>
        </div>
        <ul v-else v-reveal class="list-plain">
          <li v-for="doc in visibleDocuments" :key="doc.id" class="row-card">
            <div class="row-top">
              <span class="row-title">
                {{ doc.title }}
                <span class="pill sage">v{{ doc.version }}</span>
              </span>
              <span class="text-faint" style="font-size: 12.5px">{{ formatDateTime(doc.created_at) }}</span>
            </div>
            <p class="row-meta" style="margin: 0">
              来源 {{ doc.source }} · 许可 {{ doc.license }} ·
              <span class="mono">{{ doc.content_hash.slice(0, 12) }}…</span>
            </p>
            <div class="row-actions">
              <button type="button" class="btn btn-danger btn-small" :disabled="busy" @click="removeDocument(doc)">
                下线文档
              </button>
            </div>
          </li>
        </ul>
        <div v-if="documents.length > DOC_PREVIEW" class="more-wrap">
          <button type="button" class="more-btn" :class="{ open: showAllDocs }" @click="showAllDocs = !showAllDocs">
            <AppIcon name="arrow-right" :size="13" />
            {{ showAllDocs ? '收起文档' : `展开更多 ${documents.length - DOC_PREVIEW} 篇` }}
          </button>
        </div>
      </section>

      <section class="card">
        <div class="card-heading">
          <div>
            <p class="eyebrow">检索演练</p>
            <h3 class="card-title">试试知识能否被找到</h3>
          </div>
        </div>
        <form class="chat-compose" @submit.prevent="runRetrieve">
          <textarea
            v-model="retrieveQuery"
            rows="1"
            placeholder="例如：阿司匹林 有效期 保存条件"
            @keydown.enter.exact.prevent="runRetrieve"
          />
          <button type="submit" class="btn btn-primary" :disabled="!retrieveQuery.trim() || retrieving" style="align-self: flex-end">
            {{ retrieving ? '检索中' : '检索' }}
          </button>
        </form>
        <template v-if="retrieval">
          <p v-if="retrieval.degraded" class="notice warn" style="margin-top: 14px">
            <AppIcon name="info" :size="15" />
            检索已受控降级（{{ retrieval.degrade_reason ?? '无可授权内容' }}），不会返回越权或未登记的知识。
          </p>
          <p v-else-if="retrieval.results.length === 0" class="notice info" style="margin-top: 14px">
            <AppIcon name="info" :size="15" />
            没有命中任何分块；可以补充更贴近的关键词或登记新文档。
          </p>
          <div v-else class="section-stack" style="gap: 9px; margin-top: 14px">
            <div v-for="(hit, index) in retrieval.results" :key="index" class="chunk-hit">
              <span class="text-soft" style="font-size: 12px">
                《{{ hit.document_title ?? '未命名文档' }}》
                <span v-if="hit.score != null" class="hit-score"> · 相关度 {{ Number(hit.score).toFixed(3) }}</span>
              </span>
              <span style="font-size: 13.5px; line-height: 1.65">{{ hit.text }}</span>
            </div>
          </div>
        </template>
      </section>
    </div>

    <div class="section-stack" style="align-self: start">
      <section class="card">
        <div class="card-heading">
          <div>
            <p class="eyebrow">只读运维</p>
            <h3 class="card-title">联网搜索运行状态</h3>
          </div>
          <button
            type="button"
            class="btn btn-ghost btn-small"
            :disabled="webSearchOpsLoading"
            @click="loadWebSearchOps"
          >
            <AppIcon name="refresh" :size="14" />
            刷新
          </button>
        </div>
        <div v-if="webSearchOpsLoading" class="inline-loading" role="status">
          <span class="loading-dots"><span /><span /><span /></span>
          正在读取运行指标
        </div>
        <p v-else-if="webSearchOpsForbidden" class="text-faint" style="margin: 0">
          当前账号无权查看运维指标
        </p>
        <p v-else-if="webSearchOpsError" class="card-note" style="margin: 0">
          运行指标暂时不可用，可稍后刷新。
        </p>
        <template v-else-if="webSearchOps">
          <div class="ops-status-line">
            <span class="pill" :class="webSearchOps.web_search_ready ? 'sage' : 'gold'">
              {{ webSearchOps.web_search_ready ? '已就绪' : '未就绪' }}
            </span>
            <span>Provider：<span class="mono">{{ webSearchOps.web_search_provider }}</span></span>
          </div>
          <dl class="ops-metrics">
            <div>
              <dt>缓存命中率</dt>
              <dd>{{ formatHitRate(webSearchOps.cache_hit_rate) }}</dd>
            </div>
            <div>
              <dt>限速次数</dt>
              <dd>{{ webSearchOps.rate_limited_hits }}</dd>
            </div>
            <div>
              <dt>缓存条目</dt>
              <dd>{{ webSearchOps.cache_entries }}</dd>
            </div>
            <div>
              <dt>实际搜索</dt>
              <dd>{{ webSearchOps.searches }}</dd>
            </div>
          </dl>
          <p class="text-faint" style="font-size: 12px; line-height: 1.55; margin: 10px 0 0">
            指标不包含搜索正文、成员资料或健康记录。
          </p>
        </template>
      </section>

      <section class="card">
        <div class="card-heading">
          <div>
            <p class="eyebrow">登记文档</p>
            <h3 class="card-title">添加一篇知识</h3>
          </div>
        </div>
        <form class="section-stack" @submit.prevent="createDocument">
          <label class="field">
            标题
            <input v-model="docDraft.title" autocomplete="off" required placeholder="例如 阿司匹林肠溶片说明书摘要" />
          </label>
          <label class="field">
            来源
            <input v-model="docDraft.source" autocomplete="off" required placeholder="例如 药品说明书 2025 修订版" />
          </label>
          <div class="grid-two" style="gap: 12px">
            <label class="field">
              版本
              <input v-model="docDraft.version" autocomplete="off" placeholder="1.0" />
            </label>
            <label class="field">
              许可
              <input v-model="docDraft.license" autocomplete="off" placeholder="internal" />
            </label>
          </div>
          <label class="field">
            正文（自动分块）
            <textarea v-model="docDraft.content" rows="6" required placeholder="粘贴知识正文；不要包含任何真实家庭健康数据。" />
          </label>
          <button type="submit" class="btn btn-clay" :disabled="!canCreateDoc">
            {{ busy ? '正在登记' : '登记知识文档' }}
          </button>
        </form>
      </section>

      <section class="card">
        <div class="card-heading">
          <div>
            <p class="eyebrow">版本固定</p>
            <h3 class="card-title">索引快照</h3>
          </div>
        </div>
        <form class="section-stack" @submit.prevent="createSnapshot">
          <label class="field">
            快照版本号
            <input v-model="snapshotVersion" autocomplete="off" placeholder="例如 knowledge-2026w33" />
          </label>
          <button type="submit" class="btn btn-ghost btn-small" :disabled="!snapshotVersion.trim() || busy">
            固定当前索引
          </button>
          <p v-if="snapshotResult" class="notice ok" style="margin: 0">
            <AppIcon name="check" :size="15" />
            {{ snapshotResult }}
          </p>
        </form>
      </section>

      <section class="card">
        <div class="card-heading">
          <div>
            <p class="eyebrow">助手能力</p>
            <h3 class="card-title">已批准的工具</h3>
          </div>
        </div>
        <p v-if="tools.length === 0" class="card-note" style="margin: 0">助手工具清单当前不可用。</p>
        <ul v-else class="list-plain" style="gap: 8px">
          <li v-for="tool in tools" :key="tool.name" class="row-card" style="padding: 11px 14px">
            <span class="row-title mono" style="font-size: 13px">{{ tool.name }}</span>
            <p v-if="tool.description" class="row-meta" style="margin: 0">{{ tool.description }}</p>
          </li>
        </ul>
        <p class="text-faint" style="font-size: 12px; line-height: 1.6; margin: 10px 0 0">
          助手只能调用这份白名单里的工具，且每次回答都要带出处；无证据时拒答。
        </p>
      </section>
    </div>
  </div>
</template>
