<script setup lang="ts">
import { computed, ref } from 'vue'

import type { AssistantCitation } from '@/api/types'
import {
  assistantCitationTitle,
  extraAssistantSources,
  uniqueAssistantCitations,
} from '@/utils/assistantEvidence'

const props = withDefaults(defineProps<{
  citations?: AssistantCitation[] | null
  sources?: string[] | null
  degraded?: boolean
  degradeReason?: string | null
}>(), {
  citations: null,
  sources: null,
  degraded: false,
  degradeReason: null,
})

const normalizedCitations = computed(() => uniqueAssistantCitations(props.citations))
const extraSources = computed(() => extraAssistantSources(props.sources, normalizedCitations.value))
const selectedCitation = ref<AssistantCitation | null>(null)
const hasEvidenceDetails = computed(() =>
  props.degraded || normalizedCitations.value.length > 0 || extraSources.value.length > 0,
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

function openCitation(citation: AssistantCitation): void {
  selectedCitation.value = citation
}

function closeCitation(): void {
  selectedCitation.value = null
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
          <button
            type="button"
            class="btn btn-secondary assistant-citation-detail"
            :aria-label="`查看${assistantCitationTitle(citation)}的只读引用详情`"
            @click="openCitation(citation)"
          >
            查看只读详情
          </button>
        </li>
      </ul>

      <p v-if="extraSources.length" class="meta-line assistant-extra-sources">
        其他依据标识：{{ extraSources.join('、') }}
      </p>
      <p v-if="!normalizedCitations.length" class="assistant-no-evidence" role="status">
        本次回答没有可引用的知识文档；{{ props.degradeReason ? `当前为受控降级（${props.degradeReason}），` : '' }}请勿把回答当作已核验的医疗建议。
      </p>
    </div>
  </details>

  <Teleport to="body">
    <div
      v-if="selectedCitation"
      class="assistant-citation-backdrop"
      role="dialog"
      aria-modal="true"
      aria-labelledby="assistant-citation-detail-title"
      @click.self="closeCitation"
    >
      <section class="assistant-citation-dialog">
        <div class="assistant-citation-dialog-head">
          <div>
            <p class="eyebrow">只读引用详情</p>
            <h2 id="assistant-citation-detail-title">{{ assistantCitationTitle(selectedCitation) }}</h2>
          </div>
          <button type="button" class="btn btn-secondary" @click="closeCitation">关闭</button>
        </div>
        <dl class="assistant-citation-detail-meta">
          <div><dt>文档标识</dt><dd>{{ selectedCitation.document_id }}</dd></div>
          <div><dt>索引版本</dt><dd>{{ citationVersion(selectedCitation) }}</dd></div>
          <div><dt>引用分块</dt><dd>{{ selectedCitation.chunk_id }}</dd></div>
          <div v-if="selectedCitation.locator"><dt>定位</dt><dd>{{ selectedCitation.locator }}</dd></div>
        </dl>
        <p class="eyebrow">原文片段</p>
        <p class="assistant-citation-detail-text">{{ citationText(selectedCitation) }}</p>
        <p class="meta-line">内容仅供本次回答核对，移动端不支持编辑或替换服务端引用。</p>
      </section>
    </div>
  </Teleport>
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
.assistant-citation-detail:focus-visible,
.assistant-citation-dialog button:focus-visible {
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
.assistant-citation-text,
.assistant-citation-detail-text {
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
.assistant-citation-backdrop {
  align-items: center;
  background: rgb(0 0 0 / 42%);
  display: flex;
  inset: 0;
  justify-content: center;
  padding: 16px;
  position: fixed;
  z-index: 20;
}
.assistant-citation-dialog {
  background: var(--surface);
  border: 1px solid color-mix(in srgb, var(--text) 14%, transparent);
  border-radius: 16px;
  display: grid;
  gap: 12px;
  max-height: min(84vh, 680px);
  max-width: 620px;
  overflow: auto;
  padding: 18px;
  width: min(100%, 620px);
}
.assistant-citation-dialog h2 { margin: 0; overflow-wrap: anywhere; }
.assistant-citation-dialog-head {
  align-items: flex-start;
  display: flex;
  gap: 12px;
  justify-content: space-between;
}
.assistant-citation-detail-meta {
  display: grid;
  gap: 8px;
  margin: 0;
}
.assistant-citation-detail-meta div {
  display: grid;
  gap: 2px;
}
.assistant-citation-detail-meta dt { color: var(--muted); font-size: 0.86rem; }
.assistant-citation-detail-meta dd { margin: 0; overflow-wrap: anywhere; }
.assistant-citation-dialog .eyebrow { margin: 0; }
@media (prefers-reduced-motion: reduce) {
  .assistant-citation-backdrop { transition: none; }
}
</style>
