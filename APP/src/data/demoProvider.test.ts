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
})
