<script setup lang="ts">
import { computed, ref } from 'vue'
import type { DigitalTwinNode, DigitalTwinResponse } from '../../api/types'
import { buildGlobalOrbitNodes, buildLocalOrbitNodes, countByCluster, GALAXY_CLUSTERS, visibleTwinNodes } from '../../digital-twin/galaxy-layout'
import type { GalaxyCluster, GalaxyClusterId, GalaxyOrbitNode } from '../../digital-twin/galaxy-types'
import AppIcon from '../AppIcon.vue'
import GalaxyBackdrop from './GalaxyBackdrop.vue'
import GalaxyNodeDetail from './GalaxyNodeDetail.vue'
import GalaxyPlanet from './GalaxyPlanet.vue'

const props = defineProps<{ twin: DigitalTwinResponse; focusCluster: GalaxyClusterId | null; selectedNodeId: string | null; recentNodeIds: Set<string>; deltaCounts: Record<GalaxyClusterId, number>; showUnconfirmed: boolean; autoOrbit: boolean; syncing: boolean }>()
const emit = defineEmits<{ drill: [clusterId: GalaxyClusterId]; back: []; selectNode: [node: DigitalTwinNode]; clearSelection: []; toggleUnconfirmed: []; toggleOrbit: []; refresh: [] }>()

const stage = ref<HTMLElement | null>(null)
const spatial = ref(true)
const tiltX = ref(0); const tiltY = ref(0)
const panX = ref(0); const panY = ref(0); const zoom = ref(1)
const dragging = ref(false)
let dragPointer = -1; let dragStartX = 0; let dragStartY = 0; let panStartX = 0; let panStartY = 0

const nodes = computed(() => visibleTwinNodes(props.twin, props.showUnconfirmed))
const counts = computed(() => countByCluster(nodes.value))
const focus = computed(() => GALAXY_CLUSTERS.find(item => item.id === props.focusCluster) ?? null)
const selectedNode = computed(() => props.twin.nodes.find(node => node.id === props.selectedNodeId) ?? null)
const householdNode = computed(() => props.twin.nodes.find(node => node.kind === 'household') ?? null)
const orbitNodes = computed(() => focus.value ? buildLocalOrbitNodes(nodes.value, focus.value.id) : GALAXY_CLUSTERS.flatMap(cluster => buildGlobalOrbitNodes(nodes.value, cluster)))
const relationLines = computed(() => {
  const positions = new Map(orbitNodes.value.filter(item => item.node).map(item => [item.node!.id, item]))
  return props.twin.edges.map(edge => ({ edge, source: positions.get(edge.source), target: positions.get(edge.target) }))
    .filter((item): item is { edge: DigitalTwinResponse['edges'][number]; source: GalaxyOrbitNode; target: GalaxyOrbitNode } => Boolean(item.source && item.target)).slice(0, 24)
})
const worldTransform = computed(() => `translate3d(${panX.value}px,${panY.value}px,0) scale(${zoom.value})`)

function clusterStyle(cluster: GalaxyCluster): Record<string, string> { return { '--cluster-color': cluster.color, '--cluster-soft': cluster.soft } }
function orbitNodeStyle(item: GalaxyOrbitNode): Record<string, string> {
  const cluster = GALAXY_CLUSTERS.find(candidate => candidate.id === item.clusterId)!
  const depthScale = spatial.value ? .9 + ((item.z + 1) / 2) * .22 : 1
  return { '--cluster-color': cluster.color, '--cluster-soft': cluster.soft, '--depth': spatial.value ? `${Math.round(item.z * 46)}px` : '0px', '--depth-scale': String(depthScale), '--depth-opacity': String(spatial.value ? .72 + ((item.z + 1) / 2) * .28 : 1), '--depth-blur': `${spatial.value && item.z < -.45 ? .45 : 0}px`, left: `${item.x}%`, top: `${item.y}%`, zIndex: String(30 + Math.round(item.z * 12)) }
}
function truncate(value: string, max = 16): string { return value.length > max ? `${value.slice(0, max)}…` : value }
function resetView(): void { panX.value = 0; panY.value = 0; zoom.value = 1; tiltX.value = 0; tiltY.value = 0 }
function onPointerDown(event: PointerEvent): void {
  if ((event.target as HTMLElement).closest('button, input, aside')) return
  dragging.value = true; dragPointer = event.pointerId; dragStartX = event.clientX; dragStartY = event.clientY; panStartX = panX.value; panStartY = panY.value
  stage.value?.setPointerCapture(event.pointerId)
}
function onPointerMove(event: PointerEvent): void {
  if (dragging.value && event.pointerId === dragPointer) { panX.value = panStartX + event.clientX - dragStartX; panY.value = panStartY + event.clientY - dragStartY; return }
  if (!spatial.value || !stage.value) return
  const bounds = stage.value.getBoundingClientRect(); tiltY.value = ((event.clientX - bounds.left) / bounds.width - .5) * 3.5; tiltX.value = (.5 - (event.clientY - bounds.top) / bounds.height) * 2.6
}
function onPointerUp(event: PointerEvent): void { if (event.pointerId !== dragPointer) return; dragging.value = false; stage.value?.releasePointerCapture(event.pointerId); dragPointer = -1 }
function onWheel(event: WheelEvent): void { zoom.value = Math.max(.76, Math.min(1.38, zoom.value - event.deltaY * .0008)) }
</script>

