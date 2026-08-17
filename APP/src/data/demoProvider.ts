import { reactive } from 'vue'

import { formatDay } from '@/utils/format'
import type {
  CareTask,
  DataProvider,
  MemberDetail,
  MemberSummary,
  ProviderInfo,
  QualityCheckResult,
  RecognitionCandidate,
  RiskCard,
  TaskAction,
  TaskActionPayload,
  TimelineItem,
  TodaySnapshot,
  TrendPoint,
} from './types'

const WEEKDAY_LABELS = ['日', '一', '二', '三', '四', '五', '六']

/**
 * 演示模式数据：全部为虚构人物与虚构药品记录，仅用于教学演示体验，
 * 不包含任何真实健康数据（主仓库数据与隐私规范约束）。
 */

function todayAt(hours: number, minutes = 0): string {
  const date = new Date()
  date.setHours(hours, minutes, 0, 0)
  return date.toISOString()
}

function daysFromNow(days: number, hours = 9): string {
  const date = new Date()
  date.setDate(date.getDate() + days)
  date.setHours(hours, 0, 0, 0)
  return date.toISOString()
}

const EXPIRED_DATE = daysFromNow(-12)

interface DemoState {
  tasks: CareTask[]
  risks: RiskCard[]
  membersBase: Omit<MemberSummary, 'pendingTaskCount' | 'severeRiskCount' | 'warningRiskCount'>[]
  recentEvents: Record<string, TimelineItem[]>
}

