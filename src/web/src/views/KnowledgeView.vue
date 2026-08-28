<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'

import { ApiClientError, apiClient } from '../api/client'
import {
  STAGING_CHANGE_LABELS,
  crawlAccessFromError,
  crawlRunSummary,
  pendingTeachingDrafts,
  simulateUpdateSummary,
  stagingChangeKind,
  teachingLoopSummary,
} from '../knowledge/crawlPanel'
import type {
  AssistantTool,
  KnowledgeDocument,
  KnowledgeDocumentDetail,
  KnowledgeRetrieveResponse,
  KnowledgeStagingDetail,
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

const TOOL_DESCRIPTION_ZH: Record<string, string> = {
  retrieve_knowledge: '检索已审核的本地知识文档（说明书、照护指引等）。',
  get_health_events: '读取家庭成员的健康事件时间线（只读）。',
  get_member_state: '读取成员当前状态投影（只读）。',
  get_applied_rules: '查看当前生效的规则与提醒依据（只读）。',
  get_care_plan_status: '查看用药计划与提醒状态（只读）。',
}

function toolDescriptionLabel(tool: AssistantTool): string {
  return TOOL_DESCRIPTION_ZH[tool.name] ?? tool.description ?? ''
}

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
const webSearchOpsErrorText = ref('')
const stagingItems = ref<Array<Record<string, unknown>>>([])
const crawlStatus = ref<Record<string, unknown> | null>(null)
const crawlBusy = ref(false)
const crawlReport = ref('')
const crawlForbidden = ref(false)
const crawlLoadErrorText = ref('')
const docsLoadErrorText = ref('')
const ingestHint = ref('')

const dueCount = computed(() => Number(crawlStatus.value?.due_count ?? 0))
const stagingApprovedCount = computed(
  () => stagingItems.value.filter((item) => item.status === 'approved').length,
)
const crawlSources = computed<Array<Record<string, unknown>>>(() =>
  Array.isArray(crawlStatus.value?.sources)
    ? (crawlStatus.value?.sources as Array<Record<string, unknown>>)
    : [],
)
const showSources = ref(false)

// 只读详情抽屉：在用文档 / staging 草稿共用一个模态。
const detailKind = ref<'document' | 'staging' | null>(null)
const detailLoading = ref(false)
const detailErrorText = ref('')
const docDetail = ref<KnowledgeDocumentDetail | null>(null)
const stagingDetail = ref<KnowledgeStagingDetail | null>(null)
const detailTitle = computed(() => {
  if (detailKind.value === 'document') return docDetail.value?.title ?? '知识文档详情'
  if (detailKind.value === 'staging') return stagingDetail.value?.title ?? 'Staging 草稿详情'
  return '详情'
})
const stagingDetailChangeLabel = computed(() =>
  stagingDetail.value
    ? STAGING_CHANGE_LABELS[
        stagingChangeKind(stagingDetail.value as unknown as Record<string, unknown>)
      ]
    : '',
)

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
    // 读取失败与「真的 0 篇」必须区分：否则连接/鉴权故障会被误读成空知识库。
    docsLoadErrorText.value =
      docsResult.status === 'rejected' ? formatError(docsResult.reason) : ''
    tools.value = toolsResult.status === 'fulfilled' ? toolsResult.value.tools : []
  } finally {
    loading.value = false
  }
}

