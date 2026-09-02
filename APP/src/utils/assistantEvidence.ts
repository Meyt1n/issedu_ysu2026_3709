import type { AssistantCitation, EvidencePreview } from '@/api/types'

/**
 * 引用展示的上限只用于保护移动端渲染和会话存储，不会改变服务端的引用校验。
 * 详情仍然只来自本次回答返回的 citation。
 */
export const MAX_ASSISTANT_CITATIONS = 24
export const MAX_CITATION_TEXT_LENGTH = 4_000

function boundedText(value: unknown, maxLength: number): string | null {
  if (typeof value !== 'string') return null
  const text = value.trim()
  return text ? text.slice(0, maxLength) : null
}

function citationKey(citation: AssistantCitation): string {
  return [citation.document_id, citation.version || 'unknown', citation.chunk_id].join('\u0000')
}

/**
 * 过滤结构异常引用并按文档、索引版本、分块去重。
 * 同一文档的不同分块仍需保留，以免把回答的证据范围压缩错。
 */
export function uniqueAssistantCitations(
  citations?: AssistantCitation[] | null,
): AssistantCitation[] {
  const result: AssistantCitation[] = []
  const seen = new Set<string>()
  for (const citation of citations ?? []) {
    if (!citation || typeof citation !== 'object') continue
    const documentId = boundedText(citation.document_id, 240)
    const chunkId = boundedText(citation.chunk_id, 240)
    if (!documentId || !chunkId) continue
    const normalized: AssistantCitation = {
      document_id: documentId,
      version: boundedText(citation.version, 120) ?? '',
      chunk_id: chunkId,
      document_title: boundedText(citation.document_title, 240),
      text: boundedText(citation.text, MAX_CITATION_TEXT_LENGTH),
      locator: boundedText(citation.locator, 500),
    }
    const key = citationKey(normalized)
    if (seen.has(key)) continue
    seen.add(key)
    result.push(normalized)
    if (result.length >= MAX_ASSISTANT_CITATIONS) break
  }
  return result
}

/** 只保留没有被引用卡片覆盖的来源标识，避免同一来源重复堆叠。 */
export function extraAssistantSources(
  sources?: string[] | null,
  citations?: AssistantCitation[] | null,
): string[] {
  const cited = new Set<string>()
  for (const citation of uniqueAssistantCitations(citations)) {
    for (const value of [citation.document_id, citation.document_title, citation.chunk_id]) {
      if (value?.trim()) cited.add(value.trim())
    }
  }
  const result: string[] = []
  const seen = new Set<string>()
  for (const source of sources ?? []) {
    if (typeof source !== 'string') continue
    const value = source.trim()
    if (!value || cited.has(value) || seen.has(value)) continue
    seen.add(value)
    result.push(value.slice(0, 240))
  }
  return result
}

export function assistantCitationTitle(citation: AssistantCitation): string {
  return citation.document_title?.trim() || citation.document_id
}

/**
 * 判断回答是否需要明确显示“没有可引用依据”。
 *
 * 仅凭空的 citations/sources 无法区分旧版响应和服务端明确返回的“没有命中
 * 知识文档”预览，因此只有在降级，或服务端预览明确表示本轮没有本地/外部
 * 资料且没有其他来源标识时才展示该提示。这样既不伪造依据，也不会把家庭
 * 事实来源误报成无证据。
 */
export function shouldShowAssistantNoEvidence(
  citations?: AssistantCitation[] | null,
  sources?: string[] | null,
  evidencePreview?: EvidencePreview | null,
  degraded = false,
): boolean {
  if (uniqueAssistantCitations(citations).length > 0) return false
  if (extraAssistantSources(sources, citations).length > 0) return false
  if (degraded) return true
  if (!evidencePreview) return false
  return evidencePreview.knowledge_count <= 0 && evidencePreview.external_count <= 0
}