function buildInitialState(): DemoState {
  return {
    membersBase: [
      {
        id: 'm-wang',
        name: '王秀兰（演示）',
        relation: '母亲',
        role: 'DEPENDENT',
        avatarText: '王',
        visibleScope: {
          fields: ['已确认健康事件', '用药与计划'],
          purpose: 'family-care',
          validUntil: daysFromNow(28),
        },
      },
      {
        id: 'm-li',
        name: '李建国（演示）',
        relation: '父亲',
        role: 'DEPENDENT',
        avatarText: '李',
        visibleScope: {
          fields: ['已确认健康事件'],
          purpose: 'family-care',
          validUntil: daysFromNow(9),
        },
      },
      {
        id: 'm-self',
        name: '王芳（我）',
        relation: '本人',
        role: 'SELF',
        avatarText: '芳',
        visibleScope: 'FULL',
      },
    ],
    tasks: [
      {
        id: 't-am-med',
        memberId: 'm-wang',
        memberName: '王秀兰（演示）',
        title: '早餐后服药：苯磺酸氨氯地平片',
        detail: '5mg，1 片，随早餐后温水送服。',
        level: 'GENERAL',
        dueAt: todayAt(8, 0),
        status: 'PENDING',
        planEventId: 'EVT-PLAN-101',
      },
      {
        id: 't-bp',
        memberId: 'm-wang',
        memberName: '王秀兰（演示）',
        title: '午后测量血压并记录',
        detail: '静坐 5 分钟后测量，记录收缩压/舒张压。',
        level: 'INFO',
        dueAt: todayAt(15, 0),
        status: 'PENDING',
        planEventId: 'EVT-PLAN-102',
      },
      {
        id: 't-pm-med',
        memberId: 'm-wang',
        memberName: '王秀兰（演示）',
        title: '晚间服药：二甲双胍缓释片',
        detail: '0.5g，1 片，晚餐后服用。昨晚未确认，本条提醒等级已上调。',
        level: 'HIGH',
        dueAt: todayAt(19, 0),
        status: 'PENDING',
        planEventId: 'EVT-PLAN-103',
      },
      {
        id: 't-walk',
        memberId: 'm-li',
        memberName: '李建国（演示）',
        title: '外出散步前查看环境提示',
        detail: '明日降温幅度较大，出门前查看环境行动卡。',
        level: 'INFO',
        dueAt: todayAt(17, 30),
        status: 'PENDING',
        planEventId: 'EVT-PLAN-104',
      },
    ],
    risks: [
      {
        ruleId: 'rule-expiry-01',
        ruleVersion: 'v1.2',
        level: 'SEVERE',
        message: `阿司匹林肠溶片（批次 A2025-118）已于 ${formatDay(EXPIRED_DATE)} 过期`,
        memberId: 'm-wang',
        memberName: '王秀兰（演示）',
        createdAt: todayAt(7, 30),
        sourceCount: 2,
        explanation:
          '依据已确认的药品批次事实（登记有效期）与过期检查规则 rule-expiry-01 得出，属于确定性规则结论，不是模型推断。',
        suggestion:
          '请勿继续服用该批次，并请家人协助处理过期药品、补充登记新批次。本提示不构成停药或换药建议，如有疑问请联系医生或药师。',
        acknowledged: false,
        sourceEvents: [
          {
            id: 'EVT-2101',
            eventType: 'MEDICATION_BATCH_ADDED',
            confirmationStatus: 'CONFIRMED',
            createdAt: daysFromNow(-40),
          },
          {
            id: 'EVT-2140',
            eventType: 'RULE_EVALUATED',
            confirmationStatus: 'CONFIRMED',
            createdAt: todayAt(7, 30),
          },
        ],
      },
      {
        ruleId: 'rule-duplicate-02',
        ruleVersion: 'v1.0',
        level: 'WARNING',
        message: '感冒灵颗粒 与 对乙酰氨基酚片 含相同成分「对乙酰氨基酚」',
        memberId: 'm-wang',
        memberName: '王秀兰（演示）',
        createdAt: todayAt(7, 30),
        sourceCount: 2,
        explanation:
          '两条已确认用药事实的成分表中出现同一成分，触发重复成分规则 rule-duplicate-02。',
        suggestion:
          '请注意避免同时服用含相同成分的药品；如已同时服用或不确定，请联系医生或药师确认。',
        acknowledged: false,
        sourceEvents: [
          {
            id: 'EVT-2110',
            eventType: 'MEDICATION_ADDED',
            confirmationStatus: 'CONFIRMED',
            createdAt: daysFromNow(-6),
          },
          {
            id: 'EVT-2118',
            eventType: 'MEDICATION_ADDED',
            confirmationStatus: 'CONFIRMED',
            createdAt: daysFromNow(-2),
          },
        ],
      },
      {
        ruleId: 'rule-stock-03',
        ruleVersion: 'v1.1',
        level: 'INFO',
        message: '苯磺酸氨氯地平片 剩余约 4 天用量',
        memberId: 'm-wang',
        memberName: '王秀兰（演示）',
        createdAt: todayAt(7, 30),
        sourceCount: 1,
        explanation: '按当前计划每日用量与最近一次库存登记推算，触发低库存规则 rule-stock-03。',
        suggestion: '请尽快安排补充，取得新药后可在“拍药盒”中登记新批次。',
        acknowledged: false,
        sourceEvents: [
          {
            id: 'EVT-2125',
            eventType: 'STOCK_UPDATED',
            confirmationStatus: 'CONFIRMED',
            createdAt: daysFromNow(-1),
          },
        ],
      },
      {
        ruleId: 'rule-weather-04',
        ruleVersion: 'v1.0',
        level: 'TIP',
        message: '明日最低气温 3°C，较今日下降 8°C',
        memberId: 'm-li',
        memberName: '李建国（演示）',
        createdAt: todayAt(6, 0),
        sourceCount: 1,
        explanation:
          '环境行动卡：天气适配器仅使用城市编码获取天气，不上传任何健康信息（主仓库 FR-07）。',
        suggestion: '外出请注意保暖，可将散步调整到午后气温较高的时段。',
        acknowledged: false,
        sourceEvents: [
          {
            id: 'EVT-2130',
            eventType: 'WEATHER_ACTION_CARD',
            confirmationStatus: 'CONFIRMED',
            createdAt: todayAt(6, 0),
          },
        ],
      },
    ],
    recentEvents: {
      'm-wang': [
        {
          id: 'EVT-2201',
          eventType: 'MEDICATION_ADDED',
          title: '新增药品：苯磺酸氨氯地平片（视觉录入，已人工确认）',
          confirmationStatus: 'CONFIRMED',
          occurredAt: daysFromNow(-1, 10),
          source: 'VISION',
        },
        {
          id: 'EVT-2202',
          eventType: 'PLAN_CONFIRMED',
          title: '确认昨日早间服药计划',
          confirmationStatus: 'CONFIRMED',
          occurredAt: daysFromNow(-1, 8),
          source: 'MANUAL',
        },
        {
          id: 'EVT-2203',
          eventType: 'AUTHORIZATION_UPDATED',
          title: '更新授权：王芳 可查看「用药与计划」',
          confirmationStatus: 'CONFIRMED',
          occurredAt: daysFromNow(-3, 20),
          source: 'MANUAL',
        },
        {
          id: 'EVT-2204',
          eventType: 'DOCUMENT_ADDED',
          title: '上传检查报告《血脂四项（演示）》，等待本人确认',
          confirmationStatus: 'UNCONFIRMED',
          occurredAt: daysFromNow(-2, 16),
          source: 'MANUAL',
        },
      ],
      'm-li': [
        {
          id: 'EVT-2301',
          eventType: 'PLAN_CONFIRMED',
          title: '确认晚间服药计划',
          confirmationStatus: 'CONFIRMED',
          occurredAt: daysFromNow(-1, 20),
          source: 'MANUAL',
        },
      ],
      'm-self': [
        {
          id: 'EVT-2401',
          eventType: 'AUTHORIZATION_GRANTED',
          title: '获得授权：查看 王秀兰（演示）的用药与计划',
          confirmationStatus: 'CONFIRMED',
          occurredAt: daysFromNow(-3, 20),
          source: 'MANUAL',
        },
      ],
    },
  }
}

