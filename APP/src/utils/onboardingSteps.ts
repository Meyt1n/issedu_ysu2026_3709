/**
 * MOB-164：「我的」页的联机三步清单。
 * 只根据已有会话状态与探测结果推导展示文案，不做任何授权判定，也不发请求。
 */
export type OnboardingStepStatus = 'todo' | 'current' | 'blocked' | 'done'

export type OnboardingStepId = 'server' | 'household' | 'connection'

export interface OnboardingStep {
  id: OnboardingStepId
  title: string
  status: OnboardingStepStatus
  /** 当前状态说明，或失败的具体原因。 */
  detail: string
  /** 下一步该做什么；已完成或尚未轮到时为空串。 */
  nextAction: string
}

export interface OnboardingChecklist {
  steps: OnboardingStep[]
  complete: boolean
  /** 三步齐全后的数据来源与能力快照摘要。 */
  summary: string
}

export interface OnboardingChecklistInput {
  liveMode: boolean
  serverBaseUrl: string
  /** 地址校验失败时的具体原因（来自 MOB-140 的校验器）。 */
  serverAddressError: string
  householdCount: number
  selectedHouseholdId: string
  selectedHouseholdName: string
  connectionState: 'idle' | 'testing' | 'ok' | 'failed'
  /** 自检失败时的原因文案；不得包含服务端内部细节。 */
  connectionError: string
  /** 已探测到的可用能力数量；null 表示尚未完成能力探测。 */
  capabilityAvailableCount: number | null
}

/** 允许的地址形式提示，与 `validateServerBaseUrl()` 的规则保持一致。 */
export const SERVER_ADDRESS_HINT =
  '允许的形式：http://局域网IP:端口（例如 http://192.168.1.10:8000）或 https://域名；不能带账号密码、查询参数或 # 片段。'

function serverStep(input: OnboardingChecklistInput): OnboardingStep {
  const base = { id: 'server' as const, title: '填写家庭服务器地址' }
  if (input.serverAddressError) {
    return {
      ...base,
      status: 'blocked',
      detail: `${input.serverAddressError}${SERVER_ADDRESS_HINT}`,
      nextAction: '修正地址后重新保存；地址不通过校验时不会进入后面两步。',
    }
  }
  if (!input.serverBaseUrl.trim()) {
    return {
      ...base,
      status: 'current',
      detail: `还没有填写家庭服务器地址。${SERVER_ADDRESS_HINT}`,
      nextAction: '在下面的「家庭服务器地址」里填入电脑的局域网地址并保存。',
    }
  }
  return {
    ...base,
    status: 'done',
    detail: `已保存：${input.serverBaseUrl.trim()}`,
    nextAction: '',
  }
}

function householdStep(input: OnboardingChecklistInput, serverDone: boolean): OnboardingStep {
  const base = { id: 'household' as const, title: '选择家庭' }
  if (!serverDone) {
    return { ...base, status: 'todo', detail: '需要先填好服务器地址。', nextAction: '' }
  }
  if (input.selectedHouseholdId.trim()) {
    const name = input.selectedHouseholdName.trim()
    return {
      ...base,
      status: 'done',
      detail: name ? `已选择「${name}」。` : '已选择一个家庭。',
      nextAction: '',
    }
  }
  if (input.householdCount > 1) {
    return {
      ...base,
      status: 'current',
      detail: '当前身份可访问多个家庭，需要显式选择一个。在选择之前不会发起任何成员或事件请求。',
      nextAction: '在下面的家庭列表里选择一个家庭。',
    }
  }
  if (input.householdCount === 1) {
    return {
      ...base,
      status: 'current',
      detail: '只有一个可访问的家庭，做一次连接自检后会自动选定。',
      nextAction: '点「测试连接」，完成后这一步会自动打勾。',
    }
  }
  return {
    ...base,
    status: 'todo',
    detail: '还没有读到可访问的家庭列表；连接自检成功后会自动读取。',
    nextAction: '',
  }
}

function connectionStep(input: OnboardingChecklistInput, serverDone: boolean): OnboardingStep {
  const base = { id: 'connection' as const, title: '测试连接' }
  if (!serverDone) {
    return { ...base, status: 'todo', detail: '需要先填好服务器地址。', nextAction: '' }
  }
  if (input.connectionState === 'testing') {
    return { ...base, status: 'current', detail: '正在自检连接与能力…', nextAction: '' }
  }
  if (input.connectionState === 'failed') {
    return {
      ...base,
      status: 'blocked',
      detail: input.connectionError || '连接自检没有通过。',
      nextAction: '按上面的提示处理后再点「测试连接」。',
    }
  }
  if (input.connectionState === 'ok') {
    return {
      ...base,
      status: 'done',
      detail:
        input.capabilityAvailableCount === null
          ? '连接可用，但能力探测未完成；未探测到的能力一律按不可用处理。'
          : `连接可用，已探测到 ${input.capabilityAvailableCount} 项可用能力。`,
      nextAction: '',
    }
  }
  return {
    ...base,
    status: 'current',
    detail: '还没有做过连接自检。',
    nextAction: '点「测试连接」做一次自检。',
  }
}

/** 步骤状态的朗读文案；读屏器按 标题 → 状态 → 说明 → 下一步 的顺序依次读到。 */
export function stepStatusLabel(status: OnboardingStepStatus): string {
  if (status === 'done') return '已完成'
  if (status === 'blocked') return '需要处理'
  if (status === 'current') return '当前要做'
  return '未开始'
}

export function buildOnboardingChecklist(
  input: OnboardingChecklistInput,
): OnboardingChecklist {
  const server = serverStep(input)
  const serverDone = server.status === 'done'
  const household = householdStep(input, serverDone)
  const connection = connectionStep(input, serverDone)
  const steps = [server, household, connection]

  // 只高亮一步：优先暴露被卡住的那步，否则高亮第一个未完成的步骤。
  const firstBlocked = steps.findIndex(step => step.status === 'blocked')
  const highlight = firstBlocked >= 0 ? firstBlocked : steps.findIndex(step => step.status !== 'done')
  for (const [index, step] of steps.entries()) {
    if (step.status === 'current' && index !== highlight) step.status = 'todo'
  }

  const complete = steps.every(step => step.status === 'done')
  const sourceLabel = input.liveMode ? '家庭服务器（联机）' : '本机演示数据'
  const capabilityLabel =
    input.capabilityAvailableCount === null
      ? '能力快照：未完成探测'
      : `能力快照：${input.capabilityAvailableCount} 项可用`
  return {
    steps,
    complete,
    summary: complete ? `当前数据来源：${sourceLabel} · ${capabilityLabel}` : '',
  }
}
