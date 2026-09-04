<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import type { DigitalTwinNode, DigitalTwinResponse } from '../../api/types'
import { clusterForNode, GALAXY_CLUSTERS, visibleTwinNodes } from '../../digital-twin/galaxy-layout'
import type { GalaxyClusterId } from '../../digital-twin/galaxy-types'
import { formatDateTime } from '../../ui/labels'
import AppIcon from '../AppIcon.vue'

const props = defineProps<{ twin: DigitalTwinResponse; node: DigitalTwinNode | null; focusCluster: GalaxyClusterId | null; deltaCount: number; actionBusy: boolean }>()
const emit = defineEmits<{ confirm: []; reject: [] }>()
const expanded = ref(false)
watch(() => props.node?.id, () => { expanded.value = false })

const cluster = computed(() => GALAXY_CLUSTERS.find(item => item.id === (props.node ? clusterForNode(props.node) : props.focusCluster)) ?? null)
const selectedEdges = computed(() => props.node ? props.twin.edges.filter(edge => edge.source === props.node!.id || edge.target === props.node!.id).sort((a, b) => b.weight - a.weight) : [])
const nodeMap = computed(() => new Map(props.twin.nodes.map(node => [node.id, node])))
const relatedNodes = computed(() => selectedEdges.value.map(edge => nodeMap.value.get(edge.source === props.node?.id ? edge.target : edge.source)).filter((node): node is DigitalTwinNode => Boolean(node)))
const evidence = computed(() => {
  if (!props.node) return []
  const result = [props.node, ...relatedNodes.value].filter(node => node.status !== 'REJECTED')
  const used = new Set<string>()
  return result.filter(node => !used.has(node.source_id) && Boolean(used.add(node.source_id))).slice(0, 28)
})
const similarity = computed(() => selectedEdges.value.filter(edge => edge.relation.includes('term_vector') || edge.relation.includes('↔')).reduce<number | null>((best, edge) => Math.max(best ?? 0, edge.weight), null))
const categoryCount = computed(() => props.focusCluster ? visibleTwinNodes(props.twin).filter(node => clusterForNode(node) === props.focusCluster).length : props.twin.nodes.filter(node => node.kind !== 'household' && node.status !== 'REJECTED').length)
const relatedMembers = computed(() => [...new Set([props.node?.member_name, ...relatedNodes.value.map(node => node.member_name), ...relatedNodes.value.filter(node => node.kind === 'member').map(node => node.label)].filter(Boolean))] as string[])
const sourceCounts = computed(() => {
  const labels: Record<string, string> = { MEMBER: '成员档案', HEALTH_EVENT: '健康事件', CHAT: '聊天记录', KNOWLEDGE: 'RAG 片段', HOUSEHOLD: '家庭空间' }
  return Object.entries(labels).map(([kind, label]) => ({ label, count: evidence.value.filter(node => node.source_kind === kind).length })).filter(item => item.count)
})
const isPendingMemory = computed(() => props.node?.kind === 'memory' && props.node.status === 'UNCONFIRMED')

function sourceLabel(node: DigitalTwinNode): string {
  return ({ CHAT: '聊天记录 · 自动提取', KNOWLEDGE: '已审核本地知识库', HEALTH_EVENT: '已确认健康事件', MEMBER: '成员档案', HOUSEHOLD: '家庭空间' } as Record<string, string>)[node.source_kind] ?? '家庭记录'
}
function statusLabel(node: DigitalTwinNode): string { return node.status === 'UNCONFIRMED' ? '未确认聊天线索' : node.status === 'CONFIRMED' ? '已确认' : '已拒绝' }
function excerpt(node: DigitalTwinNode): string { return node.source_excerpt?.trim() || node.detail?.trim() || node.label }
function truncate(value: string, max = 76): string { return value.length > max ? `${value.slice(0, max)}…` : value }
</script>