<template>
  <section ref="stage" class="galaxy-card card" :class="{ 'is-paused': !autoOrbit, 'is-flat': !spatial, dragging }" @pointerdown="onPointerDown" @pointermove="onPointerMove" @pointerup="onPointerUp" @pointercancel="onPointerUp" @wheel.prevent="onWheel">
    <header class="galaxy-toolbar">
      <div class="galaxy-path">
        <button v-if="focus" type="button" @click="emit('back')"><AppIcon name="rewind" :size="13" /> 家庭语义空间</button>
        <span v-else><i /> 家庭语义空间</span>
        <template v-if="focus"><b>/</b><strong>{{ focus.label }}局部星系</strong></template>
      </div>
      <div class="galaxy-controls">
        <label title="显示聊天中自动提取、尚未经人工确认的线索"><input :checked="showUnconfirmed" type="checkbox" @change="emit('toggleUnconfirmed')" /> 未确认线索</label>
        <button type="button" :disabled="syncing" title="重新读取当前家庭的真实投影" @click="emit('refresh')"><AppIcon name="refresh" :size="12" /> {{ syncing ? '同步中' : '刷新投影' }}</button>
        <div class="mode-switch"><button type="button" :class="{ active: spatial }" @click="spatial = true">2.5D</button><button type="button" :class="{ active: !spatial }" @click="spatial = false">平面</button></div>
        <button type="button" title="重置缩放与位置" @click="resetView"><AppIcon name="compass" :size="12" /> 复位</button>
        <button type="button" @click="emit('toggleOrbit')"><AppIcon :name="autoOrbit ? 'pause' : 'play'" :size="11" /> {{ autoOrbit ? '暂停' : '流动' }}</button>
      </div>
    </header>
    <div class="galaxy-viewport">
      <div class="world-frame" :style="{ transform: worldTransform }">
        <Transition name="galaxy-shift" mode="out-in">
          <div :key="focus?.id ?? 'overview'" class="galaxy-world" :style="{ '--tilt-x': `${tiltX}deg`, '--tilt-y': `${tiltY}deg` }">
            <GalaxyBackdrop :paused="!autoOrbit" />
            <div class="galaxy-floor"><i /><i /><i /><i /></div>
            <svg class="galaxy-links" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
              <template v-if="!focus"><path v-for="cluster in GALAXY_CLUSTERS" :key="cluster.id" :d="`M 50 52 Q ${(50 + cluster.x) / 2} ${cluster.y - 4} ${cluster.x} ${cluster.y}`" class="core-link" /></template>
              <template v-else><line v-for="item in orbitNodes" :key="item.id" x1="50" y1="52" :x2="item.x" :y2="item.y" class="core-link" :class="{ recent: item.node && recentNodeIds.has(item.node.id) }" /></template>
              <path v-for="item in relationLines" :key="item.edge.id" :d="`M ${item.source.x} ${item.source.y} Q 50 50 ${item.target.x} ${item.target.y}`" class="real-link" :class="{ strong: item.edge.weight >= .65 }" :style="{ '--edge-weight': String(item.edge.weight) }" />
            </svg>
            <template v-if="!focus"><GalaxyPlanet v-for="cluster in GALAXY_CLUSTERS" :key="cluster.id" :cluster="cluster" :count="counts[cluster.id]" :delta="deltaCounts[cluster.id]" @open="emit('drill', cluster.id)" /></template>
            <template v-else><GalaxyPlanet v-for="cluster in GALAXY_CLUSTERS.filter(item => item.id !== focus?.id)" :key="cluster.id" :cluster="cluster" :count="counts[cluster.id]" :delta="0" subdued /></template>
            <button v-for="item in orbitNodes" :key="item.id" type="button" class="orbit-node" :class="{ guide: item.guide, selected: item.node?.id === selectedNodeId, recent: item.node && recentNodeIds.has(item.node.id) }" :style="orbitNodeStyle(item)" :disabled="item.guide" @click="item.node && emit('selectNode', item.node)"><i /><span>{{ truncate(item.label, focus ? 24 : 14) }}</span><small v-if="item.node?.status === 'UNCONFIRMED'">待确认</small></button>
            <button type="button" class="galaxy-core" :style="focus ? clusterStyle(focus) : undefined" :disabled="Boolean(focus)" @click="householdNode && emit('selectNode', householdNode)">
              <span class="core-ring ring-a"><i /><i /></span><span class="core-ring ring-b"><i /></span><span class="core-ring ring-c" />
              <span class="core-sphere"><span class="core-glint" /><AppIcon :name="focus?.icon ?? 'home'" :size="34" /><strong>{{ focus?.shortLabel ?? '家庭语义核心' }}</strong><small v-if="focus">{{ counts[focus.id] }} 个真实节点 · 点击词项查看证据</small><small v-else>{{ twin.stats.member_count }} 位成员 · {{ twin.nodes.length }} 个节点</small></span>
            </button>
            <div v-if="focus && !orbitNodes.some(item => item.node)" class="empty-hint">当前类别暂无真实记录，虚线词项仅表示可接入维度。</div>
          </div>
        </Transition>
      </div>
    </div>
    <Transition name="detail-slide"><GalaxyNodeDetail v-if="selectedNode" :twin="twin" :node="selectedNode" @close="emit('clearSelection')" @select="emit('selectNode', $event)" /></Transition>
    <footer class="galaxy-footer"><span><i class="real-dot" /> 真实节点</span><span><i class="guide-dot" /> 可接入维度</span><span><i class="relation-line" /> 真实关系</span><small>拖拽移动 · 滚轮缩放 · 点击类别进入局部星系</small></footer>
  </section>
