import { describe, expect, it } from 'vitest'

import type { WeatherResponse } from '../api/types'
import { calmWeatherBadge, calmWeatherMessage, presentWeather } from './weatherView'

function response(overrides: Partial<WeatherResponse> = {}): WeatherResponse {
  return {
    status: 'ok',
    action_cards: [],
    cache_status: 'miss',
    location_scope: 'city',
    ruleset_version: 'weather-actions-v1',
    disclaimer: '环境行动建议仅供日常生活安排参考，不构成诊断或用药建议。',
    ...overrides,
  }
}

describe('presentWeather', () => {
  it('presents current city-level weather with source metadata', () => {
    const view = presentWeather(
      response({
        temperature: 28,
        source_observed_at: '2026-08-18T01:00:00Z',
      }),
    )

    expect(view.available).toBe(true)
    expect(view.stale).toBe(false)
    expect(view.statusLabel).toBe('天气已更新')
    expect(view.scopeLabel).toBe('城市级范围')
    expect(view.sourceLabel).toContain('08月18日')
  })

  it('keeps stale cards visible but labels them as cached data', () => {
    const view = presentWeather(
      response({
        status: 'stale',
        cache_status: 'stale',
        degraded_reason: 'timeout',
        action_cards: [{ rule_id: 'rain-travel', level: 'info', message: '雨雪天气' }],
      }),
    )

    expect(view.available).toBe(true)
    expect(view.stale).toBe(true)
    expect(view.statusLabel).toBe('缓存数据 · 已降级')
    expect(view.detail).toContain('超时')
  })

  it('explains disabled and unavailable states without pretending success', () => {
    expect(presentWeather(response({ status: 'disabled' })).statusLabel).toBe('天气出口未启用')
    const unavailable = presentWeather(response({ status: 'invalid_response' }))
    expect(unavailable.available).toBe(false)
    expect(unavailable.statusLabel).toBe('天气暂不可用')
    expect(unavailable.detail).toContain('家庭事实、规则和任务不受影响')
  })

  it('never exposes location codes in the presentation', () => {
    const view = presentWeather(response({ location_scope: 'district' }))

    expect(view.scopeLabel).toBe('区县级范围')
    expect(JSON.stringify(view)).not.toContain('110000')
  })

  it('handles a missing response and invalid source timestamp', () => {
    const missing = presentWeather(null)
    const invalidTime = presentWeather(response({ source_observed_at: 'not-a-date' }))

    expect(missing.available).toBe(false)
    expect(missing.scopeLabel).toBe('粗粒度位置未配置')
    expect(invalidTime.sourceLabel).toBe('来源时间无效')
  })

  it('labels a fresh cache without implying a new provider request', () => {
    const view = presentWeather(response({ cache_status: 'fresh' }))

    expect(view.available).toBe(true)
    expect(view.statusLabel).toBe('缓存仍有效')
  })

  it('explains missing provider or location configuration', () => {
    const view = presentWeather(response({ status: 'location_required', location_scope: null }))

    expect(view.available).toBe(false)
    expect(view.statusLabel).toBe('等待安全配置')
    expect(view.detail).toContain('获批的位置代码')
  })
})

describe('daily calm weather copy', () => {
  it('keeps the same copy within a day and rotates it on the next day', () => {
    const today = new Date(2026, 8, 3)
    const tomorrow = new Date(2026, 8, 4)

    expect(calmWeatherMessage(today)).toBe(calmWeatherMessage(today))
    expect(calmWeatherBadge(today)).toBe(calmWeatherBadge(today))
    expect(calmWeatherMessage(today)).not.toBe(calmWeatherMessage(tomorrow))
    expect(calmWeatherBadge(today)).not.toBe(calmWeatherBadge(tomorrow))
  })
})
