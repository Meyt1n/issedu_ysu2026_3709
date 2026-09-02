<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, type RouteLocationRaw } from 'vue-router'

import type { AssistantCitation, EvidencePreview } from '@/api/types'
import {
  assistantCitationTitle,
  extraAssistantSources,
  shouldShowAssistantNoEvidence,
  uniqueAssistantCitations,
} from '@/utils/assistantEvidence'

const props = withDefaults(defineProps<{
  citations?: AssistantCitation[] | null
  sources?: string[] | null
  evidencePreview?: EvidencePreview | null
  degraded?: boolean
  degradeReason?: string | null
}>(), {
  citations: null,
  sources: null,
  evidencePreview: null,
  degraded: false,
  degradeReason: null,
})

const normalizedCitations = computed(() => uniqueAssistantCitations(props.citations))
const extraSources = computed(() => extraAssistantSources(props.sources, normalizedCitations.value))
const noEvidence = computed(() => shouldShowAssistantNoEvidence(
  normalizedCitations.value,
  props.sources,
  props.evidencePreview,
  props.degraded,
))
const hasEvidenceDetails = computed(() =>
  noEvidence.value || normalizedCitations.value.length > 0 || extraSources.value.length > 0,
)
const disclosureSummary = computed(() => {
  const parts: string[] = []
  if (normalizedCitations.value.length) parts.push(`${normalizedCitations.value.length} 条引用`)
  if (extraSources.value.length) parts.push(`${extraSources.value.length} 个其他来源`)
  if (props.degraded) parts.push('回答已降级')
  return parts.join(' · ') || '暂无可展开依据'
})

function citationVersion(citation: AssistantCitation): string {
  return citation.version || '未提供'
}

function citationText(citation: AssistantCitation): string {
  return citation.text || '本次响应未返回片段正文，仅保留服务端核验过的引用标识。'
}

/**
 * 跳转到 MOB-162 的知识条目只读页，并带上引用分块与本次回答所用索引版本。
 * 版本作为查询参数传下去，供详情页与服务端当前版本比对、发现版本二义。
 */
function citationRoute(citation: AssistantCitation): RouteLocationRaw {
  return {
    name: 'knowledge-document',
    params: { docId: citation.document_id },
    query: {
      chunk: citation.chunk_id,
      ...(citation.version ? { version: citation.version } : {}),
    },
  }
}
</script>

<template>
  <details v-if="hasEvidenceDetails" class="assistant-evidence">
    <summary class="assistant-evidence-summary">
      <span>查看依据</span>
      <span class="meta-line">{{ disclosureSummary }}</span>
    </summary>

    <div class="assistant-evidence-body">
      <p v-if="normalizedCitations.length" class="meta-line">
        以下内容由家庭服务器在本次回答中返回，仅供核对，不代表诊断或处方建议。
      </p>

      <ul v-if="normalizedCitations.length" class="assistant-citation-list">
        <li v-for="citation in normalizedCitations" :key="`${citation.document_id}:${citation.version}:${citation.chunk_id}`" class="assistant-citation-card">
          <div class="assistant-citation-heading">
            <strong>{{ assistantCitationTitle(citation) }}</strong>
          </div>
          <p class="assistant-citation-text">{{ citationText(citation) }}</p>
          <p class="meta-line">版本 {{ citationVersion(citation) }} · 片段 {{ citation.chunk_id }}</p>
          <p v-if="citation.locator" class="meta-line assistant-citation-locator">定位：{{ citation.locator }}</p>
          <RouterLink
            class="btn btn-secondary assistant-citation-detail"
            :to="citationRoute(citation)"
            :aria-label="`打开${assistantCitationTitle(citation)}的只读条目详情并定位到被引用分块`"
          >
            查看条目详情
          </RouterLink>
        </li>
      </ul>

      <p v-if="extraSources.length" class="meta-line assistant-extra-sources">
        其他依据标识：{{ extraSources.join('、') }}
      </p>
      <p v-if="noEvidence" class="assistant-no-evidence" role="status">
        本次回答没有可引用的知识文档；{{ props.degradeReason ? `当前为受控降级（${props.degradeReason}），` : '' }}请勿把回答当作已核验的医疗建议。
      </p>
    </div>
  </details>
</template>

<style scoped>
.assistant-evidence {
  border: 1px solid color-mix(in srgb, var(--text) 14%, transparent);
  border-radius: 12px;
  overflow: hidden;
}
.assistant-evidence-summary {
  align-items: baseline;
  cursor: pointer;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: space-between;
  min-height: var(--tap);
  padding: 9px 11px;
}
.assistant-evidence-summary:focus-visible,
.assistant-citation-detail:focus-visible {
  outline: 3px solid color-mix(in srgb, var(--accent) 58%, transparent);
  outline-offset: 2px;
}
.assistant-evidence-body {
  border-top: 1px solid color-mix(in srgb, var(--text) 10%, transparent);
  display: grid;
  gap: 10px;
  padding: 10px 11px 12px;
}
.assistant-citation-list {
  display: grid;
  gap: 9px;
  list-style: none;
  margin: 0;
  padding: 0;
}
.assistant-citation-card {
  background: color-mix(in srgb, var(--surface) 90%, var(--accent) 10%);
  border-radius: 10px;
  display: grid;
  gap: 6px;
  padding: 10px;
}
.assistant-citation-heading {
  display: grid;
  gap: 2px;
  min-width: 0;
}
.assistant-citation-text {
  line-height: 1.6;
  margin: 0;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
  word-break: break-word;
}
.assistant-citation-locator { overflow-wrap: anywhere; }
.assistant-citation-detail { justify-self: start; min-height: var(--tap); }
.assistant-extra-sources { overflow-wrap: anywhere; }
.assistant-no-evidence {
  color: var(--muted);
  line-height: 1.55;
  margin: 0;
}
@media (prefers-reduced-motion: reduce) {
  .assistant-evidence { transition: none; }
}
@media (prefers-reduced-motion: reduce) {
  .assistant-citation-backdrop { transition: none; }
}
</style>