<template>
  <aside class="detail-card card" aria-live="polite">
    <template v-if="node">
      <header><div><span>语义节点详情</span><h3>{{ node.label }}</h3></div><b :style="{ '--tone': cluster?.color }"><i />{{ cluster?.shortLabel }}</b></header>
      <p class="status"><AppIcon :name="node.status === 'UNCONFIRMED' ? 'clock' : 'check'" :size="13" /> {{ statusLabel(node) }}</p>
      <dl><div><dt>节点类型</dt><dd>{{ node.kind }} / {{ node.category }}</dd></div><div><dt>来源</dt><dd>{{ sourceLabel(node) }}</dd></div><div><dt>关联成员</dt><dd>{{ relatedMembers.join('、') || '暂无直接关联' }}</dd></div><div><dt>最近更新</dt><dd>{{ formatDateTime(node.source_recorded_at) }}</dd></div></dl>

      <section class="similarity"><div><span>最高词项相似度</span><strong>{{ similarity === null ? '—' : similarity.toFixed(2) }}</strong></div><p><i :style="{ width: `${(similarity ?? 0) * 100}%` }" /></p><small>当前后端为 term_vector 稀疏词项相似关系</small></section>

      <section v-if="node.kind === 'knowledge'" class="rag-trace">
        <h4>RAG 命中解释</h4>
        <dl><div><dt>chunk id</dt><dd>{{ node.source_id }}</dd></div><div><dt>来源文档</dt><dd>{{ node.label }}</dd></div><div><dt>向量词项</dt><dd>{{ node.vector_size }}</dd></div><div><dt>被回答引用</dt><dd>当前快照未记录</dd></div><div><dt>回答片段</dt><dd>当前快照未记录</dd></div></dl>
      </section>

      <section class="evidence"><h4>证据来源 <small>{{ evidence.length }} 条可追溯记录</small></h4><div class="badges"><span v-for="item in sourceCounts" :key="item.label">{{ item.label }} <b>{{ item.count }}</b></span></div>
        <article v-for="item in evidence.slice(0, expanded ? 28 : 3)" :key="item.source_id"><p>{{ truncate(excerpt(item)) }}</p><footer>{{ sourceLabel(item) }}<strong>{{ formatDateTime(item.source_recorded_at) }}</strong></footer></article>
        <p v-if="!evidence.length" class="empty-copy">当前节点没有可展开的真实来源记录。</p>
      </section>
      <button class="expand" type="button" :disabled="evidence.length <= 3" @click="expanded = !expanded"><AppIcon name="eye" :size="13" /> {{ expanded ? '收起证据' : `查看完整证据（${evidence.length}）` }}</button>
      <section class="terms"><span>term_vector 词项（{{ node.vector_size }}）</span><div><code v-for="term in node.vector_terms" :key="term">{{ term }}</code><small v-if="!node.vector_terms.length">暂无可显示词项</small></div></section>
      <section v-if="isPendingMemory" class="memory-action"><p>聊天提取结果需确认后才会进入正式健康事实。</p><div><button class="btn btn-primary" :disabled="actionBusy" @click="emit('confirm')">确认入档</button><button class="btn btn-secondary" :disabled="actionBusy" @click="emit('reject')">忽略</button></div></section>
    </template>

    <template v-else>
      <header><div><span>{{ focusCluster ? '局部星系' : '全局语义空间' }}</span><h3>{{ cluster?.label ?? '家庭语义核心' }}</h3></div><b v-if="deltaCount" class="delta">+{{ deltaCount }} 新增</b></header>
      <div class="cluster-summary"><span :style="{ '--tone': cluster?.color ?? '#477461' }"><AppIcon :name="cluster?.icon ?? 'home'" :size="28" /></span><strong>{{ categoryCount }}</strong><small>{{ focusCluster ? '当前类别真实节点' : '家庭语义节点总数' }}</small></div>
      <dl><div><dt>成员数量</dt><dd>{{ twin.stats.member_count }}</dd></div><div><dt>确认事实</dt><dd>{{ twin.stats.fact_count }}</dd></div><div><dt>关系数量</dt><dd>{{ twin.stats.edge_count }}</dd></div><div><dt>最近投影</dt><dd>{{ formatDateTime(twin.generated_at) }}</dd></div><div><dt>空间类型</dt><dd>本地 term_vector</dd></div><div><dt>RAG 证据投影</dt><dd>{{ twin.stats.knowledge_count ? '已启用' : '暂无知识块' }}</dd></div></dl>
      <section class="truth-note"><AppIcon name="lock" :size="15" /><p><strong>本地、可追溯</strong><br />淡色词项仅为能力维度；节点、数字与证据均来自当前家庭快照。</p></section>
      <section class="trace-flow"><h4>聊天 → 检索 → 证据 → 回答</h4><div><span>聊天记忆<b>{{ twin.stats.memory_count }}</b></span><i>→</i><span>知识块<b>{{ twin.stats.knowledge_count }}</b></span><i>→</i><span>真实关系<b>{{ twin.stats.edge_count }}</b></span></div><small>当前 API 尚未保存逐次“问题—命中块—回答引用”链路，因此不展示虚构引用。</small></section>
    </template>
  </aside>
</template>

