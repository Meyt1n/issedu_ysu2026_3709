import { describe, expect, it } from 'vitest'
import { trustedReviewTarget } from './reviewHandoff'

describe('review handoff target', () => {
  it('only permits an HTTPS same-origin review target', () => {
    const result = trustedReviewTarget('vision-1', 'https://app.example/review', 'https://app.example')
    expect(result.url).toBe('https://app.example/review?task=vision-1')
  })
  it('rejects external, HTTP and missing targets', () => {
    expect(trustedReviewTarget('vision-1', 'https://outside.example', 'https://app.example').url).toBeNull()
    expect(trustedReviewTarget('vision-1', 'http://app.example', 'https://app.example').url).toBeNull()
    expect(trustedReviewTarget('vision-1', undefined, 'https://app.example').url).toBeNull()
  })
})
