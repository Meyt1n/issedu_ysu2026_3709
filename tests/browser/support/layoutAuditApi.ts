import type { Page } from '@playwright/test'

/**
 * 排版审计用的合成家庭：数据形态刻意做"满"——长中文药名、多成员、
 * 多风险、长消息，用来把溢出与错位暴露出来，而不是让空态掩盖问题。
 */

export const household = {
  id: 'household-audit',
  name: '排版审计家庭',
  created_by: 'audit-admin',
  created_at: '2026-08-01T00:00:00Z',
}

export const members = [
  { id: 'm-grandma', display_name: '奶奶', role: 'DEPENDENT', actor_id: 'grandma-acct' },
  { id: 'm-grandpa', display_name: '爷爷', role: 'DEPENDENT', actor_id: 'grandpa-acct' },
  { id: 'm-dad', display_name: '爸爸', role: 'SELF', actor_id: 'audit-admin' },
  { id: 'm-mom', display_name: '妈妈', role: 'CAREGIVER', actor_id: 'mom-acct' },
].map(member => ({
  ...member,
  household_id: household.id,
  created_at: '2026-08-01T00:00:00Z',
}))

const LONG_DRUG = '苯磺酸氨氯地平片（络活喜）5mg 缓释剂型'
const LONG_MESSAGE =
  '检测到同类降压药可能重复：苯磺酸氨氯地平片与硝苯地平控释片均属二氢吡啶类钙通道阻滞剂，请携带两盒药品与最近一次门诊记录咨询医师或药师后再调整。'

function isoDaysAgo(days: number, hour = 9): string {
  const date = new Date()
  date.setDate(date.getDate() - days)
  date.setHours(hour, 0, 0, 0)
  return date.toISOString()
}

const EVENT_TYPES = [
  'medication_added',
  'plan_confirmed',
  'plan_deferred',
  'plan_missed',
  'metric_recorded',
  'note_added',
  'report_added',
  'allergy_added',
]

export function timelineFor(memberId: string) {
  return Array.from({ length: 18 }, (_, index) => ({
    id: `evt-${memberId}-${index}`,
    household_id: household.id,
    member_id: memberId,
    sequence_no: index + 1,
    event_type: EVENT_TYPES[index % EVENT_TYPES.length]!,
    source: 'MANUAL',
    confirmation_status: 'CONFIRMED',
    payload: {
      drug: index % 3 === 0 ? LONG_DRUG : '硝苯地平控释片',
      schedule: '每日两次 · 早晚饭后各一片',
      metric: '收缩压 148 / 舒张压 92',
      note: '今天散步 20 分钟后略感头晕，已记录并提醒家人留意。',
      allergy: '青霉素类',
    },
    evidence: {},
    created_by: 'audit-admin',
    confirmed_by: 'audit-admin',
    idempotency_key: null,
    compensates_event_id: null,
    occurred_at: isoDaysAgo(index % 7, 8 + (index % 6)),
    recorded_at: isoDaysAgo(index % 7, 8 + (index % 6)),
    correlation_id: `corr-${index}`,
    causation_id: null,
    supersedes_event_id: null,
    schema_version: 1,
    created_at: isoDaysAgo(index % 7, 8 + (index % 6)),
  }))
}

export function plansFor(memberId: string) {
  return Array.from({ length: 4 }, (_, index) => ({
    plan_event_id: `plan-${memberId}-${index}`,
    drug: index % 2 === 0 ? LONG_DRUG : '二甲双胍缓释片 0.5g',
    schedule: '每日两次 · 早晚饭后各一片',
    dose: '5mg',
    times: ['08:00', '20:00'],
    start_date: '2026-08-01',
    end_date: null,
    status: index === 0 ? 'DUE' : index === 1 ? 'OVERDUE' : 'NORMAL',
    next_action_at: isoDaysAgo(-(index % 2), 8 + index * 3),
    last_action: null,
    action_history: [],
    allowed_actions: ['CONFIRM', 'DEFER', 'SKIP', 'MISS'],
  }))
}

