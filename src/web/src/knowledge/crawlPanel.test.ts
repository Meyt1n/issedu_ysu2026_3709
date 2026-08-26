import { describe, expect, it } from 'vitest'

import { ApiClientError } from '../api/client'
import {
  CRAWL_FORBIDDEN_GUIDANCE,
  STAGING_CHANGE_LABELS,
  crawlAccessFromError,
  crawlRunSummary,
  pendingTeachingDrafts,
  simulateUpdateSummary,
  stagingChangeKind,
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

  it('distinguishes an unreachable API (network) from a steward rejection', () => {
    const cause = new ApiClientError('API service is unavailable', {
      status: 0,
      code: 'DEPENDENCY_UNAVAILABLE',
    })
    expect(crawlAccessFromError(cause)).toBe('network')
  })

  it('distinguishes a request timeout from an unreachable API', () => {
    const cause = new ApiClientError('API request timed out after 15000ms', {
      status: 0,
      code: 'REQUEST_TIMEOUT',
    })
    expect(crawlAccessFromError(cause)).toBe('timeout')
  })

  it('flags a deployment missing the crawl allowlist as config-missing', () => {
    const cause = new ApiClientError('KNOWLEDGE_CRAWL_CONFIG_MISSING', {
      status: 503,
      code: 'HTTP_ERROR',
    })
    expect(crawlAccessFromError(cause)).toBe('config-missing')
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

describe('stagingChangeKind', () => {
  it('labels first fetches as new sources', () => {
    expect(stagingChangeKind({ first_fetch: true, unchanged: false })).toBe('new')
    expect(STAGING_CHANGE_LABELS.new).toBe('新来源')
  })

  it('labels hash changes as updated and identical hashes as unchanged', () => {
    expect(stagingChangeKind({ first_fetch: false, unchanged: false })).toBe('changed')
    expect(stagingChangeKind({ first_fetch: false, unchanged: true })).toBe('unchanged')
    expect(STAGING_CHANGE_LABELS.changed).toBe('有更新')
    expect(STAGING_CHANGE_LABELS.unchanged).toBe('未变更')
  })
})

describe('crawlRunSummary', () => {
  it('breaks results down into new / updated / unchanged counts', () => {
    const summary = crawlRunSummary({
      fetched: 6,
      changed: 3,
      unchanged: 3,
      new_sources: 2,
      errors: [],
    })
    expect(summary).toContain('共 6 条')
    expect(summary).toContain('新来源 2')
    expect(summary).toContain('有更新 1')
    expect(summary).toContain('未变更 3')
    expect(summary).toContain('不会自动入库')
    expect(summary).toContain('重置为 draft')
  })

  it('explains that an all-unchanged run is normal and points to the demo path', () => {
    const summary = crawlRunSummary({
      fetched: 4,
      changed: 0,
      unchanged: 4,
      new_sources: 0,
      errors: [],
    })
    expect(summary).toContain('未变更 4')
    expect(summary).toContain('内容哈希与上次一致')
    expect(summary).toContain('属正常现象')
    expect(summary).toContain('模拟来源更新')
  })

  it('surfaces per-source failures without hiding successful counts', () => {
    const summary = crawlRunSummary({
      fetched: 5,
      changed: 5,
      unchanged: 0,
      new_sources: 5,
      errors: [{ source_id: 'x', error: 'FIXTURE_NOT_FOUND' }],
    })
    expect(summary).toContain('失败 1')
    expect(summary).toContain('新来源 5')
  })
})

describe('simulateUpdateSummary', () => {
  it('describes the teaching bump and the next crawl step', () => {
    const summary = simulateUpdateSummary({
      reset: false,
      bumped: [{ source_id: 'a' }, { source_id: 'b' }],
    })
    expect(summary).toContain('2 个本地夹具来源')
    expect(summary).toContain('教学演示')
    expect(summary).toContain('不出网')
    expect(summary).toContain('仍不会自动入库')
  })

  it('describes reset as returning to the pristine fixtures', () => {
    const summary = simulateUpdateSummary({ reset: true, cleared: ['a.html'] })
    expect(summary).toContain('已清除 1 个')
    expect(summary).toContain('夹具原文')
  })
})