<style scoped>
.detail-card{--card-pattern:none;background:linear-gradient(160deg,rgba(255,253,248,.96),rgba(247,243,234,.91));height:680px;overflow:auto;padding:17px}.detail-card>header{align-items:flex-start;border-bottom:1px solid var(--line-soft);display:flex;gap:8px;justify-content:space-between;padding-bottom:13px}.detail-card header span{color:var(--clay-deep);font-size:8.5px;font-weight:700;letter-spacing:.12em}.detail-card h3{color:var(--pine-deep);font-family:var(--font-display);font-size:20px;line-height:1.2;margin:4px 0 0}.detail-card header>b{--tone:#477461;align-items:center;background:color-mix(in srgb,var(--tone) 9%,white);border:1px solid color-mix(in srgb,var(--tone) 20%,var(--line));border-radius:999px;color:var(--tone);display:flex;font-size:8px;gap:4px;padding:4px 7px;white-space:nowrap}.detail-card header>b i{background:var(--tone);border-radius:50%;height:5px;width:5px}.detail-card header>b.delta{color:#a66c20}.status{align-items:center;color:var(--pine);display:flex;font-size:10px;gap:5px;margin:11px 0}.detail-card dl{display:grid;gap:7px;margin:0}.detail-card dl div{display:grid;font-size:9.5px;gap:7px;grid-template-columns:72px minmax(0,1fr)}.detail-card dt{color:var(--ink-faint)}.detail-card dd{color:var(--ink-soft);margin:0;overflow-wrap:anywhere;text-align:right}.similarity{border-bottom:1px solid var(--line-soft);border-top:1px solid var(--line-soft);margin-top:12px;padding:10px 0}.similarity>div{display:flex;justify-content:space-between}.similarity span,.similarity small{color:var(--ink-faint);font-size:8.5px}.similarity strong{color:var(--pine-deep);font:700 11px var(--font-numeric)}.similarity p{background:var(--paper-deep);border-radius:999px;height:5px;margin:6px 0 4px;overflow:hidden}.similarity p i{background:linear-gradient(90deg,#6fa07b,#d0a551);display:block;height:100%}.rag-trace,.evidence,.terms,.memory-action,.trace-flow{margin-top:13px}.detail-card h4{align-items:baseline;color:var(--ink);display:flex;font-size:10px;justify-content:space-between;margin:0 0 7px}.detail-card h4 small{color:var(--ink-faint);font-size:8px;font-weight:400}.rag-trace{background:rgba(224,239,237,.48);border:1px solid rgba(69,151,145,.16);border-radius:11px;padding:10px}.rag-trace dl div{font-size:8.5px;grid-template-columns:65px 1fr}.badges{display:flex;flex-wrap:wrap;gap:4px;margin-bottom:6px}.badges span{background:rgba(241,237,228,.76);border:1px solid var(--line-soft);border-radius:999px;color:var(--ink-soft);font-size:8px;padding:3px 6px}.badges b{color:var(--pine-deep)}.evidence article{background:rgba(242,237,226,.57);border:1px solid var(--line-soft);border-radius:9px;margin-top:5px;padding:7px 8px}.evidence article p{color:var(--ink-soft);font-size:8.5px;line-height:1.45;margin:0}.evidence article footer{color:var(--ink-faint);display:flex;font-size:7px;justify-content:space-between;margin-top:4px}.evidence article footer strong{font-weight:400}.expand{align-items:center;background:rgba(226,239,230,.54);border:1px solid rgba(70,118,94,.18);border-radius:9px;color:var(--pine-deep);display:flex;font-size:9px;gap:5px;justify-content:center;margin-top:9px;padding:7px;width:100%}.expand:disabled{opacity:.45}.terms>span{color:var(--ink-faint);font-size:8.5px}.terms>div{display:flex;flex-wrap:wrap;gap:4px;margin-top:5px}.terms code{background:rgba(240,235,224,.8);border:1px solid var(--line-soft);border-radius:5px;color:var(--pine-deep);font-size:7.5px;padding:2px 5px}.terms small,.empty-copy{color:var(--ink-faint);font-size:8px}.memory-action{border-top:1px solid var(--line);padding-top:10px}.memory-action p{color:var(--ink-soft);font-size:8.5px;line-height:1.5}.memory-action>div{display:flex;gap:6px}.memory-action .btn{font-size:9px;min-height:30px}.cluster-summary{align-items:center;display:flex;flex-direction:column;padding:30px 0 25px}.cluster-summary>span{--tone:#477461;align-items:center;background:color-mix(in srgb,var(--tone) 10%,white);border-radius:50%;box-shadow:0 10px 24px color-mix(in srgb,var(--tone) 14%,transparent);color:var(--tone);display:flex;height:64px;justify-content:center;width:64px}.cluster-summary strong{color:var(--pine-deep);font:700 34px var(--font-numeric);margin-top:10px}.cluster-summary small{color:var(--ink-faint);font-size:9px}.truth-note{align-items:flex-start;background:rgba(226,239,230,.45);border:1px solid rgba(70,118,94,.15);border-radius:12px;color:var(--pine);display:flex;gap:8px;margin-top:18px;padding:10px}.truth-note p{color:var(--ink-soft);font-size:8.5px;line-height:1.5;margin:0}.truth-note strong{color:var(--pine-deep)}.trace-flow{border-top:1px solid var(--line-soft);padding-top:13px}.trace-flow>div{align-items:center;display:flex;gap:5px}.trace-flow>div span{background:rgba(242,237,226,.68);border-radius:8px;color:var(--ink-soft);display:flex;flex:1;flex-direction:column;font-size:7.5px;padding:7px 4px;text-align:center}.trace-flow>div b{color:var(--pine-deep);font:700 13px var(--font-numeric);margin-top:3px}.trace-flow>div i{color:var(--gold);font-style:normal}.trace-flow>small{color:var(--ink-faint);display:block;font-size:7.5px;line-height:1.5;margin-top:7px}@media(max-width:1180px){.detail-card{height:620px}}
</style>