export function reviewTasksFor(memberId: string) {
  return Array.from({ length: 5 }, (_, index) => ({
    id: `review-${memberId}-${index}`,
    vision_task_id: `vt-${memberId}-${index}`,
    household_id: household.id,
    member_id: memberId,
    status: 'PENDING_REVIEW',
    fusion_status: index % 2 === 0 ? 'CONFLICT' : 'REVIEW',
    candidates: [
      {
        drug_name: LONG_DRUG,
        confidence: 0.72,
        evidence_kind: 'OCR',
        source: 'ocr',
      },
    ],
    selected_candidate: null,
    manual_payload: null,
    model_version: 'yolo-v8n-2026.07',
    rule_version: 'rules-2026.08',
    version: 1,
    confirmed_by: null,
    confirmed_at: null,
    created_at: isoDaysAgo(index % 5, 10),
    updated_at: isoDaysAgo(index % 5, 10),
  }))
}

export function risksFor(memberId: string) {
  const levels = ['SEVERE', 'WARNING', 'INFO']
  const alerts = Array.from({ length: 3 }, (_, index) => ({
    rule_id: `rule-duplicate-${index}`,
    level: levels[index]!,
    message: LONG_MESSAGE,
    source_event_ids: [`evt-${memberId}-0`, `evt-${memberId}-1`],
    created_at: isoDaysAgo(index, 11),
    rule_version: 'rules-2026.08',
    risk_fingerprint: `fp-${memberId}-${index}`,
    acknowledgement: null,
  }))
  return {
    member_id: memberId,
    alerts,
    total: alerts.length,
    severe_count: 1,
    warning_count: 1,
  }
}

export function graphFor(memberId: string) {
  const nodes = [
    { id: 'd1', category: 'drug', label: LONG_DRUG },
    { id: 'd2', category: 'drug', label: '二甲双胍缓释片 0.5g' },
    { id: 'a1', category: 'allergy', label: '青霉素类过敏' },
    { id: 's1', category: 'disease', label: '2 型糖尿病合并高血压' },
    { id: 'p1', category: 'plan', label: '每日两次 · 早晚饭后' },
    { id: 'c1', category: 'caregiver', label: '妈妈（授权照护者）' },
  ].map(node => ({
    ...node,
    source_event_id: 'evt-1',
    source_recorded_at: isoDaysAgo(1, 9),
  }))
  return {
    member_id: memberId,
    generated_at: isoDaysAgo(0, 12),
    events_count: 18,
    nodes,
    edges: [
      { source: 'd1', target: 'a1', relation: 'conflicts', source_event_id: 'evt-1' },
      { source: 'd1', target: 'p1', relation: 'scheduled', source_event_id: 'evt-2' },
      { source: 'd2', target: 's1', relation: 'treats', source_event_id: 'evt-3' },
      { source: 'c1', target: 'p1', relation: 'monitors', source_event_id: 'evt-4' },
    ],
  }
}

function weekSeries() {
  return Array.from({ length: 7 }, (_, index) => {
    const date = new Date()
    date.setDate(date.getDate() - (6 - index))
    return { day: date.toISOString().slice(0, 10), count: [2, 5, 1, 8, 3, 0, 6][index]! }
  })
}

