<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { apiClient } from '../api/client'
import type { RelationshipGraphNode } from '../api/types'
import AppIcon from '../components/AppIcon.vue'
import {
  formatError,
  onHealthDataRefresh,
  requestOptions,
  selectMember,
  selectedMember,
  session,
} from '../store'
import { formatDateTime } from '../ui/labels'
import { vTilt } from '../ui/tilt'

interface GraphNode extends RelationshipGraphNode {
  tone: string
  x: number
  y: number
}

const CENTER_X = 500
const CENTER_Y = 330

const CATEGORY_META: Record<
  RelationshipGraphNode['category'],
  { label: string; tone: string; fill: string; stroke: string; sphereEdge: string }
> = {
  drug: { label: '在用药品', tone: 'pine', fill: '#e3ece7', stroke: '#38665a', sphereEdge: '#b7cfc4' },
  allergy: { label: '过敏史', tone: 'rose', fill: '#f4dde0', stroke: '#ad4152', sphereEdge: '#e2b6bd' },
  disease: { label: '关注疾病', tone: 'gold', fill: '#f4e8c8', stroke: '#a97e1f', sphereEdge: '#e2cd97' },
  plan: { label: '用药计划', tone: 'sky', fill: '#dfe9ef', stroke: '#47708c', sphereEdge: '#b9cedb' },
  caregiver: { label: '照护者', tone: 'sage', fill: '#e6ede4', stroke: '#6e8a74', sphereEdge: '#c6d6c1' },
}

const graph = ref<{ eventsCount: number; nodes: RelationshipGraphNode[] }>({
  eventsCount: 0,
  nodes: [],
})
const loading = ref(false)
const loadError = ref('')
const selectedNodeId = ref<string | null>(null)
let removeHealthRefreshListener: (() => void) | null = null

const nodes = computed<GraphNode[]>(() => {
  const raw = graph.value.nodes.map(node => ({
    ...node,
    tone: CATEGORY_META[node.category].tone,
  }))

  const total = raw.length
  return raw.map((node, index) => {
    const angle = (index / Math.max(total, 1)) * Math.PI * 2 - Math.PI / 2
    const radius = total <= 6 ? 200 : index % 2 === 0 ? 172 : 238
    return {
      ...node,
      x: CENTER_X + Math.cos(angle) * radius * 1.32,
      y: CENTER_Y + Math.sin(angle) * radius * 0.86,
    }
  })
})

const selectedNode = computed(
  () => nodes.value.find(node => node.id === selectedNodeId.value) ?? null,
)

const legendCounts = computed(() => [
  { key: 'drug', count: nodes.value.filter(node => node.category === 'drug').length },
  { key: 'allergy', count: nodes.value.filter(node => node.category === 'allergy').length },
  { key: 'disease', count: nodes.value.filter(node => node.category === 'disease').length },
  { key: 'plan', count: nodes.value.filter(node => node.category === 'plan').length },
  { key: 'caregiver', count: nodes.value.filter(node => node.category === 'caregiver').length },
])

function edgePath(node: GraphNode): string {
  const midX = (CENTER_X + node.x) / 2
  const midY = (CENTER_Y + node.y) / 2
  const dx = node.x - CENTER_X
  const dy = node.y - CENTER_Y
  const norm = Math.sqrt(dx * dx + dy * dy) || 1
  const bend = 26
  const controlX = midX - (dy / norm) * bend
  const controlY = midY + (dx / norm) * bend
  return `M ${CENTER_X} ${CENTER_Y} Q ${controlX} ${controlY} ${node.x} ${node.y}`
}

function edgeDomId(node: GraphNode): string {
  return `edge-${node.id.replace(/[^a-zA-Z0-9_-]/g, '-')}`
}

function truncate(text: string, max = 9): string {
  return text.length > max ? `${text.slice(0, max)}…` : text
}

