<script setup lang="ts">
import { computed } from 'vue'
import type { DigitalTwinNode, DigitalTwinResponse } from '../../api/types'
import AppIcon from '../AppIcon.vue'

const props = defineProps<{ twin: DigitalTwinResponse; node: DigitalTwinNode }>()
defineEmits<{ close: []; select: [node: DigitalTwinNode] }>()

const nodeById = computed(() => new Map(props.twin.nodes.map(node => [node.id, node])))
const relations = computed(() => props.twin.edges.filter(edge => edge.source === props.node.id || edge.target === props.node.id).map(edge => {
  const targetId = edge.source === props.node.id ? edge.target : edge.source
  return { ...edge, node: nodeById.value.get(targetId) }
}).filter(item => item.node).sort((a, b) => b.weight - a.weight).slice(0, 6))
const vectorRelations = computed(() => relations.value.filter(item => item.relation.includes('term_vector') || item.relation.includes('聊天线索')))
const maxSimilarity = computed(() => vectorRelations.value[0]?.weight ?? null)
const kindLabel = computed(() => ({ household: '家庭核心', member: '家庭成员', fact: '已确认事实', memory: '聊天线索', knowledge: '知识分块' })[props.node.kind])

function formatTime(value: string): string {
  const time = new Date(value)
  return Number.isNaN(time.getTime()) ? value : time.toLocaleString('zh-CN', { hour12: false })
}
</script>

<template>
  <aside class="node-detail" aria-label="语义节点详情">
    <header>
      <div><span>{{ kindLabel }}</span><h3>{{ node.label }}</h3></div>
      <button type="button" aria-label="关闭详情" @click="$emit('close')"><AppIcon name="close" :size="15" /></button>
    </header>
    <p v-if="node.status === 'UNCONFIRMED'" class="pending"><i /> 未确认聊天线索，不参与风险与正式事实计算</p>
    <dl>
      <div><dt>来源</dt><dd>{{ node.source_kind }}</dd></div>
      <div><dt>关联成员</dt><dd>{{ node.member_name || '家庭级记录' }}</dd></div>
      <div><dt>更新时间</dt><dd>{{ formatTime(node.source_recorded_at) }}</dd></div>
      <div><dt>向量类型</dt><dd>稀疏 term_vector</dd></div>
    </dl>
    <section v-if="maxSimilarity !== null" class="similarity">
      <div><span>最高词项相似度</span><strong>{{ maxSimilarity.toFixed(2) }}</strong></div>
      <p><i :style="{ width: `${Math.round(maxSimilarity * 100)}%` }" /></p>
      <small>仅表示词项重合，不表示医学因果或神经 embedding。</small>
    </section>
    <section class="evidence">
      <h4>来源证据</h4>
      <p>{{ node.source_excerpt || node.detail || '当前接口未提供可展示的正文片段。' }}</p>
      <code>{{ node.source_id }}</code>
    </section>
    <section class="relations">
      <h4>真实关联 <small>{{ relations.length }}</small></h4>
      <button v-for="item in relations" :key="item.id" type="button" @click="item.node && $emit('select', item.node)">
        <span>{{ item.relation }}</span><strong>{{ item.node?.label }}</strong><em>{{ item.weight.toFixed(2) }}</em>
      </button>
      <p v-if="!relations.length" class="empty">当前接口暂无该节点的可见关联。</p>
    </section>
    <section class="terms">
      <h4>词项向量 <small>{{ node.vector_size }} 维</small></h4>
      <div v-if="node.vector_terms.length"><code v-for="term in node.vector_terms.slice(0, 10)" :key="term">{{ term }}</code></div>
      <p v-else class="empty">尚无可展示词项。</p>
    </section>
    <footer><AppIcon name="info" :size="13" /><span>逐次 top-k、引用状态与回答片段尚未由当前 API 保存，因此不展示虚构链路。</span></footer>
  </aside>
</template>

<style scoped>
.node-detail{backdrop-filter:blur(16px);background:linear-gradient(155deg,rgba(255,253,248,.95),rgba(245,240,229,.9));border:1px solid rgba(255,255,255,.92);border-radius:18px;box-shadow:0 24px 58px rgba(53,74,61,.19),inset 0 0 0 1px rgba(94,120,101,.08);max-height:calc(100% - 82px);overflow:auto;padding:17px;position:absolute;right:18px;top:64px;width:292px;z-index:120}.node-detail header{align-items:flex-start;border-bottom:1px solid var(--line-soft);display:flex;justify-content:space-between;padding-bottom:11px}.node-detail header span{color:var(--clay-deep);font-size:8px;font-weight:800;letter-spacing:.12em}.node-detail h3{color:var(--pine-deep);font-family:var(--font-display);font-size:19px;margin:4px 0 0}.node-detail header button{align-items:center;background:rgba(255,255,255,.7);border:1px solid var(--line-soft);border-radius:50%;color:var(--ink-faint);display:flex;height:29px;justify-content:center;width:29px}.pending{align-items:flex-start;background:rgba(248,238,208,.55);border-radius:9px;color:#8b6622;display:flex;font-size:8.5px;gap:6px;line-height:1.45;padding:7px}.pending i{background:#c89a36;border-radius:50%;flex:0 0 6px;height:6px;margin-top:3px;width:6px}.node-detail dl{display:grid;gap:7px;margin:12px 0}.node-detail dl div{display:flex;font-size:9px;justify-content:space-between}.node-detail dt{color:var(--ink-faint)}.node-detail dd{color:var(--ink-soft);margin:0;max-width:175px;text-align:right}.node-detail section{border-top:1px solid var(--line-soft);margin-top:12px;padding-top:11px}.similarity>div{display:flex;justify-content:space-between}.similarity span,.similarity small{color:var(--ink-faint);font-size:8px}.similarity strong{color:var(--pine-deep);font:700 11px var(--font-numeric)}.similarity p{background:var(--paper-deep);border-radius:999px;height:5px;margin:6px 0;overflow:hidden}.similarity p i{background:linear-gradient(90deg,#6fa07b,#d0a551);display:block;height:100%}.node-detail h4{color:var(--ink);font-size:9.5px;margin:0 0 7px}.node-detail h4 small{color:var(--ink-faint);font-weight:400}.evidence p{background:rgba(244,239,229,.68);border-radius:9px;color:var(--ink-soft);font-size:8.5px;line-height:1.55;margin:0 0 6px;padding:8px}.evidence>code{color:var(--ink-faint);display:block;font-size:7px;overflow-wrap:anywhere}.relations button{align-items:center;background:rgba(255,255,255,.54);border:1px solid var(--line-soft);border-radius:9px;display:grid;gap:2px;grid-template-columns:1fr auto;margin-top:5px;padding:6px 8px;text-align:left;width:100%}.relations button span{color:var(--ink-faint);font-size:7px;grid-column:1/3}.relations button strong{color:var(--pine-deep);font-size:8.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.relations button em{color:var(--gold-ink);font:normal 8px var(--font-numeric)}.terms>div{display:flex;flex-wrap:wrap;gap:4px}.terms code{background:rgba(224,239,236,.62);border-radius:5px;color:var(--pine);font-size:7.5px;padding:3px 5px}.empty{color:var(--ink-faint);font-size:8px}.node-detail footer{align-items:flex-start;background:rgba(226,239,230,.5);border-radius:9px;color:var(--pine);display:flex;font-size:8px;gap:6px;line-height:1.5;margin-top:12px;padding:8px}@media(max-width:920px){.node-detail{bottom:12px;left:12px;max-height:48%;right:12px;top:auto;width:auto}}
</style>
