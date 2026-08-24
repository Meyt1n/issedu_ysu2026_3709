import { beforeEach, describe, expect, it } from 'vitest'

import { demoProvider, resetDemoData } from './demoProvider'

function fileOfSize(size: number): File {
  return new File([new Uint8Array(size)], 'sample.jpg', { type: 'image/jpeg' })
}

describe('演示数据 provider', () => {
  beforeEach(() => {
    resetDemoData()
  })

  it('提供三位虚构成员，且名称带演示标注', async () => {
    const members = await demoProvider.listMembers()
    expect(members.map(m => m.id)).toEqual(['m-wang', 'm-li', 'm-self'])
    expect(members[0]!.name).toContain('演示')
  })

  it('今日快照包含任务、风险与最近事件', async () => {
    const snapshot = await demoProvider.getTodaySnapshot('m-wang')
    expect(snapshot.tasks.length).toBe(3)
    expect(snapshot.risks.length).toBe(3)
    expect(snapshot.recentEvents.length).toBeGreaterThan(0)
  })

  it('环境行动卡仅在已授权的演示成员上显示虚构且可追溯的内容', async () => {
    const snapshot = await demoProvider.getTodaySnapshot('m-wang')

    expect(snapshot.environmentAction).toMatchObject({
      availability: 'AVAILABLE',
      card: {
        id: 'demo-environment-m-wang',
        source: '家庭服务器环境行动（演示）',
        ruleVersion: 'environment-rules-demo-1',
        configVersion: 'weather-adapter-demo-1',
      },
    })
    expect(snapshot.environmentAction.card?.action).toContain('演示')
    expect(snapshot.environmentAction.card?.generatedAt).toBeTruthy()
    expect(snapshot.environmentAction.card?.validUntil).toBeTruthy()
  })

  it('未获环境行动授权的演示成员不返回卡片', async () => {
    const snapshot = await demoProvider.getTodaySnapshot('m-li')

    expect(snapshot.environmentAction).toMatchObject({ availability: 'UNAUTHORIZED', card: null })
  })

  it('确认任务后状态变化，重复处理会被拒绝', async () => {
    const task = await demoProvider.submitTaskAction('t-am-med', 'confirm')
    expect(task.status).toBe('CONFIRMED')
    await expect(demoProvider.submitTaskAction('t-am-med', 'confirm')).rejects.toThrow('已处理')
  })

  it('跳过任务必须填写原因', async () => {
    await expect(demoProvider.submitTaskAction('t-bp', 'skip')).rejects.toThrow('原因')
    const task = await demoProvider.submitTaskAction('t-bp', 'skip', { reason: '今日在医院已测量' })
    expect(task.status).toBe('SKIPPED')
    expect(task.skipReason).toBe('今日在医院已测量')
  })

  it('延期任务会把提醒时间推后', async () => {
    const before = Date.now()
    const task = await demoProvider.submitTaskAction('t-pm-med', 'defer', { deferHours: 2 })
    expect(task.status).toBe('DEFERRED')
    expect(new Date(task.dueAt).getTime()).toBeGreaterThan(before)
  })

  it('风险详情保留证据和非医疗建议，并可记录知晓状态', async () => {
    const risk = await demoProvider.getRiskDetail('m-wang', 'rule-expiry-01')
    expect(risk.sourceEvents).toHaveLength(risk.sourceCount)
    expect(risk.explanation).toContain('确定性规则')
    expect(risk.suggestion).toContain('需要进一步确认')
    expect(risk.suggestion).not.toMatch(/停药|换药|剂量|诊断|处方/)

    const acknowledged = await demoProvider.acknowledgeRisk('m-wang', risk.ruleId)
    expect(acknowledged.acknowledged).toBe(true)
  })

  it('记录知晓后风险不再出现在今日快照', async () => {
    const acknowledged = await demoProvider.acknowledgeRisk('m-wang', 'rule-expiry-01')
    expect(acknowledged.acknowledged).toBe(true)
    const snapshot = await demoProvider.getTodaySnapshot('m-wang')
    expect(snapshot.risks.some(r => r.ruleId === 'rule-expiry-01')).toBe(false)
  })

  it('质量门控：过小文件要求重拍，正常文件通过并返回回执', async () => {
    const retake = await demoProvider.checkImageQuality(fileOfSize(1_000))
    expect(retake.decision).toBe('RETAKE')
    expect(retake.retakePrompts.length).toBeGreaterThan(0)
    expect(retake.qualityReceipt).toBeNull()

    const pass = await demoProvider.checkImageQuality(fileOfSize(60_000))
    expect(pass.decision).toBe('PASS')
    expect(pass.qualityReceipt).toBeTruthy()
  })

  it('识别四态可复现，且永远要求人工确认', async () => {
    const matched = await demoProvider.recognizeMedicine(fileOfSize(30_000), 'm-wang')
    const conflict = await demoProvider.recognizeMedicine(fileOfSize(30_001), 'm-wang')
    const unknown = await demoProvider.recognizeMedicine(fileOfSize(30_002), 'm-wang')

    expect(matched.status).toBe('MATCHED')
    expect(conflict.status).toBe('CONFLICT')
    expect(conflict.conflicts.length).toBeGreaterThan(0)
    expect(unknown.status).toBe('UNKNOWN')
    for (const candidate of [matched, conflict, unknown]) {
      expect(candidate.requiresHumanConfirmation).toBe(true)
    }
  })

  it('未授权字段返回 UNAUTHORIZED 而不是空数据', async () => {
    const detail = await demoProvider.getMemberDetail('m-li')
    expect(detail.medications).toBe('UNAUTHORIZED')
  })

  it('近 7 天趋势返回 7 项，今天与任务状态联动', async () => {
    const before = await demoProvider.getWeeklyTrend('m-wang')
    expect(before).toHaveLength(7)
    expect(before[6]!.label).toBe('今')
    expect(before[6]!.done).toBe(0)
    expect(before[6]!.total).toBe(3)

    await demoProvider.submitTaskAction('t-am-med', 'confirm')
    const after = await demoProvider.getWeeklyTrend('m-wang')
    expect(after[6]!.done).toBe(1)
  })

  it('确认、延期和跳过均写回今日快照', async () => {
    await demoProvider.submitTaskAction('t-am-med', 'confirm')
    await demoProvider.submitTaskAction('t-pm-med', 'defer', { deferHours: 1 })
    await demoProvider.submitTaskAction('t-bp', 'skip', { reason: '今日在医院已测量' })
    const snapshot = await demoProvider.getTodaySnapshot('m-wang')
    expect(Object.fromEntries(snapshot.tasks.map(task => [task.id, task.status]))).toMatchObject({
      't-am-med': 'CONFIRMED',
      't-pm-med': 'DEFERRED',
      't-bp': 'SKIPPED',
    })
  })
})

