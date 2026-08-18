import { describe, expect, it } from 'vitest'

import { normalizeSuggestedQuestions } from './followUp'

describe('assistant follow-up question display contract', () => {
  it('keeps at most three unique, non-empty questions', () => {
    expect(normalizeSuggestedQuestions([
      '  查看依据？  ',
      '查看依据？',
      '补充哪些信息？',
      '如何查看规则？',
      '这条会被截断吗？',
    ])).toEqual(['查看依据？', '补充哪些信息？', '如何查看规则？'])
  })

  it('ignores malformed, overlong, and non-array responses', () => {
    expect(normalizeSuggestedQuestions(null)).toEqual([])
    expect(normalizeSuggestedQuestions([
      42,
      '',
      'x'.repeat(81),
      '  合法问题？  ',
    ])).toEqual(['合法问题？'])
  })
})