const state = reactive<DemoState>(buildInitialState())

/** 测试与“恢复演示数据”入口。 */
export function resetDemoData(): void {
  Object.assign(state, buildInitialState())
}

function delay(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms))
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

function memberSummaries(): MemberSummary[] {
  return state.membersBase.map(base => {
    const pending = state.tasks.filter(t => t.memberId === base.id && t.status === 'PENDING')
    const risks = state.risks.filter(r => r.memberId === base.id && !r.acknowledged)
    return {
      ...clone(base),
      pendingTaskCount: pending.length,
      severeRiskCount: risks.filter(r => r.level === 'SEVERE').length,
      warningRiskCount: risks.filter(r => r.level === 'WARNING').length,
    }
  })
}

const DEMO_MEDICATIONS: Record<string, MemberDetail['medications']> = {
  'm-wang': [
    {
      name: '苯磺酸氨氯地平片（演示）',
      spec: '5mg×28 片',
      schedule: '每日 1 次，早餐后',
      stockDaysLeft: 4,
      expiryDate: daysFromNow(560),
      expired: false,
      confirmed: true,
    },
    {
      name: '二甲双胍缓释片（演示）',
      spec: '0.5g×30 片',
      schedule: '每日 2 次，早晚餐后',
      stockDaysLeft: 21,
      expiryDate: daysFromNow(500),
      expired: false,
      confirmed: true,
    },
    {
      name: '阿司匹林肠溶片（演示）',
      spec: '100mg×30 片',
      schedule: '每日 1 次，早餐前',
      stockDaysLeft: 12,
      expiryDate: EXPIRED_DATE,
      expired: true,
      confirmed: true,
    },
    {
      name: '感冒灵颗粒（演示）',
      spec: '10g×9 袋',
      schedule: '按需（发热或感冒症状时）',
      stockDaysLeft: 6,
      expiryDate: daysFromNow(130),
      expired: false,
      confirmed: true,
    },
  ],
  // 授权范围只有“已确认健康事件”，用药字段未获授权。
  'm-li': 'UNAUTHORIZED',
  'm-self': [],
}