async function loadGraph(): Promise<void> {
  const householdId = session.selectedHouseholdId
  const memberId = session.selectedMemberId
  if (!householdId || !memberId) return

  loading.value = true
  loadError.value = ''
  selectedNodeId.value = null
  try {
    const response = await apiClient.getRelationshipGraph(householdId, memberId, requestOptions.value)
    graph.value = { eventsCount: response.events_count, nodes: response.nodes }
  } catch (cause) {
    graph.value = { eventsCount: 0, nodes: [] }
    loadError.value = formatError(cause)
  } finally {
    loading.value = false
  }
}

function onMemberChange(event: Event): void {
  selectMember((event.target as HTMLSelectElement).value)
}

watch(
  () => [session.selectedHouseholdId, session.selectedMemberId],
  () => void loadGraph(),
)

onMounted(() => {
  void loadGraph()
  removeHealthRefreshListener = onHealthDataRefresh(() => void loadGraph())
})

onBeforeUnmount(() => removeHealthRefreshListener?.())
</script>

<template>
  <section class="page-hero">
    <div class="card-heading" style="margin-bottom: 0">
      <div>
        <h2 class="hero-greeting gradient-text">家庭健康图谱</h2>
      </div>
      <label class="context-select">
        成员
        <select :value="session.selectedMemberId" :disabled="loading" @change="onMemberChange">
          <option v-for="member in session.members" :key="member.id" :value="member.id">
            {{ member.display_name }}
          </option>
        </select>
      </label>
    </div>
  </section>

  <p v-if="loadError" class="notice error" role="alert">
    <AppIcon name="alert" :size="16" />
    {{ loadError }}
  </p>

  <div v-tilt="2.2" class="graph-stage">
    <div v-if="nodes.length > 0" class="graph-legend-overlay" aria-label="图例">
      <span v-for="item in legendCounts" :key="item.key" class="legend-row">
        <i :style="{ background: CATEGORY_META[item.key]!.stroke }" />
        <span>{{ CATEGORY_META[item.key]!.label }}</span>
        <span class="legend-count">{{ item.count }}</span>
      </span>
      <span class="legend-row legend-row--total">
        <AppIcon name="timeline" :size="12" style="color: var(--ink-faint)" />
        <span>已确认事件</span>
        <span class="legend-count">{{ graph.eventsCount }}</span>
      </span>
    </div>
    <div v-if="loading" class="inline-loading" style="padding: 48px 24px">
      <span class="loading-dots"><span /><span /><span /></span>
      正在从已授权事件重建关系投影
    </div>
    <div v-else-if="nodes.length === 0" class="empty-state" style="padding: 60px 24px">
      <AppIcon class="empty-art" name="compass" :size="44" />
      <strong>尚无可投影的已确认事实</strong>
      <p>录入药品、过敏或计划后，{{ selectedMember?.display_name ?? '成员' }}的健康关系会在这里生长出来。</p>
    </div>
    <svg v-else viewBox="0 0 1000 660" role="img" :aria-label="`${selectedMember?.display_name ?? '成员'}的健康关系图谱`">
      <defs>
        <radialGradient
          v-for="(meta, key) in CATEGORY_META"
          :id="`node-sphere-${key}`"
          :key="`sphere-${key}`"
          cx="0.34"
          cy="0.3"
          r="0.92"
        >
          <stop offset="0%" stop-color="#ffffff" />
          <stop offset="46%" :stop-color="meta.fill" />
          <stop offset="100%" :stop-color="meta.sphereEdge" />
        </radialGradient>
        <radialGradient id="node-sphere-center" cx="0.34" cy="0.3" r="0.95">
          <stop offset="0%" stop-color="#5d8d7d" />
          <stop offset="55%" stop-color="#2a5045" />
          <stop offset="100%" stop-color="#1c372f" />
        </radialGradient>
      </defs>
      <path
        v-for="node in nodes"
        :id="edgeDomId(node)"
        :key="`edge-${node.id}`"
        class="graph-edge"
        :d="edgePath(node)"
        :stroke="CATEGORY_META[node.category]!.stroke"
        stroke-width="1.6"
      />

      <circle
        v-for="(node, index) in nodes.slice(0, 10)"
        :key="`particle-${node.id}`"
        class="graph-particle"
        r="2.8"
        :fill="CATEGORY_META[node.category]!.stroke"
      >
        <!-- 用负 begin 错峰：动画视作已在过去开始，挂载瞬间粒子就在路径上。
             正 begin 会让粒子在等待期停在画布原点 (0,0)，左上角露出半个点。 -->
        <animateMotion
          :dur="`${4.6 + (index % 5) * 0.9}s`"
          :begin="`-${(index % 5) * 0.7}s`"
          repeatCount="indefinite"
          keyPoints="0;1"
          keyTimes="0;1"
          calcMode="linear"
        >
          <mpath :href="`#${edgeDomId(node)}`" />
        </animateMotion>
      </circle>

      <circle class="graph-orbit" :cx="CENTER_X" :cy="CENTER_Y" r="306" fill="none" stroke="#38665a" stroke-opacity="0.3" stroke-width="1.2" stroke-dasharray="3 10" stroke-linecap="round" />
      <circle class="graph-orbit graph-orbit--inner" :cx="CENTER_X" :cy="CENTER_Y" r="238" fill="none" stroke="#a97e1f" stroke-opacity="0.22" stroke-width="1" stroke-dasharray="2 12" stroke-linecap="round" />
      <circle class="graph-center-pulse" :cx="CENTER_X" :cy="CENTER_Y" r="58" fill="none" stroke="#38665a" stroke-width="1.5" />
      <circle class="graph-center-sphere" :cx="CENTER_X" :cy="CENTER_Y" r="46" fill="url(#node-sphere-center)" />
      <circle :cx="CENTER_X" :cy="CENTER_Y" r="46" fill="none" stroke="#f4eddd" stroke-opacity="0.35" stroke-width="1.5" />
      <text :x="CENTER_X" :y="CENTER_Y - 2" text-anchor="middle" fill="#f4eddd" font-size="16" font-weight="700">
        {{ truncate(selectedMember?.display_name ?? '成员', 4) }}
      </text>
      <text :x="CENTER_X" :y="CENTER_Y + 17" text-anchor="middle" fill="#cfc4ac" font-size="10">
        {{ nodes.length }} 个关联事实
      </text>

      <g
        v-for="(node, index) in nodes"
        :key="node.id"
        class="graph-node"
        :class="{ selected: selectedNodeId === node.id }"
        role="button"
        :aria-label="`${CATEGORY_META[node.category]!.label}：${node.label}`"
        tabindex="0"
        @click="selectedNodeId = selectedNodeId === node.id ? null : node.id"
        @keydown.enter="selectedNodeId = selectedNodeId === node.id ? null : node.id"
      >
        <g class="graph-node-inner" :style="{ animationDelay: `${(index % 6) * 0.55}s` }">
          <ellipse
            class="graph-node-shadow"
            :cx="node.x"
            :cy="node.y + 30"
            rx="17"
            ry="4.5"
          />
          <!-- 类别光晕 -->
          <circle :cx="node.x" :cy="node.y" r="30" :fill="CATEGORY_META[node.category]!.stroke" opacity="0.12" />
          <circle
            :cx="node.x"
            :cy="node.y"
            r="24"
            :fill="`url(#node-sphere-${node.category})`"
            :stroke="CATEGORY_META[node.category]!.stroke"
            :stroke-width="selectedNodeId === node.id ? 3 : 1.8"
          />
          <!-- 类别专属图形：药品胶囊 / 过敏水滴 / 关注十字 / 计划时钟 / 照护者小人 -->
          <g v-if="node.category === 'drug'" class="graph-glyph" :transform="`translate(${node.x} ${node.y}) rotate(-38)`">
            <rect x="-12" y="-6" width="24" height="12" rx="6" fill="#fffdf6" :stroke="CATEGORY_META.drug!.stroke" stroke-width="2" />
            <path d="M0 -6h6a6 6 0 0 1 0 12H0z" :fill="CATEGORY_META.drug!.stroke" opacity="0.85" />
            <line x1="0" y1="-6" x2="0" y2="6" :stroke="CATEGORY_META.drug!.stroke" stroke-width="1.6" />
          </g>
          <g v-else-if="node.category === 'allergy'" class="graph-glyph" :transform="`translate(${node.x} ${node.y})`">
            <path d="M0 -12C5.5 -5 9 -1.5 9 3a9 9 0 1 1-18 0C-9 -1.5 -5.5 -5 0 -12z" fill="#fffdf6" :stroke="CATEGORY_META.allergy!.stroke" stroke-width="2" />
            <circle cx="-3" cy="4" r="2.1" :fill="CATEGORY_META.allergy!.stroke" opacity="0.5" />
          </g>
          <g v-else-if="node.category === 'disease'" class="graph-glyph" :transform="`translate(${node.x} ${node.y})`">
            <path d="M-4 -11h8v7h7v8h-7v7h-8v-7h-7v-8h7z" fill="#fffdf6" :stroke="CATEGORY_META.disease!.stroke" stroke-width="2" stroke-linejoin="round" />
          </g>
          <g v-else-if="node.category === 'plan'" class="graph-glyph" :transform="`translate(${node.x} ${node.y})`">
            <circle r="11" fill="#fffdf6" :stroke="CATEGORY_META.plan!.stroke" stroke-width="2" />
            <path d="M0 -6V0L4.5 2.5" :stroke="CATEGORY_META.plan!.stroke" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" fill="none" />
          </g>
          <g v-else class="graph-glyph" :transform="`translate(${node.x} ${node.y})`">
            <circle cy="-4.5" r="5" fill="#fffdf6" :stroke="CATEGORY_META.caregiver!.stroke" stroke-width="2" />
            <path d="M-9 11a9 8.4 0 0 1 18 0z" fill="#fffdf6" :stroke="CATEGORY_META.caregiver!.stroke" stroke-width="2" stroke-linejoin="round" />
          </g>
        </g>
        <text class="node-label" :x="node.x" :y="node.y + 44" text-anchor="middle">
          {{ truncate(node.label, 10) }}
        </text>
        <text class="node-sub" :x="node.x" :y="node.y + 58" text-anchor="middle">
          {{ CATEGORY_META[node.category]!.label }}
        </text>
      </g>
    </svg>

    <div v-if="selectedNode" class="graph-detail-card">
      <div class="row-top" style="align-items: center; display: flex; gap: 8px; justify-content: space-between">
        <strong>{{ selectedNode.label }}</strong>
        <span class="pill" :class="CATEGORY_META[selectedNode.category]!.tone">
          {{ CATEGORY_META[selectedNode.category]!.label }}
        </span>
      </div>
      <template v-if="selectedNode.source_event_id">
        <span class="text-soft" style="font-size: 12.5px">
          来源事件：{{ selectedNode.source_event_id.slice(0, 8) }}… · 已确认
        </span>
        <span class="text-soft" style="font-size: 12.5px">
          记录时间：{{ formatDateTime(selectedNode.source_recorded_at) }}
        </span>
        <span class="text-soft" style="font-size: 12.5px">
          记录人：{{ selectedNode.source_created_by }}
        </span>
      </template>
      <span v-else class="text-soft" style="font-size: 12.5px">
        来源于已确认的照护关系记录。
      </span>
      <span class="text-faint" style="font-size: 11.5px">
        节点仅由已确认事件生成，可见范围由 API 授权决定。
      </span>
    </div>
  </div>

</template>

<style scoped>
.node-label {
  fill: var(--ink);
  font-size: 11.5px;
  font-weight: 650;
}

/* 类别图形随球体微浮动；选中时整体放大并投出更明显的高光。 */
.graph-glyph { pointer-events: none; }
.graph-node.selected { transform: scale(1.16); }
.graph-node.selected .graph-glyph { filter: drop-shadow(0 4px 8px rgba(42, 80, 69, 0.35)); }

.graph-orbit {
  animation: graph-orbit-spin 90s linear infinite;
  transform-box: view-box;
  transform-origin: 500px 330px;
}

.graph-orbit--inner { animation-duration: 64s; animation-direction: reverse; }

@keyframes graph-orbit-spin {
  to { transform: rotate(360deg); }
}

@media (prefers-reduced-motion: reduce) {
  .graph-orbit { animation: none; }
  .graph-node.selected { transform: none; }
}
</style>
