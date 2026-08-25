/**
 * 联调造数脚本：向主仓库 FastAPI 写入一套【虚构】演示家庭数据，
 * 用于移动端（联机模式）与网页端互通验证。
 *
 * 用法：node scripts/seed-live-demo.mjs [--base http://127.0.0.1:8000] [--actor dev-wang]
 *
 * 事件语义与主仓库 app/projection.py 对齐：
 *   disease_added / allergy_added / medication_added / plan_created（小写）。
 * 数据均为教学演示编造，病史—过敏—药品—计划故意互相关联，禁止写入真实健康信息。
 */

const args = process.argv.slice(2)
function argOf(flag, fallback) {
  const index = args.indexOf(flag)
  return index >= 0 && args[index + 1] ? args[index + 1] : fallback
}

const BASE = argOf('--base', 'http://127.0.0.1:18800')
const OWNER = argOf('--actor', 'dev-wang')
const CAREGIVER = argOf('--caregiver', 'dev-uncle')
const HOUSEHOLD_NAME = '演示家庭（联调）'

async function api(path, { method = 'GET', body, actor = OWNER, purpose = 'family-care' } = {}) {
  const response = await fetch(`${BASE}${path}`, {
    method,
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
      'X-Actor-Id': actor,
      'X-Access-Purpose': purpose,
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const text = await response.text()
  const data = text ? JSON.parse(text) : null
  if (!response.ok) {
    throw new Error(`${method} ${path} -> HTTP ${response.status}: ${text.slice(0, 300)}`)
  }
  return data
}

async function main() {
  const health = await api('/health')
  console.log(`后端连接成功：${health.service} v${health.version}`)

  // 幂等：同名家庭已存在则复用成员，仍尝试写入健康事件（idempotency_key 去重）。
  const households = await api('/api/v1/households')
  let household = households.find(h => h.name === HOUSEHOLD_NAME)
  let grandma
  let grandpa
  if (household) {
    console.log(`家庭已存在，复用：${household.id}`)
    const members = await api(`/api/v1/households/${household.id}/members`)
    grandma = members.find(m => String(m.display_name || '').includes('王秀兰'))
    grandpa = members.find(m => String(m.display_name || '').includes('李建国'))
    if (!grandma || !grandpa) {
      printSummary(household, members)
      throw new Error('演示家庭已存在但缺少王秀兰/李建国成员，请清理后重跑或手工补成员。')
    }
  } else {
    household = await api('/api/v1/households', { method: 'POST', body: { name: HOUSEHOLD_NAME } })
    console.log(`已创建家庭：${household.id}（owner=${OWNER}）`)

    async function addMember(display_name, role, actor_id = null) {
      const member = await api(`/api/v1/households/${household.id}/members`, {
        method: 'POST',
        body: { display_name, role, actor_id },
      })
      console.log(`  成员：${display_name} -> ${member.id}`)
      return member
    }

    grandma = await addMember('王秀兰（演示）', 'DEPENDENT')
    grandpa = await addMember('李建国（演示）', 'DEPENDENT')
    await addMember('王芳（演示·我）', 'SELF', OWNER)
  }

  async function addEvent(memberId, event_type, payload, key) {
    const event = await api(`/api/v1/households/${household.id}/events`, {
      method: 'POST',
      body: {
        member_id: memberId,
        event_type,
        source: 'MANUAL',
        confirmation_status: 'CONFIRMED',
        payload,
        idempotency_key: key,
      },
    })
    console.log(`  事件：${event_type} -> ${event.id}`)
    return event
  }

  // 王秀兰：病史 → 过敏 → 冲突药/治疗药 → 计划（全部虚构演示）
  await addEvent(
    grandma.id,
    'disease_added',
    { disease: '高血压（演示）', note: '教学病史，非诊断' },
    'seed-disease-1',
  )
  await addEvent(
    grandma.id,
    'disease_added',
    { disease: '2型糖尿病（演示）', note: '教学病史，非诊断' },
    'seed-disease-2',
  )
  await addEvent(grandma.id, 'allergy_added', { allergy: '阿司匹林' }, 'seed-allergy-1')
  await addEvent(
    grandma.id,
    'medication_added',
    {
      drug: '阿司匹林肠溶片（演示）',
      spec: '100mg×30片',
      schedule: '每日 1 次，早餐前（演示，不给剂量建议）',
      expiry_date: '2026-08-01',
      stock: 12,
      ingredient: '阿司匹林',
      note: '故意与过敏史对齐，仅用于冲突规则演示',
    },
    'seed-med-1',
  )
  await addEvent(
    grandma.id,
    'medication_added',
    {
      drug: '苯磺酸氨氯地平片（演示）',
      spec: '5mg×28片',
      schedule: '每日 1 次，早餐后',
      expiry_date: '2027-03-01',
      stock: 4,
      ingredient: '氨氯地平',
      related_disease: '高血压（演示）',
    },
    'seed-med-2',
  )
  await addEvent(
    grandma.id,
    'medication_added',
    {
      drug: '二甲双胍缓释片（演示）',
      spec: '0.5g×30片',
      schedule: '晚餐后（演示）',
      expiry_date: '2027-09-01',
      stock: 20,
      ingredient: '二甲双胍',
      related_disease: '2型糖尿病（演示）',
    },
    'seed-med-metformin',
  )
  const plan1 = await addEvent(
    grandma.id,
    'plan_created',
    {
      drug: '苯磺酸氨氯地平片（演示）',
      schedule: '每日早餐后服用 1 片（演示）',
      due_time: '08:00',
      level: 'GENERAL',
      related_disease: '高血压（演示）',
    },
    'seed-plan-1',
  )
  const plan2 = await addEvent(
    grandma.id,
    'plan_created',
    {
      drug: '二甲双胍缓释片（演示）',
      schedule: '晚餐后服用 1 片（演示）',
      due_time: '19:00',
      level: 'HIGH',
      related_disease: '2型糖尿病（演示）',
    },
    'seed-plan-2',
  )

  // 李建国：血脂/冠心病病史 + 青霉素过敏冲突 + 他汀计划
  await addEvent(
    grandpa.id,
    'disease_added',
    { disease: '高脂血症（演示）', note: '教学病史，非诊断' },
    'seed-disease-3',
  )
  await addEvent(
    grandpa.id,
    'disease_added',
    { disease: '冠心病（演示）', note: '教学病史，非诊断' },
    'seed-disease-4',
  )
  await addEvent(grandpa.id, 'allergy_added', { allergy: '青霉素' }, 'seed-allergy-2')
  await addEvent(
    grandpa.id,
    'medication_added',
    {
      drug: '阿托伐他汀钙片（演示）',
      spec: '20mg×28片',
      schedule: '每晚 1 次',
      expiry_date: '2027-05-01',
      stock: 18,
      ingredient: '阿托伐他汀',
      related_disease: '高脂血症（演示）',
    },
    'seed-med-3',
  )
  await addEvent(
    grandpa.id,
    'medication_added',
    {
      drug: '青霉素V钾片（演示）',
      spec: '250mg×24片',
      schedule: '待与医嘱核对（演示）',
      expiry_date: '2026-03-01',
      stock: 10,
      ingredient: '青霉素',
      note: '故意与过敏史对齐，仅用于冲突规则演示',
    },
    'seed-med-4',
  )
  await addEvent(
    grandpa.id,
    'plan_created',
    {
      drug: '阿托伐他汀钙片（演示）',
      schedule: '每晚睡前服用 1 片（演示）',
      due_time: '21:00',
      level: 'GENERAL',
      related_disease: '高脂血症（演示）',
    },
    'seed-plan-3',
  )

  // 照护者授权：dev-uncle 只能读 王秀兰 的已确认健康事件（30 天）
  const validUntil = new Date(Date.now() + 30 * 24 * 3600 * 1000).toISOString()
  const auth = await api(`/api/v1/households/${household.id}/authorizations`, {
    method: 'POST',
    body: {
      member_id: grandma.id,
      grantee_actor_id: CAREGIVER,
      data_fields: ['health_events'],
      actions: ['READ_EVENTS'],
      purpose: 'family-care',
      valid_until: validUntil,
    },
  })
  console.log(`  授权：${CAREGIVER} 可读 王秀兰 health_events -> ${auth.id}`)

  const members = await api(`/api/v1/households/${household.id}/members`)
  printSummary(household, members, { plan1: plan1.id, plan2: plan2.id })
}

function printSummary(household, members, extra = {}) {
  console.log('\n===== 联调信息 =====')
  console.log(`家庭 ID：${household.id}`)
  for (const member of members) console.log(`成员：${member.display_name} = ${member.id}`)
  if (extra.plan1) console.log(`计划事件：早间计划=${extra.plan1} 晚间计划=${extra.plan2}`)
  console.log(`Owner 身份：${OWNER}；照护者身份：${CAREGIVER}（仅读王秀兰事件）`)
  console.log('移动端联机模式设置：服务器地址填后端地址（或走 dev 代理留空），身份填上述 Actor。')
}

main().catch(error => {
  console.error(String(error))
  process.exit(1)
})
