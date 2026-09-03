import type { HealthNewsItem } from '../api/types'

/**
 * Editorial art for health-news cards. Keep local and remote art in separate
 * pools so a live whitelist headline never silently inherits a seasonal card.
 */
const HEALTH_NEWS_VISUALS: Record<string, string> = {
  'autumn-transition-dry': '/seasonal-art/autumn-sunlight.png',
  'autumn-flu-like-caution': '/seasonal-art/autumn-rest.png',
  'autumn-dry-air': '/seasonal-art/autumn-dry-air.png',
  'autumn-window-airing': '/seasonal-art/autumn-ventilation.png',
  'autumn-gentle-walk': '/seasonal-art/autumn-walk.png',
  'autumn-family-checkin': '/seasonal-art/autumn-routine.png',
}

const REMOTE_HEALTH_NEWS_VISUALS = [
  '/news-art/remote-care-center.png',
  '/news-art/remote-hygiene.png',
  '/news-art/remote-care-notes.png',
  '/news-art/remote-outdoor.png',
  '/news-art/remote-daily-routine.png',
  '/news-art/remote-community.png',
] as const

export function healthNewsVisualFor(item: HealthNewsItem, position = 0): string | null {
  const localVisual = HEALTH_NEWS_VISUALS[item.id]
  if (localVisual) return localVisual

  // Remote headlines change over time, so use their display position for a
  // deliberate visual rotation instead of leaving every live card blank.
  if (item.kind === 'remote' || item.source === 'remote_whitelist') {
    return REMOTE_HEALTH_NEWS_VISUALS[Math.abs(position) % REMOTE_HEALTH_NEWS_VISUALS.length]
  }

  return null
}