export const demoProvider: DataProvider = {
  info(): ProviderInfo {
    return {
      mode: 'demo',
      label: '演示数据（虚构）',
      detail: '内置虚构家庭数据，不连接任何服务器；切换到联机模式可连接家庭服务器。',
    }
  },

  async listMembers(): Promise<MemberSummary[]> {
    await delay(160)
    return memberSummaries()
  },

  async getMemberDetail(memberId: string): Promise<MemberDetail> {
    await delay(180)
    const summary = memberSummaries().find(m => m.id === memberId)
    if (!summary) throw new Error('成员不存在或未获授权')
    const authorizations =
      memberId === 'm-wang'
        ? [
            {
              granteeName: '王芳（我）',
              fields: ['已确认健康事件', '用药与计划'],
              purpose: 'family-care',
              validUntil: daysFromNow(28),
            },
          ]
        : memberId === 'm-li'
          ? [
              {
                granteeName: '王芳（我）',
                fields: ['已确认健康事件'],
                purpose: 'family-care',
                validUntil: daysFromNow(9),
              },
            ]
          : []
    return {
      summary,
      medications: clone(DEMO_MEDICATIONS[memberId] ?? []),
      timeline: clone(state.recentEvents[memberId] ?? []),
      authorizations,
    }
  },

  async getTodaySnapshot(memberId: string): Promise<TodaySnapshot> {
    await delay(200)
    return {
      memberId,
      tasks: clone(state.tasks.filter(t => t.memberId === memberId)),
      risks: clone(state.risks.filter(r => r.memberId === memberId && !r.acknowledged)),
      recentEvents: clone((state.recentEvents[memberId] ?? []).slice(0, 4)),
    }
  },

  async listRisks(memberId?: string): Promise<RiskCard[]> {
    await delay(180)
    const list = memberId ? state.risks.filter(r => r.memberId === memberId) : state.risks
    return clone(list)
  },

  async getRiskDetail(memberId: string, ruleId: string): Promise<RiskCard> {
    await delay(140)
    const risk = state.risks.find(r => r.memberId === memberId && r.ruleId === ruleId)
    if (!risk) throw new Error('该风险提示不存在或未获授权')
    return clone(risk)
  },

  async acknowledgeRisk(memberId: string, ruleId: string): Promise<RiskCard> {
    await delay(140)
    const risk = state.risks.find(r => r.memberId === memberId && r.ruleId === ruleId)
    if (!risk) throw new Error('该风险提示不存在或未获授权')
    risk.acknowledged = true
    return clone(risk)
  },

  async submitTaskAction(
    taskId: string,
    action: TaskAction,
    payload: TaskActionPayload = {},
  ): Promise<CareTask> {
    await delay(200)
    const task = state.tasks.find(t => t.id === taskId)
    if (!task) throw new Error('任务不存在')
    if (task.status !== 'PENDING' && task.status !== 'DEFERRED') {
      throw new Error('该任务已处理，请刷新查看最新状态')
    }
    const now = new Date().toISOString()
    if (action === 'confirm') {
      task.status = 'CONFIRMED'
    } else if (action === 'defer') {
      const hours = payload.deferHours ?? 1
      task.status = 'DEFERRED'
      task.dueAt = new Date(Date.now() + hours * 3_600_000).toISOString()
    } else {
      const reason = payload.reason?.trim()
      if (!reason) throw new Error('跳过前请填写原因，便于家人了解情况')
      task.status = 'SKIPPED'
      task.skipReason = reason
    }
    task.lastActionAt = now
    return clone(task)
  },

  async checkImageQuality(file: File): Promise<QualityCheckResult> {
    await delay(420)
    // 演示规则：极小文件视为质量不足，保证质量门控路径可以被稳定演示与测试。
    if (file.size < 30_000) {
      return {
        decision: 'RETAKE',
        reasons: ['画面亮度不足或分辨率过低'],
        retakePrompts: ['请在光线充足的环境下重新拍摄', '让药盒正面尽量占满取景框'],
        metrics: [
          { label: '清晰度', value: '0.42', passed: false },
          { label: '亮度', value: '0.35', passed: false },
          { label: '反光', value: '正常', passed: true },
          { label: '朝向', value: '正常', passed: true },
        ],
        qualityReceipt: null,
      }
    }
    return {
      decision: 'PASS',
      reasons: [],
      retakePrompts: [],
      metrics: [
        { label: '清晰度', value: '0.86', passed: true },
        { label: '亮度', value: '0.74', passed: true },
        { label: '反光', value: '正常', passed: true },
        { label: '朝向', value: '正常', passed: true },
      ],
      qualityReceipt: `demo-receipt-${Date.now()}`,
    }
  },

  async getWeeklyTrend(memberId: string): Promise<TrendPoint[]> {
    await delay(160)
    // 前 6 天为稳定的虚构数据（按成员区分），今天与当前任务状态联动。
    const seed = memberId === 'm-li' ? [1, 1, 1, 0, 1, 1] : [2, 3, 2, 3, 1, 3]
    const totalSeed = memberId === 'm-li' ? [1, 1, 1, 1, 1, 1] : [3, 3, 3, 3, 3, 3]
    const points: TrendPoint[] = []
    for (let offset = 6; offset >= 1; offset -= 1) {
      const date = new Date()
      date.setDate(date.getDate() - offset)
      const index = 6 - offset
      points.push({
        label: WEEKDAY_LABELS[date.getDay()]!,
        done: seed[index] ?? 0,
        total: totalSeed[index] ?? 0,
      })
    }
    const todayTasks = state.tasks.filter(t => t.memberId === memberId)
    points.push({
      label: '今',
      done: todayTasks.filter(t => t.status === 'CONFIRMED').length,
      total: todayTasks.length,
    })
    return points
  },

  async recognizeMedicine(file: File): Promise<RecognitionCandidate> {
    await delay(700)
    const versions = {
      ocr: 'paddleocr-demo-0.1',
      检测: 'yolo11n-demo-0.1',
      主数据: 'demo-master-2026-08',
    }
    const branch = file.size % 3
    if (branch === 0) {
      return {
        status: 'MATCHED',
        fields: [
          { label: '药名', value: '布洛芬缓释胶囊（演示）', source: 'OCR', confidence: 0.93 },
          { label: '规格', value: '0.3g×20 粒', source: 'OCR', confidence: 0.88 },
          { label: '条码', value: '6901234567892', source: '条码', confidence: 0.99 },
          { label: '有效期', value: '2027-06', source: 'OCR', confidence: 0.81 },
          { label: '生产厂家', value: '示例制药（虚构）', source: '主数据', confidence: 0.95 },
        ],
        conflicts: [],
        versions,
        requiresHumanConfirmation: true,
        notice: '候选已与本地主数据匹配。高置信度也必须人工确认后才会写入健康档案。',
      }
    }
    if (branch === 1) {
      return {
        status: 'CONFLICT',
        fields: [
          { label: '药名（OCR）', value: '阿莫西林胶囊（演示）', source: 'OCR', confidence: 0.84 },
          { label: '药名（条码主数据）', value: '头孢克肟分散片（演示）', source: '条码', confidence: 0.97 },
          { label: '有效期', value: '2026-11', source: 'OCR', confidence: 0.78 },
        ],
        conflicts: ['OCR 识别的药名与条码对应的主数据药名不一致'],
        versions,
        requiresHumanConfirmation: true,
        notice: '多渠道证据出现冲突，系统不会自动入库，请转人工复核。',
      }
    }
    return {
      status: 'UNKNOWN',
      fields: [
        { label: '文字片段', value: '「…颗粒 12袋」', source: 'OCR', confidence: 0.52 },
      ],
      conflicts: [],
      versions,
      requiresHumanConfirmation: true,
      notice: '未能在本地药品主数据中找到匹配项。未知药品不会自动入库，可补拍更清晰的照片或转人工复核。',
    }
  },
}
