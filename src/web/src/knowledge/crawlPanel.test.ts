import { describe, expect, it } from 'vitest'

import { ApiClientError } from '../api/client'
import {
  CRAWL_FORBIDDEN_GUIDANCE,
  crawlAccessFromError,
  pendingTeachingDrafts,
  teachingLoopSummary,
} from './crawlPanel'

describe('crawlAccessFromError', () => {
  it('maps KNOWLEDGE_STEWARD_REQUIRED (403) to explicit forbidden guidance', () => {
    const cause = new ApiClientError('KNOWLEDGE_STEWARD_REQUIRED', {
      status: 403,
      code: 'KNOWLEDGE_STEWARD_REQUIRED',
    })
    expect(crawlAccessFromError(cause)).toBe('forbidden')
    expect(CRAWL_FORBIDDEN_GUIDANCE).toContain('知识管理员')
    expect(CRAWL_FORBIDDEN_GUIDANCE).toContain('KNOWLEDGE_ADMIN_ACTORS')
  })

  it('keeps other failures as generic errors', () => {
    const serverError = new ApiClientError('boom', { status: 500, code: 'INTERNAL' })
    expect(crawlAccessFromError(serverError)).toBe('error')
    expect(crawlAccessFromError(new TypeError('network down'))).toBe('error')
  })
})

describe('pendingTeachingDrafts', () => {
  it('selects only draft and reviewed staging entries', () => {
    const items = [
      { source_id: 'a', status: 'draft' },
      { source_id: 'b', status: 'reviewed' },
      { source_id: 'c', status: 'approved' },
      { source_id: 'd', status: 'promoted' },
      { source_id: 'e', status: 'rejected' },
    ]
    expect(pendingTeachingDrafts(items).map((item) => item.source_id)).toEqual(['a', 'b'])
  })
})

describe('teachingLoopSummary', () => {
  it('states each step and that nothing auto-ingests', () => {
    const summary = teachingLoopSummary(4, 4, 4)
    expect(summary).toContain('抓取 4 条')
    expect(summary).toContain('批准 4 条')
    expect(summary).toContain('晋升 4 篇')
    expect(summary).toContain('不会自动入库')
  })
})