/** 装一整套只读 API mock，覆盖管理端全部视图所需的接口。 */
export async function installAuditApi(page: Page): Promise<void> {
  await page.route('**/api/v1/**', async route => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    const respond = (body: unknown, status = 200) =>
      route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })

    const memberOf = (): string => {
      const match = path.match(/\/members\/([^/]+)/)
      return match?.[1] ?? 'm-grandma'
    }

    if (request.method() === 'POST' && path === '/api/v1/auth/login') {
      return respond({
        actor_id: 'audit-admin',
        session_token: 'a'.repeat(48),
        expires_at: Math.floor(Date.now() / 1000) + 3600,
      })
    }
    if (request.method() === 'POST' && path === '/api/v1/auth/session') {
      return respond({ actor_id: 'audit-admin', expires_at: Math.floor(Date.now() / 1000) + 3600 })
    }
    if (request.method() === 'POST' && path === '/api/v1/auth/logout') return respond({ status: 'ok' })
    if (path === '/api/v1/households') return respond([household])
    if (path.endsWith('/members')) return respond(members)
    if (path === '/api/v1/meta/capabilities') {
      return respond({
        phase: 'P1-vision',
        available: ['manual-health-event', 'household-member', 'review-task', 'vision-inference', 'weather-cards'],
        unavailable: ['llm-cloud', 'external-web'],
      })
    }
    if (path === '/api/v1/health/db') return respond({ status: 'ok' })
    if (path.endsWith('/dashboard-summary')) {
      return respond({
        generated_at: new Date().toISOString(),
        member_count: members.length,
        events_today: 6,
        events_total: 72,
        severe_count: 2,
        warning_count: 4,
        info_count: 7,
        pending_reviews: 5,
        pending_outbox: 2,
        week_series: weekSeries(),
      })
    }
    if (path.endsWith('/timeline')) return respond(timelineFor(memberOf()))
    if (path.endsWith('/plan-workbench')) {
      return respond({
        member_id: memberOf(),
        generated_at: new Date().toISOString(),
        plans: plansFor(memberOf()),
      })
    }
    if (path.includes('/review-tasks')) return respond(reviewTasksFor(memberOf()))
    if (path.endsWith('/risks')) return respond(risksFor(memberOf()))
    if (path.endsWith('/relationship-graph')) return respond(graphFor(memberOf()))
    if (path.endsWith('/state')) {
      return respond({
        member_id: memberOf(),
        household_id: household.id,
        state: { events_count: 18 },
        last_event_id: 'evt-1',
        last_sequence: 18,
        version: 1,
        state_hash: null,
        updated_at: isoDaysAgo(0, 12),
      })
    }
    if (path.endsWith('/outbox')) return respond([])
    if (path.startsWith('/api/v1/weather/')) {
      return respond({
        status: 'ok',
        cache_status: 'fresh',
        location_scope: 'district',
        ruleset_version: 'weather-2026.08',
        source_observed_at: isoDaysAgo(0, 8),
        fetched_at: isoDaysAgo(0, 8),
        temperature: 31,
        condition: '多云转晴',
        humidity: 78,
        wind: '东北风 · 3级',
        aqi: 62,
        action_cards: [
          { rule_id: 'heat', level: 'warning', message: '午后体感偏热：建议长辈避开 12–15 点外出，随身携带温水。' },
          { rule_id: 'humid', level: 'info', message: '空气湿度较高：可适时除湿并保持室内衣物干燥。' },
          { rule_id: 'uv', level: 'info', message: '紫外线中等：外出戴帽或使用遮阳伞。' },
        ],
      })
    }
    if (path.startsWith('/api/v1/health-news')) {
      return respond({
        status: 'local_only',
        generated_at: new Date().toISOString(),
        disclaimer: '本栏目为教学演示内容，不构成医疗建议。',
        items: Array.from({ length: 6 }, (_, index) => ({
          id: `news-${index}`,
          kind: 'local',
          tag: ['起居', '饮食', '运动', '通风', '情绪', '复查'][index]!,
          title: `秋季照护提示 ${index + 1}：昼夜温差加大时的穿衣与作息建议`,
          summary: '早晚温差超过 8℃ 时建议长辈采用分层穿衣，室内保持 20–24℃，并在通风后再开窗。',
          source: '本地季节日历',
          published_at: isoDaysAgo(index, 7),
          url: null,
        })),
      })
    }
    if (path.includes('/vision-tasks')) return respond([])
    if (path.endsWith('/authorizations')) return respond([])
    if (path.endsWith('/authorization-audits')) return respond([])
    return respond([])
  })
}
