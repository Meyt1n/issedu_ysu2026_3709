import type { DigitalTwinNode, DigitalTwinResponse } from '../api/types'
import type { GalaxyCluster, GalaxyClusterId, GalaxyOrbitNode, GalaxySnapshotDelta } from './galaxy-types'

export const GALAXY_CLUSTERS: GalaxyCluster[] = [
  { id: 'family', label: '用户 / 家庭', shortLabel: '用户 / 家庭', caption: '成员与照护关系', color: '#5d9a76', soft: '#e4f0e6', icon: 'members', x: 24, y: 27 },
  { id: 'condition', label: '疾病 / 病史', shortLabel: '疾病 / 病史', caption: '病史、症状与就诊', color: '#cf7d48', soft: '#f7e5d8', icon: 'heart', x: 76, y: 27 },
  { id: 'medicine', label: '药品 / 用药', shortLabel: '药品 / 用药', caption: '药品、剂量与计划', color: '#5f8fc6', soft: '#e0ebf7', icon: 'pill', x: 20, y: 70 },
  { id: 'conversation', label: '聊天记忆', shortLabel: '聊天记忆', caption: '问题、反馈与意图', color: '#8b6abb', soft: '#ece5f6', icon: 'assistant', x: 80, y: 70 },
  { id: 'rag', label: 'RAG 知识块', shortLabel: 'RAG 知识块', caption: '召回证据与来源', color: '#459791', soft: '#dcefed', icon: 'cloud', x: 50, y: 84 },
  { id: 'insight', label: '风险与建议', shortLabel: '风险与建议', caption: '过敏、风险与提醒', color: '#c99a37', soft: '#f7edcf', icon: 'alert', x: 50, y: 15 },
]

export const GALAXY_GUIDES: Record<GalaxyClusterId, string[]> = {
  family: ['家庭成员', '年龄 / 性别', '家庭关系', '基础档案', '照护者'],
  condition: ['慢病', '既往病史', '症状表现', '就诊记录', '关注疾病'],
  medicine: ['当前在用药', '通用名 / 成分', '用法用量', '药盒识别', '用药计划'],
  conversation: ['最近提问', '对话片段', '生活反馈', '关注话题', '用户表达'],
  rag: ['chunk', 'term_vector', 'top-k', '检索命中', '来源文档', '召回证据'],
  insight: ['风险提示', '触发规则', '用药风险', '生活建议', '异常提示'],
}

export function clusterForNode(node: DigitalTwinNode): GalaxyClusterId {
  if (node.kind === 'memory' || node.category === 'chat') return 'conversation'
  if (node.kind === 'knowledge' || node.category === 'knowledge') return 'rag'
  if (node.category === 'disease') return 'condition'
  if (node.category === 'medication' || node.category === 'plan') return 'medicine'
  if (node.category === 'allergy') return 'insight'
  return 'family'
}

export function visibleTwinNodes(twin: DigitalTwinResponse | null, showUnconfirmed = true): DigitalTwinNode[] {
  return (twin?.nodes ?? []).filter(node => node.kind !== 'household' && node.status !== 'REJECTED' && (showUnconfirmed || node.status !== 'UNCONFIRMED'))
}

export function countByCluster(nodes: DigitalTwinNode[]): Record<GalaxyClusterId, number> {
  const result: Record<GalaxyClusterId, number> = { family: 0, condition: 0, medicine: 0, conversation: 0, rag: 0, insight: 0 }
  nodes.forEach(node => { result[clusterForNode(node)] += 1 })
  return result
}

export function snapshotDelta(previous: DigitalTwinResponse | null, next: DigitalTwinResponse): GalaxySnapshotDelta {
  const previousIds = new Set((previous?.nodes ?? []).map(node => node.id))
  const added = next.nodes.filter(node => !previousIds.has(node.id) && node.kind !== 'household')
  const counts: Record<GalaxyClusterId, number> = { family: 0, condition: 0, medicine: 0, conversation: 0, rag: 0, insight: 0 }
  added.forEach(node => { counts[clusterForNode(node)] += 1 })
  return { addedNodeIds: new Set(added.map(node => node.id)), counts }
}

function displayLabel(node: DigitalTwinNode, index: number): string {
  if (node.kind === 'knowledge') return node.detail?.trim() || `${node.label} · 分块 ${index + 1}`
  return node.label
}

export function buildGlobalOrbitNodes(nodes: DigitalTwinNode[], cluster: GalaxyCluster): GalaxyOrbitNode[] {
  const seen = new Set<string>()
  const actual = nodes.filter(node => clusterForNode(node) === cluster.id).filter(node => {
    const key = node.label.trim().toLocaleLowerCase()
    if (seen.has(key)) return false
    seen.add(key)
    return true
  }).slice(0, 4)
  const guides = GALAXY_GUIDES[cluster.id].filter(label => !seen.has(label.toLocaleLowerCase())).slice(0, Math.max(0, 4 - actual.length))
  const entries = [...actual.map((node, index) => ({ id: node.id, label: displayLabel(node, index), node, guide: false })), ...guides.map((label, index) => ({ id: `guide:${cluster.id}:${index}`, label, node: null, guide: true }))]
  return entries.map((entry, index) => {
    const angle = (-145 + index * (290 / Math.max(entries.length - 1, 1))) * Math.PI / 180
    return { ...entry, clusterId: cluster.id, x: cluster.x + Math.cos(angle) * 10.5, y: cluster.y + Math.sin(angle) * 8, z: index % 2 ? .5 : -.15, ring: 1 }
  })
}

export function buildLocalOrbitNodes(nodes: DigitalTwinNode[], clusterId: GalaxyClusterId): GalaxyOrbitNode[] {
  const actual = nodes.filter(node => clusterForNode(node) === clusterId).slice(0, 18)
  const guides = actual.length ? [] : GALAXY_GUIDES[clusterId].map((label, index) => ({ id: `guide:${clusterId}:${index}`, label, node: null, guide: true }))
  const entries = actual.length ? actual.map((node, index) => ({ id: node.id, label: displayLabel(node, index), node, guide: false })) : guides
  return entries.map((entry, index) => {
    const ring = index < 7 ? 1 : 2
    const ringIndex = ring === 1 ? index : index - 7
    const ringCount = ring === 1 ? Math.min(entries.length, 7) : entries.length - 7
    const angle = (-Math.PI / 2) + (ringIndex / Math.max(ringCount, 1)) * Math.PI * 2
    const radiusX = ring === 1 ? 25 : 41
    const radiusY = ring === 1 ? 22 : 36
    return { ...entry, clusterId, x: 50 + Math.cos(angle) * radiusX, y: 52 + Math.sin(angle) * radiusY, z: ring === 1 ? .55 : -.15, ring }
  })
}