describe('演示模式视觉任务状态回查（MOB-132）', () => {
  it('按回查次数演示排队→处理→完成，文案明确标注演示且不冒充服务器', async () => {
    const first = await demoProvider.fetchVisionTaskStatus('demo-review-pending')
    const second = await demoProvider.fetchVisionTaskStatus('demo-review-pending')
    const third = await demoProvider.fetchVisionTaskStatus('demo-review-pending')

    expect(first.status).toBe('queued')
    expect(first.terminal).toBe(false)
    expect(second.status).toBe('running')
    expect(second.terminal).toBe(false)
    expect(third.status).toBe('succeeded')
    expect(third.terminal).toBe(true)
    expect(third.nextStep).toContain('演示')
    expect(third.nextStep).toContain('不会创建真实复核任务')
  })
})

describe('演示模式任务操作历史（MOB-135）', () => {
  beforeEach(async () => {
    resetDemoData()
    await demoProvider.submitTaskAction('t-am-med', 'confirm')
    await demoProvider.submitTaskAction('t-bp', 'skip', { reason: '外出（演示）' })
  })

  it('操作写入内存日志并按成员过滤、倒序展示回执', async () => {
    const wang = await demoProvider.listTaskActionHistory('m-wang')
    const li = await demoProvider.listTaskActionHistory('m-li')

    expect(wang).toHaveLength(2)
    expect(wang[0]).toMatchObject({ action: 'skip', actionLabel: '跳过', receipt: 'RECEIPTED', finalStatus: 'SKIPPED' })
    expect(wang[0]!.taskTitle).toContain('血压')
    expect(wang[1]).toMatchObject({ action: 'confirm', actionLabel: '确认', finalStatus: 'CONFIRMED' })
    expect(wang[1]!.note).toContain('演示')
    // 其他成员看不到别人的操作
    expect(li).toHaveLength(0)
  })

  it('恢复演示数据后历史清空', async () => {
    resetDemoData()
    expect(await demoProvider.listTaskActionHistory('m-wang')).toHaveLength(0)
  })
})