</template>

<style scoped>
.galaxy-card{--card-pattern:none;background:radial-gradient(circle at 50% 45%,rgba(255,252,243,.78),rgba(255,250,238,.91) 45%,rgba(242,237,225,.94));height:680px;min-width:0;overflow:hidden;padding:0;position:relative;touch-action:none}.galaxy-toolbar{align-items:center;background:rgba(255,253,248,.58);backdrop-filter:blur(10px);border-bottom:1px solid rgba(111,102,83,.1);display:flex;justify-content:space-between;padding:12px 16px;position:relative;z-index:130}.galaxy-path{align-items:center;display:flex;gap:8px}.galaxy-path span,.galaxy-path button{align-items:center;background:none;border:0;color:var(--pine-deep);display:flex;font-size:12px;font-weight:750;gap:6px;padding:0}.galaxy-path span i{animation:live 1.8s ease-in-out infinite;background:#66a27d;border-radius:50%;box-shadow:0 0 0 4px rgba(102,162,125,.11);height:7px;width:7px}.galaxy-path b{color:var(--line);font-weight:400}.galaxy-path strong{color:var(--clay-deep);font-size:10px}.galaxy-controls{align-items:center;display:flex;gap:6px}.galaxy-controls label{align-items:center;color:var(--ink-faint);display:flex;font-size:8.5px;gap:4px}.galaxy-controls input{accent-color:var(--pine)}.galaxy-controls>button{align-items:center;background:rgba(255,253,248,.7);border:1px solid var(--line-soft);border-radius:999px;color:var(--ink-faint);display:flex;font-size:8.5px;gap:4px;padding:5px 8px}.galaxy-controls>button:hover{border-color:rgba(60,105,84,.24);color:var(--pine)}.galaxy-controls>button:disabled{opacity:.48}.mode-switch{background:rgba(232,228,218,.7);border-radius:999px;padding:2px}.mode-switch button{background:transparent;border:0;border-radius:999px;color:var(--ink-faint);font-size:8.5px;padding:4px 7px}.mode-switch button.active{background:white;box-shadow:0 2px 7px rgba(57,68,56,.1);color:var(--pine-deep)}.galaxy-viewport{cursor:grab;inset:48px 0 39px;overflow:hidden;perspective:1200px;position:absolute}.dragging .galaxy-viewport{cursor:grabbing}.world-frame{height:100%;transform-origin:center;transition:transform .15s ease;width:100%}.dragging .world-frame{transition:none}.galaxy-world{height:100%;position:relative;transform:rotateX(var(--tilt-x)) rotateY(var(--tilt-y));transform-style:preserve-3d;transition:transform .2s ease;width:100%}.is-flat .galaxy-world{transform:none}.galaxy-floor{height:82%;left:50%;position:absolute;top:52%;transform:translate(-50%,-50%) rotateX(72deg) translateZ(-120px);width:94%}.galaxy-floor i{border:1px solid rgba(67,116,93,.09);border-radius:50%;inset:0;position:absolute}.galaxy-floor i:nth-child(2){border-color:rgba(195,151,79,.12);inset:13%}.galaxy-floor i:nth-child(3){inset:27%}.galaxy-floor i:nth-child(4){border-color:rgba(195,151,79,.16);inset:40%}.galaxy-links{height:100%;inset:0;overflow:visible;pointer-events:none;position:absolute;width:100%;z-index:8}.galaxy-links path,.galaxy-links line{fill:none;vector-effect:non-scaling-stroke}.core-link{animation:dash 10s linear infinite;stroke:rgba(75,125,101,.34);stroke-dasharray:7 8;stroke-width:1.3}.core-link.recent{filter:drop-shadow(0 0 4px #78a887);stroke:#67a27f;stroke-width:2}.real-link{opacity:calc(.24 + var(--edge-weight) * .45);stroke:rgba(183,136,58,.62);stroke-dasharray:2 5;stroke-width:calc(.55px + var(--edge-weight) * 1.1px)}.real-link.strong{filter:drop-shadow(0 0 2px rgba(190,143,64,.35))}.orbit-node{--cluster-color:#5d9a76;--cluster-soft:#e4f0e6;--depth:0px;--depth-scale:1;--depth-opacity:1;--depth-blur:0;align-items:center;background:linear-gradient(145deg,rgba(255,255,255,.94),color-mix(in srgb,var(--cluster-soft) 78%,white));border:1px solid color-mix(in srgb,var(--cluster-color) 30%,var(--line));border-radius:999px;box-shadow:0 8px 18px color-mix(in srgb,var(--cluster-color) 16%,transparent);color:color-mix(in srgb,var(--cluster-color) 78%,#273a32);display:flex;filter:blur(var(--depth-blur));gap:5px;max-width:184px;opacity:var(--depth-opacity);padding:7px 11px;position:absolute;transform:translate(-50%,-50%) translateZ(var(--depth)) scale(var(--depth-scale));transition:filter .5s ease,opacity .5s ease,transform .5s ease;white-space:nowrap}.orbit-node i{background:radial-gradient(circle at 30% 25%,#fff,var(--cluster-color));border-radius:50%;box-shadow:0 0 6px color-mix(in srgb,var(--cluster-color) 36%,transparent);height:7px;flex:0 0 7px;width:7px}.orbit-node span{font-size:10px;font-weight:680;overflow:hidden;text-overflow:ellipsis}.orbit-node small{background:rgba(255,255,255,.7);border-radius:999px;color:#95651e;font-size:7px;padding:1px 4px}.orbit-node:hover,.orbit-node.selected{filter:none;opacity:1;transform:translate(-50%,-50%) translateZ(calc(var(--depth) + 16px)) scale(calc(var(--depth-scale) + .08));z-index:75!important}.orbit-node.selected{box-shadow:0 12px 27px color-mix(in srgb,var(--cluster-color) 30%,transparent),0 0 0 4px color-mix(in srgb,var(--cluster-color) 13%,transparent)}.orbit-node.guide{border-style:dashed;box-shadow:none;cursor:default;opacity:.5}.orbit-node.recent{animation:node-in .58s both,pulse-node 1.5s .6s 2}.galaxy-core{--cluster-color:#416f5d;--cluster-soft:#dce9df;background:none;border:0;height:252px;left:50%;padding:0;position:absolute;top:52%;transform:translate(-50%,-50%) translateZ(92px);width:320px;z-index:60}.galaxy-core:disabled{cursor:default;opacity:1}.core-sphere{align-items:center;background:radial-gradient(circle at 31% 20%,rgba(255,255,255,.98) 0 8%,rgba(136,171,151,.93) 27%,color-mix(in srgb,var(--cluster-color) 85%,#193b2f) 69%,#183f32 100%);border:2px solid rgba(255,255,255,.82);border-radius:50%;box-shadow:0 29px 48px rgba(47,91,72,.32),0 0 0 9px rgba(255,255,255,.22),inset 8px 8px 18px rgba(255,255,255,.72),inset -13px -18px 28px rgba(16,55,40,.34);color:#fffaf1;display:flex;flex-direction:column;height:164px;justify-content:center;left:50%;overflow:hidden;position:absolute;text-shadow:0 2px 6px rgba(12,45,34,.34);top:50%;width:164px;z-index:5}.core-sphere::after{background:linear-gradient(105deg,transparent 28%,rgba(255,255,255,.45) 47%,transparent 64%);content:"";inset:-15%;position:absolute;transform:translateX(-48%) rotate(-12deg)}.core-sphere>*{position:relative;z-index:2}.core-glint{background:rgba(255,255,255,.94);border-radius:50%;filter:blur(3px);height:16px;left:34px;position:absolute;top:20px;width:39px}.core-sphere strong{font-family:var(--font-display);font-size:19px;margin-top:6px}.core-sphere small{font-size:8.5px;line-height:1.45;margin-top:4px;max-width:132px;opacity:.8}.core-ring{border:1px solid color-mix(in srgb,var(--cluster-color) 34%,transparent);border-radius:50%;left:50%;position:absolute;top:50%;transform:translate(-50%,-50%) rotateX(69deg)}.core-ring.ring-a{animation:orbit 17s linear infinite;height:212px;width:316px}.core-ring.ring-b{animation:orbit 12s linear infinite reverse;border-color:rgba(197,147,74,.45);border-style:dashed;height:166px;width:276px}.core-ring.ring-c{height:130px;opacity:.5;width:350px}.core-ring i{background:radial-gradient(circle at 30% 25%,white,#d2a859);border-radius:50%;box-shadow:0 0 11px rgba(197,147,73,.55);height:9px;left:14%;position:absolute;top:54%;width:9px}.core-ring i:nth-child(2){left:auto;right:12%;top:31%}.ring-b i{left:55%;top:-4px}.empty-hint{background:rgba(255,250,238,.91);border:1px solid var(--line);border-radius:999px;bottom:18px;color:var(--gold-ink);font-size:9px;left:50%;padding:6px 10px;position:absolute;transform:translateX(-50%);z-index:80}.galaxy-footer{align-items:center;background:linear-gradient(180deg,transparent,rgba(255,253,248,.72));bottom:0;display:flex;gap:14px;left:0;padding:11px 16px;position:absolute;right:0;z-index:130}.galaxy-footer span{align-items:center;color:var(--ink-faint);display:flex;font-size:8.5px;gap:4px}.galaxy-footer i{display:inline-block}.real-dot{background:var(--pine);border-radius:50%;height:7px;width:7px}.guide-dot{border:1px dashed var(--sage);border-radius:50%;height:7px;width:7px}.relation-line{border-top:1px dashed var(--gold);width:13px}.galaxy-footer small{color:var(--ink-faint);font-size:8.5px;margin-left:auto}.is-paused :is(.core-ring,.galaxy-links path,.galaxy-links line,.orbit-node.recent){animation-play-state:paused}.galaxy-shift-enter-active,.galaxy-shift-leave-active{transition:opacity .45s ease,transform .58s cubic-bezier(.22,.8,.24,1)}.galaxy-shift-enter-from{opacity:0;transform:scale(.84)}.galaxy-shift-leave-to{opacity:0;transform:scale(1.08)}.detail-slide-enter-active,.detail-slide-leave-active{transition:opacity .3s ease,transform .42s cubic-bezier(.22,.8,.24,1)}.detail-slide-enter-from,.detail-slide-leave-to{opacity:0;transform:translateX(28px)}@keyframes orbit{to{transform:translate(-50%,-50%) rotateX(69deg) rotateZ(360deg)}}@keyframes dash{to{stroke-dashoffset:-38}}@keyframes live{50%{opacity:.42;box-shadow:0 0 0 8px rgba(102,162,125,.04)}}@keyframes node-in{from{opacity:0;transform:translate(-50%,-50%) scale(.3)}}@keyframes pulse-node{50%{box-shadow:0 12px 28px color-mix(in srgb,var(--cluster-color) 34%,transparent),0 0 0 9px color-mix(in srgb,var(--cluster-color) 10%,transparent)}}@media(max-width:1180px){.galaxy-card{height:620px}.orbit-node{max-width:150px;padding:6px 9px}.orbit-node span{font-size:9px}.galaxy-controls label,.galaxy-controls>button{font-size:0}.core-sphere{height:148px;width:148px}}@media(max-width:760px){.galaxy-footer span{display:none}.galaxy-controls label{display:none}.galaxy-path strong{display:none}}@media(prefers-reduced-motion:reduce){.galaxy-card *{animation:none!important;transition:none!important}}
</style>