async function loadWebSearchOps(): Promise<void> {
  webSearchOpsLoading.value = true
  webSearchOpsForbidden.value = false
  webSearchOpsErrorText.value = ''
  try {
    webSearchOps.value = await apiClient.getAssistantWebSearchOps(requestOptions.value)
  } catch (cause) {
    webSearchOps.value = null
    if (cause instanceof ApiClientError && cause.status === 403) {
      webSearchOpsForbidden.value = true
    } else {
      webSearchOpsErrorText.value = formatError(cause)
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

async function loadStaging(): Promise<void> {
  crawlForbidden.value = false
  crawlLoadErrorText.value = ''
  try {
    const [staging, status] = await Promise.all([
      apiClient.listKnowledgeStaging(requestOptions.value),
      apiClient.knowledgeCrawlStatus(requestOptions.value),
    ])
    stagingItems.value = staging.items ?? []
    crawlStatus.value = status
  } catch (cause) {
    stagingItems.value = []
    crawlStatus.value = null
    // KNOWLEDGE_STEWARD_REQUIRED must surface as guidance, not a silent
    // empty panel that looks like "no drafts yet".  Every other failure
    // shows its real cause (连不上 API / 超时 / 部署缺配置 / 服务端错误)。
    if (crawlAccessFromError(cause) === 'forbidden') {
      crawlForbidden.value = true
    } else {
      crawlLoadErrorText.value = formatError(cause)
    }
  }
}

async function runCrawl(dueOnly = false): Promise<void> {
  crawlBusy.value = true
  crawlReport.value = ''
  try {
    const report = await apiClient.runKnowledgeCrawl(requestOptions.value, { dueOnly })
    crawlReport.value = crawlRunSummary(report)
    pushToast('success', dueOnly ? '到期白名单已刷新到 staging' : '白名单来源已刷新到 staging')
    await loadStaging()
  } catch (cause) {
    pushToast('error', formatError(cause))
  } finally {
    crawlBusy.value = false
  }
}

/** 教学演示：给夹具来源叠加模拟更新，让下一次抓取显示「有更新」。 */
async function simulateUpdate(): Promise<void> {
  if (crawlBusy.value) return
  crawlBusy.value = true
  try {
    const report = await apiClient.simulateKnowledgeCrawlUpdate(requestOptions.value)
    crawlReport.value = simulateUpdateSummary(report)
    pushToast('success', '教学演示更新已就绪；点「全量抓取」查看「有更新」草稿。')
  } catch (cause) {
    pushToast('error', formatError(cause))
  } finally {
    crawlBusy.value = false
  }
}

function closeDetail(): void {
  detailKind.value = null
  docDetail.value = null
  stagingDetail.value = null
  detailErrorText.value = ''
}

async function openDocumentDetail(doc: KnowledgeDocument): Promise<void> {
  detailKind.value = 'document'
  detailLoading.value = true
  detailErrorText.value = ''
  docDetail.value = null
  try {
    docDetail.value = await apiClient.getKnowledgeDocument(doc.id, requestOptions.value)
  } catch (cause) {
    detailErrorText.value = formatError(cause)
  } finally {
    detailLoading.value = false
  }
}

async function openStagingDetail(sourceId: string): Promise<void> {
  detailKind.value = 'staging'
  detailLoading.value = true
  detailErrorText.value = ''
  stagingDetail.value = null
  try {
    stagingDetail.value = await apiClient.getKnowledgeStagingDetail(
      sourceId,
      requestOptions.value,
    )
  } catch (cause) {
    detailErrorText.value = formatError(cause)
  } finally {
    detailLoading.value = false
  }
}

function onDetailKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape' && detailKind.value) closeDetail()
}

async function approveStaging(sourceId: string): Promise<void> {
  crawlBusy.value = true
  try {
    await apiClient.reviewKnowledgeStaging(sourceId, { approve: true, notes: 'web-approve' }, requestOptions.value)
    pushToast('success', `已批准 ${sourceId}`)
    await loadStaging()
  } catch (cause) {
    pushToast('error', formatError(cause))
  } finally {
    crawlBusy.value = false
  }
}

async function rejectStaging(sourceId: string): Promise<void> {
  crawlBusy.value = true
  try {
    await apiClient.reviewKnowledgeStaging(
      sourceId,
      { reject: true, notes: 'web-reject' },
      requestOptions.value,
    )
    pushToast('info', `已拒绝 ${sourceId}`)
    await loadStaging()
  } catch (cause) {
    pushToast('error', formatError(cause))
  } finally {
    crawlBusy.value = false
  }
}

async function promoteStaging(): Promise<void> {
  crawlBusy.value = true
  try {
    const report = await apiClient.promoteKnowledgeStaging(requestOptions.value)
    pushToast('success', `已晋升 ${report.document_count ?? 0} 篇到 approved/incoming`)
    crawlReport.value = `已晋升 ${report.document_count ?? 0} 篇；下一步在终端执行 dry-run 预检查（仍不会自动入库）。`
    ingestHint.value = String(report.ingest_hint ?? '')
    await loadStaging()
  } catch (cause) {
    pushToast('error', formatError(cause))
  } finally {
    crawlBusy.value = false
  }
}

/** One-click teaching loop: crawl fixtures → approve drafts → promote. */
async function runTeachingLoop(): Promise<void> {
  if (crawlBusy.value) return
  crawlBusy.value = true
  crawlReport.value = ''
  try {
    const report = await apiClient.runKnowledgeCrawl(requestOptions.value, {})
    const staging = await apiClient.listKnowledgeStaging(requestOptions.value)
    const pending = pendingTeachingDrafts(staging.items ?? [])
    for (const item of pending) {
      await apiClient.reviewKnowledgeStaging(
        String(item.source_id),
        { approve: true, notes: 'teaching-loop-web' },
        requestOptions.value,
      )
    }
    const promoted = await apiClient.promoteKnowledgeStaging(requestOptions.value)
    crawlReport.value = teachingLoopSummary(
      Number(report.fetched ?? 0),
      pending.length,
      Number(promoted.document_count ?? 0),
    )
    ingestHint.value = String(promoted.ingest_hint ?? '')
    pushToast('success', '教学夹具闭环已完成；正式入库仍需人工 dry-run。')
    await loadStaging()
  } catch (cause) {
    pushToast('error', formatError(cause))
  } finally {
    crawlBusy.value = false
  }
}

onMounted(() => {
  window.addEventListener('keydown', onDetailKeydown)
  void loadKnowledge()
  void loadWebSearchOps()
  void loadStaging()
})

onBeforeUnmount(() => window.removeEventListener('keydown', onDetailKeydown))
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
        <div v-else-if="docsLoadErrorText" class="notice warn" role="status">
          <strong>知识库读取失败（不代表知识库为空）</strong>
          <p style="margin: 6px 0 0; line-height: 1.65">{{ docsLoadErrorText }}</p>
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
                <button
                  type="button"
                  class="doc-title-link"
                  :title="`查看《${doc.title}》详情`"
                  @click="openDocumentDetail(doc)"
                >
                  {{ doc.title }}
                </button>
                <span class="pill sage">v{{ doc.version }}</span>
              </span>
              <span class="text-faint" style="font-size: 12.5px">{{ formatDateTime(doc.created_at) }}</span>
            </div>
            <p class="row-meta" style="margin: 0">
              来源 {{ doc.source }} · 许可 {{ doc.license }} ·
              <span class="mono">{{ doc.content_hash.slice(0, 12) }}…</span>
            </p>
            <div class="row-actions">
              <button type="button" class="btn btn-ghost btn-small" @click="openDocumentDetail(doc)">
                查看详情
              </button>
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
                《{{ hit.document_title ?? hit.title ?? '未命名文档' }}》
                <span v-if="hit.score != null" class="hit-score"> · 相关度 {{ Number(hit.score).toFixed(3) }}</span>
              </span>
              <span v-if="hit.match_reason" class="text-faint" style="font-size: 12px; display: block">
                为何命中：{{ hit.match_reason }}
              </span>
              <span style="font-size: 13.5px; line-height: 1.65">{{ hit.text }}</span>
            </div>
          </div>
        </template>
      </section>

      <section v-if="!crawlForbidden" class="card">
        <div class="card-heading">
          <div>
            <p class="eyebrow">维护者专用</p>
            <h3 class="card-title">知识抓取与审核（Staging）</h3>
          </div>
          <div style="display: flex; gap: 8px; flex-wrap: wrap">
            <button type="button" class="btn btn-ghost btn-small" :disabled="crawlBusy" @click="runCrawl(true)">
              <AppIcon name="refresh" :size="15" />
              {{ crawlBusy ? '刷新中' : `到期刷新${dueCount ? ` (${dueCount})` : ''}` }}
            </button>
            <button type="button" class="btn btn-ghost btn-small" :disabled="crawlBusy" @click="runCrawl(false)">
              全量抓取
            </button>
            <button
              type="button"
              class="btn btn-ghost btn-small"
              :disabled="crawlBusy"
              title="仅本地夹具：叠加清晰标注的模拟更新，让下一次抓取显示「有更新」；不出网、不改仓库文件、永不自动入库。"
              @click="simulateUpdate"
            >
              模拟来源更新（教学演示）
            </button>
          </div>
        </div>
        <p class="card-note" style="margin-top: 0">
          面向知识管理员的<strong>教学演示</strong>：把白名单来源写入 staging 草稿，人工批准后才可晋升入库；日常家庭问答请用上方「检索」或「登记知识文档」。
        </p>
        <template>
          <p v-if="crawlLoadErrorText" class="notice warn" role="status" style="margin: 0 0 8px">
            爬虫状态读取失败：{{ crawlLoadErrorText }}
          </p>
          <p v-if="crawlStatus" class="row-meta" style="margin: 0 0 8px">
            白名单 {{ crawlStatus.source_count ?? 0 }} 源 · 到期 {{ dueCount }} · staging {{ stagingItems.length }} ·
            已批准待晋升 {{ stagingApprovedCount }} · auto_ingest 关闭
            <button
              v-if="crawlSources.length > 0"
              type="button"
              class="doc-title-link"
              style="font-size: 12.5px"
              @click="showSources = !showSources"
            >
              {{ showSources ? '收起来源列表' : '为什么总是这几个来源？查看白名单' }}
            </button>
          </p>
          <div v-if="showSources && crawlSources.length > 0" class="source-list">
            <p class="row-meta" style="margin: 0 0 6px; line-height: 1.65">
              抓取范围只来自这份白名单。网页端抓取<strong>只运行本地夹具（fixture）来源</strong>，服务端不出网；
              远程 HTTPS 来源需在 <span class="mono">docs/knowledge/crawl/allowlist.json</span> 中
              <span class="mono">enabled: true</span> 且域名命中 <span class="mono">allowed_hosts</span>，
              再由管理员在终端执行：
            </p>
            <pre class="mono ingest-hint-block"><code>uv run python scripts/crawl_knowledge_sources.py --live --due-only</code></pre>
            <ul class="list-plain" style="gap: 6px">
              <li
                v-for="source in crawlSources"
                :key="String(source.source_id)"
                class="row-card"
                style="padding: 9px 12px"
              >
                <span class="row-title" style="font-size: 13.5px">{{ source.title }}</span>
                <span class="row-meta" style="margin: 0">
                  <span class="pill" :class="source.is_fixture ? 'sage' : 'gold'">
                    {{ source.is_fixture ? '本地夹具' : '远程 HTTPS' }}
                  </span>
                  <span v-if="!source.is_fixture" class="pill" :class="source.enabled ? 'sage' : ''">
                    {{ source.enabled ? '已启用（仅 CLI --live）' : '未启用' }}
                  </span>
                  <span v-if="source.due" class="pill gold">到期待刷新</span>
                  <span v-if="source.demo_override" class="pill clay">含教学演示更新</span>
                  · 每 {{ source.refresh_hours ?? '—' }} 小时到期
                  <template v-if="source.staging_status"> · staging：{{ source.staging_status }}</template>
                  <template v-if="source.fetched_at"> · 上次抓取 {{ formatDateTime(String(source.fetched_at)) }}</template>
                </span>
              </li>
            </ul>
          </div>
          <p v-if="crawlReport" class="notice info" role="status">{{ crawlReport }}</p>
          <pre v-if="ingestHint" class="mono ingest-hint-block"><code>{{ ingestHint }}</code></pre>
          <div v-if="stagingItems.length === 0 && !crawlLoadErrorText" class="empty-state">
            <strong>暂无 staging 草稿</strong>
            <p>点击「全量抓取」或「到期刷新」生成本地夹具草稿，或用「一键教学闭环」演示完整流程。</p>
          </div>
          <ul v-else class="list-plain" style="gap: 8px">
            <li v-for="item in stagingItems" :key="String(item.source_id)" class="row-card" style="padding: 11px 14px">
              <button
                type="button"
                class="doc-title-link"
                style="font-weight: 600"
                :title="`查看《${item.title}》抓取正文与审核信息`"
                @click="openStagingDetail(String(item.source_id))"
              >
                {{ item.title }}
              </button>
              <span class="row-meta">
                {{ item.status }} ·
                <span
                  class="pill"
                  :class="{
                    sage: stagingChangeKind(item) === 'new',
                    gold: stagingChangeKind(item) === 'changed',
                  }"
                >
                  {{ STAGING_CHANGE_LABELS[stagingChangeKind(item)] }}
                </span>
                <span v-if="item.demo_override" class="pill clay">教学演示更新</span>
                · {{ String(item.content_sha256 || '').slice(0, 12) }}…
                <template v-if="item.fetched_at"> · {{ formatDateTime(String(item.fetched_at)) }}</template>
              </span>
              <span
                v-if="stagingChangeKind(item) === 'unchanged'"
                class="text-faint"
                style="font-size: 12px; line-height: 1.55"
              >
                内容哈希与上次一致，属正常；审核状态保持不变。
              </span>
              <span
                v-else-if="stagingChangeKind(item) === 'changed'"
                class="text-faint"
                style="font-size: 12px; line-height: 1.55"
              >
                内容有更新，已重置为 draft，请点标题查看正文后重新审核。
              </span>
              <div style="display: flex; gap: 8px; margin-top: 8px; flex-wrap: wrap">
                <button
                  type="button"
                  class="btn btn-ghost btn-small"
                  @click="openStagingDetail(String(item.source_id))"
                >
                  查看
                </button>
                <button
                  type="button"
                  class="btn btn-ghost btn-small"
                  :disabled="crawlBusy || item.status === 'approved' || item.status === 'promoted'"
                  @click="approveStaging(String(item.source_id))"
                >
                  批准
                </button>
                <button
                  type="button"
                  class="btn btn-ghost btn-small"
                  :disabled="crawlBusy || item.status === 'rejected' || item.status === 'promoted'"
                  @click="rejectStaging(String(item.source_id))"
                >
                  拒绝
                </button>
              </div>
            </li>
          </ul>
          <div style="display: flex; gap: 8px; margin-top: 12px; flex-wrap: wrap">
            <button type="button" class="btn btn-clay btn-small" :disabled="crawlBusy || stagingApprovedCount === 0" @click="promoteStaging">
              晋升已批准草稿（{{ stagingApprovedCount }}）
            </button>
            <button type="button" class="btn btn-ghost btn-small" :disabled="crawlBusy" @click="runTeachingLoop">
              {{ crawlBusy ? '执行中' : '一键教学闭环：抓取 → 批准 → 晋升' }}
            </button>
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
        <p v-else-if="webSearchOpsErrorText" class="card-note" style="margin: 0">
          运行指标读取失败：{{ webSearchOpsErrorText }}
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
            <p v-if="toolDescriptionLabel(tool)" class="row-meta" style="margin: 0">{{ toolDescriptionLabel(tool) }}</p>
          </li>
        </ul>
        <p class="text-faint" style="font-size: 12px; line-height: 1.6; margin: 10px 0 0">
          助手只能调用白名单工具，回答必须带出处；无证据时拒答。
        </p>
      </section>
    </div>
  </div>

  <Teleport to="body">
    <Transition name="modal">
      <div
        v-if="detailKind"
        class="modal-backdrop"
        role="dialog"
        aria-modal="true"
        :aria-label="detailTitle"
        @click.self="closeDetail"
      >
        <div class="modal-card knowledge-detail-card">
          <div class="detail-head">
            <h3 class="modal-title" style="margin: 0">{{ detailTitle }}</h3>
            <button type="button" class="btn btn-ghost btn-small" @click="closeDetail">关闭</button>
          </div>

          <div v-if="detailLoading" class="inline-loading" role="status">
            <span class="loading-dots"><span /><span /><span /></span>
            正在读取详情
          </div>
          <p v-else-if="detailErrorText" class="notice warn" style="margin: 0">
            详情读取失败：{{ detailErrorText }}
          </p>

          <template v-else-if="detailKind === 'document' && docDetail">
            <dl class="detail-meta">
              <div><dt>来源</dt><dd>{{ docDetail.source }}</dd></div>
              <div><dt>版本</dt><dd>v{{ docDetail.version }}</dd></div>
              <div><dt>许可</dt><dd>{{ docDetail.license }}</dd></div>
              <div><dt>状态</dt><dd>{{ docDetail.status }}</dd></div>
              <div><dt>登记人</dt><dd class="mono">{{ docDetail.created_by }}</dd></div>
              <div><dt>登记时间</dt><dd>{{ formatDateTime(docDetail.created_at) }}</dd></div>
              <div><dt>分块数</dt><dd>{{ docDetail.chunk_count }}</dd></div>
              <div><dt>内容哈希</dt><dd class="mono">{{ docDetail.content_hash.slice(0, 16) }}…</dd></div>
              <div v-if="docDetail.effective_until">
                <dt>有效期至</dt><dd>{{ formatDateTime(docDetail.effective_until) }}</dd>
              </div>
            </dl>
            <p class="eyebrow" style="margin: 4px 0 0">正文（只读）</p>
            <pre class="detail-body mono">{{ docDetail.content || '（该文档未保存正文，仅有分块索引）' }}</pre>
            <template v-if="docDetail.chunks.length > 0">
              <p class="eyebrow" style="margin: 4px 0 0">检索分块预览（助手引用的最小单元）</p>
              <ul class="list-plain" style="gap: 6px; max-height: 180px; overflow: auto">
                <li v-for="chunk in docDetail.chunks" :key="chunk.id" class="row-card" style="padding: 8px 10px">
                  <span class="row-meta" style="margin: 0">
                    #{{ chunk.chunk_index }}<template v-if="chunk.locator"> · {{ chunk.locator }}</template>
                  </span>
                  <span style="font-size: 13px; line-height: 1.6">{{ chunk.text }}</span>
                </li>
              </ul>
            </template>
          </template>

          <template v-else-if="detailKind === 'staging' && stagingDetail">
            <p class="notice warn" style="margin: 0">
              staging 草稿仅供审核，<strong>不是正式检索证据</strong>；批准晋升并 dry-run 入库后才参与检索。
            </p>
            <dl class="detail-meta">
              <div><dt>来源 URL</dt><dd class="mono" style="word-break: break-all">{{ stagingDetail.url }}</dd></div>
              <div><dt>许可意图</dt><dd>{{ stagingDetail.license }}</dd></div>
              <div><dt>审核状态</dt><dd>{{ stagingDetail.status }}</dd></div>
              <div><dt>抓取时间</dt><dd>{{ stagingDetail.fetched_at ? formatDateTime(stagingDetail.fetched_at) : '—' }}</dd></div>
              <div><dt>SHA-256</dt><dd class="mono" style="word-break: break-all">{{ stagingDetail.content_sha256 }}</dd></div>
              <div>
                <dt>本次变更</dt>
                <dd>{{ stagingDetailChangeLabel }}</dd>
              </div>
              <div v-if="stagingDetail.review_notes"><dt>审核备注</dt><dd>{{ stagingDetail.review_notes }}</dd></div>
              <div v-if="stagingDetail.approved_by">
                <dt>批准人</dt>
                <dd>{{ stagingDetail.approved_by }}<template v-if="stagingDetail.approved_at">（{{ formatDateTime(stagingDetail.approved_at) }}）</template></dd>
              </div>
              <div v-if="stagingDetail.rejected_by">
                <dt>拒绝人</dt>
                <dd>{{ stagingDetail.rejected_by }}<template v-if="stagingDetail.rejected_at">（{{ formatDateTime(stagingDetail.rejected_at) }}）</template></dd>
              </div>
            </dl>
            <p v-if="stagingDetail.demo_override" class="notice info" style="margin: 0">
              本内容包含「模拟来源更新」叠加的教学演示段落，仅用于课堂演示变更检测，不是真实来源更新。
            </p>
            <p class="eyebrow" style="margin: 4px 0 0">抓取正文（Markdown 原文）</p>
            <pre class="detail-body mono">{{ stagingDetail.content_available ? stagingDetail.content_markdown : '（正文文件缺失，请重新抓取）' }}</pre>
          </template>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.ingest-hint-block {
  background: color-mix(in srgb, var(--ink) 6%, transparent);
  border-radius: 8px;
  font-size: 12px;
  line-height: 1.55;
  margin: 0 0 8px;
  overflow-x: auto;
  padding: 8px 10px;
  user-select: all;
  white-space: pre-wrap;
  word-break: break-all;
}

.doc-title-link {
  background: none;
  border: none;
  color: inherit;
  cursor: pointer;
  font: inherit;
  padding: 0;
  text-align: left;
  text-decoration: underline;
  text-decoration-color: color-mix(in srgb, var(--ink) 30%, transparent);
  text-underline-offset: 3px;
}

.doc-title-link:hover,
.doc-title-link:focus-visible {
  text-decoration-color: currentcolor;
}

.source-list {
  border: 1px dashed var(--line);
  border-radius: 10px;
  margin: 0 0 10px;
  padding: 10px 12px;
}

.knowledge-detail-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 84vh;
  max-width: 720px;
  overflow-y: auto;
  text-align: left;
}

.detail-head {
  align-items: center;
  display: flex;
  gap: 10px;
  justify-content: space-between;
  width: 100%;
}

.detail-meta {
  display: grid;
  gap: 6px 16px;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  margin: 0;
  width: 100%;
}

.detail-meta dt {
  color: var(--ink-soft);
  font-size: 12px;
}

.detail-meta dd {
  font-size: 13px;
  line-height: 1.55;
  margin: 2px 0 0;
}

.detail-body {
  background: color-mix(in srgb, var(--ink) 5%, transparent);
  border-radius: 10px;
  font-size: 12.5px;
  line-height: 1.7;
  margin: 0;
  max-height: 320px;
  overflow: auto;
  padding: 12px 14px;
  white-space: pre-wrap;
  width: 100%;
  word-break: break-word;
}
</style>
