import { describe, expect, it } from 'vitest'

import {
  buildOnboardingChecklist,
  SERVER_ADDRESS_HINT,
  stepStatusLabel,
  type OnboardingChecklistInput,
} from './onboardingSteps'

function input(patch: Partial<OnboardingChecklistInput> = {}): OnboardingChecklistInput {
  return {
    liveMode: true,
    serverBaseUrl: '',
    serverAddressError: '',
    householdCount: 0,
    selectedHouseholdId: '',
    selectedHouseholdName: '',
    connectionState: 'idle',
    connectionError: '',
    capabilityAvailableCount: null,
    ...patch,
  }
}

describe('联机三步清单（MOB-164）', () => {
  it('全新安装时三步都未完成，只高亮第一步', () => {
    const { steps, complete, summary } = buildOnboardingChecklist(input())

    expect(steps.map(step => step.id)).toEqual(['server', 'household', 'connection'])
    expect(steps.every(step => step.status !== 'done')).toBe(true)
    expect(steps.filter(step => step.status === 'current')).toHaveLength(1)
    expect(steps[0]!.status).toBe('current')
    expect(steps[0]!.nextAction).not.toBe('')
    expect(steps[0]!.detail).toContain(SERVER_ADDRESS_HINT)
    expect(complete).toBe(false)
    expect(summary).toBe('')
  })

  it('地址不合法时第一步给出原因与允许形式，且不进入后续步骤', () => {
    const { steps } = buildOnboardingChecklist(
      input({ serverAddressError: '服务器地址不能包含账号或密码。' }),
    )

    expect(steps[0]!.status).toBe('blocked')
    expect(steps[0]!.detail).toContain('不能包含账号或密码')
    expect(steps[0]!.detail).toContain('http://192.168.1.10:8000')
    expect(steps[1]!.status).toBe('todo')
    expect(steps[2]!.status).toBe('todo')
  })

  it('可访问多个家庭且未选择时，第二步要求显式选择并说明不会发请求', () => {
    const { steps } = buildOnboardingChecklist(
      input({ serverBaseUrl: 'http://192.168.1.10:8000', householdCount: 3 }),
    )

    expect(steps[0]!.status).toBe('done')
    expect(steps[1]!.status).toBe('current')
    expect(steps[1]!.detail).toContain('需要显式选择')
    expect(steps[1]!.detail).toContain('不会发起任何成员或事件请求')
    // 同一时刻只高亮一步，第三步不抢焦点。
    expect(steps[2]!.status).toBe('todo')
  })

  it('只有一个家庭时说明自检后会自动选定', () => {
    const { steps } = buildOnboardingChecklist(
      input({ serverBaseUrl: 'http://192.168.1.10:8000', householdCount: 1 }),
    )

    expect(steps[1]!.status).toBe('current')
    expect(steps[1]!.detail).toContain('自动选定')
  })

  it('自检失败时第三步暴露原因并给出下一步', () => {
    const { steps, complete } = buildOnboardingChecklist(
      input({
        serverBaseUrl: 'http://192.168.1.10:8000',
        householdCount: 1,
        selectedHouseholdId: 'hh-1',
        selectedHouseholdName: '王家',
        connectionState: 'failed',
        connectionError: '无法连接家庭服务器，请确认电脑后端已启动。',
      }),
    )

    expect(steps[2]!.status).toBe('blocked')
    expect(steps[2]!.detail).toContain('确认电脑后端已启动')
    expect(steps[2]!.nextAction).toContain('测试连接')
    expect(complete).toBe(false)
  })

  it('三步齐全后给出数据来源与能力快照摘要', () => {
    const { steps, complete, summary } = buildOnboardingChecklist(
      input({
        serverBaseUrl: 'http://192.168.1.10:8000',
        householdCount: 1,
        selectedHouseholdId: 'hh-1',
        selectedHouseholdName: '王家',
        connectionState: 'ok',
        capabilityAvailableCount: 7,
      }),
    )

    expect(steps.every(step => step.status === 'done')).toBe(true)
    expect(steps.every(step => step.nextAction === '')).toBe(true)
    expect(complete).toBe(true)
    expect(summary).toContain('家庭服务器（联机）')
    expect(summary).toContain('7 项可用')
  })

  it('能力探测未完成时不谎称能力可用', () => {
    const { steps, summary } = buildOnboardingChecklist(
      input({
        serverBaseUrl: 'http://192.168.1.10:8000',
        householdCount: 1,
        selectedHouseholdId: 'hh-1',
        connectionState: 'ok',
        capabilityAvailableCount: null,
      }),
    )

    expect(steps[2]!.status).toBe('done')
    expect(steps[2]!.detail).toContain('能力探测未完成')
    expect(steps[2]!.detail).toContain('按不可用处理')
    expect(summary).toContain('未完成探测')
  })

  it('自检进行中不催用户重复点击', () => {
    const { steps } = buildOnboardingChecklist(
      input({
        serverBaseUrl: 'http://192.168.1.10:8000',
        selectedHouseholdId: 'hh-1',
        connectionState: 'testing',
      }),
    )

    expect(steps[2]!.status).toBe('current')
    expect(steps[2]!.nextAction).toBe('')
  })

  it('每种状态都有可朗读的中文标签', () => {
    expect(stepStatusLabel('done')).toBe('已完成')
    expect(stepStatusLabel('blocked')).toBe('需要处理')
    expect(stepStatusLabel('current')).toBe('当前要做')
    expect(stepStatusLabel('todo')).toBe('未开始')
  })
})
