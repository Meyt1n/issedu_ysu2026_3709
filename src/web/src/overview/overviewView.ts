import type { MemberState, ReviewTask } from '../api/types'

const DRUG_NAME_KEYS = ['drug_name', 'drug', 'name', '药品名称', '药名'] as const

function firstText(source: Record<string, unknown> | null | undefined): string | null {
  if (!source) return null
  for (const key of DRUG_NAME_KEYS) {
    const value = source[key]
    if (typeof value === 'string' && value.trim()) return value.trim()
  }
  return null
}
/**
 * Extracts a display-only drug candidate. It never treats this value as a
 * confirmed health fact; the overview labels it as an identification candidate.
 */
export function reviewDrugCandidate(task: Pick<ReviewTask, 'selected_candidate' | 'manual_payload' | 'candidates'>): string {
  return (
    firstText(task.selected_candidate) ??
    firstText(task.manual_payload) ??
    task.candidates.map(candidate => firstText(candidate)).find((value): value is string => Boolean(value)) ??
    '药品名称待确认'
  )
}

export function memberEventCount(state: MemberState | null | undefined): number {
  const value = state?.state?.active_event_count ?? state?.state?.events_count
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : 0
}

export function isSameLocalDay(value: string | null | undefined, now = new Date()): boolean {
  if (!value) return false
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return false
  return (
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate()
  )
}
