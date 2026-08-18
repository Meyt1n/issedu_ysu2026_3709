/**
 * 移动端—网页端联动验收脚本。
 *
 * 脚本只使用仓库已有的虚构「演示家庭（联调）」数据，不创建真实健康信息。
 * 先运行 seed:live，再运行本脚本：
 *   npm run seed:live -- --base http://127.0.0.1:18800
 *   npm run verify:linkage -- --base http://127.0.0.1:18800
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
const MEMBER_NAME = '王秀兰（演示）'
const ACCESS_PURPOSE = 'family-care'

async function api(path, { method = 'GET', actor = OWNER, body, idempotencyKey } = {}) {
  const headers = {
    Accept: 'application/json',
    'X-Actor-Id': actor,
    'X-Access-Purpose': ACCESS_PURPOSE,
  }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (idempotencyKey) headers['Idempotency-Key'] = idempotencyKey
  const response = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const text = await response.text()
  let data = null
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      data = { detail: text }
    }
  }
  return { response, data, text }
}

function requireOk(result, description) {
  if (!result.response.ok) {
    throw new Error(`${description} 失败：HTTP ${result.response.status} ${result.text.slice(0, 240)}`)
  }
  return result.data
}

function require(condition, message) {
  if (!condition) throw new Error(`联动验收失败：${message}`)
}

async function main() {
  const health = requireOk(await api('/health'), '后端健康检查')
  console.log(`后端连接成功：${health.service} v${health.version}`)

  const households = requireOk(await api('/api/v1/households'), '读取演示家庭')
  const household = households.find(item => item.name === HOUSEHOLD_NAME)
  require(household, `未找到 ${HOUSEHOLD_NAME}，请先运行 npm run seed:live`)

  const members = requireOk(
    await api(`/api/v1/households/${household.id}/members`),
    '读取演示成员',
  )
  const member = members.find(item => item.display_name === MEMBER_NAME)
  require(member, `未找到 ${MEMBER_NAME}，请先运行 npm run seed:live`)

  // 1) 移动端写入的虚构事件可被网页端（owner）读取。
  const ownerTimeline = requireOk(
    await api(`/api/v1/households/${household.id}/members/${member.id}/timeline`),
    '网页端读取成员时间线',
  )
  const seededEvent = ownerTimeline.find(
    event => event.event_type === 'allergy_added' && event.payload?.allergy === '阿司匹林',
  )
  require(seededEvent, '网页端未看到移动端写入的演示过敏事件')
  console.log(`✓ 移动端写入事件已在网页端可见：${seededEvent.id}`)

  const plan = ownerTimeline.find(
    event => event.event_type === 'plan_created' && event.payload?.drug === '苯磺酸氨氯地平片（演示）',
  )
  require(plan, '未找到可用于复核联动的演示计划')

  // 2) 未授予 WRITE_EVENTS 的照护者不能代替网页端提交复核结果。
  const denied = await api(
    `/api/v1/households/${household.id}/members/${member.id}/plans/confirm?plan_event_id=${encodeURIComponent(plan.id)}`,
    { method: 'POST', actor: CAREGIVER },
  )
  require(denied.response.status === 404, `越权复核应返回 404，实际为 HTTP ${denied.response.status}`)
  console.log('✓ 授权边界生效：只读照护者不能提交网页复核结果')

  // 3) owner 在网页端确认计划后，移动端以照护者身份重新读取即可看到结果。
  const confirmed = requireOk(
    await api(
      `/api/v1/households/${household.id}/members/${member.id}/plans/confirm?plan_event_id=${encodeURIComponent(plan.id)}`,
      { method: 'POST', actor: OWNER, idempotencyKey: `confirm:${plan.id}` },
    ),
    '网页端确认演示计划',
  )
  require(confirmed.event_type === 'plan_confirmed', '网页复核未产生 plan_confirmed 事件')

  const mobileTimeline = requireOk(
    await api(`/api/v1/households/${household.id}/members/${member.id}/timeline`, { actor: CAREGIVER }),
    '移动端重新读取成员时间线',
  )
  const reflected = mobileTimeline.find(
    event => event.id === confirmed.id ||
      (event.event_type === 'plan_confirmed' && event.payload?.plan_event_id === plan.id),
  )
  require(reflected, '移动端未看到网页复核结果')
  console.log(`✓ 网页复核结果已按授权回写移动端视图：${reflected.id}`)

  console.log('\n联动验收通过：虚构造数、网页可见性、授权复核和移动端回读均已验证。')
}

main().catch(error => {
  console.error(String(error))
  process.exit(1)
})
